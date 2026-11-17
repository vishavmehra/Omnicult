"""The Omnicult demo fixtures (fictional brand Aamod) stay consistent, labelled and complete.

Other streams read these files (Brand Kit, Glossary, Campaign Brief, original Maharashtra creative); this guards
their shared shape: creative elements, anchors, asset references, region and language codes.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.reference.india import DEMO_REGIONS, REGIONS, SCRIPT_OF
from scripts.demo_assets.common import guard, record, spent

ROOT = Path(__file__).resolve().parents[3] / "app" / "fixtures" / "omnicult_demo"
FILES = ("brand_kit.json", "brand_glossary.json", "campaign_brief.json", "creative_mh_original.json")
ELEMENT_KEYS = {"id", "kind", "value", "language", "script", "bbox", "scene_id", "locked"}
ELEMENT_KINDS = {"headline", "body", "cta", "tagline", "logo", "product", "packshot", "image_region", "scene", "voiceover",
                 "music", "caption"}
ASSET_PATH = re.compile(r"^(brand|creative)/[\w./-]+\.(png|jpg|svg|mp4|wav|srt)$")


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)
    elif isinstance(node, str):
        yield node


@pytest.mark.parametrize("name", FILES)
def test_every_file_is_a_labelled_fixture_whose_assets_exist(name):
    doc = load(name)
    assert doc["fixture"]["kind"] == "demo_fixture" and doc["fixture"]["version"] >= 1
    assert re.search(r"fictional|Demonstration", doc["fixture"]["label"])
    paths = [s for s in strings(doc) if ASSET_PATH.match(s)]
    assert all((ROOT / p).is_file() for p in paths), [p for p in paths if not (ROOT / p).is_file()]


def test_creative_elements_follow_the_shared_shape():
    doc = load("creative_mh_original.json")
    ids = []
    for creative in doc["creatives"]:
        scene_ids = {s["id"] for s in creative.get("scenes", [])}
        for el in creative["elements"]:
            assert set(el) == ELEMENT_KEYS and el["kind"] in ELEMENT_KINDS, el["id"]
            assert el["scene_id"] is None or el["scene_id"] in scene_ids, el["id"]
            assert el["language"] in {None, "mr", "en"} and el["script"] in {None, "Deva", "Latn"}
            if el["bbox"] is not None:
                x, y, w, h = el["bbox"]
                assert 0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1.001 and y + h <= 1.001, el["id"]
            ids.append(el["id"])
        locked = {el["kind"] for el in creative["elements"] if el["locked"]}
        assert {"logo", "packshot", "tagline"} <= locked  # never-change zones are locked in both creatives
    assert len(ids) == len(set(ids))


def test_creative_assets_match_their_hashes_and_the_video_brief():
    doc = load("creative_mh_original.json")
    video, key_visual = doc["creatives"]
    for asset in (video["asset"], video["captions"], key_visual["asset"], key_visual["plate"], *filter(None, doc["stems"].values())):
        data = (ROOT / asset["path"]).read_bytes()
        assert len(data) == asset["bytes"] and hashlib.sha256(data).hexdigest() == asset["sha256"], asset["path"]
    meta = video["asset"]
    assert (meta["width"], meta["height"]) == (1080, 1920) and 20_000 <= meta["duration_ms"] <= 30_000
    assert meta["bytes"] < 10 * 1024 * 1024
    lines = video["transcript"]
    assert all(a["end_ms"] <= b["start_ms"] for a, b in zip(lines, lines[1:]))
    assert lines[-1]["end_ms"] <= meta["duration_ms"] and all(line["translation_en"] for line in lines)
    assert (ROOT / video["captions"]["path"]).read_text(encoding="utf-8").count(" --> ") == len(lines)


def test_authoring_notes_point_at_real_elements_and_the_planted_risk_is_there():
    doc = load("creative_mh_original.json")
    elements = {el["id"]: el for c in doc["creatives"] for el in c["elements"]}
    transcript = {line["id"] for line in doc["creatives"][0]["transcript"]}
    scenes = {s["id"] for s in doc["creatives"][0]["scenes"]}
    notes = doc["authoring_notes"]
    assert "not evidence" in notes["label"].lower()
    for item in notes["adaptation_hooks"] + notes["deliberate_risks"]:
        assert set(item.get("element_ids", [])) <= set(elements), item["id"]
        assert set(item.get("transcript_ids", [])) <= transcript and set(item.get("scene_ids", [])) <= scenes
    planted = [r for r in notes["deliberate_risks"] if r["planted"]]
    assert planted and all("सर्वोत्तम" in elements[e]["value"] for e in ("mh-vid-small-print", "mh-kv-small-print"))


def test_brief_regions_languages_dates_and_budget_are_consistent():
    brief, kit, glossary = load("campaign_brief.json"), load("brand_kit.json"), load("brand_glossary.json")
    codes = {row.code for row in REGIONS}
    regions = [brief["regions"]["origin"], *brief["regions"]["targets"]]
    assert regions == list(DEMO_REGIONS) and set(regions) <= codes
    for region, langs in brief["languages"].items():
        assert [SCRIPT_OF[lang] for lang in langs] == brief["scripts"][region]
    start, end = date.fromisoformat(brief["dates"]["start"]), date.fromisoformat(brief["dates"]["end"])
    assert start < end and {start.month, end.month} <= {10, 11}
    source_ids = {s["id"] for s in brief["dates"]["sources"]}
    assert all(set(m["source_ids"]) <= source_ids and start <= date.fromisoformat(m["date"]) <= end
               for m in brief["dates"]["key_moments"])
    assert sum(brief["budget"]["by_region"].values()) == brief["budget"]["total"]
    terms = {e["term"] for e in glossary["entries"]}
    assert set(glossary["never_translate"]) <= terms
    assert {t["term"] for t in kit["protected_terms"]} == set(glossary["never_translate"])
    assert kit["tagline"]["text"] in glossary["never_translate"]


def test_spend_ledger_sums_rows_and_the_guard_stops_overspend(tmp_path):
    log = tmp_path / "log.md"
    assert spent(log) == 0.0
    record("pack", "m", "global", "1:1", "ok", 10, "1/2", 0.067, "a.png", log=log)
    assert record("tts", "m", "global", "a|b", "ok", 10, "-", 0.5, "b.wav", log=log) == pytest.approx(0.567)
    assert spent(log) == pytest.approx(0.567)
    guard(1.4, log=log, budget=2.0)
    with pytest.raises(SystemExit):
        guard(1.5, log=log, budget=2.0)
