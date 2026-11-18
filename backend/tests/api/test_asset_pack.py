"""Asset Pack: a ZIP per region for the approved version, with provenance and checksums, behind an expiring link."""

import hashlib
import io
import json
import zipfile
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import delivery as d
from app.services import asset_pack
from tests.api.delivery_support import KL, TN, add_asset, add_creative, add_scene, add_version, approve, campaign_of
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_desk import fixture_brief
from tests.conftest import BOB

CAPTIONS = [
    {"id": "cap-1", "kind": "caption", "value": "First line", "language": "ta", "scene_id": "S1"},
    {"id": "cap-2", "kind": "caption", "value": "Second line", "language": "ta", "scene_id": "S2"},
]


async def with_brief(client: httpx.AsyncClient, c: dict[str, Any]) -> None:
    saved = await client.put(f"{c['base']}/brief", json={"content": fixture_brief(), "expected_version": 0})
    assert saved.status_code == 200, saved.text


async def pack_setup(client: httpx.AsyncClient) -> dict[str, Any]:
    """A live campaign with a brief, a Tamil version with captions in two scenes, and a spread of registered creative files."""
    c = await campaign_of(client)
    await with_brief(client, c)
    film = await add_asset(c, filename="film.mp4", data=b"mp4-bytes", kind="video", content_type="video/mp4")
    still = await add_asset(c, filename="still.png", data=b"png-bytes")
    draft = await add_asset(c, filename="draft.png", data=b"png-draft", rights=False)
    other = await add_asset(c, filename="kerala.png", data=b"png-kerala")
    loose = await add_asset(c, filename="loose.png", data=b"png-loose")
    film_creative = await add_creative(c, film, label="Tamil film", region=TN, kind="video")
    await add_creative(c, still, label="Tamil key visual", region=TN)
    await add_creative(c, draft, label="Tamil draft", region=TN)
    await add_creative(c, other, label="Kerala visual", region=KL)
    await add_creative(c, loose, label="Unplaced visual", region=None)
    s1, s2 = await add_scene(c, film_creative, film, 0, 4000), await add_scene(c, film_creative, film, 4000, 9000)
    elements = [{**e, "scene_id": str({"S1": s1, "S2": s2}[e["scene_id"]])} for e in CAPTIONS] + [
        {"id": "headline", "kind": "headline", "value": "Deepavali vazhthukkal", "language": "ta"}]
    version = await add_version(c, "Tamil Nadu: Tamil", TN, "ta", elements)
    logo = await add_asset(c, filename="logo.png", data=b"logo-bytes")
    kit = await client.put(f"{API}/projects/{c['project']['id']}/brand-kit", json={"design": {
        "logo": {"lockups": [{"id": "primary", "use": "Main lockup", "asset_id": str(logo.id)}]},
        "product_images": [{"id": "pack", "asset_id": str(draft.id)}, {"id": "unlinked"}]}})
    assert kit.status_code == 200, kit.text
    return c | {"version": version, "assets": {"film": film, "still": still, "draft": draft, "logo": logo}}


async def unzip(client: httpx.AsyncClient, url: str) -> zipfile.ZipFile:
    response = await client.get(url, headers={"Authorization": ""})
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


# --- the gate ---------------------------------------------------------------------------------------------------------------


