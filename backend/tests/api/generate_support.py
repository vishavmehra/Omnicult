"""Helpers for the Generate studio tests: fake model adapters (no network), a prepared live world with a Brand Kit, run helpers."""

import io
import wave
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.llm.media import MusicClip, SpeechAudio
from app.schemas.common import StepTrace, Usage
from app.workflows import WorkflowDeps
from tests.conftest import wait_for_run

API = "/api/v1"
TAMIL_LINES = ["தீபாவளி வந்தால் வீடு முழுக்க பலகார மணம் வீசும்.", "அதே வீட்டுச் சுவை, இப்போது ஆமோத் ஃபெஸ்டிவ் டின்னில்."]
TAMIL_HEADLINE = "தீபாவளி என்றால் பலகாரம்!"
LOGO_ID, PRODUCT_ID = "primary", "tin"


def png_bytes(size: tuple[int, int] = (600, 800), colour: tuple[int, int, int] = (30, 60, 90), *, alpha: bool = False) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", size, colour + ((0,) if alpha else ()))
    if alpha:  # a mark on a transparent ground
        ImageDraw.Draw(image).ellipse((4, 4, size[0] - 4, size[1] - 4), fill=colour + (255,))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def wav_bytes(seconds: float, rate: int = 24000, channels: int = 1, *, loud: int = 4000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels), w.setsampwidth(2), w.setframerate(rate)
        frame = loud.to_bytes(2, "little", signed=True) * channels
        w.writeframes(frame * int(seconds * rate))
    return out.getvalue()


def trace(stage: str, model: str, cost: float) -> StepTrace:
    return StepTrace(stage=stage, agent="fake", status="completed", provider="google", model_id=model, latency_ms=5, usage=Usage(estimated_cost_usd=cost))


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
        return SpeechAudio(wav_bytes(self.seconds), 24000, self.seconds, "gemini-3.8-flash-tts", kwargs["voice"], "ta-IN",
                           trace(kwargs["stage"], "gemini-3.8-flash-tts", 0.001))


class FakeMusic:
    def __init__(self, error: Exception | None = None, seconds: float = 4.0) -> None:
        self.error, self.seconds, self.calls = error, seconds, []

    async def generate(self, prompt: str, **kwargs: Any) -> MusicClip:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error:
            raise self.error
        return MusicClip(wav_bytes(self.seconds, 48000, 2), self.seconds, 48000, 2, "lyria-002", "us-central1",
                         trace(kwargs["stage"], "lyria-002", 0.06))


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

    def build(mode: str, settings: Any, *, source_cache: Any = None) -> WorkflowDeps:
        return WorkflowDeps(llm=holder.llm)  # type: ignore[arg-type]

    monkeypatch.setattr("app.workflows.build_workflow_deps", build)
    return holder


@dataclass
class World:
    project: str
    campaign: str
    logo: str
    product: str
    version: str | None = None


async def upload(client: httpx.AsyncClient, project_id: str, data: bytes, name: str = "a.png") -> str:
    response = await client.post(f"{API}/projects/{project_id}/assets", files={"file": (name, data, "application/octet-stream")}, data={"kind": "image"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def build_world(client: httpx.AsyncClient, *, version: bool = True) -> World:
    """A live project with a campaign, a Brand Kit (two colours, a logo and a product image uploaded and linked) and, by default,
    one Studio version to add generated outputs to."""
    from tests.api.test_crud import make_campaign, make_project

    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    logo = await upload(client, project["id"], png_bytes((900, 260), (240, 240, 230), alpha=True), "logo.png")
    product = await upload(client, project["id"], png_bytes((500, 480), (200, 150, 40), alpha=True), "pack.png")
    design = {
        "colours": [{"id": "teal", "name": "Peacock Teal", "hex": "#0E4D58"}, {"id": "gold", "name": "Marigold", "hex": "#F2A33A"}],
        "logo": {"lockups": [{"id": LOGO_ID, "use": "Horizontal", "asset_id": logo}], "min_width_px": {"horizontal": 160}},
        "product_images": [{"id": PRODUCT_ID, "description": "Festive tin", "asset_id": product}],
        "tone_of_voice": {"traits": ["warm", "familial"]},
    }
    saved = await client.put(f"{API}/projects/{project['id']}/brand-kit", json={"design": design})
    assert saved.status_code == 200, saved.text
    version_id = None
    if version:
        created = await client.post(f"{API}/campaigns/{campaign['id']}/versions", json={
            "label": "Original", "elements": [{"id": "headline", "kind": "headline", "value": "Sweet festival", "language": "en", "script": "Latn"}]})
        assert created.status_code == 201, created.text
        version_id = created.json()["id"]
    return World(project["id"], campaign["id"], logo, product, version_id)


def image_body(world: World, **extra: Any) -> dict[str, Any]:
    return {"region_code": "IN-TN", "language": "ta", "format": "4:5", "idea": "Brass lamps on a teal table", "confirm_cost": True,
            "use_region_claims": False, **extra}


def voice_body(**extra: Any) -> dict[str, Any]:
    return {"region_code": "IN-TN", "language": "ta", "lines": [{"text": t} for t in TAMIL_LINES], "voice": "Sulafat", "confirm_cost": True, **extra}


def jingle_body(**extra: Any) -> dict[str, Any]:
    return {"region_code": "IN-TN", "mood": "Warm and joyful", "festival": "Deepavali", "instruments": ["flute", "tabla"], "seconds": 10,
            "confirm_cost": True, **extra}


async def start(client: httpx.AsyncClient, campaign: str, kind: str, body: dict[str, Any], **kwargs: Any) -> httpx.Response:
    return await client.post(f"{API}/campaigns/{campaign}/generate/{kind}", json=body, **kwargs)


async def finish(client: httpx.AsyncClient, campaign: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await start(client, campaign, kind, body)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["run_type"] == f"generate_{kind}"
    return await wait_for_run(client, accepted["run_id"], timeout=60)


async def item_of(client: httpx.AsyncClient, campaign: str, run: dict[str, Any]) -> dict[str, Any]:
    response = await client.get(f"{API}/campaigns/{campaign}/generate/items/{run['id']}")
    assert response.status_code == 200, response.text
    return response.json()
