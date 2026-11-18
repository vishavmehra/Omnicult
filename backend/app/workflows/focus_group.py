"""Live Focus Group: a moderated, multi-turn discussion among synthetic participants drawn from a panel (lab-t3).

The moderator guide drives the session. Each guide question is a moderator turn the server writes from the guide (plus, when
the previous round split, one sentence written by code from the saved turns). The chosen participants then answer in a model
call that voices them in a rotated order, and they may reply to earlier turns. Every turn is saved as it is written, so the
transcript streams while the session runs. A person's interjection is relayed at the next turn boundary as a researcher turn
followed by a round of replies. Themes, splits and position changes are counted from the saved turns at read time
(`analytics.focus_group`); nothing in this module counts.
"""

import time
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.agents import focus_group as agent
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, norm, pick
from app.analytics.focus_group import disagreement_probe, speaking_order
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.audience import GroundingClaim
from app.schemas.common import StepTrace
from app.schemas.runs import RunError
from app.workflows._common import execute, linear_graph, llm_error, local_step, merge_steps, outcome_status
from app.workflows.lab_t3_types import DraftTurn, FocusGroupInput, FocusGroupOutcome, FocusIO, FocusSpeaker
from app.workflows.quick_read import DEMO_NOTE, INDEPENDENCE_NOTE, announce, claims_digest

STAGES = ("loading_context", "moderated_discussion", "analysing_themes")
WINDOW = 24  # turns of transcript the model sees
MAX_TEXT = 420


def handle_of(speaker: FocusSpeaker) -> str:
    return f"P{speaker.ordinal + 1}"


def _speaker_row(s: FocusSpeaker) -> dict:
    return {"participant": handle_of(s), "ordinal": s.ordinal, "persona": s.persona, "state": s.state_name, "language": s.language_name,
            "city_tier": s.city_tier, "age_band": s.age_band, "traits": s.traits,
            "said_before": {"stance": s.stance, "first_reaction": s.first_reaction, "message_restated": s.restated}}


class _Session:
    """What one run knows while it talks: the transcript so far and the callbacks that save it."""

    def __init__(self, inp: FocusGroupInput, llm: LLMGateway, io: FocusIO, handles: dict[str, GroundingClaim], digest: list[dict],
                 progress: Any) -> None:
        self.inp, self.llm, self.io, self.handles, self.digest, self.progress = inp, llm, io, handles, digest, progress
        self.by_handle = {handle_of(s): s for s in inp.speakers}
        self.turns: list[DraftTurn] = []
        self.rounds = 0
        self.interjections = 0
        self.traces: list[StepTrace] = []
        self.notes: list[str] = []
        self.dropped = 0
        self.skipped = 0
        self.failure: LLMError | None = None

    def window(self) -> list[dict]:
        label = {"moderator": "Moderator", "researcher": "Researcher"}
        return [{"turn": f"T{t.index + 1}", "speaker": label.get(t.kind) or f"P{(t.ordinal or 0) + 1}", "text": t.text[:300]}
                for t in self.turns[-WINDOW:]]

    async def add(self, turn: DraftTurn) -> None:
        self.turns.append(turn)
        await self.io.save_turn(turn)

    async def play_round(self, kind: str, question: str, shown: str, interjection_id: UUID | None = None) -> bool:
        """One question and the replies to it. False when the model could not answer (the opening turn stays saved)."""
        round_index = self.rounds
        self.rounds += 1
        await self.add(DraftTurn(index=len(self.turns), round_index=round_index, kind=kind, text=shown, interjection_id=interjection_id))
        order = [self.inp.speakers[i] for i in speaking_order(len(self.inp.speakers), round_index)]
        rows = [_speaker_row(s) for s in order]
        first = len(self.turns) + 1  # the T number of the first speaker's turn
        try:
            result = await agent.focus_round(
                self.llm, stage=STAGES[1], question=question, kind="interjection" if kind == "researcher" else "guide",
                round_index=round_index, rows=rows, first_turn=first, transcript=self.window(), creative=content_dict(self.inp.creative),
                intended_message=self.inp.intended_message, claims=self.digest, seed=self.inp.seed + round_index)
        except LLMError as exc:
            self.traces.append(exc.trace)
            self.failure = exc
            return False
        self.traces.append(result.trace)
        said = {norm(t.participant): t for t in result.value.turns}
        actual: dict[int, int] = {}  # told T number -> saved turn index, for replies inside this round
        missing = 0
        for j, speaker in enumerate(order):
            out = said.get(handle_of(speaker))
            if out is None:
                missing += 1
                continue
            index = len(self.turns)
            actual[first + j] = index
            reply = self._reply(out.reply_to, index, speaker, first, actual)
            if out.reply_to and reply is None:
                self.dropped += 1
            relation = "new_point" if reply is None else ("builds_on" if out.relation == "new_point" else out.relation)
            cited, lost = pick(out.claims, self.handles)
            self.dropped += lost
            await self.add(DraftTurn(
                index=index, round_index=round_index, kind="participant", participant_id=speaker.id, ordinal=speaker.ordinal,
                text=out.text[:MAX_TEXT], reply_to=reply, relation=relation, stance=out.stance, themes=list(out.themes),
                claim_ids=[c.id for c in cited]))
        self.skipped += missing
        if missing:
            self.notes.append(f"The model gave no turn for {missing} of {len(order)} participants in round {round_index + 1}; they are not guessed.")
        return missing < len(order)

    def _reply(self, handle: str | None, own_index: int, speaker: FocusSpeaker, first: int, actual: dict[int, int]) -> int | None:
        """A reply must point at an earlier participant turn of someone else; anything else is dropped, never repaired."""
        key = norm(handle or "")
        if key[:1] != "T" or not key[1:].isdigit():
            return None
        number = int(key[1:])
        index = actual.get(number) if number >= first else number - 1
        if index is None or not 0 <= index < own_index:
            return None
        target = next((t for t in self.turns if t.index == index), None)
        if target is None or target.kind != "participant" or target.participant_id == speaker.id:
            return None
        return index

    async def drain(self) -> bool:
        """Relay what people typed while the session ran. False when a round could not be answered."""
        while self.interjections < self.inp.max_interjections:
            pending = await self.io.take_interjections(self.inp.max_interjections - self.interjections)
            if not pending:
                return True
            for interjection_id, text in pending:
                self.interjections += 1
                if not await self.play_round("researcher", text, text, interjection_id):
                    return False
        return True


