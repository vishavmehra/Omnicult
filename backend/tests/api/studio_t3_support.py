"""Shared helpers for the Creative Studio Tier 3 tests: a live project with a positioned creative, and the Aamod demo journey."""

from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageDraw

from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from tests.api.test_crud import make_campaign, make_project

API = "/api/v1"
# A 4:5 key visual: a locked logo and pack, Marathi copy with a superiority claim in the small print, an English CTA.
ELEMENTS: list[dict[str, Any]] = [
    {"id": "logo", "kind": "logo", "value": "brand/logo.svg", "bbox": [0.05, 0.03, 0.22, 0.05]},
    {"id": "pack", "kind": "packshot", "value": "brand/pack.png", "bbox": [0.57, 0.52, 0.40, 0.30]},
    {"id": "headline", "kind": "headline", "value": "दिवाळी म्हणजे फराळ!", "language": "mr", "script": "Deva", "bbox": [0.05, 0.10, 0.42, 0.13]},
    {"id": "small", "kind": "body", "value": "*ग्राहकांच्या पसंतीनुसार महाराष्ट्रातील सर्वोत्तम फराळ टिन.", "language": "mr", "script": "Deva", "bbox": [0.05, 0.958, 0.36, 0.017]},
    {"id": "cta", "kind": "cta", "value": "आजच ऑर्डर करा · Order now", "language": "mr", "script": "Deva", "bbox": [0.05, 0.86, 0.40, 0.04]},
    {"id": "voice", "kind": "voiceover", "value": {"path": "vo.wav"}, "language": "mr", "script": "Deva"},
]


def picture(size: tuple[int, int] = (1080, 1350)) -> bytes:
    image = Image.new("RGB", size, "#1d5a66")
    draw = ImageDraw.Draw(image)
    draw.rectangle((size[0] * 0.57, size[1] * 0.52, size[0] * 0.97, size[1] * 0.82), fill="#f2a33a")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def live_creative(client: httpx.AsyncClient, *, elements: list[dict[str, Any]] | None = None, size: tuple[int, int] = (1080, 1350),
                        locked: tuple[str, ...] = ("logo", "pack")) -> dict[str, Any]:
    """A live project, campaign, original version (region IN-MH, Marathi), locked logo and pack, and a registered picture creative."""
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    cid = campaign["id"]
    version = (await client.post(f"{API}/campaigns/{cid}/versions", json={
        "elements": elements or ELEMENTS, "label": "Original", "region_code": "IN-MH", "language": "mr"})).json()
    for element_id in locked:
        assert (await client.put(f"{API}/campaigns/{cid}/locks/{element_id}", json={})).status_code == 200
    data = picture(size)
    upload = await client.post(f"{API}/projects/{project['id']}/assets", files={"file": ("key-visual.png", data, "image/png")}, data={"kind": "image"})
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    creative_id = uuid4()
    async with session() as s, s.begin():
        s.add(m.CreativeAsset(id=creative_id, project_id=UUID(project["id"]), campaign_id=UUID(cid), asset_id=UUID(asset["id"]), kind="image",
                              label="Key visual", region_code="IN-MH", language="mr", created_at=utcnow(), updated_at=utcnow()))
    return {"project": project, "campaign": campaign, "cid": cid, "version": version, "asset": asset, "creative_id": str(creative_id)}
