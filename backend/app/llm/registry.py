"""Google model registry, task routing and the price table (D-023, Omnicult gateway).

Model ids are configuration (`GEMINI_MODEL_*`, Settings); this module only knows what each id can do and what it costs.
A configured id that is not listed here still runs for plain text, but its cost is unknown (the gateway then budgets
with a conservative price and records `estimated_cost_usd = null`), and it is never sent images.

PRICES ARE ESTIMATES. Source: the official Gemini pricing page https://aistudio.google.com/docs/pricing (the former
ai.google.dev/gemini-api/docs/pricing), read on 2026-11-17, plus the Vertex AI model pages under
https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models for ids and locations. The Vertex AI pricing page
(https://cloud.google.com/vertex-ai/generative-ai/pricing) is rendered by script and could not be read by the tooling used
here, so Vertex list prices are assumed equal to the Gemini API paid tier. Check the billing report before relying on
them. Thinking tokens bill as output. Audio input to Flash models can bill higher than text input; that is not modelled.
`transcribe` (speech to timed text, app/llm/transcribe.py) is listed for the multimodal Gemini 3 and 4 models, which
accept audio input on Vertex AI; the first live call is recorded in `verified`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.core.config import Settings

Tier = Literal["fast", "default", "reasoning"]
Capability = Literal[
    "chat", "embeddings", "vision", "transcribe", "image_generation", "tts", "live", "grounded_research", "music", "video"
]
TaskClass = Literal[
    "extraction",
    "research_synthesis",
    "study_design",
    "synthetic_generation",
    "sentiment_analysis",
    "risk_analysis",
    "creative_adaptation",
    "comparative_judgment",
    "report_generation",
]

ROUTING_POLICY_VERSION = "routing-v2"
PRICE_TABLE_VERSION = "prices-2026-11-18"  # bump when any number below changes

# docs/05 section 6.3: small, deterministic task -> tier table.
TASK_TIERS: dict[TaskClass, Tier] = {
    "extraction": "fast",
    "sentiment_analysis": "fast",
    "research_synthesis": "default",
    "study_design": "default",
    "synthetic_generation": "default",
    "creative_adaptation": "default",
    "comparative_judgment": "default",
    "report_generation": "default",
    "risk_analysis": "reasoning",
}

# Approved same-provider fallback (MASTER_PROMPT 5.2): when a tier's model stays unavailable after bounded retries the
# call may go to the next tier down, but never below the task's floor, and never outside Google. A fallback is recorded
# in the StepTrace (`fallback_used`, `model_id`).
_RANK: dict[Tier, int] = {"fast": 0, "default": 1, "reasoning": 2}
TASK_FLOOR: dict[TaskClass, Tier] = {
    "extraction": "fast",
    "sentiment_analysis": "fast",
    "report_generation": "fast",
    "research_synthesis": "fast",
    "study_design": "fast",
    "synthetic_generation": "fast",
    "creative_adaptation": "default",
    "comparative_judgment": "default",
    "risk_analysis": "default",
}


@dataclass(frozen=True)
class Price:
    """USD. Token prices are per 1M tokens; `per_image` and `per_second` are flat per unit."""

    input_per_m: float = 0.0
    output_per_m: float = 0.0  # includes thinking tokens
    per_image: float | None = None  # image models: flat estimate per generated image
    per_second: float | None = None  # audio and video models: per generated second (audio tokens are 25 per second)
    long_input_threshold: int | None = None  # prompts above this many tokens bill at the long_* rates
    long_input_per_m: float | None = None
    long_output_per_m: float | None = None


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    capabilities: frozenset[str]
    price: Price
    price_from: tuple[date, Price] | None = None  # a published price change: from this date the other price applies
    structured_output: bool = False
    multimodal_input: bool = False
    thinking: bool = False  # spends thinking tokens before answering
    thinking_headroom: int = 0  # extra max_output_tokens so thinking cannot starve the visible answer
    thinking_levels: tuple[str, ...] = ()  # accepted `thinking_level` values; empty = not configurable
    embedding_task_type: bool = False  # embed_content accepts task_type
    embedding_max_batch: int = 1  # inputs per embed_content request
    locations: tuple[str, ...] = ("global",)
    verified: str | None = None  # date of the last successful live call through this gateway
    note: str = ""


def _spec(model_id: str, caps: str, price: Price, **kw) -> ModelSpec:
    return ModelSpec(model_id, frozenset(caps.split()), price, **kw)


_TEXT = "chat vision grounded_research"
_TEXT_AUDIO = _TEXT + " transcribe"  # multimodal models that also take audio input
_FLASH_38_NOW = Price(0.75, 3.75)
_FLASH_38_2027 = Price(1.50, 7.50)

# Image and TTS models bill per token plus a published per-image figure; the flat figure is used for budgeting.
MODELS: dict[str, ModelSpec] = {
    spec.model_id: spec
    for spec in (
        _spec("gemini-3.5-flash-lite", _TEXT_AUDIO, Price(0.30, 2.50), structured_output=True, multimodal_input=True,
              thinking=True, thinking_headroom=1024, locations=("global", "asia-south1"), verified="2026-11-17"),
        _spec("gemini-3.8-flash", _TEXT_AUDIO, _FLASH_38_NOW, price_from=(date(2027, 1, 1), _FLASH_38_2027),
              structured_output=True, multimodal_input=True, thinking=True, thinking_headroom=2048,
              thinking_levels=("LOW", "MEDIUM", "HIGH"), locations=("global", "us", "eu"), verified="2026-11-17"),
        _spec("gemini-3.6-flash", _TEXT_AUDIO, _FLASH_38_NOW, price_from=(date(2027, 1, 1), _FLASH_38_2027),
              structured_output=True, multimodal_input=True, thinking=True, thinking_headroom=2048,
              locations=("global", "us", "eu")),
        _spec("gemini-3.5-flash", _TEXT_AUDIO, Price(1.50, 9.00), structured_output=True, multimodal_input=True,
              thinking=True, thinking_headroom=2048, locations=("global",), verified="2026-11-17",
              note="Vertex price from third-party aggregators; not on the Gemini API page"),
        # Pro class. Argon: introductory $2/$10 through 2026-11-30, $4/$20 from 2026-12-01 (aggregator reports; Google's Vertex
        # price page was not machine-readable). Sampling parameters are fixed by the model; MINIMAL thinking is rejected.
        _spec("gemini-4-argon", _TEXT_AUDIO, Price(2.00, 10.00), price_from=(date(2026, 12, 1), Price(4.00, 20.00)),
              structured_output=True, multimodal_input=True, thinking=True, thinking_headroom=4096,
              thinking_levels=("LOW", "MEDIUM", "HIGH"), locations=("global", "us", "eu"), verified="2026-11-17"),
        _spec("gemini-3.1-pro-preview", _TEXT_AUDIO, Price(2.00, 12.00, long_input_threshold=200_000, long_input_per_m=4.00,
              long_output_per_m=18.00), structured_output=True, multimodal_input=True, thinking=True,
              thinking_headroom=4096, verified="2026-11-17", note="preview"),
        _spec("gemini-2.5-pro", _TEXT, Price(1.25, 10.00, long_input_threshold=200_000, long_input_per_m=2.50,
              long_output_per_m=15.00), structured_output=True, multimodal_input=True, thinking=True,
              thinking_headroom=4096, note="deprecated; requests route to gemini-3.8-flash from 2026-12-01"),
        _spec("gemini-2.5-flash", _TEXT, Price(0.30, 2.50), structured_output=True, multimodal_input=True,
              thinking=True, thinking_headroom=2048, note="deprecated; routes to gemini-3.5-flash-lite from 2026-12-01"),
        # Image generation (Vertex location `global`; verified: 1024x1024 PNG).
        _spec("gemini-3.1-flash-image", "image_generation vision", Price(0.50, 3.00, per_image=0.067),
              multimodal_input=True, thinking=True, verified="2026-11-17"),
        _spec("gemini-3.1-flash-lite-image", "image_generation vision", Price(0.25, 1.50, per_image=0.0336),
              multimodal_input=True),
        _spec("gemini-nano-banana-2.1", "image_generation vision", Price(1.50, 7.50, per_image=0.0336),
              multimodal_input=True),
        _spec("gemini-3-pro-image", "image_generation vision", Price(2.00, 12.00, per_image=0.134),
              multimodal_input=True, thinking=True),
        _spec("gemini-2.5-flash-image", "image_generation vision", Price(0.30, 0.0, per_image=0.039),
              multimodal_input=True, note="deprecated; shuts down 2027-03-15"),
        # Text to speech (audio output: 25 tokens per second).
        _spec("gemini-3.8-flash-tts", "tts", Price(0.50, 9.00, per_second=9.00 * 25 / 1e6),
              price_from=(date(2027, 1, 1), Price(1.00, 18.00, per_second=18.00 * 25 / 1e6)), verified="2026-11-17",
              note="Hindi and Tamil verified"),
        _spec("gemini-3.8-flash-lite-tts", "tts", Price(0.50, 6.00, per_second=6.00 * 25 / 1e6),
              price_from=(date(2027, 1, 1), Price(1.00, 12.00, per_second=12.00 * 25 / 1e6))),
        _spec("gemini-2.5-flash-preview-tts", "tts", Price(0.50, 10.00, per_second=10.00 * 25 / 1e6), verified="2026-11-17",
              note="preview; Hindi and Tamil verified"),
        # Live (not exercised by the gateway; listed so the configured id is recognised).
        _spec("gemini-live-2.5-flash", "live", Price(0.50, 2.00)),
        _spec("gemini-3.8-live", "live", Price(0.75, 3.75)),
        # Music (Lyria 2 on Vertex, 30 s WAV clips at $0.06; exercised by scripts/verify_google_models.py only).
        _spec("lyria-002", "music", Price(per_second=0.06 / 30), locations=("us-central1",), verified="2026-11-17"),
        # Video (Veo 3.1 on Vertex AI, us-central1 only, reached over REST `predictLongRunning`). `per_second` is the
        # video-only 720p rate, the only mode Remake: Video requests (audio is joined in code). Published rates per second
        # (https://cloud.google.com/vertex-ai/generative-ai/pricing, read 2026-11-18; the unit there reads "1 count"):
        # Fast 720p $0.08 video-only, $0.10 with audio, 1080p $0.10 and $0.12; Lite $0.03 and $0.05 (1080p $0.05 and $0.08);
        # standard $0.20 and $0.40. The page is script-rendered, so check the billing report before relying on them.
        _spec("veo-3.1-fast-generate-001", "video", Price(per_second=0.08), locations=("us-central1",), note="GA"),
        _spec("veo-3.1-lite-generate-001", "video", Price(per_second=0.03), locations=("us-central1",), note="preview"),
        _spec("veo-3.1-generate-001", "video", Price(per_second=0.20), locations=("us-central1",), note="GA"),
        # Embeddings (input tokens only).
        # Verified 2026-11-17 on Vertex at `global`: gemini-embedding-001 answers 404 (not available to this project there);
        # gemini-embedding-2 works, folds a list of inputs into ONE vector (so one text per request) and ignores task_type.
        _spec("gemini-embedding-001", "embeddings", Price(0.15), embedding_task_type=True, note="404 at global"),
        _spec("gemini-embedding-2", "embeddings", Price(0.20), embedding_max_batch=1, verified="2026-11-17"),
    )
}

# Google Search grounding: $14 per 1,000 requests for Gemini 3 and newer after a monthly free quota (not modelled, so
# this overestimates early use).
GROUNDING_USD_PER_REQUEST = 0.014
# Used to budget a call to a model that is not in MODELS: Pro-level, so an unknown model cannot slip under a ceiling.
UNKNOWN_MODEL_PRICE = Price(2.00, 12.00)


def spec_for(model_id: str | None) -> ModelSpec | None:
    return MODELS.get(model_id or "")


def price_for(model_id: str, on: date | None = None) -> tuple[Price, bool]:
    """(price, known). Unknown models get UNKNOWN_MODEL_PRICE with known=False."""
    spec = MODELS.get(model_id)
    if spec is None:
        return UNKNOWN_MODEL_PRICE, False
    day = on or date.today()
    if spec.price_from is not None and day >= spec.price_from[0]:
        return spec.price_from[1], True
    return spec.price, True


def tier_model(settings: Settings, tier: Tier) -> str | None:
    """Configured model id for a tier."""
    return {"fast": settings.gemini_model_fast, "default": settings.gemini_model_default,
            "reasoning": settings.gemini_model_reasoning}[tier] or None


def tier_chain(settings: Settings, task: TaskClass) -> list[tuple[Tier, str]]:
    """The task's tier model first, then approved fallbacks: lower tiers down to the task floor, models de-duplicated."""
    start, floor = TASK_TIERS[task], TASK_FLOOR[task]
    chain: list[tuple[Tier, str]] = []
    for tier in sorted(_RANK, key=_RANK.get, reverse=True):
        if _RANK[tier] > _RANK[start] or _RANK[tier] < _RANK[floor]:
            continue
        model = tier_model(settings, tier)
        if model and model not in (m for _, m in chain):
            chain.append((tier, model))
    return chain


