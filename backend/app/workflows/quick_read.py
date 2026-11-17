"""Quick Read and Audience Study: synthetic panels sampled by state, language, city tier and age band, grounded in the
region's claims, with deterministic tallies (the existing mvp-1 aggregation and the population tallies).

Quick Read is one small panel, one creative, one region. Audience Study is a bounded larger panel interviewed with the
population interview schema across one or more states. In both, the model writes language and code does the counting;
everything the model says is a synthetic interpretation, and a statement is "claim_supported" only when it cites a stored
claim that is observed or calculated.
"""

import asyncio
import time
from collections import Counter
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import quick_read as agent
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, norm, pick
from app.agents.brand import brand_block
from app.analytics import aggregate
from app.analytics.panel import CITY_TIER_LABELS
from app.analytics.population import distribution, normalize_label, stance_distribution, theme_counts
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.audience import (
    SHARED_MODEL_NOTE,
    DimensionSlice,
    GroundedPoint,
    GroundingClaim,
    MessageSurvival,
    MessageUnderstanding,
    PointCount,
    QuickReadResponse,
    QuickReadSummary,
    StudyInterview,
    StudySummary,
)
from app.schemas.common import Market, StepTrace
from app.schemas.population import Interview, InterviewAnswer
from app.schemas.runs import RunError
from app.schemas.studies import DimensionResults
from app.workflows._common import execute, linear_graph, llm_error, local_step, merge_steps, outcome_status
from app.workflows.audience_types import (
    AudienceStudyInput,
    AudienceStudyOutcome,
    GroundingStats,
    PanelMember,
    QuickReadInput,
    QuickReadOutcome,
)

QUICK_READ_STAGES = ("loading_context", "generating_reactions", "aggregating_results")
STUDY_STAGES = ("loading_context", "running_interviews", "aggregating_results", "analysing_results")
CONCURRENCY = 2
MAX_CLAIMS = 30
MAX_POINTS = 8
MAX_FOLLOW_UPS = 5
DEMO_NOTE = "Demo mode: every model result in this run is a labelled fixture; no model was called."
INDEPENDENCE_NOTE = "Repeated generations from one model are not independent confirmation."
SURVIVAL_NOTE = "Counts of synthetic participants who restated the message correctly; not a measure of real comprehension."
CATEGORY_PRIORITY = ("sensitivity", "symbol", "colour", "custom", "humour", "family", "language", "script", "festival",
                     "moment", "food", "trend", "media", "demographic")
KIND_RANK = {"observed": 0, "calculated": 1, "synthetic": 2, "interpretation": 3, "unverified": 4}
CONFIDENCE_RANK = {"high": 0, "moderate": 1, "low": 2}


async def announce(config: RunnableConfig, stages: Sequence[str], index: int, message: str) -> None:
    progress = config["configurable"].get("progress")
    if progress is not None:
        if config["configurable"]["mode"] == "demo":
            message = message.rstrip(".") + " (demo fixtures)."
        await progress(stages[index], index, len(stages), message)


def claims_digest(claims: Sequence[GroundingClaim], limit: int = MAX_CLAIMS) -> tuple[list[dict], dict[str, GroundingClaim]]:
    """Numbered claims for the prompt: sensitive categories first, then strongest kind and confidence."""
    def rank(c: GroundingClaim) -> tuple:
        cat = CATEGORY_PRIORITY.index(c.category) if c.category in CATEGORY_PRIORITY else len(CATEGORY_PRIORITY)
        return (cat, KIND_RANK[c.kind], CONFIDENCE_RANK[c.confidence], str(c.id))

    chosen = sorted(claims, key=rank)[:limit]
    handles = {f"C{i}": c for i, c in enumerate(chosen, 1)}
    digest = [{"handle": h, "region": c.region_code, "category": c.category, "statement": c.value_text, "kind": c.kind,
               "confidence": c.confidence} for h, c in handles.items()]
    return digest, handles


def ground(points: Sequence[agent.PointOut], handles: dict[str, GroundingClaim], stats: GroundingStats) -> list[GroundedPoint]:
    """Map the model's citations back to stored claims. `claim_supported` needs an observed or calculated claim; a point
    that cites only interpretations or unverified claims, or nothing, stays an interpretation."""
    out = []
    for p in points:
        cited, lost = pick(p.claims, handles)
        stats.dropped_handles += lost
        strong = any(c.kind in ("observed", "calculated") for c in cited)
        out.append(GroundedPoint(
            text=p.text, basis="claim_supported" if strong else "interpretation", claim_ids=[c.id for c in cited],
            claim_kinds=list(dict.fromkeys(c.kind for c in cited)),
        ))
        stats.claim_supported += strong
        stats.interpretation += not strong
        stats.cited_claim_ids += [c.id for c in cited if c.id not in stats.cited_claim_ids]
    return out


