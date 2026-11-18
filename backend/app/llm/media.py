"""Media capability adapters: image generation (Gemini image model) and text to speech (Gemini TTS).

Both are reached through `LLMGateway.capability(...)`, are metered and budget-checked like every model call, and raise
`LLMError` for provider, safety-block and budget failures.

Image generation never asks the model to draw text: Indic scripts (and any lettering) are rendered in code later, so
`NO_TEXT_DIRECTIVE` is added to every prompt unless the caller opts out, and the returned `text` field is for diagnostics
only. Long-running video and music generation are out of scope for this module.
"""

import base64
import io
import logging
import struct
import time
import wave
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.llm import google
from app.llm.budget import Meter, metered as google_metered
from app.llm.gateway import LLMError, ProviderError, budget_llm_error, failure_trace, provider_llm_error
from app.schemas.common import StepTrace, Usage
from app.llm.registry import capability_model, estimate_cost, spec_for

log = logging.getLogger(__name__)
IMAGE_LOCATION = "global"  # Gemini image models are reachable at `global` on Vertex AI (docs/GOOGLE_ACCESS_AUDIT.md)
ASPECT_RATIOS = frozenset({"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"})
NO_TEXT_DIRECTIVE = (
    "Do not render any text, letters, numerals, logos or watermarks anywhere in the image; leave clean space where "
    "text will be added later."
)
IMAGE_TOKEN_ESTIMATE = 1500  # input side of a reference-image request; budget sizing only
MAX_REFERENCE_BYTES = 7 * 1024 * 1024
MAX_EXTRA_REFERENCES = 2  # reference images after the first (a clean plate, then the product)
MAX_PROMPT_CHARS = 8_000

LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN", "ta": "ta-IN", "ml": "ml-IN", "bn": "bn-IN"}
DEFAULT_VOICE = "Kore"
MAX_TTS_CHARS = 5_000
TTS_SAMPLE_RATE = 24_000  # Gemini TTS returns 16-bit mono PCM at 24 kHz
TTS_TOKENS_PER_SECOND = 25


@dataclass(frozen=True)
class GeneratedImage:
    image: bytes
    mime_type: str
    width: int | None  # read from the PNG header; None for other formats
    height: int | None
    model: str
    location: str
    text: str | None  # text the model returned next to the image (diagnostics only, never shown as copy)
    trace: StepTrace


@dataclass(frozen=True)
class SpeechAudio:
    wav: bytes
    sample_rate: int
    duration_seconds: float
    model: str
    voice: str
    language_code: str
    trace: StepTrace


def png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's IHDR chunk, or None when `data` is not a PNG."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def pcm_to_wav(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def _with_cost(usage: Usage | None, usd: float, known: bool) -> Usage:
    base = usage or Usage()
    return base.model_copy(update={"estimated_cost_usd": usd if known else None})


class _Adapter:
    capability = ""

    def __init__(self, settings: Settings, *, client: Any = None, meter: Meter | None = None,
                 backoff_seconds: float = 0.5, location: str | None = None) -> None:
        self._settings, self._client, self._meter, self._backoff, self._location = settings, client, meter, backoff_seconds, location
        self.model = capability_model(settings, self.capability) if client is not None or google.is_configured(settings) else None  # type: ignore[arg-type]
        spec = spec_for(self.model)
        if self.model and (spec is None or self.capability not in spec.capabilities):
            self.model = None  # a model that is not registered for this capability is never called

    def is_configured(self) -> bool:
        return self.model is not None

    @property
    def api(self) -> Any:
        if self._client is None:
            self._client = google.build_client(
                self._settings, location=self._location, timeout_seconds=self._settings.llm_request_timeout_seconds
            )
        return self._client

    def _require(self, stage: str, agent: str) -> str:
        if self.model is None:
            trace = StepTrace(stage=stage, agent=agent, status="failed", error_code="PROVIDER_NOT_CONFIGURED")
            raise LLMError("PROVIDER_NOT_CONFIGURED", f"No {self.capability.replace('_', ' ')} model is configured.",
                           retryable=False, trace=trace)
        return self.model