# Thinking effort per tier, applied only to models that list the level in `thinking_levels` (others use their default).
TIER_THINKING: dict[Tier, str] = {"fast": "LOW", "default": "LOW", "reasoning": "MEDIUM"}


def thinking_level_for(model_id: str, tier: Tier | None) -> str | None:
    spec = MODELS.get(model_id)
    level = TIER_THINKING.get(tier) if tier else None
    return level if spec and level in spec.thinking_levels else None


def capability_model(settings: Settings, capability: Capability) -> str | None:
    """Configured model id for a non-text capability. Vision uses the fast text model (gemini-3.5-flash-lite read the Aamod
    keyframes, Devanagari and boxes included, in about 3 s each; gemini-3.8-flash took 10 to 60 s and timed out on some);
    transcription and grounded research use the default text model."""
    return {
        "chat": settings.gemini_model_default,
        "vision": settings.gemini_model_fast,
        "transcribe": settings.gemini_model_default,
        "grounded_research": settings.gemini_model_default,
        "image_generation": settings.gemini_model_image,
        "tts": settings.gemini_model_tts,
        "live": settings.gemini_model_live,
        "music": settings.gemini_model_music,
        "video": settings.gemini_model_video,
        "embeddings": settings.gemini_embedding_model,
    }[capability] or None


