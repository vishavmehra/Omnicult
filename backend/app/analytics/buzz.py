"""Buzz Simulator network, exposure and tallies (lab-t3). Pure functions, no model calls.

It extends the population simulation (`analytics.population`): the seeded "who sees whose posts" network is that module's
`peer_network`, fed panel participants adapted to its `Participant` shape, with language, city tier and age band as the
interests that make two accounts alike and the state as the group. Who is shown the creative, how far it travelled, the
sentiment of what was said and how the message changed are all counted here from the stored acts. None of it is a forecast.
"""

import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.analytics.lab_text import label_key
from app.analytics.population import peer_network, stance_distribution
from app.schemas.common import Market
from app.schemas.lab_buzz import (
    BuzzAmplifier,
    BuzzCohortRow,
    BuzzConfusion,
    BuzzInfluenceEdge,
    BuzzMutation,
    BuzzMutationExample,
    BuzzReach,
    BuzzRoundRow,
    BuzzSummary,
    BuzzTheme,
)
from app.schemas.population import InterestRef, Participant

MUTATION_THRESHOLD = 0.34  # a passed-on message sharing fewer than this share of words with the reference counts as changed

def network_method(degree: int) -> str:
    return (f"Each account sees posts from {degree} other accounts, about three quarters in its own state, ranked by how many of "
            "language, city tier and age band they share; ties are broken with the run seed. The links are a modelling choice, "
            "not a measured follower graph.")


TOP_AMPLIFIERS = 5
MAX_EXAMPLES = 4
MAX_THEMES = 8


@dataclass(frozen=True)
class ActRec:
    id: UUID
    round_index: int
    participant_id: UUID
    action: str
    stance: str
    topics: tuple[str, ...] = ()
    parent_act_id: UUID | None = None
    exposed_by: UUID | None = None
    gloss: str | None = None
    overlap: float | None = None


def adapt(members: Sequence[Any]) -> list[Participant]:
    """Panel members as population participants: group = state, interests = language, city tier and age band."""
    out = []
    for m in members:
        interests = [InterestRef(ref_id=f"{kind}:{value}", ref_kind="tag", name=value, weight=1.0, evidence_ids=[])
                     for kind, value in (("lang", m.language), ("tier", m.city_tier), ("age", m.age_band))]
        out.append(Participant(
            id=m.id, population_id=m.id, group_id=m.state_code, ordinal=m.ordinal,
            region=Market(country_code="IN", display_name=m.state_name[:100]), interests=interests, traits=dict(m.traits),
            evidence_ids=[]))
    return out


def build_network(members: Sequence[Any], degree: int, seed: int) -> dict[UUID, list[UUID]]:
    """Whose posts each account sees. Directed: A seeing B does not mean B sees A."""
    return peer_network(adapt(members), min(degree, max(1, len(members) - 1)), seed)


def followers(network: Mapping[UUID, Sequence[UUID]]) -> dict[UUID, list[UUID]]:
    """Reverse of `build_network`: who sees each account's posts."""
    out: dict[UUID, list[UUID]] = defaultdict(list)
    for viewer, sources in network.items():
        for source in sources:
            out[source].append(viewer)
    return {k: sorted(v, key=str) for k, v in out.items()}


def seed_audience(members: Sequence[Any], share: float, seed: int) -> list[UUID]:
    """The accounts that see the creative first: a seeded draw of `share` of the population (at least two)."""
    ordered = sorted(members, key=lambda m: m.ordinal)
    k = min(len(ordered), max(2, round(len(ordered) * share)))
    return [m.id for m in sorted(random.Random(f"buzz-seed:{seed}").sample(ordered, k), key=lambda m: m.ordinal)]


def next_exposure(round_acts: Sequence[ActRec], followers_of: Mapping[UUID, Sequence[UUID]], exposed: set[UUID],
                  order: Mapping[UUID, int]) -> dict[UUID, UUID]:
    """Accounts shown the creative for the first time by this round's posts and reshares: follower -> the account whose
    post showed it. The lowest-ordinal sharer wins a follower reached twice, so the result never depends on dict order."""
    out: dict[UUID, UUID] = {}
    for act in sorted((a for a in round_acts if a.action in ("post", "share")), key=lambda a: order[a.participant_id]):
        for f in followers_of.get(act.participant_id, ()):
            if f not in exposed and f not in out:
                out[f] = act.participant_id
    return out


def _depth(exposed_by: Mapping[UUID, UUID | None]) -> int:
    memo: dict[UUID, int] = {}

    def depth(p: UUID, seen: frozenset[UUID] = frozenset()) -> int:
        if p in memo:
            return memo[p]
        parent = exposed_by.get(p)
        value = 0 if parent is None or parent in seen else 1 + depth(parent, seen | {p})
        memo[p] = value
        return value

    return max((depth(p) for p in exposed_by), default=0)