class ImageGenerationClient(_Adapter):
    capability = "image_generation"

    def __init__(self, settings: Settings, *, client: Any = None, meter: Meter | None = None,
                 backoff_seconds: float = 0.5) -> None:
        super().__init__(settings, client=client, meter=meter, backoff_seconds=backoff_seconds, location=IMAGE_LOCATION)

    async def generate(
        self, prompt: str, *, reference_image: bytes | None = None, reference_mime_type: str = "image/png",
        aspect_ratio: str | None = None, allow_text: bool = False, stage: str = "generating_image",
        agent: str = "image", extra_reference_images: Sequence[tuple[bytes, str]] = (),
    ) -> GeneratedImage:
        """One image from `prompt` and an optional reference image (edit or restyle). Returns the bytes the model
        produced (PNG when the API returns PNG) with metadata. Raises LLMError."""
        model = self._require(stage, agent)
        prompt = " ".join(prompt.split())[:MAX_PROMPT_CHARS]
        if not prompt:
            raise ValueError("An image prompt is required.")
        if aspect_ratio is not None and aspect_ratio not in ASPECT_RATIOS:
            raise ValueError(f"Unsupported aspect ratio {aspect_ratio!r}.")
        if reference_image is not None and (not reference_image or len(reference_image) > MAX_REFERENCE_BYTES):
            raise ValueError("The reference image is empty or too large.")
        if extra_reference_images and reference_image is None:
            raise ValueError("Extra reference images need a first reference image.")
        if len(extra_reference_images) > MAX_EXTRA_REFERENCES or any(
            not data or len(data) > MAX_REFERENCE_BYTES for data, _ in extra_reference_images
        ):
            raise ValueError("An extra reference image is empty or too large, or there are too many.")
        from google.genai import types

        parts = [types.Part(text=prompt if allow_text else f"{prompt}\n\n{NO_TEXT_DIRECTIVE}")]
        if reference_image is not None:
            parts.append(types.Part.from_bytes(data=reference_image, mime_type=reference_mime_type))
        for data, mime in extra_reference_images:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio) if aspect_ratio else None,
        )
        started = time.perf_counter()

        def extract(response: Any, record: Any) -> tuple[bytes, str, str | None]:
            text: list[str] = []
            for part in (response.candidates[0].content.parts or []) if response.candidates and response.candidates[0].content else []:
                blob = getattr(part, "inline_data", None)
                if blob is not None and blob.data and str(blob.mime_type or "").startswith("image/"):
                    record.images = 1
                    return blob.data, blob.mime_type, " ".join(text) or None
                if getattr(part, "text", None) and not getattr(part, "thought", False):
                    text.append(part.text)
            raise ProviderError("The model returned no image.", transient=False)

        (image, mime, note), retries, usage = await google.run_generation(
            lambda: self.api, self._settings, meter=self._meter, backoff=self._backoff, capability=self.capability,
            model=model, contents=[types.Content(role="user", parts=parts)], config=config, stage=stage, agent=agent,
            prompt_version="image-generate-v1", extract=extract, warm=self._client is None,
            estimate_usd=estimate_cost(model, input_tokens=len(prompt) // 3 + IMAGE_TOKEN_ESTIMATE * ((reference_image is not None) + len(extra_reference_images)),
                                       images=1).usd,
        )
        cost = estimate_cost(model, input_tokens=usage.input_tokens if usage else None, images=1)
        size = png_size(image)
        trace = StepTrace(
            stage=stage, agent=agent, status="completed", provider="google", model_id=model,
            prompt_version="image-generate-v1", latency_ms=int((time.perf_counter() - started) * 1000), retries=retries,
            usage=_with_cost(usage, cost.usd, cost.known),
        )
        return GeneratedImage(image, mime, size[0] if size else None, size[1] if size else None, model,
                              IMAGE_LOCATION if self._settings.google_genai_backend == "vertex" else "gemini_api", note, trace)