def _copy_text(creative: Any) -> str:
    return " ".join(p for p in (creative.headline, creative.body, creative.call_to_action) if p).casefold()


def _members(batch: Sequence[PanelMember]) -> list[dict]:
    return [m.model_dump(include={"ordinal", "persona", "state_name", "language_name", "city_tier", "age_band", "traits"})
            for m in batch]


def _tally_points(items: Sequence[tuple[GroundedPoint, Any]], limit: int = MAX_POINTS) -> list[PointCount]:
    """Group identical statements (case and edge punctuation ignored); each participant counts a statement once."""
    groups: dict[str, dict] = {}
    for point, participant in items:
        key = normalize_label(point.text)
        g = groups.setdefault(key, {"text": point.text, "who": set(), "supported": False, "claims": []})
        g["who"].add(participant)
        g["supported"] = g["supported"] or point.basis == "claim_supported"
        g["claims"] += [c for c in point.claim_ids if c not in g["claims"]]
    ranked = sorted(groups.values(), key=lambda g: -len(g["who"]))[:limit]  # stable: first appearance breaks ties
    return [PointCount(text=g["text"], participants=len(g["who"]), basis="claim_supported" if g["supported"] else "interpretation",
                       claim_ids=g["claims"]) for g in ranked]


# --- Quick Read ----------------------------------------------------------------------------------------------------------


class QuickState(TypedDict, total=False):
    inp: QuickReadInput
    digest: list[dict]
    handles: dict[str, GroundingClaim]
    brand_text: str
    responses: dict
    stats: GroundingStats
    summary: QuickReadSummary | None
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def qr_loading(state: QuickState, config: RunnableConfig) -> dict:
    await announce(config, QUICK_READ_STAGES, 0, "Loading the creative and the region's claims.")
    started, inp = time.perf_counter(), state["inp"]
    digest, handles = claims_digest(inp.claims)
    notes = [] if handles else [f"No claims are recorded for {inp.region.name}, so every statement below is a model interpretation."]
    return {"digest": digest, "handles": handles, "brand_text": brand_block(inp.context.brand)[0], "limitations": notes,
            "stats": GroundingStats(), "steps": [local_step(QUICK_READ_STAGES[0], "audience", "omnicult", started)]}


async def qr_generating(state: QuickState, config: RunnableConfig) -> dict:
    await announce(config, QUICK_READ_STAGES, 1, "Generating synthetic reactions.")
    started, inp = time.perf_counter(), state["inp"]
    llm: LLMGateway = config["configurable"]["deps"].llm
    gate = asyncio.Semaphore(CONCURRENCY)
    batches = [inp.participants[i : i + agent.MAX_PER_CALL] for i in range(0, len(inp.participants), agent.MAX_PER_CALL)]
    creative = content_dict(inp.creative)

    async def call(index: int, batch: list[PanelMember]):
        async with gate:
            try:
                rows = agent.participant_rows(_members(batch), inp.seed, index * agent.MAX_PER_CALL)
                return await agent.quick_read(
                    llm, stage=QUICK_READ_STAGES[1], rows=rows, creative=creative, intended_message=inp.intended_message,
                    region=inp.region.name, claims=state["digest"], brand=state["brand_text"], seed=inp.seed + index)
            except LLMError as exc:
                return exc

    results = await asyncio.gather(*(call(i, b) for i, b in enumerate(batches)))
    responses, traces, failures, stats = {}, [], [], state["stats"]
    copy, limitations = _copy_text(inp.creative), list(state["limitations"])
    for batch, result in zip(batches, results):
        if isinstance(result, LLMError):
            failures.append(result)
            traces.append(result.trace)
            limitations.append(f"Reactions for {len(batch)} participant(s) could not be generated ({result.code}).")
            continue
        traces.append(result.trace)
        by_handle = {norm(o.participant): o for o in result.value.participants}
        for n, member in enumerate(batch, 1):
            item = by_handle.get(f"P{n}")
            if item is None:
                continue
            passage = item.relevant_passage if item.relevant_passage and item.relevant_passage.casefold() in copy else None
            responses[member.id] = QuickReadResponse(
                first_reaction=item.first_reaction, sentiment=item.sentiment,
                message=MessageUnderstanding(restated=item.message_restated, survival=item.message_survival),
                positives=ground(item.positives, state["handles"], stats), negatives=ground(item.negatives, state["handles"], stats),
                confusion=ground(item.confusion, state["handles"], stats),
                regional_concerns=ground(item.regional_concerns, state["handles"], stats),
                ratings=item.ratings.model_dump(), follow_up_question=item.follow_up_question, quoted_passage=passage,
            )
    step = merge_steps(QUICK_READ_STAGES[1], "audience", traces, started)
    if stats.dropped_handles:
        limitations.append(DROPPED_NOTE)
    if not responses:
        error = llm_error(failures[0], QUICK_READ_STAGES[1], "No reactions were saved; retrying is safe.") if failures else RunError(
            code="RUN_FAILED", message="The model returned no reaction for any participant.", stage=QUICK_READ_STAGES[1], retryable=True)
        return {"responses": {}, "steps": [*state["steps"], step], "limitations": limitations, "error": error, "stop": True}
    update: dict = {"responses": responses, "steps": [*state["steps"], step], "limitations": limitations, "stats": stats}
    missing = len(inp.participants) - len(responses)
    if failures:
        update |= {"partial": True, "error": llm_error(failures[0], QUICK_READ_STAGES[1], f"{len(responses)} reactions were saved.")}
    elif missing:
        update["limitations"] = [*limitations, f"The model returned reactions for {len(responses)} of {len(inp.participants)} participants."]
        update["partial"] = True
    return update