async def test_a_region_without_an_approval_has_no_pack(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    preview = (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()
    assert preview["can_build"] is False and preview["manifest"] is None and "approval" in preview["blocked_reason"]
    assert (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})).status_code == 409
    await approve(client, c, c["version"], decision="request_changes")
    assert (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["can_build"] is False, "a change request is no approval"
    assert (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": "IN-ZZ"})).status_code == 404


async def test_only_an_approved_version_of_the_region_can_be_packed(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    other = await add_version(c, "Tamil v2")
    await approve(client, c, c["version"])
    assert (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN, "version_id": str(other)})).status_code == 409
    assert (await client.post(f"{c['base']}/asset-packs", json={"region_code": KL})).status_code == 409, "approved for Tamil Nadu is not approved for Kerala"
    await approve(client, c, other)
    newest = (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()
    assert [v["id"] for v in newest["approved_versions"]] == [str(other), str(c["version"])]
    assert newest["manifest"]["version"]["id"] == str(other)
    older = await client.post(f"{c['base']}/asset-packs", json={"region_code": TN, "version_id": str(c["version"])})
    assert older.status_code == 201 and older.json()["version_id"] == str(c["version"])


async def test_a_later_change_request_ends_a_versions_approval(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    assert (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["can_build"] is True
    await approve(client, c, c["version"], decision="request_changes")
    assert (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["can_build"] is False


# --- what goes in --------------------------------------------------------------------------------------------------------------


async def test_the_pack_holds_the_approved_copy_creatives_captions_and_brand_kit_with_checksums(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    approval = await approve(client, c, c["version"])
    response = await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})
    assert response.status_code == 201, response.text
    pack = response.json()
    zf = await unzip(client, pack["download_url"])
    stem = "omc_" + pack["manifest"]["campaign_slug"] + "_tamil-nadu-tamil_IN-TN"
    assert pack["filename"] == f"{stem}.zip" and pack["manifest"]["naming"] == "omc_<campaign>_<version>_<region>_<channel>"
    assert sorted(zf.namelist()) == sorted([
        "SHA256SUMS", "manifest.json", f"copy/{stem}_all.json", f"copy/{stem}_all.txt", f"creatives/{stem}_instagram_reels.mp4",
        f"creatives/{stem}_meta_feed.png", f"captions/{stem}_instagram_reels.srt", "brand-kit/logo-primary.png", "brand-kit/brand-kit.json"])
    whole = (await client.get(pack["download_url"])).content
    assert pack["file_count"] == len(zf.namelist()) and hashlib.sha256(whole).hexdigest() == pack["sha256"]
    files = {f["path"]: f for f in pack["manifest"]["files"]}
    video, image = files[f"creatives/{stem}_instagram_reels.mp4"], files[f"creatives/{stem}_meta_feed.png"]
    assert (video["channel"], video["also_channels"], video["channel_match"]) == ("instagram_reels", ["youtube_shorts"], "format")
    assert (image["channel"], image["channel_match"]) == ("meta_feed", "format") and video["asset_id"] and video["rights_confirmed_at"]
    for path, entry in files.items():  # every checksum in the manifest and in SHA256SUMS is the real one
        assert hashlib.sha256(zf.read(path)).hexdigest() == entry["sha256"] and len(zf.read(path)) == entry["size"], path
    sums = {name: digest for digest, name in (line.split("  ", 1) for line in zf.read("SHA256SUMS").decode().splitlines())}
    assert sums == {p: f["sha256"] for p, f in files.items()}
    assert zf.read(f"creatives/{stem}_instagram_reels.mp4") == b"mp4-bytes"
    assert b"png-draft" not in whole and b"png-kerala" not in whole and b"png-loose" not in whole, "unconfirmed or other-region files are not in the ZIP"
    inner = json.loads(zf.read("manifest.json"))
    assert inner["files"] == pack["manifest"]["files"] and inner["approval"]["id"] == approval["id"] and inner["generated_at"]
    assert inner["version"]["id"] == str(c["version"]) and inner["campaign_id"] == c["id"] and inner["region_code"] == TN
    assert inner["approval"]["overrides_recommendation"] is True, "approved with no Go recommendation on record: the manifest says so"
    copy = json.loads(zf.read(f"copy/{stem}_all.json"))
    assert copy["version"]["id"] == str(c["version"]) and {e["id"] for e in copy["elements"]} >= {"headline", "cap-1"}
    assert "headline" in zf.read(f"copy/{stem}_all.txt").decode()
    assert zf.read(f"captions/{stem}_instagram_reels.srt").decode() == (
        "1\n00:00:00,000 --> 00:00:04,000\nFirst line\n\n2\n00:00:04,000 --> 00:00:09,000\nSecond line\n")
    assert json.loads(zf.read("brand-kit/brand-kit.json"))["logo"]["lockups"][0]["id"] == "primary"
    channels = {ch["id"]: ch["files"] for ch in inner["channels"]}
    assert channels["instagram_reels"] == 1 and channels["youtube_shorts"] == 1 and channels["meta_feed"] == 1


async def test_files_without_confirmed_rights_or_for_other_regions_are_left_out_with_the_reason(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    manifest = (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["manifest"]
    reasons = {(x["kind"], x["label"]): x["reason"] for x in manifest["excluded"]}
    assert "Rights were not confirmed" in reasons[("creative", "Tamil draft")]
    assert "IN-KL, not IN-TN" in reasons[("creative", "Kerala visual")]
    assert "No region is set" in reasons[("creative", "Unplaced visual")]
    assert "Rights were not confirmed" in reasons[("brand_kit_product", "pack")]
    assert "No uploaded file is linked" in reasons[("brand_kit_product", "unlinked")]
    assert not any("draft" in f["path"] or "kerala" in f["path"] for f in manifest["files"])


async def test_a_file_whose_bytes_no_longer_match_its_recorded_checksum_is_left_out(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    async with session() as s, s.begin():
        (await s.get(m.Asset, c["assets"]["still"].id)).sha256 = "0" * 64
    pack = (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})).json()
    assert not any(f["path"].endswith("meta_feed.png") for f in pack["manifest"]["files"])
    assert any("do not match the SHA-256" in x["reason"] for x in pack["manifest"]["excluded"])


async def test_a_file_the_version_names_in_an_element_goes_in_when_its_rights_are_confirmed(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    render, unconfirmed = await add_asset(c, filename="render.png", data=b"render"), await add_asset(c, filename="raw.png", data=b"raw", rights=False)
    version = await add_version(c, "Tamil render", TN, "ta", [
        {"id": "visual", "kind": "image_region", "value": str(render.id)}, {"id": "other", "kind": "scene", "value": {"asset_id": str(unconfirmed.id)}},
        {"id": "headline", "kind": "headline", "value": "Vanakkam"}])
    await approve(client, c, version)
    manifest = (await client.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["manifest"]
    assert [f["path"].rsplit(".", 1)[-1] for f in manifest["files"] if f["role"] == "creative"] == ["png"]
    assert any(x["label"] == "raw.png" and "Rights were not confirmed" in x["reason"] for x in manifest["excluded"])


async def test_a_pack_larger_than_the_limit_is_refused(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSET_PACK_MAX_BYTES", str(1024 * 1024))
    get_settings.cache_clear()
    c = await campaign_of(client)
    big = await add_asset(c, filename="big.png", data=b"\0" * (1024 * 1024 + 1))
    await add_creative(c, big, label="Big", region=TN)
    version = await add_version(c)
    await approve(client, c, version)
    refused = await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})
    assert refused.status_code == 409 and "limit" in refused.json()["error"]["message"]


# --- the expiring link -------------------------------------------------------------------------------------------------------


async def test_the_download_link_expires_and_every_failure_is_the_same_404(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    pack = (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})).json()
    url = pack["download_url"]
    ok = await client.get(url, headers={"Authorization": ""})
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/zip"
    assert ok.headers["content-disposition"] == f'attachment; filename="{pack["filename"]}"' and ok.headers["x-content-type-options"] == "nosniff"
    path, token = url.split("?token=")
    bad = await client.get(path, params={"token": token[:-1] + ("a" if token[-1] != "a" else "b")})
    missing = await client.get(f"{API}/asset-packs/{uuid4()}/download", params={"token": token})
    async with session() as s, s.begin():
        (await s.get(m.AssetPack, UUID(pack["id"]))).expires_at = utcnow() - timedelta(seconds=1)
    expired = await client.get(url)
    assert [r.status_code for r in (bad, missing, expired)] == [404, 404, 404]
    assert len({r.json()["error"]["message"] for r in (bad, missing, expired)}) == 1
    async with read_session() as s:
        row = (await s.execute(select(m.AssetPack))).scalar_one()
    assert token not in str(row.manifest) and row.token_hash and token not in row.token_hash
    listed = (await client.get(f"{c['base']}/asset-packs")).json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "expired"
    detail = (await client.get(f"{API}/asset-packs/{pack['id']}")).json()
    assert detail["manifest"]["files"] == pack["manifest"]["files"] and "download_url" not in detail


async def test_building_needs_a_writer_and_reading_needs_only_membership(client_for: Any, client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    await add_member(UUID(c["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{c['base']}/asset-packs/preview", params={"region_code": TN})).json()["can_build"] is True
    assert (await bob.post(f"{c['base']}/asset-packs", json={"region_code": TN})).status_code == 403
    pack = (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})).json()
    assert (await bob.get(f"{c['base']}/asset-packs")).json()["total"] == 1 and (await bob.get(f"{API}/asset-packs/{pack['id']}")).status_code == 200
    stranger = client_for({"Authorization": "Bearer dev-stranger"})
    assert (await stranger.get(f"{API}/asset-packs/{pack['id']}")).status_code == 404
    assert (await stranger.post(f"{c['base']}/asset-packs", json={"region_code": TN})).status_code == 404
    other = await campaign_of(client)
    assert (await client.get(f"{other['base']}/asset-packs")).json()["total"] == 0, "packs never cross campaigns"


async def test_building_writes_an_audit_entry(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await pack_setup(client)
    await approve(client, c, c["version"])
    pack = (await client.post(f"{c['base']}/asset-packs", json={"region_code": TN})).json()
    async with read_session() as s:
        audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "asset_pack.build"))).scalar_one()
    assert audit.target_id == pack["id"] and audit.detail["region"] == TN and audit.detail["files"] == len(pack["manifest"]["files"])


# --- pure functions ------------------------------------------------------------------------------------------------------------


def test_captions_share_a_scene_evenly_and_untimed_ones_are_skipped() -> None:
    elements = [{"kind": "caption", "value": "a", "scene_id": "s1"}, {"kind": "caption", "value": "b", "scene_id": "s1"},
                {"kind": "caption", "value": "c", "scene_id": "s2"}, {"kind": "caption", "value": "d", "scene_id": "gone"},
                {"kind": "headline", "value": "not a caption", "scene_id": "s1"}]
    srt = asset_pack.build_srt(elements, {"s1": (0, 4000), "s2": (4000, None)})
    assert srt == "1\n00:00:00,000 --> 00:00:02,000\na\n\n2\n00:00:02,000 --> 00:00:04,000\nb\n"
    assert asset_pack.build_srt(elements, {}) is None
    assert asset_pack.srt_time(3_723_456) == "01:02:03,456"


def test_names_are_predictable_ascii_cut_at_a_word() -> None:
    assert asset_pack.slug("Aamod Festive Tin, Diwali 2027: from Maharashtra") == "aamod-festive-tin-diwali"
    assert asset_pack.slug("Original - Maharashtra (Marathi)") == "original-maharashtra"
    assert asset_pack.slug("தமிழ்", "version") == "version" and asset_pack.slug("Tamil") == "tamil"
    assert asset_pack.stem("aamod", "tamil", "IN-TN", "meta_feed") == "omc_aamod_tamil_IN-TN_meta_feed"


def test_a_creative_is_named_for_the_channel_the_brief_points_at_else_the_first_that_names_its_kind_else_all() -> None:
    channels = [{"id": "reels", "format": "9:16 video"}, {"id": "shorts", "format": "video", "creative_ref": "asset-9"},
                {"id": "feed", "format": "4:5 image", "creative_ref": "cr-1"}]
    assert asset_pack.channel_for("image", {"cr-1"}, channels) == ("feed", [], "creative_ref")
    assert asset_pack.channel_for("video", {"asset-9"}, channels) == ("shorts", [], "creative_ref")
    assert asset_pack.channel_for("video", {"zzz"}, channels) == ("reels", ["shorts"], "format")
    assert asset_pack.channel_for("audio", {"zzz"}, channels) == ("all", [], "none")


def test_the_zip_is_the_same_bytes_for_the_same_inputs_and_lists_entries_in_order() -> None:
    from datetime import UTC, datetime

    files = [d.PackFile(path="a.txt", role="copy_text", size=1, sha256=hashlib.sha256(b"a").hexdigest(), source="s", asset_id=None, rights_confirmed_at=None,
                        channel="all", also_channels=[], channel_match="none", width=None, height=None)]
    manifest = d.AssetPackManifest(
        schema_version="x", naming="n", campaign_id=uuid4(), campaign_name="c", campaign_slug="c", region_code=TN, region_name="Tamil Nadu",
        version=d.PackVersion(id=uuid4(), label="v", language=None, region_code=TN, actor="user", created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        approval=d.PackApproval(id=uuid4(), decision="approve", decided_by_name=None, decided_at=datetime(2026, 1, 1, tzinfo=UTC), reason="r",
                                verdict_at_decision="go", overrides_recommendation=False),
        channels=[], files=files, excluded=[], notes=[], mode="live", generated_at=None)
    when = datetime(2026, 11, 18, 10, 0, 0, tzinfo=UTC)
    first, second = (asset_pack.build_zip(manifest, {"a.txt": b"a", "z.txt": b"z"}, when) for _ in range(2))
    assert first == second
    assert zipfile.ZipFile(io.BytesIO(first)).namelist() == ["SHA256SUMS", "a.txt", "manifest.json", "z.txt"]