class TTSClient(_Adapter):
    capability = "tts"

    async def synthesize(
        self, text: str, *, language: str = "en", voice: str = DEFAULT_VOICE, stage: str = "generating_voiceover",
        agent: str = "voice",
    ) -> SpeechAudio:
        """Speak `text` in `language` (ISO 639-1: en, hi, mr, ta, ml, bn) and return a mono 16-bit WAV. Raises LLMError."""
        model = self._require(stage, agent)
        text = text.strip()
        if not text or len(text) > MAX_TTS_CHARS:
            raise ValueError(f"Speech text must be 1 to {MAX_TTS_CHARS} characters.")
        if language not in LANGUAGE_CODES:
            raise ValueError(f"Unsupported speech language {language!r}.")
        if not voice.isalnum():
            raise ValueError("Invalid voice name.")
        from google.genai import types

        code = LANGUAGE_CODES[language]
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code=code,
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)),
            ),
        )
        started = time.perf_counter()

        def extract(response: Any, record: Any) -> tuple[bytes, int]:
            for part in (response.candidates[0].content.parts or []) if response.candidates and response.candidates[0].content else []:
                blob = getattr(part, "inline_data", None)
                if blob is not None and blob.data and str(blob.mime_type or "").startswith("audio/"):
                    rate = TTS_SAMPLE_RATE
                    for piece in str(blob.mime_type).split(";"):
                        if piece.strip().startswith("rate="):
                            rate = int(piece.strip()[5:])
                    record.audio_seconds = len(blob.data) / (rate * 2)
                    return blob.data, rate
            raise ProviderError("The model returned no audio.", transient=False)

        (pcm, rate), retries, usage = await google.run_generation(
            lambda: self.api, self._settings, meter=self._meter, backoff=self._backoff, capability=self.capability,
            model=model, contents=text, config=config, stage=stage, agent=agent, prompt_version="tts-speak-v1",
            extract=extract, warm=self._client is None,
            estimate_usd=estimate_cost(model, input_tokens=len(text) // 3 + 1,
                                       audio_seconds=len(text) / 8 + 1).usd,  # about 8 characters per second of speech
        )
        seconds = len(pcm) / (rate * 2)
        cost = estimate_cost(model, input_tokens=usage.input_tokens if usage else None,
                             output_tokens=usage.output_tokens if usage and usage.output_tokens else None,
                             audio_seconds=seconds)
        trace = StepTrace(
            stage=stage, agent=agent, status="completed", provider="google", model_id=model,
            prompt_version="tts-speak-v1", latency_ms=int((time.perf_counter() - started) * 1000), retries=retries,
            usage=_with_cost(usage, cost.usd, cost.known),
        )
        return SpeechAudio(pcm_to_wav(pcm, rate), rate, round(seconds, 2), model, voice, code, trace)


# --- music (Lyria 2 over REST) -----------------------------------------------------------------------------------

