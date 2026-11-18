"""Live Focus Group tallies (lab-t3). Pure functions over the saved transcript: who spoke, which themes were raised, where
the group split, and who changed position. The model only labels each participant turn (stance, relation, themes); every
count and every "disagreement" below is derived from those labels by code, so the same transcript always gives the same
summary and a summary can be recomputed while the session is still running.
"""

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from app.analytics.lab_text import label_key
from app.analytics.population import stance_distribution
from app.schemas.lab_focus_group import (
    FocusGroupDisagreement,
    FocusGroupPosition,
    FocusGroupRound,
    FocusGroupShift,
    FocusGroupSummary,
    FocusGroupTheme,
)

T = TypeVar("T")

DEFAULT_GUIDE = (
    "What is your first impression of this ad? Say it in a sentence or two.",
    "In your own words, what is this ad telling you, and what does it want you to do?",
    "Is there anything here that feels made for you, or that feels out of place where you live?",
    "Would you talk about it with family or friends? What would you say?",
    "If you could change one thing, what would it be?",
)
DEFAULT_GUIDE_SIZE = 4  # the form starts with the first four; more can be added
METHOD = (
    "Stances, relations and themes are the participants' own labels, written by the model. Themes are counted as the number of "
    "distinct speakers who raised a label. A split is a round in which one speaker ended positive and another negative or "
    "confused; a direct challenge is a turn that disagrees with an earlier turn of another speaker; a position change is a "
    "speaker whose last stance differs from their first. All of it is counted from the saved transcript."
)
OPPOSED = frozenset({"negative", "confused"})
MAX_THEMES = 8


@dataclass(frozen=True)
class TurnRec:
    index: int
    round_index: int
    kind: str  # moderator | participant | researcher
    participant_id: UUID | None
    ordinal: int | None
    text: str
    reply_to: int | None = None
    relation: str | None = None
    stance: str | None = None
    themes: tuple[str, ...] = ()


def pick_speakers(candidates: Sequence[T], k: int, seed: int) -> list[T]:
    """k of the candidates, seeded, kept in their original order (so the same panel and seed pick the same speakers)."""
    if k >= len(candidates):
        return list(candidates)
    chosen = set(random.Random(f"focus-speakers:{seed}").sample(range(len(candidates)), k))
    return [c for i, c in enumerate(candidates) if i in chosen]


def speaking_order(count: int, round_index: int) -> list[int]:
    """Indices 0..count-1 rotated by the round, so a different speaker opens each round."""
    start = round_index % count if count else 0
    return [(start + i) % count for i in range(count)]


def _label(ordinal: int | None) -> str:
    return f"Participant {ordinal + 1}" if ordinal is not None else "A participant"


def disagreement_probe(turns: Sequence[TurnRec], round_index: int) -> str | None:
    """A sentence the moderator adds to the next question when the last round split, written from the saved turns."""
    spoke = [t for t in turns if t.round_index == round_index and t.kind == "participant"]
    pro = [t for t in spoke if t.stance == "positive"]
    con = [t for t in spoke if t.stance in OPPOSED]
    if not pro or not con:
        return None
    a, b = sorted({t.ordinal for t in pro if t.ordinal is not None})[:2], sorted({t.ordinal for t in con if t.ordinal is not None})[:2]
    names = lambda xs: " and ".join(_label(o) for o in xs)  # noqa: E731
    return f"Before we go on: {names(a)} and {names(b)} saw that differently. Say what drives your view."


def rounds_of(turns: Sequence[TurnRec], guide: Sequence[str]) -> list[tuple[int, str, str]]:
    """(round index, kind, question) in session order. A moderator turn opens the next guide question; a researcher turn is
    its own question."""
    out, asked = [], 0
    for t in turns:
        if t.kind == "moderator":
            out.append((t.round_index, "guide", guide[asked] if asked < len(guide) else t.text))
            asked += 1
        elif t.kind == "researcher":
            out.append((t.round_index, "interjection", t.text))
    return out