async def qr_aggregating(state: QuickState, config: RunnableConfig) -> dict:
    await announce(config, QUICK_READ_STAGES, 2, "Aggregating the panel.")
    started, inp = time.perf_counter(), state["inp"]
    pairs = [(m, state["responses"][m.id]) for m in inp.participants if m.id in state["responses"]]
    rated = [r for _, r in pairs]
    survival = Counter(r.message.survival for r in rated)
    n = len(rated)
    dims = {d: aggregate(d, [r.ratings[d] for r in rated]) for d in ("clarity", "cultural_relevance", "cultural_risk")}

    def points(attr: str) -> list[PointCount]:
        return _tally_points([(p, m.id) for m, r in pairs for p in getattr(r, attr)])

    asked: dict[str, str] = {}
    for r in rated:
        asked.setdefault(normalize_label(r.follow_up_question), r.follow_up_question.strip())
    summary = QuickReadSummary(
        sentiment=stance_distribution(r.sentiment for r in rated),
        message_survival=MessageSurvival(
            understood=survival["understood"], partial=survival["partial"], misunderstood=survival["misunderstood"],
            denominator=n, understood_rate=round(survival["understood"] / n, 4) if n else None, note=SURVIVAL_NOTE),
        dimension_results=DimensionResults(**dims), positives=points("positives"), negatives=points("negatives"),
        confusion=points("confusion"), regional_concerns=points("regional_concerns"),
        suggested_follow_ups=list(asked.values())[:MAX_FOLLOW_UPS],
    )
    return {"summary": summary, "steps": [*state["steps"], local_step(QUICK_READ_STAGES[2], "analyst", "omnicult", started)]}


QUICK_GRAPH = linear_graph(QuickState, [(QUICK_READ_STAGES[0], qr_loading), (QUICK_READ_STAGES[1], qr_generating),
                                        (QUICK_READ_STAGES[2], qr_aggregating)])


async def run_quick_read(inp: QuickReadInput, llm: LLMGateway, progress: Any = None) -> QuickReadOutcome:
    state = await execute(QUICK_GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm), progress,
                          inp.context.mode)
    demo = inp.context.mode == "demo"
    notes = [SYNTHETIC_NOTE, INDEPENDENCE_NOTE, *( [DEMO_NOTE, DEMO_OUTPUT_NOTE] if demo else [])]
    return QuickReadOutcome(
        status=outcome_status(state), responses=state.get("responses", {}), summary=state.get("summary"),
        grounding=state.get("stats", GroundingStats()),
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])), steps=state.get("steps", []),
        error=state.get("error"),
    )


# --- Audience Study ------------------------------------------------------------------------------------------------------


class StudyState(TypedDict, total=False):
    inp: AudienceStudyInput
    digest: list[dict]
    handles: dict[str, GroundingClaim]
    interviews: dict
    rows: dict
    summary: StudySummary | None
    tallies: dict
    quotes: list
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


STUDY_BATCH = 8