MUSIC_CLIP_SECONDS = 30.0  # lyria-002 returns one clip of about 30 s (the verified clip measured 32.8 s, 48 kHz stereo WAV)
MAX_MUSIC_PROMPT_CHARS = 600
Poster = Callable[[str, dict[str, Any], dict[str, str]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MusicClip:
    wav: bytes
    duration_seconds: float
    sample_rate: int
    channels: int
    model: str
    location: str
    trace: StepTrace


def wav_info(data: bytes) -> tuple[int, int, float]:
    """(sample rate, channels, seconds) of a PCM WAV. The duration comes from the byte count, not the header: Lyria's
    header frame count is unreliable."""
    with wave.open(io.BytesIO(data)) as clip:
        rate, channels, width = clip.getframerate(), clip.getnchannels(), clip.getsampwidth()
    return rate, channels, round(max(0, len(data) - 44) / (rate * channels * width), 2)


class MusicClient(_Adapter):
    """Lyria 2 (`lyria-002`) through Vertex AI REST `predict` (the Gen AI SDK has no music call). Metered and
    budget-checked like every capability; Vertex AI only. `poster` (tests) replaces the HTTP call."""

    capability = "music"

    def __init__(self, settings: Settings, *, client: Any = None, meter: Meter | None = None, backoff_seconds: float = 0.5,
                 poster: Poster | None = None) -> None:
        super().__init__(settings, client=client, meter=meter, backoff_seconds=backoff_seconds,
                         location=settings.google_music_location)
        self._poster = poster
        if settings.google_genai_backend != "vertex" or not settings.google_cloud_project:
            self.model = None  # Lyria is offered on Vertex AI only

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=self._settings.llm_request_timeout_seconds) as http:
            response = await http.post(url, json=body, headers=headers)
        if response.status_code != 200:
            try:  # the API's own words go to the log only (as map_exception does for the SDK), never to a user
                error = response.json().get("error") or {}
            except ValueError:
                error = {}
            log.warning("provider error", extra={
                "provider_http": response.status_code, "provider_status": str(error.get("status") or "")[:40],
                "provider_detail": " ".join(str(error.get("message") or "").split())[:400]})
            raise ProviderError(f"HTTP {response.status_code}", transient=response.status_code in (429, 500, 502, 503, 504),
                                timeout=response.status_code in (408, 504))
        return response.json()

    @staticmethod
    async def _headers() -> dict[str, str]:
        """A bearer token from the process-wide credentials (`google.load_credentials`), never from a fresh
        `google.auth.default()` (that runs the gcloud CLI and took 48 to 200 s). Loaded and refreshed off the event loop."""
        import asyncio

        from google.auth.transport import requests as transport

        def token() -> str:
            credentials = google.load_credentials()
            if not credentials.valid:
                credentials.refresh(transport.Request())
            return credentials.token

        return {"Authorization": f"Bearer {await asyncio.to_thread(token)}", "Content-Type": "application/json"}

    async def generate(self, prompt: str, *, negative_prompt: str | None = "vocals, speech", seed: int | None = None,
                       stage: str = "generating_jingle", agent: str = "music") -> MusicClip:
        """One short instrumental clip. Raises LLMError."""
        from app.llm.budget import BudgetExceeded
        from app.llm.google import map_exception, with_retries

        model = self._require(stage, agent)
        prompt = " ".join(prompt.split())[:MAX_MUSIC_PROMPT_CHARS]
        if not prompt:
            raise ValueError("A music prompt is required.")
        location = self._location or self._settings.google_music_location
        url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{self._settings.google_cloud_project}"
               f"/locations/{location}/publishers/google/models/{model}:predict")
        instance: dict[str, Any] = {"prompt": prompt}
        if negative_prompt:
            instance["negative_prompt"] = negative_prompt
        if seed is not None:  # a seed and sample_count are mutually exclusive on the API
            instance["seed"] = seed
        body = {"instances": [instance], "parameters": {} if seed is not None else {"sample_count": 1}}
        started = time.perf_counter()
        estimate = estimate_cost(model, audio_seconds=MUSIC_CLIP_SECONDS).usd

        async def attempt() -> bytes:
            async with google_metered(self._meter, capability=self.capability, model=model, stage=stage, agent=agent,
                                      prompt_version="music-jingle-v1", estimate_usd=estimate) as record:
                try:
                    headers = {} if self._poster is not None else await self._headers()
                    payload = await (self._poster or self._post)(url, body, headers)
                except Exception as exc:
                    raise map_exception(exc) from exc
                prediction = (payload.get("predictions") or [{}])[0]
                field = next((k for k in ("bytesBase64Encoded", "audioContent") if prediction.get(k)), None)
                if field is None:
                    raise ProviderError("The model returned no audio.", transient=False)
                record.audio_seconds = MUSIC_CLIP_SECONDS  # generated (and billed) once the API answered 200
                return base64.b64decode(prediction[field])

        try:
            wav, retries = await with_retries(attempt, retries=max(0, self._settings.llm_max_retries), backoff=self._backoff)
        except BudgetExceeded as exc:
            raise budget_llm_error(exc, failure_trace(stage, agent, "google", model, started, "BUDGET_EXCEEDED")) from exc
        except ProviderError as exc:
            code = "CONTENT_BLOCKED" if exc.blocked else "PROVIDER_TIMEOUT" if exc.timeout else "PROVIDER_ERROR"
            raise provider_llm_error(exc, failure_trace(stage, agent, "google", model, started, code),
                                     timeout_seconds=self._settings.llm_request_timeout_seconds) from exc
        try:
            rate, channels, seconds = wav_info(wav)
        except (wave.Error, EOFError):
            raise LLMError("PROVIDER_ERROR", "The music model returned audio that could not be read.", retryable=False,
                           trace=failure_trace(stage, agent, "google", model, started, "PROVIDER_ERROR")) from None
        cost = estimate_cost(model, audio_seconds=MUSIC_CLIP_SECONDS)
        trace = StepTrace(stage=stage, agent=agent, status="completed", provider="google", model_id=model,
                          prompt_version="music-jingle-v1", latency_ms=int((time.perf_counter() - started) * 1000),
                          retries=retries, usage=_with_cost(None, cost.usd, cost.known))
        return MusicClip(wav, seconds, rate, channels, model, location, trace)
