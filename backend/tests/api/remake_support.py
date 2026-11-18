"""Helpers for the Remake tests: fake model adapters (no network), a prepared studio world, and run helpers."""

import io
import wave
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.llm.media import MusicClip, SpeechAudio
from app.schemas.common import StepTrace, Usage
from app.workflows import WorkflowDeps
from tests.conftest import wait_for_run

API = "/api/v1"
TAMIL = {"headline": "தீபாவளி என்றால் பலகாரம்!", "cta": "இன்றே ஆர்டர் செய்யுங்கள் · Order now"}
LINES = {"cap-1": "தீபாவளி வந்தால் வீடு முழுக்க பலகார மணம் வீசும்.", "cap-2": "அதே வீட்டுச் சுவை, இப்போது ஆமோத் ஃபெஸ்டிவ் டின்னில்."}
SIZE = (400, 500)


def png_bytes(size: tuple[int, int] = SIZE, colour: tuple[int, int, int] = (30, 60, 90), *, finished: bool = False) -> bytes:
    image = Image.new("RGB", size, colour)
    if finished:  # the finished creative: a tin and a logo painted where the locked regions are
        draw = ImageDraw.Draw(image)
        draw.rectangle((226, 255, 374, 395), fill=(200, 160, 40))
        draw.rectangle((22, 22, 118, 48), fill=(250, 250, 250))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate))
    return out.getvalue()


def trace(stage: str, model: str, cost: float) -> StepTrace:
    return StepTrace(stage=stage, agent="fake", status="completed", provider="google", model_id=model, latency_ms=5,
                     usage=Usage(estimated_cost_usd=cost))