def supports(model_id: str | None, capability: str) -> bool:
    spec = MODELS.get(model_id or "")
    return spec is not None and capability in spec.capabilities


@dataclass(frozen=True)
class CostBreakdown:
    usd: float
    known: bool  # False: the model has no entry in MODELS, so `usd` used the conservative stand-in price


def estimate_cost(
    model_id: str, *, input_tokens: int | None = None, output_tokens: int | None = None, images: int = 0,
    audio_seconds: float = 0.0, video_seconds: float = 0.0, grounded_requests: int = 0, on: date | None = None,
) -> CostBreakdown:
    """Estimated USD for one call. `output_tokens` must include thinking tokens. Image models bill the flat per-image
    figure (output tokens are then only the text part); audio models bill `audio_seconds` when no token count exists;
    video models bill `video_seconds` of generated video at the per-second rate."""
    price, known = price_for(model_id, on)
    in_rate, out_rate = price.input_per_m, price.output_per_m
    if price.long_input_threshold and (input_tokens or 0) > price.long_input_threshold:
        in_rate = price.long_input_per_m or in_rate
        out_rate = price.long_output_per_m or out_rate
    cost = (input_tokens or 0) * in_rate / 1e6
    if images and price.per_image is not None:
        cost += images * price.per_image  # image output tokens are inside the flat figure
    elif (audio_seconds or video_seconds) and price.per_second is not None and not output_tokens:
        cost += (audio_seconds + video_seconds) * price.per_second
    else:
        cost += (output_tokens or 0) * out_rate / 1e6
    cost += grounded_requests * GROUNDING_USD_PER_REQUEST
    return CostBreakdown(round(cost, 6), known)
