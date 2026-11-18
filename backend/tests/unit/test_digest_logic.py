"""Pure checks: what the code accepts from the comment reader and the digest summary, and the digest's formatting."""

import pytest
from pydantic import ValidationError

from app.agents.comment_read import CommentReadOut, validate_read
from app.agents.digest_summary import numbers_in, stray_numbers
from app.services.digest_build import fmt, fmt_pct

REFS = ["cm-0001", "cm-0002", "cm-0003", "cm-0004"]


def read(comments: list[dict], themes: list[dict]) -> CommentReadOut:
    return CommentReadOut.model_validate({"comments": comments, "themes": themes})


def test_the_reader_output_is_strict_about_shape() -> None:
    for bad in (
        {"comments": [{"ref": "cm-0001", "sentiment": "angry", "themes": []}], "themes": []},
        {"comments": [{"ref": "cm-0001", "sentiment": "positive", "themes": ["a", "b", "c", "d"]}], "themes": []},
        {"comments": [{"ref": "cm-0001", "sentiment": "positive", "themes": ["Bad Id"]}], "themes": []},
        {"comments": [{"ref": "cm-0001", "sentiment": "positive", "themes": [], "quote": "invented"}], "themes": []},
        {"comments": [], "themes": [{"id": f"t{i}", "label": "x", "summary": "y"} for i in range(9)]},
    ):
        with pytest.raises(ValidationError):
            CommentReadOut.model_validate(bad)


def test_code_keeps_only_labels_for_comments_that_were_sent() -> None:
    out = read(
        [{"ref": "cm-0001", "sentiment": "positive", "themes": ["a"]}, {"ref": "cm-0001", "sentiment": "negative", "themes": ["a"]},
         {"ref": "cm-0002", "sentiment": "neutral", "themes": ["a", "zzz"]}, {"ref": "cm-7777", "sentiment": "positive", "themes": []}],
        [{"id": "a", "label": "A", "summary": "About a."}, {"id": "a", "label": "A again", "summary": "Repeated."}])
    result = validate_read(out, REFS)
    assert result.labels == {"cm-0001": {"sentiment": "positive", "themes": ["a"]}, "cm-0002": {"sentiment": "neutral", "themes": ["a"]}}
    assert result.themes == [{"id": "a", "label": "A", "summary": "About a."}]
    assert result.dropped == {
        "repeated theme id": 1, "repeated label for one comment": 1, "theme id that was not defined": 1,
        "label for a comment that was not sent": 1}
    assert any("2 comment(s) came back without a usable label" in n for n in result.notes)


def test_a_theme_carried_by_one_comment_is_not_a_pattern() -> None:
    out = read([{"ref": "cm-0001", "sentiment": "positive", "themes": ["solo", "pair"]}, {"ref": "cm-0002", "sentiment": "negative", "themes": ["pair"]}],
               [{"id": "solo", "label": "Solo", "summary": "One."}, {"id": "pair", "label": "Pair", "summary": "Two."}])
    result = validate_read(out, REFS)
    assert [t["id"] for t in result.themes] == ["pair"] and result.labels["cm-0001"]["themes"] == ["pair"]
    assert result.dropped == {"theme with fewer than 2 comments": 1}


def test_a_summary_may_only_use_numbers_the_facts_hold() -> None:
    facts = ["Week 2026-W46, 2026-11-09 to 2026-11-15.", "Kerala, v1: CTR 0.91% (change -14.2%), CPM INR 95.12 (change +3.0%).", "Impressions 1,234,567."]
    assert numbers_in("CTR 0.91%, down 14.2%; 1,234,567 impressions.") == {"0.91", "14.2", "1234567"}
    assert stray_numbers("CTR fell to 0.91%, down 14.2% in week 2026.", facts) == []
    assert stray_numbers("Impressions were 1234567 and CPM INR 95.12.", facts) == []
    assert stray_numbers("CTR fell 14.3% and spend reached 5000.", facts) == ["14.3", "5000"]
    assert stray_numbers("Nothing to report this week.", facts) == []


def test_figures_are_formatted_the_same_way_everywhere() -> None:
    assert fmt("ratio", 0.0091234) == "0.91%" and fmt("inr", 95.1234) == "INR 95.12" and fmt("inr", 123456.7) == "INR 123,457"
    assert fmt("multiple", 3.456) == "3.46x" and fmt("count", 1234567.4) == "1,234,567" and fmt("ratio", None) == "n/a"
    assert fmt_pct(-0.1423) == "-14.2%" and fmt_pct(0.03) == "+3.0%" and fmt_pct(None) == "n/a"