class FakeImage:
    def __init__(self, image: bytes | None = None, *, error: Exception | None = None) -> None:
        self.image, self.error, self.calls = image or png_bytes((800, 1000), (160, 40, 30)), error, []

    async def generate(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        return SimpleNamespace(image=self.image, mime_type="image/png", width=800, height=1000, model="gemini-3.1-flash-image",
                               location="global", text=None, trace=trace(kwargs["stage"], "gemini-3.1-flash-image", 0.067))


class FakeSpeech:
    def __init__(self, seconds: float = 1.5, *, fail_on: dict[str, Exception] | None = None) -> None:
        self.seconds, self.fail_on, self.calls = seconds, fail_on or {}, []

    async def synthesize(self, text: str, **kwargs: Any) -> SpeechAudio:
        self.calls.append({"text": text, **kwargs})
        if text in self.fail_on:
            raise self.fail_on[text]
        return SpeechAudio(wav_bytes(self.seconds), 24000, self.seconds, "gemini-3.8-flash-tts", kwargs["voice"],
                           "ta-IN", trace(kwargs["stage"], "gemini-3.8-flash-tts", 0.001))


class FakeMusic:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    async def generate(self, prompt: str, **kwargs: Any) -> MusicClip:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        return MusicClip(wav_bytes(2.0, 48000), 2.0, 48000, 1, "lyria-002", "us-central1", trace(kwargs["stage"], "lyria-002", 0.06))


@dataclass
class FakeLLM:
    adapters: dict[str, Any] = field(default_factory=dict)

    def capability(self, name: str) -> Any:
        return self.adapters.get(name)


@dataclass
class Rig:
    llm: Any


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    """Vertex AI counts as configured, every model call is a fake, and workflows get the rig's gateway."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "qa-test-project")
    for tier in ("GEMINI_MODEL_FAST", "GEMINI_MODEL_DEFAULT", "GEMINI_MODEL_REASONING"):
        monkeypatch.setenv(tier, "test-model")
    get_settings.cache_clear()
    holder = Rig(llm=FakeLLM({"image_generation": FakeImage(), "tts": FakeSpeech(), "music": FakeMusic()}))

    def build(mode: str, settings: Any) -> WorkflowDeps:
        return WorkflowDeps(llm=holder.llm)  # type: ignore[arg-type]

    monkeypatch.setattr("app.workflows.build_workflow_deps", build)

    async def no_indexing(**kwargs: Any) -> None:  # a finished live run would embed the project with the real client (network, and a
        return None  # hang at teardown on a machine with Google credentials); nothing here needs the search index

    monkeypatch.setattr("app.services.runs.index_project", no_indexing)
    return holder


def element(eid: str, kind: str, value: Any, bbox: list[float] | None, *, language: str | None = None, script: str | None = None) -> dict[str, Any]:
    return {"id": eid, "kind": kind, "value": value, "bbox": bbox, "language": language, "script": script}


def elements() -> list[dict[str, Any]]:
    return [
        element("kv-plate", "scene", "creative/plate.jpg", [0, 0, 1, 1]),
        element("kv-logo", "logo", "brand/logo.svg", [0.05, 0.04, 0.25, 0.06]),
        element("kv-pack", "packshot", "brand/pack.png", [0.55, 0.5, 0.4, 0.3]),
        element("kv-headline", "headline", TAMIL["headline"], [0.05, 0.12, 0.7, 0.12], language="ta", script="Taml"),
        element("kv-cta", "cta", TAMIL["cta"], [0.05, 0.85, 0.9, 0.05], language="ta", script="Taml"),
        element("cap-1", "caption", LINES["cap-1"], [0.05, 0.6, 0.45, 0.08], language="ta", script="Taml"),
        element("cap-2", "caption", LINES["cap-2"], [0.05, 0.69, 0.45, 0.08], language="ta", script="Taml"),
        element("vo", "voiceover", {"path": "creative/vo_mr.wav", "voice": "Sulafat"}, None, language="mr", script="Deva"),
    ]


@dataclass
class World:
    project: str
    campaign: str
    version: str
    original: str
    plate: str


async def upload_image(client: httpx.AsyncClient, project_id: str, data: bytes) -> str:
    response = await client.post(f"{API}/projects/{project_id}/assets", files={"file": ("a.png", data, "application/octet-stream")},
                                 data={"kind": "image"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def build_world(client: httpx.AsyncClient, *, demo: bool = False, items: list[dict[str, Any]] | None = None,
                      lock: tuple[str, ...] = ("kv-logo",), assets: bool = True) -> World:
    from tests.api.test_crud import make_campaign, make_project

    if demo:
        project = (await client.post(f"{API}/projects/demo")).json()
        campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    else:
        project = await make_project(client)
        campaign = await make_campaign(client, project["id"])
    version = await client.post(f"{API}/campaigns/{campaign['id']}/versions", json={
        "label": "Tamil Nadu (Tamil)", "elements": items or elements(), "region_code": "IN-TN", "language": "ta"})
    assert version.status_code == 201, version.text
    for element_id in lock:
        assert (await client.put(f"{API}/campaigns/{campaign['id']}/locks/{element_id}", json={"reason": "never change"})).status_code == 200
    original = await upload_image(client, project["id"], png_bytes(finished=True)) if assets else ""
    plate = await upload_image(client, project["id"], png_bytes((400, 500), (20, 40, 70))) if assets else ""
    return World(project["id"], campaign["id"], version.json()["id"], original, plate)


def visual_body(world: World, **extra: Any) -> dict[str, Any]:
    return {"region_code": "IN-TN", "language": "ta", "original_asset_id": world.original, "plate_asset_id": world.plate,
            "confirm_cost": True, "use_region_claims": False, **extra}


async def start(client: httpx.AsyncClient, world: World, kind: str, body: dict[str, Any], **kwargs: Any) -> httpx.Response:
    return await client.post(f"{API}/campaigns/{world.campaign}/remakes/{kind}", json=body, **kwargs)


async def finish(client: httpx.AsyncClient, world: World, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await start(client, world, kind, body)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["run_type"] == f"remake_{kind}"
    return await wait_for_run(client, accepted["run_id"], timeout=60)


async def output_of(client: httpx.AsyncClient, world: World, run: dict[str, Any]) -> dict[str, Any]:
    page = (await client.get(f"{API}/campaigns/{world.campaign}/remakes", params={"run_id": run["id"]})).json()
    assert page["total"] == 1, page
    return page["items"][0]


def uuid_of(value: str) -> UUID:
    return UUID(value)
