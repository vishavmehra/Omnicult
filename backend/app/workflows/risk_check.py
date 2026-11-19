"""Risk Check: possible problems in a creative's elements, checked against the region's claims and the ASCI ad-code index.

Three kinds of finding, all stored as "for human review", never as a verdict:
  * a brand rule hit (a prohibited term found verbatim), deterministic, high, blocks Go;
  * a claim-pattern hit (absolute, medical or superlative wording), deterministic, medium;
  * a model finding, kept only when its quote is found in the element it names (or the element is a described, non-text
    element), with every ad-code and claim handle mapped back to a stored record.
Severity and "blocks Go" come from `analytics.risk_rules`; the model never chooses them. Nothing here is legal clearance.
"""

import re
import time
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.agents import risk_check as agent
from app.agents._common import DROPPED_NOTE, norm, pick
from app.agents.brand import applied_note, brand_block
from app.analytics.risk_rules import (
    PATTERN_TEXT,
    RULES_VERSION,
    ClaimSupport,
    decide,
    scan_patterns,
    topics_fit,
)
from app.llm.gateway import LLMError, LLMGateway
from app.reference.ad_codes import AdCodeEntry, entries_by_id, load_index
from app.schemas.audience import AdCodeRef, Anchor, CreativeElementIn, CreativeSceneIn
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import execute, linear_graph, llm_error, local_step, outcome_status
from app.workflows.audience_types import DraftFinding, DroppedCounts, RiskCheckInput, RiskCheckOutcome
from app.workflows.quick_read import announce, claims_digest

STAGES = ("loading_inputs", "assessing_risks", "verifying_findings")
MAX_FINDINGS = 40
TEXT_KINDS = frozenset({"headline", "body", "cta", "tagline", "caption", "voiceover"})
EXCERPT_IN_PROMPT = 420
MODEL_NOTE = "Model interpretation for human review; not a verified violation."
PATTERN_NOTE = "Matched by a fixed wording pattern; for human review, not a verified violation."
NO_CLAIMS_NOTE = "No region claims were supplied, so findings rest on the ad-code index and model interpretation only."
RULES_NOTE = (
    f"Severity follows {RULES_VERSION}: base level by category, raised by a cited ad-code clause, observed or calculated "
    "region claims and hard-claim wording, and capped at medium without an ad-code clause or supporting claim."
)
INDEX_NOTE = "The ad-code index is a partial set of public ASCI clauses; it does not cover every rule that may apply."


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(t for t in (_flatten(x) for x in value.values()) if t)
    if isinstance(value, (list, tuple)):
        return " ".join(t for t in (_flatten(x) for x in value) if t)
    return "" if value is None else str(value)


def element_text(el: CreativeElementIn) -> str:
    """The text an element offers for verification: a string value, or the strings inside a structured value."""
    return _flatten(el.value)


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """Span of `quote` in `text`, ignoring case and runs of whitespace. The stored quote is always `text[start:end]`."""
    words = quote.split()
    if not words or not text:
        return None
    match = re.search(r"\s+".join(re.escape(w) for w in words), text, flags=re.IGNORECASE)
    return (match.start(), match.end()) if match else None


class RiskState(TypedDict, total=False):
    inp: RiskCheckInput
    texts: dict
    element_handles: dict
    claim_handles: dict
    ad_handles: dict
    digest: dict
    deterministic: list
    draft: list
    llm_failed: bool
    findings: list
    dropped: DroppedCounts
    cited: list
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def _ref(e: AdCodeEntry) -> AdCodeRef:
    return AdCodeRef(id=e.id, document=e.document, clause=e.clause, title=e.title, url=e.url, excerpt=e.excerpt)


def _anchor(el: CreativeElementIn, scenes: dict[str, CreativeSceneIn]) -> Anchor:
    scene = scenes.get(el.scene_id or "")
    return Anchor(scene_id=el.scene_id, start_ms=scene.start_ms if scene else None, end_ms=scene.end_ms if scene else None,
                  bbox=el.bbox)


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


