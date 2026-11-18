"""Audience Lab sessions (lab-t3): the pure counting behind Live Focus Group, Buzz Simulator and Message Check.

Everything the model labels is counted by code here; these tests pin the counting, the rules and their edges, with no model and
no database.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.analytics import buzz as buzz_stats
from app.analytics import focus_group as fg
from app.analytics import message_check as mc
from app.analytics.lab_text import content_words, wording_overlap
from app.analytics.panel import sample_panel
from app.schemas.audience import CreativeCopy, RegionRef
from app.schemas.lab_message_check import MessageCheckCreate

# --- text measures --------------------------------------------------------------------------------------------------------


def test_wording_overlap_counts_shared_content_words_and_is_not_understanding():
    assert content_words("The sweets are for gifting") == {"sweet", "gifting"}
    assert wording_overlap("festive sweets to gift", "Home-style festive sweets, ready to gift") == 1.0
    assert wording_overlap("a greeting card", "festive sweets delivered") == 0.0
    assert wording_overlap("", "festive sweets") is None and wording_overlap("the of and", "festive sweets") is None
    # echoing the words is a high number even when the point is lost: the measure says nothing about meaning
    assert wording_overlap("home style festive sweets are not for gifting", "Home-style festive sweets for gifting") > 0.8


# --- Message Check -------------------------------------------------------------------------------------------------------


def test_key_points_are_split_by_code_and_edge_cases_hold():
    assert mc.split_key_points("Home-style festive sweets, ready to gift and delivered before the festival day.") == [
        "Home-style festive sweets", "ready to gift", "delivered before the festival day"]
    assert mc.split_key_points("One simple message") == ["One simple message"]
    assert mc.split_key_points("Gift sweets and savouries") == ["Gift sweets and savouries"]  # a one-word fragment is not a point
    assert mc.split_key_points("") == []
    assert len(mc.split_key_points("a one; b two; c three; d four; e five; f six; g seven")) == mc.MAX_KEY_POINTS


@pytest.mark.parametrize(("coverage", "misread", "verdict"), [
    (["yes", "yes", "yes"], False, "understood"),
    (["yes", "yes", "partly"], False, "understood"),  # 0.83
    (["yes", "yes", "no"], False, "partly"),  # 0.67
    (["yes", "no", "no"], False, "missed"),  # 0.33
    (["partly", "partly", "no"], False, "missed"),  # 0.33
    (["yes", "yes", "yes"], True, "misread"),  # a named misreading overrides a high score
    ([], False, None),
])
def test_verdict_rules_and_their_edges(coverage, misread, verdict):
    assert mc.verdict_of(mc.score_of(coverage), misread) == verdict


def test_verdict_thresholds_are_inclusive_at_the_lower_edge():
    assert (mc.verdict_of(0.8, False), mc.verdict_of(0.4, False), mc.verdict_of(0.39, False)) == ("understood", "partly", "missed")


def checked(ordinal: int, state: str, language: str, coverage: list[str], misreading: str | None = None, completed: bool = True) -> mc.Checked:
    ids = [f"K{n}" for n in range(1, len(coverage) + 1)]
    return mc.Checked(
        id=uuid4(), ordinal=ordinal, state_code=state, language=language, language_name=language.upper(), completed=completed,
        restated=f"r{ordinal}", restated_en=f"restated {ordinal}", coverage=dict(zip(ids, coverage)),
        recalled={k: c == "yes" for k, c in zip(ids, coverage)}, misreading=misreading)


def test_rates_count_only_compared_participants_and_report_the_rest_as_failed():
    ids = ["K1", "K2"]
    people = [checked(0, "IN-TN", "ta", ["yes", "yes"]), checked(1, "IN-TN", "ta", ["yes", "no"]), checked(2, "IN-TN", "ta", ["no", "no"]),
              checked(3, "IN-TN", "ta", ["yes", "yes"], misreading="Reads as a greeting"), checked(4, "IN-TN", "ta", [], completed=False)]
    r = mc.rates(people, ids)
    assert (r.denominator, r.failed, r.understood, r.partly, r.missed, r.misread) == (4, 1, 1, 1, 1, 1)
    assert r.understood_rate == 0.25
    assert mc.rates([], ids).understood_rate is None


def test_summary_is_per_region_with_languages_misreadings_and_recommendations_that_name_their_numbers():
    points = [("K1", "festive sweets"), ("K2", "delivered before the festival")]
    people = [checked(i, "IN-KL", "ml", ["yes", "no"]) for i in range(3)] + [checked(3, "IN-KL", "en", ["yes", "yes"]),
              checked(4, "IN-KL", "ml", ["no", "no"], misreading="Reads as a greeting"), checked(5, "IN-TN", "ta", ["yes", "yes"])]
    kl, tn = RegionRef(code="IN-KL", name="Kerala"), RegionRef(code="IN-TN", name="Tamil Nadu")
    summary = mc.summarise(points, people, [(kl, CreativeCopy(headline="h", body=None, call_to_action=None), None),
                                            (tn, CreativeCopy(headline="t", body=None, call_to_action=None), "node-1")])
    assert summary.rules_version == "message-check-rules-v1" and len(summary.rules) == 5
    k, t = summary.regions
    assert (k.rates.denominator, k.rates.understood, k.rates.partly, k.rates.misread) == (5, 1, 3, 1)
    assert [p.restated_yes for p in k.points] == [4, 1] and [p.recalled for p in k.points] == [4, 1]
    assert {row.language for row in k.by_language} == {"ml", "en"}
    assert k.misreadings[0].label == "Reads as a greeting" and k.misreadings[0].participants == 1
    joined = " ".join(k.recommendations)
    assert "\"delivered before the festival\": carried by 1 of 5" in joined and "1 of 5 restatements were marked as misreading" in joined
    assert t.rates.understood == 1 and t.recommendations == [
        "1 of 1 restatements in Tamil Nadu carried every key point and none was marked as a misreading. This check suggests no correction."]
    assert summary.overall.denominator == 6 and t.version_ref == "node-1"


def test_a_region_with_nothing_compared_says_so_instead_of_inventing_a_result():
    summary = mc.summarise([("K1", "x")], [checked(0, "IN-TN", "ta", [], completed=False)],
                           [(RegionRef(code="IN-TN", name="Tamil Nadu"), CreativeCopy(headline="h", body=None, call_to_action=None), None)])
    region = summary.regions[0]
    assert region.rates.denominator == 0 and region.rates.failed == 1 and region.rates.understood_rate is None
    assert "No restatement could be compared in Tamil Nadu" in region.recommendations[0]


def test_message_check_request_rules():
    target = {"region_code": "IN-TN"}
    with pytest.raises(ValidationError):
        MessageCheckCreate(targets=[target, target])  # a region once
    with pytest.raises(ValidationError):
        MessageCheckCreate(targets=[{"region_code": "IN-TN", "content_version_id": str(uuid4()), "creative": {"headline": "h"}}])
    with pytest.raises(ValidationError):
        MessageCheckCreate(targets=[target], size_per_region=2)
    assert MessageCheckCreate(targets=[target]).size_per_region == 8


# --- Live Focus Group -----------------------------------------------------------------------------------------------------


def turn(index: int, round_index: int, kind: str, ordinal: int | None = None, *, stance: str | None = None, reply_to: int | None = None,
         relation: str | None = None, themes: tuple[str, ...] = (), pid: UUID | None = None) -> fg.TurnRec:
    return fg.TurnRec(index=index, round_index=round_index, kind=kind, participant_id=pid or (UUID(int=ordinal + 1) if ordinal is not None else None),
                      ordinal=ordinal, text=f"turn {index}", reply_to=reply_to, relation=relation, stance=stance, themes=themes)


def session() -> list[fg.TurnRec]:
    return [
        turn(0, 0, "moderator"),
        turn(1, 0, "participant", 0, stance="positive", themes=("Warm tone",)),
        turn(2, 0, "participant", 1, stance="negative", reply_to=1, relation="disagrees", themes=("warm tone", "price")),
        turn(3, 0, "participant", 2, stance="mixed", reply_to=2, relation="builds_on"),
        turn(4, 1, "moderator"),
        turn(5, 1, "participant", 1, stance="mixed", themes=("price",)),
        turn(6, 1, "participant", 0, stance="positive", reply_to=5, relation="agrees"),
        turn(7, 2, "researcher"),
        turn(8, 2, "participant", 2, stance="positive", reply_to=6, relation="agrees"),
    ]


def test_summary_counts_come_from_the_saved_turns():
    s = fg.summarise(session(), ["first", "second"])
    assert (s.turn_count, s.participant_turns, s.speakers_heard) == (9, 6, 3)
    assert [(r.kind, r.question, r.answered) for r in s.rounds] == [("guide", "first", 3), ("guide", "second", 2), ("interjection", "turn 7", 1)]
    assert s.rounds[0].stance.counts["positive"] == 1 and s.rounds[0].stance.denominator == 3
    # themes: distinct speakers, normalised labels, most speakers first
    assert [(t.label, t.participants) for t in s.themes] == [("Warm tone", 2), ("price", 1)]  # price came up twice, from one speaker
    assert s.themes[0].turn_indices == [1, 2] and s.themes[1].turn_indices == [2, 5]


def test_disagreements_are_splits_and_direct_challenges_only():
    s = fg.summarise(session(), ["first", "second"])
    kinds = [(d.kind, d.round_index) for d in s.disagreements]
    assert kinds == [("stance_split", 0), ("direct_challenge", 0)]  # round 1 had no opposed stance, so no split
    split, challenge = s.disagreements
    assert {p.stance for p in split.positions} == {"positive", "negative", "mixed"} and "1 of 3 speakers ended positive while 1" in split.description
    assert (challenge.from_turn_index, challenge.to_turn_index) == (2, 1) and "Participant 2 disagreed with Participant 1" in challenge.description


def test_a_challenge_to_oneself_or_to_the_moderator_is_not_counted():
    own = turn(2, 0, "participant", 0, stance="negative", reply_to=1, relation="disagrees", pid=UUID(int=1))
    to_mod = turn(3, 0, "participant", 1, stance="negative", reply_to=0, relation="disagrees")
    turns = [turn(0, 0, "moderator"), turn(1, 0, "participant", 0, stance="positive", pid=UUID(int=1)), own, to_mod]
    assert [d.kind for d in fg.disagreements(turns, [(0, "guide", "q")]) if d.kind == "direct_challenge"] == []


def test_position_changes_compare_first_and_last_stance_per_speaker():
    changes = fg.summarise(session(), ["a", "b"]).shifts
    assert [(c.ordinal, c.from_stance, c.to_stance) for c in changes] == [(1, "negative", "mixed"), (2, "mixed", "positive")]


def test_the_moderator_probe_is_written_from_the_split_and_only_when_there_is_one():
    probe = fg.disagreement_probe(session(), 0)
    assert probe and "Participant 1" in probe and "Participant 2" in probe and probe.startswith("Before we go on")
    assert fg.disagreement_probe(session(), 1) is None


def test_speakers_are_picked_by_seed_in_panel_order_and_the_rotation_covers_everyone():
    people = list(range(12))
    a = fg.pick_speakers(people, 5, seed=3)
    assert a == fg.pick_speakers(people, 5, seed=3) and a == sorted(a) and len(a) == 5 and a != fg.pick_speakers(people, 5, seed=4)
    assert fg.pick_speakers(people, 20, seed=1) == people
    assert [fg.speaking_order(3, r)[0] for r in range(4)] == [0, 1, 2, 0] and sorted(fg.speaking_order(4, 3)) == [0, 1, 2, 3]


# --- Buzz Simulator --------------------------------------------------------------------------------------------------------


@dataclass
class Member:
    id: UUID
    ordinal: int
    state_code: str
    state_name: str
    language: str
    language_name: str
    city_tier: str
    age_band: str
    traits: dict[str, str]


def members(n: int = 12) -> list[Member]:
    people = sample_panel(size=n, states=["IN-TN", "IN-KL"], languages=["ta", "ml"], city_tiers=["tier1", "tier2"], age_bands=["25-34", "35-44"], seed=5)
    names = {"ta": "Tamil", "ml": "Malayalam"}
    return [Member(UUID(int=p.ordinal + 1), p.ordinal, p.state_code, p.state_code, p.language, names[p.language], p.city_tier, p.age_band, p.traits)
            for p in people]


def test_network_is_seeded_directed_and_without_self_links():
    people = members()
    a, b = buzz_stats.build_network(people, 3, seed=9), buzz_stats.build_network(people, 3, seed=9)
    assert a == b and a != buzz_stats.build_network(people, 3, seed=10)
    assert all(len(v) == 3 and k not in v for k, v in a.items())
    follows = buzz_stats.followers(a)
    assert all(viewer in follows[source] for viewer, sources in a.items() for source in sources)


def test_seed_audience_is_a_seeded_share_of_the_population_with_a_floor_of_two():
    people = members()
    seeds = buzz_stats.seed_audience(people, 0.25, seed=1)
    assert len(seeds) == 3 and seeds == buzz_stats.seed_audience(people, 0.25, seed=1)
    assert len(buzz_stats.seed_audience(people[:6], 0.1, seed=1)) == 2


def act(round_index: int, who: Member, action: str, *, stance: str = "positive", exposed_by: Member | None = None, gloss: str | None = None,
        overlap: float | None = None, topics: tuple[str, ...] = ()) -> buzz_stats.ActRec:
    return buzz_stats.ActRec(id=uuid4(), round_index=round_index, participant_id=who.id, action=action, stance=stance, topics=topics,
                             exposed_by=exposed_by.id if exposed_by else None, gloss=gloss, overlap=overlap)


def test_next_exposure_shows_followers_once_and_never_depends_on_dict_order():
    people = members(6)
    a, b, c, d = people[:4]
    followers = {a.id: [c.id, d.id], b.id: [c.id]}
    order = {p.id: p.ordinal for p in people}
    acts = [act(1, b, "share"), act(1, a, "post"), act(1, c, "ignore")]
    out = buzz_stats.next_exposure(acts, followers, {a.id, b.id}, order)
    assert out == {c.id: a.id, d.id: a.id}  # the lower ordinal wins a follower both reached; ignores expose nobody
    assert buzz_stats.next_exposure(acts, followers, {a.id, b.id, c.id, d.id}, order) == {}


def test_buzz_summary_counts_reach_cohorts_sentiment_depth_and_mutation():
    people = members(12)
    p = people
    acts = [act(1, p[0], "post", exposed_by=None, gloss="festive sweets as a gift", overlap=0.9, topics=("gifting",)),
            act(1, p[1], "reply", stance="confused", topics=("gifting", "price")),
            act(1, p[2], "ignore", stance="neutral"),
            act(2, p[3], "share", exposed_by=p[0], gloss="a greeting", overlap=0.1, stance="mixed"),
            act(3, p[4], "reply", exposed_by=p[3], stance="negative")]
    exposed_by = {p[0].id: None, p[1].id: None, p[2].id: None, p[3].id: p[0].id, p[4].id: p[3].id, p[5].id: p[3].id}
    s = buzz_stats.summarise(people, acts, exposed_by=exposed_by, rounds_run=3, ended="rounds_used", reference="festive sweets as a gift",
                             reference_source="intended_message", network_method="m")
    r = s.reach
    assert (r.population, r.seed_exposed, r.exposed, r.acted, r.resharers, r.cascade_depth, r.rounds_run) == (12, 3, 6, 5, 2, 2, 3)
    assert r.exposed_share == 0.5
    assert [(x.round_index, x.exposed, x.posts, x.replies, x.shares, x.ignored, x.newly_exposed) for x in s.rounds] == [
        (1, 3, 1, 1, 0, 1, 1 + 0), (2, 1, 0, 0, 1, 0, 2), (3, 1, 0, 1, 0, 0, 0)]
    assert s.sentiment.denominator == 4 and s.sentiment.counts["positive"] == 1 and s.sentiment.counts["confused"] == 1  # ignores are not sentiment
    assert (s.confusion.count, s.mutation.compared, s.mutation.changed) == (1, 2, 1) and s.mutation.examples[0].overlap == 0.1
    assert [(a.ordinal, a.exposed_others) for a in s.amplifiers] == [(3, 2), (0, 1)]
    assert [t.label for t in s.themes] == ["gifting", "price"] and s.themes[0].participants == 2
    assert {c.value for c in s.by_state} == {"IN-TN", "IN-KL"} and sum(c.participants for c in s.by_state) == 12
    assert sum(c.shares for c in s.by_language) == 1 and sum(c.expressed for c in s.by_state) == 4
    assert s.sentiment.rates["positive"] == 0.25


def test_a_cascade_with_a_cycle_does_not_loop():
    a, b = members(2)
    assert buzz_stats._depth({a.id: b.id, b.id: a.id}) == 1
