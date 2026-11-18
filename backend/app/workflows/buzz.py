"""Buzz Simulator: synthetic social reactions to a creative, per region and language (lab-t3).

Extends the population simulation: the seeded peer network and the round structure come from `analytics.population` (through
`analytics.buzz`), while the actions are the new part: post, reply, reshare or scroll past, in the account's own language.
Each account acts once, in the round after it first sees the creative; a post or reshare shows the creative to the accounts that
see that account's posts. The model writes the text and labels the stance; code decides who is shown what and counts it
(`analytics.buzz`). It illustrates how this synthetic population could pass a creative on and never forecasts real virality.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.runnables import RunnableConfig

from app.agents import buzz as agent
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, norm
from app.analytics import buzz as stats
from app.analytics.lab_text import wording_overlap
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import execute, linear_graph, llm_error, local_step, merge_steps, outcome_status
from app.workflows.audience_types import PanelMember
from app.workflows.lab_t3_types import BuzzInput, BuzzIO, BuzzOutcome, DraftAct
from app.workflows.quick_read import DEMO_NOTE, INDEPENDENCE_NOTE, announce

STAGES = ("loading_context", "simulating_rounds", "tallying_spread")
BATCH = 10
CONCURRENCY = 2
OPEN_NOTE = ("An illustration of how this synthetic population could pass the creative on, given its network and the exposure setting. "
             "It is not a forecast of real reach, views or virality.")


def handle_of(m: PanelMember) -> str:
    return f"A{m.ordinal + 1}"


def reference_message(creative: Any, intended_message: str | None) -> tuple[str, str]:
    """The text a passed-on message is compared with: the intended message, else the creative's own copy."""
    if intended_message:
        return intended_message, "intended_message"
    return " ".join(p for p in (creative.headline, creative.body, creative.call_to_action) if p), "creative"


class State(TypedDict, total=False):
    inp: BuzzInput
    members: dict[UUID, PanelMember]
    network: dict[UUID, list[UUID]]
    followers: dict[UUID, list[UUID]]
    seed_ids: list[UUID]
    exposed_by: dict[UUID, UUID | None]
    acts: list[DraftAct]
    rounds_run: int
    ended: str
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def loading(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 0, "Building the population and its network.")
    started, inp = time.perf_counter(), state["inp"]
    network = stats.build_network(inp.participants, inp.degree, inp.seed)
    seed_ids = stats.seed_audience(inp.participants, inp.initial_exposure, inp.seed)
    return {"members": {m.id: m for m in inp.participants}, "network": network, "followers": stats.followers(network), "seed_ids": seed_ids,
            "exposed_by": {pid: None for pid in seed_ids}, "acts": [], "rounds_run": 0, "ended": "rounds_used",
            "steps": [local_step(STAGES[0], "audience", "omnicult", started)]}


def _feed(account: PanelMember, reached_by: UUID | None, state: State, creative: dict, handle_to_act: dict[str, DraftAct]) -> list[dict]:
    """What the account sees: the post that reached it (or the brand's creative), then up to two other posts from accounts it follows."""
    members, acts = state["members"], state["acts"]
    feed: list[dict] = []
    if reached_by is None:
        feed.append({"handle": "F1", "from": "the brand", "kind": "brand_post", "text": creative})
    else:
        by = next(a for a in acts if a.participant_id == reached_by)
        feed.append({"handle": "F1", "from": handle_of(members[reached_by]), "kind": by.action,
                     "text": by.text_en or by.text or "(reshared without a comment)", "passes_on": by.message_gloss})
        handle_to_act["F1"] = by
    seen = {reached_by}
    for source in state["network"][account.id]:
        if len(feed) >= 3:
            break
        post = next((a for a in acts if a.participant_id == source and a.action in ("post", "share") and source not in seen), None)
        if post is not None:
            seen.add(source)
            handle = f"F{len(feed) + 1}"
            feed.append({"handle": handle, "from": handle_of(members[source]), "kind": post.action, "text": post.text_en or post.text or "",
                         "passes_on": post.message_gloss})
            handle_to_act[handle] = post
    return feed