async def rc_loading(state: RiskState, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 0, "Loading elements, claims and the ad-code index.")
    started, inp = time.perf_counter(), state["inp"]
    texts = {el.id: element_text(el) for el in inp.elements}
    element_handles = {f"E{n}": el for n, el in enumerate(inp.elements, 1)}
    claims_rows, claim_handles = claims_digest(inp.claims)
    index = load_index()
    ad_handles = {f"A{n}": e for n, e in enumerate(index.entries, 1)}
    ad_rows = [{"handle": h, "id": e.id, "document": e.document, "clause": e.clause, "topics": e.topics,
                "excerpt": e.excerpt[:EXCERPT_IN_PROMPT]} for h, e in ad_handles.items()]
    scene_by_id = {s.id: s for s in inp.scenes}
    element_rows = [{"handle": h, "kind": el.kind, "language": el.language, "script": el.script, "scene": el.scene_id,
                     "text": texts[el.id][:1500] if texts[el.id] else None, "has_position": el.bbox is not None}
                    for h, el in element_handles.items()]
    scene_rows = [{"scene": s.id, "start_ms": s.start_ms, "end_ms": s.end_ms, "summary": s.summary} for s in inp.scenes]

    deterministic: list[DraftFinding] = []
    brand = inp.context.brand
    for el in inp.elements:
        text = texts[el.id]
        if not text or el.kind not in TEXT_KINDS:
            continue
        anchor = _anchor(el, scene_by_id)
        for term in brand.prohibited_terms:
            span = locate(text, term)
            if span:
                decision = decide("brand_rule", ad_code_topics=[], claims=[], quote=text[span[0]:span[1]], deterministic=True)
                deterministic.append(DraftFinding(
                    element_id=el.id, category="brand_rule", severity=decision.severity, blocks_go=decision.blocks_go,
                    confidence_label=decision.confidence, anchor=anchor, quote=text[span[0]:span[1]], quote_start=span[0],
                    quote_end=span[1], verification="deterministic", observation=text[span[0]:span[1]],
                    interpretation="Brand Memory prohibits this term (deterministic, case-insensitive check).",
                    suggested_fix=None, ad_codes=[], claim_ids=[], source="deterministic_check",
                    severity_rules=[r.as_dict() for r in decision.rules], limitations=[]))
        for hit in scan_patterns(text):
            decision = decide(hit.category, ad_code_topics=[], claims=[], quote=text[hit.start:hit.end])
            refs = [_ref(entries_by_id()[i]) for i in hit.ad_code_ids if i in entries_by_id()]
            deterministic.append(DraftFinding(
                element_id=el.id, category=hit.category, severity=decision.severity, blocks_go=decision.blocks_go,
                confidence_label="insufficient", anchor=anchor, quote=text[hit.start:hit.end], quote_start=hit.start,
                quote_end=hit.end, verification="deterministic", observation=text[hit.start:hit.end],
                interpretation=PATTERN_TEXT[hit.pattern], suggested_fix=None, ad_codes=refs, claim_ids=[],
                source="deterministic_check", severity_rules=[r.as_dict() for r in decision.rules], limitations=[PATTERN_NOTE]))
    notes = [] if claim_handles else [NO_CLAIMS_NOTE]
    return {"texts": texts, "element_handles": element_handles, "claim_handles": claim_handles, "ad_handles": ad_handles,
            "digest": {"elements": element_rows, "scenes": scene_rows, "claims": claims_rows, "ad_codes": ad_rows},
            "deterministic": deterministic, "limitations": notes,
            "steps": [local_step(STAGES[0], "red_team", "omnicult", started)]}


async def rc_assessing(state: RiskState, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 1, "Assessing risks.")
    inp, digest = state["inp"], state["digest"]
    llm: LLMGateway = config["configurable"]["deps"].llm
    try:
        result = await agent.check(
            llm, stage=STAGES[1], region=inp.region.name, product_category=inp.product_category, elements=digest["elements"],
            scenes=digest["scenes"], claims=digest["claims"], ad_codes=digest["ad_codes"], brand=brand_block(inp.context.brand)[0])
    except LLMError as exc:
        saved = "Deterministic checks were saved." if state["deterministic"] else "No findings were saved; retrying is safe."
        error = llm_error(exc, STAGES[1], saved)
        if state["deterministic"]:
            return {"draft": [], "llm_failed": True, "partial": True, "error": error, "steps": [*state["steps"], exc.trace]}
        return {"draft": [], "llm_failed": True, "error": error, "stop": True, "steps": [*state["steps"], exc.trace]}
    return {"draft": result.value.findings, "steps": [*state["steps"], result.trace]}


