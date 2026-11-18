"""Comment Pulse and the Weekly Digest on the Aamod demo journey: the demo hook populates both with no provider and no network."""

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.db import models as m
from app.db.session import read_session
from app.services.digest_demo import seed_comment_pulse_and_digests
from tests.api.test_demo_aamod import aamod, no_network  # noqa: F401

API = "/api/v1"


async def test_the_demo_hook_populates_comment_pulse_and_the_digest_for_the_aamod_campaign(aamod: httpx.AsyncClient) -> None:
    client = aamod
    with no_network():
        project = (await client.post(f"{API}/projects/demo")).json()
        cid = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]["id"]
        await seed_comment_pulse_and_digests(dev_user_id("alice"), UUID(cid))
        await seed_comment_pulse_and_digests(dev_user_id("alice"), UUID(cid))  # a repeat changes nothing
    pulse = f"{API}/campaigns/{cid}/pulse"

    # Comment Pulse: read from labelled fixtures, flagged comments anchored to real Creative Studio versions
    status = (await client.get(f"{pulse}/comments/status")).json()
    assert status["loaded"] is True and status["comment_count"] == 88 and status["analysis"]["is_fixture"] is True
    assert status["analysis"]["status"] == "completed" and status["analysis"]["provider"] == "fixture"
    flagged = (await client.get(f"{pulse}/comments?flag=any&limit=100")).json()["items"]
    assert len(flagged) == 16
    assert all(c["anchor"]["studio_version_id"] is not None and c["anchor"]["studio_version_label"] for c in flagged), \
        "every flagged comment points at a version that exists in Creative Studio"
    claims = [c for c in flagged if c["flags"][0]["kind"] == "planted_claim"]
    assert len(claims) == 8 and {c["anchor"]["studio_version_label"] for c in claims} == {"Original · Maharashtra (Marathi)"}
    festival = [c for c in flagged if c["flags"][0]["kind"] == "cultural_misstep"]
    assert {c["region_code"] for c in festival} == {"IN-KL", "IN-WB"} and all(c["interpretation"]["sentiment"] for c in festival)
    themes = (await client.get(f"{pulse}/comments/themes")).json()
    assert {t["id"] for t in themes["themes"]} >= {"language-fit", "superiority-claim", "festival-reference"}

    # Weekly Digest: three stored weeks, the newest carrying what the seed recorded
    listing = (await client.get(f"{pulse}/digests")).json()
    assert len(listing["items"]) == 3 and listing["narrative_available"] is False
    assert [i["week"]["start"] for i in listing["items"]] == sorted((i["week"]["start"] for i in listing["items"]), reverse=True)
    assert listing["items"][0]["week"]["label"] == listing["current_week"]["label"]
    digest = (await client.get(f"{pulse}/digests/{listing['items'][0]['id']}")).json()
    content = digest["content"]
    changed = content["what_changed"]["counts"]
    assert changed["creative_versions"] > 0 and changed["verdicts"] > 0 and changed["agent_runs"] > 0 and changed["audience_runs"] > 0
    assert content["pulse"]["available"] is True and content["pulse"]["alerts"], "the Pulse sample's wearing-out and cost-spike alerts"
    assert content["comments"]["available"] is True and content["comments"]["themes"] and content["comments"]["sentiment"] is not None
    assert content["mode"] == "demo" and digest["narrative"] is None and digest["trigger"] == "manual"
    for item in content["open_items"]["not_ready"]:
        assert item["verdict"] in ("fix", "rethink")
    assert [a["rule"] for a in content["next_actions"]][:1] != [] and len(content["next_actions"]) <= 8
    older = (await client.get(f"{pulse}/digests/{listing['items'][2]['id']}")).json()["content"]
    assert older["pulse"]["available"] is True and sum(older["what_changed"]["counts"].values()) == 0, "records of the seed are not in an older week"

    # exports of the seeded digest
    md = await client.get(f"{pulse}/digests/{digest['id']}/export?format=md")
    assert md.status_code == 200 and "Aamod" in md.text and "Theme (Model interpretation)" in md.text
    pdf = await client.get(f"{pulse}/digests/{digest['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseComment)) == 88, "a repeat of the hook replaced, not appended"
        assert await s.scalar(select(func.count()).select_from(m.PulseDigest)) == 3
        assert await s.scalar(select(func.count()).select_from(m.CommentAnalysis)) == 1, "the newest reading was reused"
        providers: Any = set(await s.scalars(select(m.CommentAnalysis.provider)))
        assert providers == {"fixture"}
