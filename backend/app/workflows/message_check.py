"""Message Check: does the intended message survive in each region? A lighter Quick Read (lab-t3).

Per region, synthetic participants read only the regional copy and restate and recall the message; a separate comparison marks
each key point of the intended message. Both steps are model calls in separate voices, batched per region. Scores, verdicts,
rates and recommendations are computed from the marks at read time by `analytics.message_check`, never by the model. A
participant whose restatement or comparison the model did not return is left out of every rate and reported, not guessed.
"""

import asyncio
import time
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.agents import message_check as agent
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, norm
from app.agents.quick_read import participant_rows
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import execute, linear_graph, llm_error, local_step, merge_steps, outcome_status
from app.workflows.audience_types import PanelMember
from app.workflows.lab_t3_types import JudgementRecord, MessageCheckInput, MessageCheckOutcome, ReadingRecord
from app.workflows.quick_read import DEMO_NOTE, INDEPENDENCE_NOTE, announce

STAGES = ("loading_context", "reading_message", "comparing_restatements", "aggregating_results")
CONCURRENCY = 2


class State(TypedDict, total=False):
    inp: MessageCheckInput
    groups: list[tuple[Any, list[PanelMember]]]  # (target, its participants)
    readings: dict[UUID, ReadingRecord]
    judgements: dict[UUID, JudgementRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def _batches(people: list[PanelMember]) -> list[list[PanelMember]]:
    return [people[i : i + agent.MAX_PER_CALL] for i in range(0, len(people), agent.MAX_PER_CALL)]


def _dims(batch: list[PanelMember]) -> list[dict]:
    return [m.model_dump(include={"ordinal", "persona", "state_name", "language_name", "city_tier", "age_band", "traits"}) for m in batch]


async def loading(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 0, "Loading the copy, the intended message and its key points.")
    started, inp = time.perf_counter(), state["inp"]
    groups = [(t, sorted((m for m in inp.participants if m.state_code == t.region_code), key=lambda m: m.ordinal)) for t in inp.targets]
    return {"groups": groups, "readings": {}, "judgements": {}, "steps": [local_step(STAGES[0], "audience", "omnicult", started)]}


async def reading(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 1, "Participants read the copy and restate it.")
    started, inp, llm = time.perf_counter(), state["inp"], config["configurable"]["deps"].llm
    gate = asyncio.Semaphore(CONCURRENCY)
    points = list(inp.key_points.values())

    async def call(target, index: int, batch: list[PanelMember]):
        async with gate:
            try:
                rows = participant_rows(_dims(batch), inp.seed, index * agent.MAX_PER_CALL)
                return await agent.read_message(
                    llm, stage=STAGES[1], rows=rows, creative=content_dict(target.creative), region=target.region_name,
                    key_points=points, intended_message=inp.intended_message, seed=inp.seed + index)
            except LLMError as exc:
                return exc

    jobs = [(t, i, b) for t, people in state["groups"] for i, b in enumerate(_batches(people))]
    results = await asyncio.gather(*(call(t, i, b) for t, i, b in jobs))
    readings: dict[UUID, ReadingRecord] = {}
    traces, failures = [], []
    for (_, _, batch), result in zip(jobs, results):
        if isinstance(result, LLMError):
            failures.append(result)
            traces.append(result.trace)
            continue
        traces.append(result.trace)
        said = {norm(o.participant): o for o in result.value.participants}
        for n, member in enumerate(batch, 1):
            out = said.get(f"P{n}")
            if out is not None:
                readings[member.id] = ReadingRecord(restated=out.restated, restated_en=out.restated_en, recall=list(out.recall))
    step = merge_steps(STAGES[1], "audience", traces, started)
    total = len(inp.participants)
    notes = list(state.get("limitations", []))
    update: dict = {"readings": readings, "steps": [*state["steps"], step], "limitations": notes}
    if not readings:
        update |= {"stop": True, "error": llm_error(failures[0], STAGES[1], "No restatement was saved; retrying is safe.") if failures else RunError(
            code="RUN_FAILED", message="The model returned no restatement for any participant.", stage=STAGES[1], retryable=True)}
        return update
    if failures:
        update |= {"partial": True, "error": llm_error(failures[0], STAGES[1], f"{len(readings)} restatements were saved.")}
    if len(readings) < total:
        notes.append(f"Restatements came back for {len(readings)} of {total} participants; the others are left out of every rate.")
        update["partial"] = True
    return update


async def comparing(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 2, "Comparing each restatement with the key points.")
    started, inp, llm = time.perf_counter(), state["inp"], config["configurable"]["deps"].llm
    gate = asyncio.Semaphore(CONCURRENCY)
    readings = state["readings"]
    point_ids = list(inp.key_points)

    async def call(target, index: int, batch: list[PanelMember]):
        async with gate:
            rows = [{"participant": f"P{n}", **readings[m.id].model_dump()} for n, m in enumerate(batch, 1)]
            try:
                return await agent.compare(
                    llm, stage=STAGES[2], intended_message=inp.intended_message, key_points=inp.key_points,
                    copy=content_dict(target.creative), rows=rows, seed=inp.seed + 50 + index)
            except LLMError as exc:
                return exc

    jobs = [(t, i, b) for t, people in state["groups"] for i, b in enumerate(_batches([m for m in people if m.id in readings]))]
    results = await asyncio.gather(*(call(t, i, b) for t, i, b in jobs)) if jobs else []
    judgements: dict[UUID, JudgementRecord] = {}
    traces, failures, dropped, incomplete = [], [], 0, 0
    for (_, _, batch), result in zip(jobs, results):
        if isinstance(result, LLMError):
            failures.append(result)
            traces.append(result.trace)
            continue
        traces.append(result.trace)
        said = {norm(o.participant): o for o in result.value.participants}
        for n, member in enumerate(batch, 1):
            out = said.get(f"P{n}")
            if out is None:
                incomplete += 1
                continue
            marks = {norm(p.point): p for p in out.points if norm(p.point) in inp.key_points}
            dropped += len(out.points) - len(marks)
            if set(marks) != set(point_ids):
                incomplete += 1  # a participant must be marked on every key point or they are left out, not marked "no"
                continue
            judgements[member.id] = JudgementRecord(
                coverage={k: marks[k].restated for k in point_ids}, recalled={k: marks[k].recalled for k in point_ids},
                misreading=(out.misreading.label, out.misreading.why) if out.misreading else None)
    step = merge_steps(STAGES[2], "analyst", traces, started) if traces else local_step(STAGES[2], "analyst", None, started, status="skipped")
    notes = list(state.get("limitations", []))
    if dropped:
        notes.append(DROPPED_NOTE)
    if incomplete:
        notes.append(f"{incomplete} restatements were not fully compared and are left out of every rate.")
    update: dict = {"judgements": judgements, "steps": [*state["steps"], step], "limitations": notes}
    if not judgements:
        update |= {"stop": True, "error": llm_error(failures[0], STAGES[2], "The restatements were saved but could not be compared.") if failures else RunError(
            code="RUN_FAILED", message="The comparison returned no usable mark for any participant.", stage=STAGES[2], retryable=True)}
        return update
    if failures or incomplete:
        update["partial"] = True
        if failures and not state.get("error"):
            update["error"] = llm_error(failures[0], STAGES[2], f"{len(judgements)} restatements were compared.")
    return update


async def aggregating(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 3, "Scoring and counting.")
    return {"steps": [*state["steps"], local_step(STAGES[3], "analyst", "omnicult", time.perf_counter())]}


GRAPH = linear_graph(State, [(STAGES[0], loading), (STAGES[1], reading), (STAGES[2], comparing), (STAGES[3], aggregating)])


async def run_message_check(inp: MessageCheckInput, llm: LLMGateway, progress: Any = None) -> MessageCheckOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm), progress, inp.context.mode)
    demo = inp.context.mode == "demo"
    notes = [SYNTHETIC_NOTE, INDEPENDENCE_NOTE, *([DEMO_NOTE, DEMO_OUTPUT_NOTE] if demo else [])]
    return MessageCheckOutcome(
        status=outcome_status(state), readings=state.get("readings", {}), judgements=state.get("judgements", {}),
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])), steps=state.get("steps", []), error=state.get("error"))