def themes(turns: Sequence[TurnRec]) -> list[FocusGroupTheme]:
    seen: dict[str, tuple[str, set[UUID], list[int]]] = {}
    for t in turns:
        if t.kind != "participant" or t.participant_id is None:
            continue
        for theme in t.themes:
            key = label_key(theme)
            if not key:
                continue
            label, who, at = seen.setdefault(key, (theme.strip(), set(), []))
            who.add(t.participant_id)
            at.append(t.index)
    ranked = sorted(seen.values(), key=lambda v: (-len(v[1]), v[2][0]))[:MAX_THEMES]
    return [FocusGroupTheme(label=label, participants=len(who), turn_indices=at[:6]) for label, who, at in ranked]


def _positions(turns: Sequence[TurnRec]) -> list[FocusGroupPosition]:
    by_stance: dict[str, list[TurnRec]] = defaultdict(list)
    for t in turns:
        if t.stance:
            by_stance[t.stance].append(t)
    return [FocusGroupPosition(stance=s, ordinals=sorted({t.ordinal for t in ts if t.ordinal is not None}),  # type: ignore[arg-type]
                               turn_indices=[t.index for t in ts])
            for s, ts in sorted(by_stance.items(), key=lambda kv: kv[1][0].index)]


def disagreements(turns: Sequence[TurnRec], rounds: Sequence[tuple[int, str, str]]) -> list[FocusGroupDisagreement]:
    out: list[FocusGroupDisagreement] = []
    question = {r: q for r, _, q in rounds}
    by_index = {t.index: t for t in turns}
    for round_index, _, q in rounds:
        spoke = [t for t in turns if t.round_index == round_index and t.kind == "participant" and t.stance]
        pro = [t for t in spoke if t.stance == "positive"]
        con = [t for t in spoke if t.stance in OPPOSED]
        if pro and con:
            out.append(FocusGroupDisagreement(
                kind="stance_split", round_index=round_index, question=q, positions=_positions(spoke), from_turn_index=None,
                to_turn_index=None,
                description=f"{len(pro)} of {len(spoke)} speakers ended positive while {len(con)} ended negative or confused."))
    for t in turns:
        if t.kind != "participant" or t.relation != "disagrees" or t.reply_to is None:
            continue
        target = by_index.get(t.reply_to)
        if target is None or target.kind != "participant" or target.participant_id == t.participant_id:
            continue
        out.append(FocusGroupDisagreement(
            kind="direct_challenge", round_index=t.round_index, question=question.get(t.round_index, ""),
            positions=_positions([target, t]), from_turn_index=t.index, to_turn_index=target.index,
            description=f"{_label(t.ordinal)} disagreed with {_label(target.ordinal)}."))
    return out


def shifts(turns: Sequence[TurnRec]) -> list[FocusGroupShift]:
    """Speakers whose last labelled stance differs from their first."""
    first: dict[UUID, TurnRec] = {}
    last: dict[UUID, TurnRec] = {}
    for t in turns:
        if t.kind == "participant" and t.participant_id and t.stance:
            first.setdefault(t.participant_id, t)
            last[t.participant_id] = t
    return [FocusGroupShift(participant_id=pid, ordinal=a.ordinal or 0, from_stance=a.stance, to_stance=last[pid].stance,  # type: ignore[arg-type]
                            from_turn_index=a.index, to_turn_index=last[pid].index)
            for pid, a in first.items() if last[pid].stance != a.stance]


def summarise(turns: Sequence[TurnRec], guide: Sequence[str]) -> FocusGroupSummary:
    rounds = rounds_of(turns, guide)
    rows = []
    for round_index, kind, question in rounds:
        spoke = [t for t in turns if t.round_index == round_index and t.kind == "participant"]
        rows.append(FocusGroupRound(round_index=round_index, kind=kind, question=question, answered=len(spoke),  # type: ignore[arg-type]
                                    stance=stance_distribution(t.stance for t in spoke)))  # type: ignore[arg-type]
    spoken = [t for t in turns if t.kind == "participant"]
    return FocusGroupSummary(
        turn_count=len(turns), participant_turns=len(spoken), speakers_heard=len({t.participant_id for t in spoken}), rounds=rows,
        themes=themes(turns), disagreements=disagreements(turns, rounds),
        shifts=sorted(shifts(turns), key=lambda s: s.ordinal), method=METHOD)
