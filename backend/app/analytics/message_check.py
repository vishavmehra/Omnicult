"""Message Check rules and tallies (lab-t3). Pure functions: the model writes restatements and marks key points; this module
turns those marks into scores, verdicts, rates, misreading groups and recommendations, the same way every time.

`message-check-rules-v1`: a participant's score is the mean over the key points (yes 1, partly 0.5, no 0). The verdict is
`misread` when the comparison named a misreading, otherwise `understood` at 0.8 or more, `partly` from 0.4, else `missed`.
Rates are counts over the participants whose restatement was compared.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.analytics.lab_text import label_key, wording_overlap
from app.schemas.audience import CreativeCopy, RegionRef
from app.schemas.lab_message_check import (
    MessageCheckExample,
    MessageCheckLanguageRow,
    MessageCheckMisreadingGroup,
    MessageCheckPointRate,
    MessageCheckRates,
    MessageCheckRegion,
    MessageCheckSummary,
    MessageVerdict,
    PointCoverage,
)

RULES_VERSION = "message-check-rules-v1"
POINT_VALUE: dict[str, float] = {"yes": 1.0, "partly": 0.5, "no": 0.0}
UNDERSTOOD_AT = 0.8
PARTLY_AT = 0.4
MAX_KEY_POINTS = 5
LANGUAGE_GAP = 0.25  # a language cohort is called out when its understood rate trails the region's by this much
LOW_POINT_RATE = 0.5
RULES = [
    "The comparison step marks each key point of the intended message as carried by the restatement (yes, partly, no) and as "
    "recalled or not in the participant's own recall.",
    "A participant's score is the mean over the key points: yes 1, partly 0.5, no 0.",
    "Verdict: misread when the comparison names a misreading; otherwise understood at a score of 0.8 or more, partly from 0.4 "
    "up to 0.8, missed below 0.4.",
    "Every rate is a count over the participants whose restatement was compared; participants the model returned nothing "
    "usable for are counted as failed and left out, never guessed.",
    "Wording overlap is the share of words a restatement holds in common with the intended message. Similar words do not show "
    "the point was understood, and different words do not show it was missed.",
]

_SPLIT = re.compile(r"\s*(?:[;,]|\band\b|&|\bthen\b)\s*", re.IGNORECASE)


def split_key_points(message: str, limit: int = MAX_KEY_POINTS) -> list[str]:
    """The message cut at commas, semicolons and 'and': a starting point the person can edit. One piece if nothing splits."""
    pieces = [p.strip(" .!?:-") for p in _SPLIT.split(message)]
    pieces = [p for p in pieces if len(p) >= 3]
    if len(pieces) < 2:
        return [message.strip(" .")] if message.strip(" .") else []
    # Merge a fragment of one or two words into the piece before it ("ready to gift"): it is a modifier, not a point.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece.split()) < 2:
            merged[-1] = f"{merged[-1]} and {piece}"
        else:
            merged.append(piece)
    return merged[:limit]


def score_of(coverage: Sequence[PointCoverage]) -> float | None:
    return round(sum(POINT_VALUE[c] for c in coverage) / len(coverage), 4) if coverage else None


def verdict_of(score: float | None, misread: bool) -> MessageVerdict | None:
    if score is None:
        return None
    if misread:
        return "misread"
    return "understood" if score >= UNDERSTOOD_AT else "partly" if score >= PARTLY_AT else "missed"


@dataclass
class Checked:
    """One participant as the comparison saw them. `completed` is False when the model returned nothing usable."""

    id: UUID
    ordinal: int
    state_code: str
    language: str
    language_name: str
    completed: bool
    restated: str = ""
    restated_en: str = ""
    coverage: dict[str, PointCoverage] = field(default_factory=dict)  # key point id -> label
    recalled: dict[str, bool] = field(default_factory=dict)
    misreading: str | None = None  # the label, when one was named

    def score(self, point_ids: Sequence[str]) -> float | None:
        return score_of([self.coverage[p] for p in point_ids if p in self.coverage]) if self.completed else None

    def verdict(self, point_ids: Sequence[str]) -> MessageVerdict | None:
        return verdict_of(self.score(point_ids), self.misreading is not None)


def rates(people: Sequence[Checked], point_ids: Sequence[str]) -> MessageCheckRates:
    done = [p for p in people if p.completed]
    counts = Counter(p.verdict(point_ids) for p in done)
    n = len(done)
    return MessageCheckRates(
        denominator=n, failed=len(people) - n, understood=counts["understood"], partly=counts["partly"], missed=counts["missed"],
        misread=counts["misread"], understood_rate=round(counts["understood"] / n, 4) if n else None)


def point_rates(people: Sequence[Checked], points: Sequence[tuple[str, str]]) -> list[MessageCheckPointRate]:
    done = [p for p in people if p.completed]
    out = []
    for pid, text in points:
        c = Counter(p.coverage.get(pid, "no") for p in done)
        out.append(MessageCheckPointRate(
            point_id=pid, text=text, restated_yes=c["yes"], restated_partly=c["partly"], restated_no=c["no"],
            recalled=sum(1 for p in done if p.recalled.get(pid)), denominator=len(done)))
    return out


def misreading_groups(people: Sequence[Checked], limit: int = 4, examples: int = 2) -> list[MessageCheckMisreadingGroup]:
    groups: dict[str, list[Checked]] = defaultdict(list)
    first: dict[str, str] = {}
    for p in people:
        if p.completed and p.misreading:
            key = label_key(p.misreading) or p.misreading
            groups[key].append(p)
            first.setdefault(key, p.misreading)
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]
    return [MessageCheckMisreadingGroup(
        label=first[k], participants=len(v),
        examples=[MessageCheckExample(participant_id=p.id, ordinal=p.ordinal, language_name=p.language_name, restated=p.restated,
                                      restated_en=p.restated_en) for p in sorted(v, key=lambda p: p.ordinal)[:examples]])
        for k, v in ranked]


def recommendations(region: str, people: Sequence[Checked], points: Sequence[tuple[str, str]], overall: MessageCheckRates,
                    groups: Sequence[MessageCheckMisreadingGroup], languages: Sequence[MessageCheckLanguageRow]) -> list[str]:
    n = overall.denominator
    if n == 0:
        return [f"No restatement could be compared in {region}. Run the check again before drawing any conclusion."]
    out: list[str] = []
    for rate in point_rates(people, points):
        if rate.restated_yes / n < LOW_POINT_RATE:
            out.append(
                f"Key point \"{rate.text}\": carried by {rate.restated_yes} of {n} restatements in {region} "
                f"(partly by {rate.restated_partly}). Check that the line carrying it is explicit in this region's copy.")
    if groups:
        top = groups[0]
        out.append(f"{overall.misread} of {n} restatements were marked as misreading the message in {region}; the most common: "
                   f"\"{top.label}\" ({top.participants}). Rewrite the line that invites it, then check again.")
    for row in languages:
        r = row.rates
        if (r.denominator >= 3 and overall.understood_rate is not None and r.understood_rate is not None
                and overall.understood_rate - r.understood_rate >= LANGUAGE_GAP):
            out.append(f"In {row.language_name}, {r.understood} of {r.denominator} understood the whole message, against "
                       f"{overall.understood} of {n} across {region}. Ask a {row.language_name} reader to review the copy.")
    if not out:
        out.append(f"{overall.understood} of {n} restatements in {region} carried every key point and none was marked as a "
                   "misreading. This check suggests no correction.")
    return out


def summarise(
    key_points: Sequence[tuple[str, str]], people: Sequence[Checked],
    regions: Sequence[tuple[RegionRef, CreativeCopy, str | None]],
) -> MessageCheckSummary:
    """Per-region and overall tallies. `regions` is (region, the copy it was shown, version ref) in request order."""
    ids = [p for p, _ in key_points]
    blocks = []
    for region, creative, ref in regions:
        mine = [p for p in people if p.state_code == region.code]
        overall = rates(mine, ids)
        by_language = []
        for code in dict.fromkeys(p.language for p in mine):
            group = [p for p in mine if p.language == code]
            by_language.append(MessageCheckLanguageRow(language=code, language_name=group[0].language_name, rates=rates(group, ids)))
        groups = misreading_groups(mine)
        blocks.append(MessageCheckRegion(
            region=region, creative=creative, version_ref=ref, rates=overall, points=point_rates(mine, key_points),
            by_language=by_language, misreadings=groups,
            recommendations=recommendations(region.name, mine, key_points, overall, groups, by_language)))
    return MessageCheckSummary(overall=rates(people, ids), regions=blocks, rules=RULES, rules_version=RULES_VERSION)


def overlap_with(message: str, restated_en: str) -> float | None:
    return wording_overlap(restated_en, message)