def _cohort(dimension: str, value: str, label: str, people: Sequence[Any], acts: Sequence[ActRec], exposed: set[UUID]) -> BuzzCohortRow:
    ids = {p.id for p in people}
    mine = [a for a in acts if a.participant_id in ids]
    said = [a for a in mine if a.action != "ignore"]
    count = Counter(a.action for a in said)
    return BuzzCohortRow(
        dimension=dimension, value=value, label=label, participants=len(ids), exposed=len(ids & exposed), expressed=len(said),  # type: ignore[arg-type]
        posts=count["post"], replies=count["reply"], shares=count["share"], sentiment=stance_distribution(a.stance for a in said))  # type: ignore[arg-type]


def summarise(
    members: Sequence[Any], acts: Sequence[ActRec], *, exposed_by: Mapping[UUID, UUID | None] | None, rounds_run: int, ended: str, reference: str, reference_source: str, network_method: str,
) -> BuzzSummary:
    by_id = {m.id: m for m in members}
    acted_round = {a.participant_id: a.round_index for a in acts}
    exposure: dict[UUID, UUID | None] = dict(exposed_by) if exposed_by is not None else {a.participant_id: a.exposed_by for a in acts}
    exposure.update({a.participant_id: a.exposed_by for a in acts})  # an act is the record of how the account was reached
    exposed = set(exposure)
    seed_count = sum(1 for p in exposure.values() if p is None)
    said = [a for a in acts if a.action != "ignore"]

    rows = []
    for r in range(1, rounds_run + 1):
        mine = [a for a in acts if a.round_index == r]
        c = Counter(a.action for a in mine)
        rows.append(BuzzRoundRow(
            round_index=r, exposed=len(mine), posts=c["post"], replies=c["reply"], shares=c["share"], ignored=c["ignore"],
            newly_exposed=sum(1 for p, by in exposure.items() if by is not None and acted_round.get(by) == r),
            sentiment=stance_distribution(a.stance for a in mine if a.action != "ignore")))  # type: ignore[arg-type]

    caused = Counter(by for by in exposure.values() if by is not None)
    amplifiers = [BuzzAmplifier(participant_id=p, ordinal=by_id[p].ordinal, state_code=by_id[p].state_code,
                                language_name=by_id[p].language_name, exposed_others=n)
                  for p, n in sorted(caused.items(), key=lambda kv: (-kv[1], by_id[kv[0]].ordinal))[:TOP_AMPLIFIERS]]
    influence = [BuzzInfluenceEdge(from_participant_id=by, to_participant_id=p, round_index=acted_round[by])
                 for p, by in sorted(exposure.items(), key=lambda kv: by_id[kv[0]].ordinal) if by is not None and by in acted_round]

    topics: dict[str, tuple[str, set[UUID]]] = {}
    for a in said:
        for topic in a.topics:
            key = label_key(topic)
            if key:
                topics.setdefault(key, (topic.strip(), set()))[1].add(a.participant_id)
    themes = [BuzzTheme(label=label, participants=len(who))
              for label, who in sorted(topics.values(), key=lambda v: (-len(v[1]), v[0]))[:MAX_THEMES]]

    confused = [a.id for a in said if a.stance == "confused"]
    compared = [a for a in said if a.gloss and a.overlap is not None]
    changed = [a for a in compared if a.overlap < MUTATION_THRESHOLD]  # type: ignore[operator]
    examples = [BuzzMutationExample(act_id=a.id, ordinal=by_id[a.participant_id].ordinal, message_gloss=a.gloss or "", overlap=a.overlap or 0.0)
                for a in sorted(changed, key=lambda a: (a.overlap or 0, by_id[a.participant_id].ordinal))[:MAX_EXAMPLES]]

    states = list(dict.fromkeys((m.state_code, m.state_name) for m in sorted(members, key=lambda m: m.ordinal)))
    languages = list(dict.fromkeys((m.language, m.language_name) for m in sorted(members, key=lambda m: m.ordinal)))
    return BuzzSummary(
        reach=BuzzReach(
            population=len(members), seed_exposed=seed_count, exposed=len(exposed), exposed_share=round(len(exposed) / len(members), 4) if members else 0.0,
            acted=len(acts), resharers=sum(1 for a in acts if a.action in ("post", "share")), cascade_depth=_depth(exposure),
            rounds_run=rounds_run, ended=ended),  # type: ignore[arg-type]
        rounds=rows, sentiment=stance_distribution(a.stance for a in said),  # type: ignore[arg-type]
        by_state=[_cohort("state", code, name, [m for m in members if m.state_code == code], acts, exposed) for code, name in states],
        by_language=[_cohort("language", code, name, [m for m in members if m.language == code], acts, exposed) for code, name in languages],
        amplifiers=amplifiers, influence=influence, themes=themes, confusion=BuzzConfusion(count=len(confused), act_ids=confused[:10]),
        mutation=BuzzMutation(reference=reference, reference_source=reference_source, compared=len(compared), changed=len(changed),  # type: ignore[arg-type]
                              threshold=MUTATION_THRESHOLD, examples=examples,
                              note="Counts words in common between what an account says it is passing on and the reference message. "
                                   "A wording measure: a changed wording can keep the point, and an echoed wording can lose it."),
        network_method=network_method)
