"""Comment Pulse API: the labelled sample comments, counts and trends by code, the model reading and its code checks, tenancy."""

import json
import unicodedata
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.fixtures import pulse_comments as sample
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway
from app.services import studio_context
from tests.api.omnicult_support import API, add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

LABEL = "Comments"
COMMENTS = len(sample.generate_comments())


async def live_campaign(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return project, f"{API}/campaigns/{campaign['id']}/pulse/comments"


async def demo_campaign(client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    return project, f"{API}/campaigns/{campaign['id']}/pulse/comments"


async def loaded(client: httpx.AsyncClient, *, demo: bool = False) -> str:
    _, base = await (demo_campaign if demo else live_campaign)(client)
    response = await client.post(f"{base}/sample")
    assert response.status_code == 200, response.text
    return base


def scripted(responder: Callable[[dict[str, Any]], Any], monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Live projects use a real LLMGateway over a provider that answers with `responder` (not the demo fixture)."""
    seen: list[dict[str, Any]] = []

    class Provider(FixtureLLMProvider):
        name = "scripted"

    def answer(ctx: Any) -> Any:
        seen.append(dict(ctx))
        return responder(dict(ctx))

    provider = Provider({"comment-read-v1": answer})
    monkeypatch.setattr(studio_context, "gateway_for", lambda mode: LLMGateway(get_settings(), provider=provider, backoff_seconds=0))
    return seen


def assert_labelled(body: dict[str, Any]) -> None:
    assert body["is_sample"] is True and body["label"] == LABEL and body["source_kind"] == "sample"
    assert body["dataset_version"] == sample.DATASET_VERSION and body["limitations"]
    assert body["source_line"] == "" and not any(w in x.lower() for x in body["limitations"] for w in ("demo", "fixture", "sample"))


# --- the dataset ---------------------------------------------------------------------------------------------------


def test_the_dataset_is_deterministic_and_covers_every_language_script_and_version() -> None:
    first, again = sample.generate_comments(), sample.generate_comments()
    assert first == again and len({c.ref for c in first}) == len(first) == 88
    assert {c.language for c in first} == {"mr", "ta", "ml", "bn", "en"}
    assert {c.script for c in first} == {"Deva", "Taml", "Mlym", "Beng", "Latn"}
    assert {c.region_code for c in first} == {"IN-MH", "IN-TN", "IN-KL", "IN-WB"}
    assert {c.version_label for c in first} == {"v1 Original (Marathi)", "v2 Adapted A (regional language)", "v3 Adapted B (local festival reference)"}
    assert any(c.code_mixed and c.script == "Latn" and c.language != "en" for c in first), "regional language in Latin letters"
    assert any(c.code_mixed and c.script != "Latn" and any("a" <= ch.lower() <= "z" for ch in c.text) for c in first), "regional script with English"
    assert all(c.platform == "youtube" and 0 <= c.likes <= 60 for c in first)
    assert all(sample.START <= c.day <= sample.START + timedelta(days=20) for c in first)


def test_the_declared_script_matches_the_letters_actually_written() -> None:
    ranges = {"Deva": (0x0900, 0x097F), "Taml": (0x0B80, 0x0BFF), "Mlym": (0x0D00, 0x0D7F), "Beng": (0x0980, 0x09FF)}
    for c in sample.generate_comments():
        letters = [ch for ch in c.text if ch.isalpha() or unicodedata.category(ch).startswith("M")]  # vowel signs are marks
        if c.script == "Latn":
            assert all(ord(ch) < 0x250 for ch in letters), c.text
        else:
            lo, hi = ranges[c.script]
            native = sum(1 for ch in letters if lo <= ord(ch) <= hi)
            assert native / len(letters) > (0.25 if c.code_mixed else 0.9), c.text
            assert all(lo <= ord(ch) <= hi or ord(ch) < 0x250 for ch in letters), c.text


def test_demo_labels_cover_every_comment_and_only_known_themes() -> None:
    labels = sample.demo_labels()
    assert set(labels) == {c.ref for c in sample.generate_comments()}
    assert {s for s, _ in labels.values()} == {"positive", "neutral", "negative", "mixed"}
    assert {t for _, themes in labels.values() for t in themes} <= set(sample.THEMES)


# --- load, label, coverage ---------------------------------------------------------------------------------------------


async def test_nothing_is_loaded_until_the_explicit_action(client: httpx.AsyncClient) -> None:
    _, base = await live_campaign(client)
    status = (await client.get(f"{base}/status")).json()
    assert status["loaded"] is False and status["comment_count"] == 0 and status["analysis"] is None and status["is_sample"] is True
    for path in ("summary", "themes", ""):
        response = await client.get(f"{base}/{path}".rstrip("/"))
        assert response.status_code == 409 and "not loaded" in response.json()["error"]["message"], path
    assert (await client.post(f"{base}/read")).status_code == 409


async def test_load_and_reload_give_identical_labelled_rows(client: httpx.AsyncClient) -> None:
    base = await loaded(client)
    first = (await client.get(f"{base}/status")).json()
    assert first["loaded"] is True and first["comment_count"] == COMMENTS and first["label"] == LABEL
    assert first["regions"] == ["IN-KL", "IN-MH", "IN-TN", "IN-WB"] and first["languages"] == ["bn", "en", "ml", "mr", "ta"]
    assert first["date_from"] >= "2026-10-27" and first["date_to"] <= "2026-11-16"
    ids = sorted(c["id"] for c in (await client.get(f"{base}?limit=100")).json()["items"])
    again = await client.post(f"{base}/sample")
    assert again.status_code == 200 and again.json() == first
    assert sorted(c["id"] for c in (await client.get(f"{base}?limit=100")).json()["items"]) == ids, "ids are stable across reloads"
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseComment)) == COMMENTS  # replaced, not appended
        assert set(await s.scalars(select(m.PulseComment.source_kind).distinct())) == {"sample"}
        audits = await s.scalar(select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "pulse.comments.sample.load"))
        assert audits == 2


async def test_every_data_response_carries_the_sample_label(client: httpx.AsyncClient) -> None:
    base = await loaded(client)
    for path in ("summary", "themes", "?limit=5"):
        response = await client.get(f"{base}{'/' + path if not path.startswith('?') else path}")
        assert response.status_code == 200, (path, response.text)
        assert_labelled(response.json())


# --- counts and trends by code ----------------------------------------------------------------------------------------


async def test_the_summary_is_counted_by_code_and_says_nothing_about_sentiment_before_a_reading(client: httpx.AsyncClient) -> None:
    base = await loaded(client)
    summary = (await client.get(f"{base}/summary")).json()
    t = summary["totals"]
    assert t["comments"] == COMMENTS and t["likes"] == sum(c.likes for c in sample.generate_comments())
    assert summary["sentiment"] is None and summary["analysis"] is None
    assert summary["coverage"] == {"comments_in_dataset": COMMENTS, "comments_in_view": COMMENTS, "read_in_view": 0, "read_share": None, "languages_in_view": 5}
    assert [s["version_label"] for s in summary["slices"]].count("v1 Original (Marathi)") == 4 and len(summary["slices"]) == 10
    assert sum(s["comments"] for s in summary["slices"]) == COMMENTS
    assert all(s["sentiment"] is None and s["negative_share"] is None and s["confidence"] == "low" for s in summary["slices"])
    assert sum(d["comments"] for d in summary["daily"]) == COMMENTS and len(summary["daily"]) == 21
    assert sum(w["comments"] for w in summary["weekly"]) == COMMENTS
    assert [w["week_start"] for w in summary["weekly"]] == ["2026-10-27", "2026-11-03", "2026-11-10"]
    assert sum(lang["comments"] for lang in summary["languages"]) == COMMENTS
    by_lang = {lang["language"]: lang for lang in summary["languages"]}
    assert by_lang["mr"]["script"] == "Deva" and by_lang["ta"]["script"] == "Taml" and by_lang["en"]["code_mixed_comments"] == 0
    assert by_lang["ta"]["code_mixed_comments"] >= 1
    # the claim and festival mentions are found by watch terms in the text, not decided by a model
    assert t["claim_mentions"] == 8 and t["cultural_mentions"] == 8 and t["flagged_comments"] == 16


async def test_filters_scope_every_number_and_reject_unknown_values(client: httpx.AsyncClient) -> None:
    base = await loaded(client)
    tn = (await client.get(f"{base}/summary?region=IN-TN")).json()
    expected = sum(1 for c in sample.generate_comments() if c.region_code == "IN-TN")
    assert tn["totals"]["comments"] == expected and {s["region_code"] for s in tn["slices"]} == {"IN-TN"} and tn["filters"]["region"] == "IN-TN"
    assert tn["coverage"]["comments_in_dataset"] == COMMENTS and tn["coverage"]["comments_in_view"] == expected
    week_two = (await client.get(f"{base}/summary?date_from=2026-11-03&date_to=2026-11-09")).json()
    assert week_two["totals"]["comments"] == sum(1 for c in sample.generate_comments() if "2026-11-03" <= c.day.isoformat() <= "2026-11-09")
    ta = (await client.get(f"{base}/summary?language=ta&version=" + "v2 Adapted A (regional language)")).json()
    assert ta["totals"]["comments"] == sum(1 for c in sample.generate_comments() if c.language == "ta" and c.version_label.startswith("v2"))
    for query, field in (("region=IN-ZZ", "region"), ("version=nope", "version"), ("language=fr", "language")):
        bad = await client.get(f"{base}/summary?{query}")
        assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == field, query
    assert (await client.get(f"{base}/summary?date_from=2026-11-09&date_to=2026-11-01")).status_code == 422


async def test_claim_and_festival_mentions_surface_with_a_version_anchor(client: httpx.AsyncClient) -> None:
    base = await loaded(client)
    claims = (await client.get(f"{base}?flag=planted_claim&limit=100")).json()
    assert claims["total"] == 8 and all(c["version_label"].startswith("v1") for c in claims["items"])
    assert {c["anchor"]["region_code"] for c in claims["items"]} == {"IN-MH", "IN-TN", "IN-KL", "IN-WB"}
    for c in claims["items"]:
        flag = c["flags"][0]
        assert flag["kind"] == "planted_claim" and flag["evidence"] == "observed" and flag["matched_term"].casefold() in c["text"].casefold()
        assert c["anchor"]["version_label"] == c["version_label"] and c["interpretation"] is None
    assert [c["likes"] for c in claims["items"]] == sorted((c["likes"] for c in claims["items"]), reverse=True)
    festivals = (await client.get(f"{base}?flag=cultural_misstep&limit=100")).json()
    assert festivals["total"] == 8 and {c["region_code"] for c in festivals["items"]} == {"IN-KL", "IN-WB"}
    assert {c["flags"][0]["watch_id"] for c in festivals["items"]} == {"festival-onam", "festival-kali-puja"}
    anyflag = (await client.get(f"{base}?flag=any&limit=100")).json()
    assert anyflag["total"] == 16
    assert (await client.get(f"{base}?limit=100")).json()["total"] == COMMENTS


async def test_a_comment_is_anchored_to_the_closest_studio_version(client: httpx.AsyncClient) -> None:
    project, base = await live_campaign(client)
    cid = base.split("/campaigns/")[1].split("/")[0]
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={
        "label": "Original", "region_code": "IN-MH", "language": "mr",
        "elements": [{"id": "headline", "kind": "headline", "value": "x", "language": "mr", "script": "Deva"}]})).json()
    await client.post(f"{base}/sample")
    items = (await client.get(f"{base}?region=IN-MH&limit=100")).json()["items"]
    assert all(i["anchor"]["studio_version_id"] == root["id"] and i["anchor"]["studio_version_label"] == "Original" for i in items)
    tn = (await client.get(f"{base}?region=IN-TN&limit=100")).json()["items"]
    assert all(i["anchor"]["studio_version_id"] is None for i in tn if i["version_label"].startswith("v2")), "no Tamil Nadu version exists"


# --- the model reading -------------------------------------------------------------------------------------------------


async def test_a_demo_project_is_read_from_labelled_fixtures_and_never_a_provider(client: httpx.AsyncClient) -> None:
    base = await loaded(client, demo=True)
    done = await client.post(f"{base}/read")
    assert done.status_code == 200, done.text
    result = done.json()
    info = result["analysis"]
    assert result["reused"] is False and info["is_fixture"] is True and info["provider"] == "fixture" and info["mode"] == "demo"
    assert info["status"] == "completed" and info["comment_count"] == info["read_count"] == COMMENTS and info["dropped"] == {}
    assert info["prompt_version"] == "comment-read-v1"

    summary = (await client.get(f"{base}/summary")).json()
    s = summary["sentiment"]
    assert s["positive"] + s["neutral"] + s["negative"] + s["mixed"] == COMMENTS and s["unread"] == 0
    assert summary["coverage"]["read_share"] == 1.0
    expected = sample.demo_labels()
    refs = {c.ref: c for c in sample.generate_comments()}
    assert s["negative"] == sum(1 for r, (sent, _) in expected.items() if sent == "negative") and len(refs) == COMMENTS
    for sl in summary["slices"]:
        read = sum(sl["sentiment"][k] for k in ("positive", "neutral", "negative", "mixed"))
        assert read == sl["comments"] and sl["confidence"] == "moderate"  # 7 or more read; never above Moderate for sample comments
        assert sl["negative_share"] == round(sl["sentiment"]["negative"] / read, 3)
    originals = [sl for sl in summary["slices"] if sl["version_label"].startswith("v1") and sl["region_code"] != "IN-MH"]
    adapted = [sl for sl in summary["slices"] if sl["version_label"].startswith("v2")]
    assert sum(sl["negative_share"] for sl in originals) / len(originals) > sum(sl["negative_share"] for sl in adapted) / len(adapted)

    themes = (await client.get(f"{base}/themes")).json()
    assert themes["analysis"]["id"] == info["id"] and 5 <= len(themes["themes"]) <= 8
    stored = {c["id"]: c for c in (await client.get(f"{base}?limit=100")).json()["items"]}
    texts = {c["text"] for c in stored.values()}
    for theme in themes["themes"]:
        assert theme["quotes"] and len(theme["quotes"]) <= 3
        assert all(q["text"] in texts and q["id"] in stored and stored[q["id"]]["text"] == q["text"] for q in theme["quotes"]), "quotes are stored comments, verbatim"
        assert [q["likes"] for q in theme["quotes"]] == sorted((q["likes"] for q in theme["quotes"]), reverse=True)
        carried = [c for c in stored.values() if c["interpretation"] and theme["id"] in [t["id"] for t in c["interpretation"]["themes"]]]
        assert theme["comments"] == len(carried), "theme counts are code counts of the labels"
        assert sum(theme["sentiment"][k] for k in ("positive", "neutral", "negative", "mixed")) == theme["comments"]
    claim = next(t for t in themes["themes"] if t["id"] == "superiority-claim")
    assert claim["comments"] >= 6 and {r["key"] for r in claim["regions"]} == {"IN-MH", "IN-TN", "IN-KL", "IN-WB"}
    only_kl = (await client.get(f"{base}/themes?region=IN-KL")).json()
    assert all(r["key"] == "IN-KL" for t in only_kl["themes"] for r in t["regions"])
    negative = (await client.get(f"{base}?sentiment=negative&limit=100")).json()
    assert negative["total"] == s["negative"] and all(i["interpretation"]["sentiment"] == "negative" for i in negative["items"])
    by_theme = (await client.get(f"{base}?theme=delivery&limit=100")).json()
    assert by_theme["total"] == next(t for t in themes["themes"] if t["id"] == "delivery")["comments"]

    again = await client.post(f"{base}/read")
    assert again.json()["reused"] is True and again.json()["analysis"]["id"] == info["id"]
    forced = await client.post(f"{base}/read", json={"force": True})
    assert forced.json()["reused"] is False and forced.json()["analysis"]["id"] != info["id"]
    async with read_session() as s2:
        assert await s2.scalar(select(func.count()).select_from(m.CommentAnalysis)) == 2
        assert await s2.scalar(select(func.count()).select_from(m.AiUsageEvent)) == 0, "a demo project records no provider call"


async def test_a_live_reading_keeps_only_what_the_code_checks_accept(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    base = await loaded(client)
    refs = [c.ref for c in sample.generate_comments()]

    def answer(ctx: dict[str, Any]) -> dict[str, Any]:
        sent = [c["ref"] for c in ctx["comments"]]
        assert sent == refs and all(set(c) == {"ref", "region", "language", "text"} for c in ctx["comments"]), "the model sees refs, never ids"
        comments = [{"ref": r, "sentiment": "negative" if i % 2 else "positive", "themes": ["delivery"] if i < 10 else ["ghost", "solo"] if i == 10 else []}
                    for i, r in enumerate(sent[:-3])]  # the last three comments get no label
        comments += [{"ref": "cm-9999", "sentiment": "positive", "themes": []}, {"ref": sent[0], "sentiment": "neutral", "themes": []}]
        return {"comments": comments, "themes": [
            {"id": "delivery", "label": "Delivery", "summary": "People ask about delivery."},
            {"id": "solo", "label": "Only one", "summary": "Carried by a single comment."},
        ]}

    seen = scripted(answer, monkeypatch)
    done = await client.post(f"{base}/read")
    assert done.status_code == 200, done.text
    info = done.json()["analysis"]
    assert len(seen) == 1 and info["is_fixture"] is False and info["provider"] == "scripted" and info["mode"] == "live"
    assert info["status"] == "partial" and info["comment_count"] == COMMENTS and info["read_count"] == COMMENTS - 3
    assert info["dropped"] == {
        "label for a comment that was not sent": 1, "repeated label for one comment": 1, "theme id that was not defined": 1,
        "theme with fewer than 2 comments": 1}
    assert any("3 comment(s) came back without a usable label" in n for n in info["notes"])
    summary = (await client.get(f"{base}/summary")).json()
    assert summary["sentiment"]["unread"] == 3 and summary["coverage"]["read_in_view"] == COMMENTS - 3
    themes = (await client.get(f"{base}/themes")).json()
    assert [t["id"] for t in themes["themes"]] == ["delivery"] and themes["themes"][0]["comments"] == 10 and themes["unthemed"] == COMMENTS - 3 - 10
    async with read_session() as s:
        row = (await s.execute(select(m.CommentAnalysis))).scalar_one()
        assert row.provider == "scripted" and row.prompt_version == "comment-read-v1" and "cm-9999" not in row.labels


async def test_a_model_that_returns_nothing_usable_stores_nothing(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    base = await loaded(client)
    scripted(lambda ctx: {"comments": [{"ref": "cm-9999", "sentiment": "positive", "themes": []}], "themes": []}, monkeypatch)
    failed = await client.post(f"{base}/read")
    assert failed.status_code == 502 and "no usable labels" in failed.json()["error"]["message"]
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.CommentAnalysis)) == 0
    scripted(lambda ctx: {"comments": [{"ref": "cm-0001", "sentiment": "angry", "themes": []}], "themes": []}, monkeypatch)
    invalid = await client.post(f"{base}/read")
    assert invalid.status_code >= 500 and "error" in invalid.json(), "invalid model output is a typed failure, never a stored reading"
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.CommentAnalysis)) == 0


async def test_injected_instructions_in_a_comment_do_not_change_what_is_stored(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A comment is untrusted text: it reaches the model inside <untrusted_data> and the reply is validated like any other."""
    base = await loaded(client)
    prompts: list[str] = []
    original = LLMGateway.generate_structured

    async def spy(self: LLMGateway, **kwargs: Any) -> Any:
        prompts.append(kwargs["user"])
        return await original(self, **kwargs)

    monkeypatch.setattr(LLMGateway, "generate_structured", spy)
    scripted(lambda ctx: {"comments": [{"ref": c["ref"], "sentiment": "neutral", "themes": []} for c in ctx["comments"]], "themes": []}, monkeypatch)
    assert (await client.post(f"{base}/read")).status_code == 200
    assert prompts and "<untrusted_data" in prompts[0] and "</untrusted_data>" in prompts[0]


# --- access --------------------------------------------------------------------------------------------------------


async def test_another_workspace_gets_404_and_a_viewer_can_read_but_not_write(client: httpx.AsyncClient, client_for: Any) -> None:
    project, base = await live_campaign(client)
    await client.post(f"{base}/sample")
    stranger = client_for(BOB)
    for method, path in (("get", "status"), ("get", "summary"), ("get", "themes"), ("get", ""), ("post", "sample"), ("post", "read")):
        response = await getattr(stranger, method)(f"{base}/{path}".rstrip("/"))
        assert response.status_code == 404, (method, path, response.status_code)
    workspace = UUID(project["workspace_id"]) if project.get("workspace_id") else await workspace_of("alice")
    await add_member(workspace, "viewer-vic", "viewer")
    viewer = client_for({"Authorization": "Bearer dev-viewer-vic"})
    assert (await viewer.get(f"{base}/summary")).status_code == 200
    assert (await viewer.post(f"{base}/sample")).status_code == 403
    assert (await viewer.post(f"{base}/read")).status_code == 403
    assert (await client.get(f"{base}/summary", headers={})).status_code == 200


async def test_responses_never_contain_database_ids_in_the_model_prompt(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    base = await loaded(client)
    seen = scripted(lambda ctx: {"comments": [{"ref": c["ref"], "sentiment": "positive", "themes": []} for c in ctx["comments"]], "themes": []}, monkeypatch)
    await client.post(f"{base}/read")
    ids = {c["id"] for c in (await client.get(f"{base}?limit=100")).json()["items"]}
    assert ids and not any(i in json.dumps(seen[0]) for i in ids)