async def rc_verifying(state: RiskState, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 2, "Verifying quotes and applying the severity rules.")
    started, inp = time.perf_counter(), state["inp"]
    dropped, kept = DroppedCounts(), []
    scene_by_id = {s.id: s for s in inp.scenes}
    order = {el.id: n for n, el in enumerate(inp.elements)}
    cited: list[UUID] = []
    for item in state.get("draft", []):
        el = state["element_handles"].get(norm(item.element))
        if el is None:
            dropped.unknown_element += 1
            continue
        text = state["texts"][el.id]
        span = None
        if item.quote:
            span = locate(text, item.quote)
            if span is None:
                dropped.unverified_quote += 1  # the model quoted text that is not in the element
                continue
            quote, verification = text[span[0]:span[1]], "quote_verified"
        elif el.kind in TEXT_KINDS or not text.strip():
            dropped.unverified_quote += 1  # a text element needs a quote; a non-text element needs a description to check against
            continue
        else:
            quote, verification = None, "element_reference"
        if any(f["element"] == el.id and f["category"] == item.category
               and ((f["span"] is None and span is None) or (f["span"] and span and _overlap(f["span"], span))) for f in kept):
            dropped.duplicate += 1
            continue
        refs, lost_a = pick(item.ad_codes, state["ad_handles"])
        refs_fit = [e for e in refs if topics_fit(item.category, e.topics)]
        claims, lost_c = pick(item.claims, state["claim_handles"])
        dropped.invalid_references += lost_a + lost_c + (len(refs) - len(refs_fit))
        decision = decide(
            item.category, ad_code_topics=[e.topics for e in refs_fit],
            claims=[ClaimSupport(c.kind, c.confidence) for c in claims], quote=quote)
        cited += [c.id for c in claims if c.id not in cited]
        kept.append({
            "element": el.id, "span": span, "category": item.category,
            "draft": DraftFinding(
                element_id=el.id, category=item.category, severity=decision.severity, blocks_go=decision.blocks_go,
                confidence_label=decision.confidence, anchor=_anchor(el, scene_by_id), quote=quote,
                quote_start=span[0] if span else None, quote_end=span[1] if span else None, verification=verification,
                observation=item.observation, interpretation=item.interpretation, suggested_fix=item.suggested_fix,
                ad_codes=[_ref(e) for e in refs_fit], claim_ids=[c.id for c in claims], source="model_assessment",
                severity_rules=[r.as_dict() for r in decision.rules],
                limitations=[MODEL_NOTE]),
        })
    final: list[DraftFinding] = []
    for d in state["deterministic"]:
        covered = d.source == "deterministic_check" and d.category != "brand_rule" and any(
            f["element"] == d.element_id and f["span"] and d.quote_start is not None and d.quote_end is not None
            and _overlap(f["span"], (d.quote_start, d.quote_end)) for f in kept)
        if covered:
            dropped.duplicate += 1  # the model's richer finding on the same words replaces the pattern hit
        else:
            final.append(d)
    final += [f["draft"] for f in kept]
    final.sort(key=lambda f: (not f.blocks_go, -("low medium high".split().index(f.severity)), order.get(f.element_id, 0),
                              f.quote_start if f.quote_start is not None else -1))
    final = final[:MAX_FINDINGS]
    limitations = list(state["limitations"])
    if dropped.unverified_quote or dropped.unknown_element:
        limitations.append(
            f"{dropped.unverified_quote + dropped.unknown_element} model finding(s) were dropped because their quote or element "
            "could not be verified against the creative.")
    if dropped.invalid_references:
        limitations.append(DROPPED_NOTE)
    return {"findings": final, "dropped": dropped, "cited": cited, "limitations": limitations,
            "steps": [*state["steps"], local_step(STAGES[2], "red_team", "omnicult", started)]}


GRAPH = linear_graph(RiskState, [(STAGES[0], rc_loading), (STAGES[1], rc_assessing), (STAGES[2], rc_verifying)])


async def run_risk_check(inp: RiskCheckInput, llm: LLMGateway, progress: Any = None) -> RiskCheckOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm), progress, inp.context.mode)
    findings, dropped, cited = state.get("findings", []), state.get("dropped", DroppedCounts()), state.get("cited", [])
    brand_note = applied_note([f"Prohibited term: {t}" for t in inp.context.brand.prohibited_terms])
    notes = [RULES_NOTE, INDEX_NOTE, brand_note]
    return RiskCheckOutcome(
        status=outcome_status(state), findings=findings, dropped=dropped, cited_claim_ids=cited,
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])), steps=state.get("steps", []),
        error=state.get("error"),
    )