async def simulating(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 1, "Simulating rounds.")
    started, inp, deps = time.perf_counter(), state["inp"], config["configurable"]["deps"]
    progress = config["configurable"].get("progress")
    members, followers = state["members"], state["followers"]
    order = {pid: m.ordinal for pid, m in members.items()}
    creative = content_dict(inp.creative)
    reference, _ = reference_message(inp.creative, inp.intended_message)
    acts: list[DraftAct] = []
    exposed_by = dict(state["exposed_by"])
    pending: dict[UUID, UUID | None] = {pid: None for pid in state["seed_ids"]}
    traces: list[StepTrace] = []
    notes: list[str] = []
    dropped = missing = rounds_run = 0
    failure: LLMError | None = None
    gate = asyncio.Semaphore(CONCURRENCY)
    ended = "rounds_used"
    local = {**state, "acts": acts}

    for round_index in range(1, inp.rounds + 1):
        if not pending:
            ended = "no_new_exposure"
            break
        todo = sorted(pending, key=lambda pid: order[pid])
        batches = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]
        feeds: dict[UUID, tuple[set[str], dict[str, DraftAct]]] = {}
        prepared = []
        for batch in batches:
            rows = []
            for pid in batch:
                m = members[pid]
                handles: dict[str, DraftAct] = {}
                feed = _feed(m, pending[pid], local, creative, handles)
                rows.append({"participant": handle_of(m), "ordinal": m.ordinal, "persona": m.persona, "state": m.state_name,
                             "language": m.language_name, "city_tier": m.city_tier, "age_band": m.age_band, "traits": m.traits,
                             "feed": feed})
                feeds[pid] = ({item["handle"] for item in feed}, handles)
            prepared.append((batch, rows))

        async def call(index: int, rows: list[dict]):
            async with gate:
                try:
                    return await agent.buzz_round(
                        deps.llm, stage=STAGES[1], platform=inp.platform, round_index=round_index, rows=rows, creative=creative,
                        intended_message=inp.intended_message, seed=inp.seed + round_index * 100 + index)
                except LLMError as exc:
                    return exc

        results = await asyncio.gather(*(call(i, rows) for i, (_, rows) in enumerate(prepared)))
        round_acts: list[DraftAct] = []
        for (batch, rows), result in zip(prepared, results):
            if isinstance(result, LLMError):
                failure = failure or result
                traces.append(result.trace)
                continue
            traces.append(result.trace)
            said = {norm(a.participant): a for a in result.value.acts}
            for pid, row in zip(batch, rows):
                out = said.get(row["participant"])
                if out is None:
                    missing += 1
                    continue
                valid, handles = feeds[pid]
                action = out.action
                if action in ("post", "reply") and not (out.text or "").strip():
                    action, dropped = "ignore", dropped + 1  # a post or a reply with no words is a scroll past, not a guess
                wanted = norm(out.reply_to or "")
                if out.reply_to and wanted not in valid:
                    dropped += 1  # a handle that is not in this account's feed: attach to the post that reached it instead
                    wanted = "F1"
                parent = handles.get(wanted or "F1") if action in ("reply", "share") else None
                posts = action in ("post", "share")
                gloss = out.message_gloss if posts else None
                round_acts.append(DraftAct(
                    id=uuid5(NAMESPACE_URL, f"omnicult-buzz-act:{inp.context.run_id}:{pid}"), round_index=round_index, participant_id=pid,
                    action=action, text=None if action == "ignore" else out.text, text_en=None if action == "ignore" else out.text_en,
                    message_gloss=gloss, stance=out.stance, topics=list(out.topics) if action != "ignore" else [],
                    parent_act_id=parent.id if parent is not None else None, exposed_by=pending[pid],
                    wording_overlap=wording_overlap(gloss, reference) if gloss else None))
        if round_acts:
            await deps.io.save_acts(round_acts)
            acts += round_acts
        rounds_run = round_index
        if progress is not None:
            demo = " (demo fixtures)" if inp.context.mode == "demo" else ""
            await progress(STAGES[1], 1, len(STAGES), f"Round {round_index} of {inp.rounds}: {len(round_acts)} accounts acted{demo}.")
        if failure is not None and not round_acts:
            ended = "stopped_early"
            break
        reached = stats.next_exposure(round_acts, followers, set(exposed_by), order)
        exposed_by.update(reached)
        pending = {pid: by for pid, by in reached.items()}
        if failure is not None:
            ended = "stopped_early"
            break
    else:
        ended = "rounds_used" if pending else "no_new_exposure"
    if pending and ended == "rounds_used" and rounds_run == inp.rounds:
        notes.append(f"{len(pending)} accounts were shown the creative by the last round's posts and did not get a round to act in.")

    update: dict = {"acts": acts, "exposed_by": exposed_by, "rounds_run": rounds_run, "ended": ended,
                    "steps": [*state["steps"], merge_steps(STAGES[1], "audience", traces, started) if traces
                              else local_step(STAGES[1], "audience", None, started, status="skipped")],
                    "limitations": [*state.get("limitations", []), *notes,
                                    *([f"{missing} account actions could not be generated and were skipped."] if missing else []),
                                    *([DROPPED_NOTE] if dropped else [])]}
    if failure is not None:
        update |= {"partial": True, "error": llm_error(failure, STAGES[1], f"The {len(acts)} acts already saved are kept." if acts else "No act was saved; retrying is safe.")}
        if not acts:
            update["stop"] = True
    elif missing:
        update["partial"] = True
    return update


async def tallying(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 2, "Counting reach, sentiment and message change.")
    return {"steps": [*state["steps"], local_step(STAGES[2], "analyst", "omnicult", time.perf_counter())]}


GRAPH = linear_graph(State, [(STAGES[0], loading), (STAGES[1], simulating), (STAGES[2], tallying)])


async def run_buzz(inp: BuzzInput, llm: LLMGateway, io: BuzzIO, progress: Any = None) -> BuzzOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm, io=io), progress, inp.context.mode)
    demo = inp.context.mode == "demo"
    notes = [SYNTHETIC_NOTE, INDEPENDENCE_NOTE, OPEN_NOTE, *([DEMO_NOTE, DEMO_OUTPUT_NOTE] if demo else [])]
    network = state.get("network", {})
    return BuzzOutcome(
        status=outcome_status(state), acts=state.get("acts", []), network={str(k): [str(x) for x in v] for k, v in network.items()},
        seed_exposed=[str(x) for x in state.get("seed_ids", [])],
        exposed_by={str(k): (str(v) if v else None) for k, v in state.get("exposed_by", {}).items()},
        rounds_run=state.get("rounds_run", 0), ended=state.get("ended", "stopped_early"),
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])), steps=state.get("steps", []), error=state.get("error"))