class State(TypedDict, total=False):
    inp: FocusGroupInput
    session: _Session
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def loading(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 0, "Loading the creative, the guide and the speakers.")
    started, inp = time.perf_counter(), state["inp"]
    deps = config["configurable"]["deps"]
    digest, handles = claims_digest(inp.claims)
    notes = [] if handles else ["No region claims were recorded for the speakers' states, so every statement is a model interpretation."]
    session = _Session(inp, deps.llm, deps.io, handles, digest, config["configurable"].get("progress"))
    return {"session": session, "limitations": notes, "steps": [local_step(STAGES[0], "audience", "omnicult", started)]}


async def discussing(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 1, "The moderator opens the discussion.")
    started, inp, s = time.perf_counter(), state["inp"], state["session"]
    progress = config["configurable"].get("progress")
    ok = await s.drain()  # a question typed before the first turn
    for k, question in enumerate(inp.guide):
        if not ok:
            break
        probe = disagreement_probe(s.turns, s.rounds - 1) if s.rounds else None
        ok = await s.play_round("moderator", question, f"{probe} {question}" if probe else question)
        if ok and progress is not None:
            demo = " (demo fixtures)" if inp.context.mode == "demo" else ""
            await progress(STAGES[1], 1, len(STAGES), f"Question {k + 1} of {len(inp.guide)} discussed{demo}.")
        ok = ok and await s.drain()
    return _discussion_result(state, s, started)


def _discussion_result(state: State, s: _Session, started: float) -> dict:
    step = merge_steps(STAGES[1], "audience", s.traces, started) if s.traces else local_step(STAGES[1], "audience", None, started, status="skipped")
    limitations = [*state.get("limitations", []), *s.notes, *([DROPPED_NOTE] if s.dropped else [])]
    spoken = sum(1 for t in s.turns if t.kind == "participant")
    update: dict = {"steps": [*state["steps"], step], "limitations": limitations, "partial": s.skipped > 0}
    if s.failure is not None:
        error = llm_error(s.failure, STAGES[1], f"The {spoken} participant turns already saved are kept." if spoken else "No participant turn was saved; retrying is safe.")
        update |= {"error": error, "partial": True}
        if not spoken:
            update["stop"] = True
    return update


async def analysing(state: State, config: RunnableConfig) -> dict:
    await announce(config, STAGES, 2, "Counting themes, splits and position changes.")
    started, s = time.perf_counter(), state["session"]
    if s.failure is None:
        await s.drain()  # a question that arrived while the last round ended; later ones are refused by the API
    return {"steps": [*state["steps"], local_step(STAGES[2], "analyst", "omnicult", started)]}


GRAPH = linear_graph(State, [(STAGES[0], loading), (STAGES[1], discussing), (STAGES[2], analysing)])


async def run_focus_group(inp: FocusGroupInput, llm: LLMGateway, io: FocusIO, progress: Any = None) -> FocusGroupOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, SimpleNamespace(llm=llm, io=io), progress, inp.context.mode)
    session: _Session = state["session"]
    demo = inp.context.mode == "demo"
    notes = [SYNTHETIC_NOTE, INDEPENDENCE_NOTE, "Replies and stances are the model's labels; counts are made by code from the saved transcript.",
             *([DEMO_NOTE, DEMO_OUTPUT_NOTE] if demo else [])]
    return FocusGroupOutcome(
        status=outcome_status(state), turns=session.turns, limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"))
