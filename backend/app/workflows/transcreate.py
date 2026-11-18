"""Transcreate: adapt copy lines into a regional language, then check the result in code.

Stages (four, like every workflow): load context, generate the lines (one structured model call), check protected and
prohibited terms on the regional copy AND its English back-translation, check the script (Unicode blocks). Pure: no
database. The run engine persists the outcome as a `transcreate` operation that creates a new version (app.services.transcreate).
"""

import time
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.agents import transcreate as agent
from app.agents._common import DEMO_OUTPUT_NOTE
from app.agents.brand import applied_note, brand_block
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.schemas.versions import Tone, TranscreatedLine
from app.studio.checks import min_share_for, script_check, term_checks, term_problems
from app.workflows._common import DEMO_RUN_NOTE, STAGES, announce, execute, linear_graph, llm_error, local_step
from app.workflows.types import OutcomeStatus, ProgressFn, WorkflowContext, WorkflowDeps

RUN = "transcreate"
S1, S2, S3, S4 = STAGES[RUN]
NO_CLAIMS_NOTE = "No region claims were available for this region, so every explanation is a model interpretation."
UNREVIEWED_NOTE = "Not reviewed by a native speaker or a local expert."


class LineIn(BaseModel):
    handle: str  # L1, L2, ...: what the model sees
    element_id: str
    kind: str
    text: str


class ClaimIn(BaseModel):
    id: UUID
    handle: str  # C1, C2, ...
    category: str
    statement: str
    kind: str
    confidence: str


class TranscreateInput(BaseModel):
    context: WorkflowContext
    source_version_id: UUID
    region_code: str
    region_name: str
    language: str
    language_name: str
    script: str
    tone: Tone
    lines: list[LineIn]
    claims: list[ClaimIn]
    glossary: list[dict[str, Any]] = []  # entries for this language and for `*`, as they were when the run started


class TranscreateOutcome(BaseModel):
    status: OutcomeStatus
    lines: list[TranscreatedLine]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None
    brand_rules_applied: list[str] = []


class State(TypedDict, total=False):
    inp: TranscreateInput
    protected: list[str]
    drafts: list[agent.LineDraft]
    checks: dict[str, dict]
    scripts: dict[str, dict]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    applied: list[str]


def _flat(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


async def loading_context(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading campaign context.")
    started, inp = time.perf_counter(), state["inp"]
    protected = _flat(inp.context.brand.protected_terms)
    return {"protected": protected, "steps": [local_step(S1, "transcreate", "omnicult", started)]}


async def generating_lines(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Transcreating lines.")
    deps: WorkflowDeps = config["configurable"]["deps"]
    inp = state["inp"]
    block, applied = brand_block(inp.context.brand)
    try:
        drafts, trace, notes = await agent.generate_lines(
            deps.llm, stage=S2, lines={line.handle: line.model_dump() for line in inp.lines}, region_name=inp.region_name,
            region_code=inp.region_code, language=inp.language, language_name=inp.language_name, script=inp.script,
            tone=inp.tone.model_dump(), claims=[c.model_dump(mode="json") for c in inp.claims],
            glossary=inp.glossary, brand=block,
        )
    except LLMError as exc:
        error = llm_error(exc, S2, "No version was created; retrying is safe.")
        return {"steps": [*state["steps"], exc.trace], "error": error, "stop": True}
    if not drafts:
        error = RunError(code="RUN_FAILED", stage=S2, retryable=True,
                         message="The model returned no usable line. No version was created; retrying is safe.")
        return {"steps": [*state["steps"], trace], "limitations": notes, "error": error, "stop": True}
    return {"drafts": drafts, "steps": [*state["steps"], trace], "applied": applied,
            "limitations": [*state.get("limitations", []), *notes, applied_note(applied)]}


async def checking_terms(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Checking protected and prohibited terms.")
    started, inp = time.perf_counter(), state["inp"]
    sources = {line.element_id: line.text for line in inp.lines}
    checks = {
        d.element_id: term_checks(
            sources[d.element_id], d.regional_copy, d.back_translation, inp.glossary, language=inp.language,
            protected=state["protected"], prohibited=inp.context.brand.prohibited_terms,
        )
        for d in state["drafts"]
    }
    return {"checks": checks, "steps": [*state["steps"], local_step(S3, "transcreate", "omnicult", started)]}


async def checking_script(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Checking the script.")
    started, inp = time.perf_counter(), state["inp"]
    min_share = min_share_for(inp.tone.code_mixing)
    scripts = {
        d.element_id: script_check(d.regional_copy, inp.script, preserved=state["checks"][d.element_id]["preserved_terms"], min_share=min_share)
        for d in state["drafts"]
    }
    return {"scripts": scripts, "steps": [*state["steps"], local_step(S4, "transcreate", "omnicult", started)]}


GRAPH = linear_graph(State, [(S1, loading_context), (S2, generating_lines), (S3, checking_terms), (S4, checking_script)])


def assemble(
    inp: TranscreateInput, drafts: list[agent.LineDraft], checks: dict[str, dict], scripts: dict[str, dict]
) -> list[TranscreatedLine]:
    """Per-line results from the drafts and the code checks. A line passes only when the script is right, every protected
    term survived in the copy and in the back-translation, and no prohibited term appears in either."""
    by_id = {line.element_id: line for line in inp.lines}
    results = []
    for d in drafts:
        line, term, script = by_id[d.element_id], checks[d.element_id], scripts[d.element_id]
        problems = term_problems(term) + ([] if script["ok"] else [script["message"]])
        verified = [t for t in d.model_preserved_terms if t.casefold() in line.text.casefold() and t.casefold() in d.regional_copy.casefold()]
        results.append(TranscreatedLine.model_validate({
            "element_id": d.element_id, "kind": line.kind, "source_text": line.text, "regional_copy": d.regional_copy,
            "back_translation": d.back_translation, "explanation": d.explanation, "claim_ids": d.claim_ids,
            "reasoning_type": "evidence_supported" if d.claim_ids else "model_interpretation",
            "preserved_terms": _flat([*term["preserved_terms"], *verified]), "script_check": script, "term_checks": term,
            "passed": not problems, "problems": problems,
        }))
    return results


async def run_transcreate(inp: TranscreateInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> TranscreateOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    demo = inp.context.mode == "demo"
    drafts = state.get("drafts", []) if "scripts" in state else []
    lines = assemble(inp, drafts, state["checks"], state["scripts"]) if drafts else []
    requested = len(inp.lines)
    failed = state.get("error") is not None and not lines
    status: OutcomeStatus = "failed" if failed else "completed" if len(lines) == requested and all(x.passed for x in lines) else "partial"
    notes = [
        agent.SAME_MODEL_NOTE, UNREVIEWED_NOTE, *([] if inp.claims else [NO_CLAIMS_NOTE]),
        *(["Some lines failed the checks; they are shown for review and were not applied."] if any(not x.passed for x in lines) else []),
        *([DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if demo else []),
    ]
    return TranscreateOutcome(
        status=status, lines=lines, limitations=list(dict.fromkeys([*state.get("limitations", []), *notes])),
        steps=state.get("steps", []), error=state.get("error"), brand_rules_applied=state.get("applied", []),
    )