async def st_loading(state: StudyState, config: RunnableConfig) -> dict:
    await announce(config, STUDY_STAGES, 0, "Loading the creative and the regions' claims.")
    started, inp = time.perf_counter(), state["inp"]
    digest, handles = claims_digest(inp.claims)
    notes = [] if handles else ["No claims are recorded for the selected states, so participants had no regional grounding."]
    notes.append("Interviews do not cite claims: the region claims were supplied as context, not as per-answer evidence.")
    return {"digest": digest, "handles": handles, "limitations": notes,
            "steps": [local_step(STUDY_STAGES[0], "audience", "omnicult", started)]}


def _interview_row(inp: AudienceStudyInput, member: PanelMember, item: Any | None, model_id: str | None) -> tuple[Interview, StudyInterview]:
    base = {"id": member.id, "run_id": inp.context.run_id, "participant_id": member.id, "group_id": member.state_code,
            "region": Market(country_code="IN", display_name=member.state_name[:100]), "content_version_id": inp.content_version_id,
            "model_id": model_id, "evidence_ids": []}
    if item is None:
        return (Interview(**base, status="failed", answers=[], reaction=None, comprehension=None, themes=[], concerns=[],
                          misunderstanding=None),
                StudyInterview(status="failed", reaction=None, comprehension=None, themes=[], concerns=[], misunderstanding=None, answers=[]))
    answers = [InterviewAnswer(question_id=q, question=text, answer=getattr(item.answers, q)) for q, text in agent.CORE_QUESTIONS]
    answers += [InterviewAnswer(question_id=f"follow_up_{k}", question=f.question, answer=f.answer) for k, f in enumerate(item.follow_ups, 1)]
    interview = Interview(**base, status="completed", answers=answers, reaction=item.reaction, comprehension=item.comprehension,
                          themes=item.themes, concerns=item.concerns, misunderstanding=item.misunderstanding)
    return interview, StudyInterview(status="completed", reaction=item.reaction, comprehension=item.comprehension, themes=item.themes,
                                     concerns=item.concerns, misunderstanding=item.misunderstanding, answers=answers)


async def st_interviewing(state: StudyState, config: RunnableConfig) -> dict:
    await announce(config, STUDY_STAGES, 1, "Running interviews.")
    started, inp = time.perf_counter(), state["inp"]
    llm: LLMGateway = config["configurable"]["deps"].llm
    gate = asyncio.Semaphore(CONCURRENCY)
    batches = [inp.participants[i : i + STUDY_BATCH] for i in range(0, len(inp.participants), STUDY_BATCH)]
    creative = content_dict(inp.creative)
    region = ", ".join(r.name for r in inp.regions)

    async def call(index: int, batch: list[PanelMember]):
        async with gate:
            rows = agent.participant_rows(_members(batch), inp.seed, index * STUDY_BATCH)
            try:
                return await agent.study_interviews(
                    llm, stage=STUDY_STAGES[1], rows=rows, depth=inp.depth, creative=creative, region=region,
                    claims=state["digest"], seed=inp.seed + index)
            except LLMError as exc:
                return exc

    results = await asyncio.gather(*(call(i, b) for i, b in enumerate(batches)))
    interviews, rows, traces, failed_batches = {}, {}, [], 0
    for batch, result in zip(batches, results):
        if isinstance(result, LLMError):
            failed_batches += 1
            traces.append(result.trace)
            model_id, by_handle = result.trace.model_id, {}
        else:
            traces.append(result.trace)
            model_id, by_handle = result.trace.model_id, {norm(i.participant): i for i in result.value.interviews}
        for n, member in enumerate(batch, 1):
            interview, view = _interview_row(inp, member, by_handle.get(f"P{n}"), model_id)
            interviews[member.id], rows[member.id] = interview, view
    step = merge_steps(STUDY_STAGES[1], "audience", traces, started)
    done = sum(1 for v in rows.values() if v.status == "completed")
    limitations = list(state["limitations"])
    if done < len(rows):
        limitations.append(f"{len(rows) - done} of {len(rows)} interviews failed and are excluded from every rate.")
    if not done:
        first = next((r for r in results if isinstance(r, LLMError)), None)
        error = llm_error(first, STUDY_STAGES[1], "No interview was saved; retrying is safe.") if first else RunError(
            code="RUN_FAILED", message="No interview completed.", stage=STUDY_STAGES[1], retryable=True)
        return {"interviews": interviews, "rows": rows, "steps": [*state["steps"], step], "limitations": limitations,
                "error": error, "stop": True}
    return {"interviews": interviews, "rows": rows, "steps": [*state["steps"], step], "limitations": limitations,
            "partial": done < len(rows)}


