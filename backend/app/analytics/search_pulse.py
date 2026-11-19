"""Search pulse: shape the BigQuery rows into stored rows, and stored rows into one state's view.

Pure functions, no I/O. Every number is copied from the dataset (rank, score, percent_gain); the only values computed here
are counts of weeks. In one dataset partition the term list and its ranks are the same for every state and week; what
differs by state and week is `score` (0 to 100, null where Google reported none), so a term's history is its score by week.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any

KEYS = ("region_code", "kind", "term", "week", "rank", "score", "percent_gain")


def shape(rows: Iterable[Mapping[str, Any]], *, weeks: int, code_for: Callable[[str], str | None]) -> list[dict[str, Any]]:
    """Dataset rows -> stored rows: Omnicult state codes (states with none are dropped), the newest `weeks` weeks of each
    kind, one row per (state, kind, term, week)."""
    kept = [r for r in rows if code_for(r["region_code"]) is not None and r.get("term")]
    newest: dict[str, set[date]] = {}
    for kind in ("top", "rising"):
        newest[kind] = set(sorted({r["week"] for r in kept if r["kind"] == kind}, reverse=True)[:weeks])
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in kept:
        if r["week"] not in newest[r["kind"]]:
            continue
        row = {"region_code": code_for(r["region_code"]), "kind": r["kind"], "term": r["term"], "week": r["week"],
               "rank": r.get("rank"), "score": r.get("score"), "percent_gain": r.get("percent_gain")}
        out[(row["region_code"], row["kind"], row["term"], row["week"])] = row
    return sorted(out.values(), key=lambda x: (x["region_code"], x["kind"], x["week"], x["rank"] or 0, x["term"]))


def view(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One state's stored rows -> {weeks, week, top, rising}. A list is the terms of the newest week of its kind, by rank;
    each term carries its history over every kept week (a week with no row has no entry) and `weeks_seen`, the weeks in
    which it has a score."""
    by_kind: dict[str, list[Mapping[str, Any]]] = {"top": [], "rising": []}
    for r in rows:
        by_kind[r["kind"]].append(r)
    weeks = sorted({r["week"] for kind in by_kind.values() for r in kind})
    lists: dict[str, list[dict[str, Any]]] = {}
    for kind, kind_rows in by_kind.items():
        latest = max((r["week"] for r in kind_rows), default=None)
        history: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in sorted(kind_rows, key=lambda x: x["week"]):
            history[r["term"]].append(r)
        lists[kind] = [
            {"term": r["term"], "rank": r["rank"], "score": r["score"], "percent_gain": r["percent_gain"], "week": latest,
             "weeks_seen": sum(1 for h in history[r["term"]] if h["score"] is not None),
             "history": [{"week": h["week"], "rank": h["rank"], "score": h["score"], "percent_gain": h["percent_gain"]} for h in history[r["term"]]]}
            for r in sorted((x for x in kind_rows if x["week"] == latest), key=lambda x: (x["rank"] or 0, x["term"]))
        ]
    return {"weeks": weeks, "week": max(weeks, default=None), **lists}