async def st_aggregating(state: StudyState, config: RunnableConfig) -> dict:
    await announce(config, STUDY_STAGES, 2, "Tallying the interviews.")
    started, inp = time.perf_counter(), state["inp"]
    interviews = [state["interviews"][m.id] for m in inp.participants]
    done = [i for i in interviews if i.status == "completed"]
    names = {r.code: r.name for r in inp.regions}
    slices: list[DimensionSlice] = []
    by_member = {m.id: m for m in inp.participants}
    for dim, label_of, key in (
        ("states", lambda v: names.get(v, v), lambda m: m.state_code),
        ("languages", lambda v: next((m.language_name for m in inp.participants if m.language == v), v), lambda m: m.language),
        ("city_tiers", lambda v: CITY_TIER_LABELS.get(v, v), lambda m: m.city_tier),
        ("age_bands", lambda v: f"age {v}", lambda m: m.age_band),
    ):
        for value in dict.fromkeys(key(m) for m in inp.participants):
            subset = [i for i in interviews if key(by_member[i.participant_id]) == value]
            slices.append(DimensionSlice(dimension=dim, value=value, label=label_of(value), participants=len(subset),
                                         distribution=distribution(subset)))
    summary = StudySummary(
        overall=distribution(interviews), by_dimension=slices, themes=theme_counts(done, "themes", 10),
        concerns=theme_counts(done, "concerns", 10), misunderstandings=theme_counts(done, "misunderstanding", 5),
        group_differences=[], evidence_gaps=[], next_actions=[])
    tallies = {
        "overall": summary.overall.model_dump(),
        "by_dimension": [{"dimension": s.dimension, "value": s.value, "label": s.label, "n": s.participants,
                          "distribution": s.distribution.model_dump()} for s in slices],
        "themes": [t.model_dump(include={"label", "count", "share"}) for t in summary.themes],
        "concerns": [t.model_dump(include={"label", "count", "share"}) for t in summary.concerns],
        "misunderstandings": [t.model_dump(include={"label", "count", "share"}) for t in summary.misunderstandings],
    }
    quotes = []
    for code in names:  # the lowest-ordinal completed interview per state: a deterministic sample
        mine = sorted((i for i in done if by_member[i.participant_id].state_code == code), key=lambda i: by_member[i.participant_id].ordinal)[:1]
        quotes += [{"state": names[code], "reaction": i.reaction, "first_impression": i.answers[0].answer} for i in mine]
    return {"summary": summary, "tallies": tallies, "quotes": quotes,
            "steps": [*state["steps"], local_step(STUDY_STAGES[2], "analyst", "omnicult", started)]}


async def st_analysing(state: StudyState, config: RunnableConfig) -> dict:
    await announce(config, STUDY_STAGES, 3, "Interpreting the tallies.")
    llm: LLMGateway = config["configurable"]["deps"].llm
    try:
        result = await agent.study_analysis(llm, stage=STUDY_STAGES[3], tallies=state["tallies"], quotes=state["quotes"])
    except LLMError as exc:
        return {"partial": True, "error": state.get("error") or llm_error(exc, STUDY_STAGES[3], "The interviews and tallies were saved."),
                "steps": [*state["steps"], exc.trace]}
    out = result.value
    summary = state["summary"].model_copy(update={
        "group_differences": list(out.group_differences), "evidence_gaps": list(out.evidence_gaps),
        "next_actions": list(out.next_actions)})
    return {"summary": summary, "steps": [*state["steps"], result.trace]}


STUDY_GRAPH = linear_graph(StudyState, [(STUDY_STAGES[0], st_loading), (STUDY_STAGES[1], st_interviewing),
                                        (STUDY_STAGES[2], st_aggregating), (STUDY_STAGES[3], st_analysing)])


async def run_audience_study(inp: AudienceStudyInput, llm: LLMGateway, progress: Any = None) -> AudienceStudyOutcome:
    state = await execute(STUDY_GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm), progress,
                          inp.context.mode)
    demo = inp.context.mode == "demo"
    notes = [SYNTHETIC_NOTE, SHARED_MODEL_NOTE, "The sample is not statistically representative and does not establish purchase intent.",
             *([DEMO_NOTE, DEMO_OUTPUT_NOTE] if demo else [])]
    return AudienceStudyOutcome(
        status=outcome_status(state), interviews=state.get("rows", {}), summary=state.get("summary"),
        grounding=GroundingStats(), limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"),
    )
