"""Opt-in live verification of the Google gateway: real, tiny calls per capability. Prints no secrets.

Run from backend/:  uv run python -m scripts.verify_google_models --run [--backend vertex|gemini_api] [--project ID]
                    [--max-usd 0.25] [--out report.md]

Reads C:\\Users\\ASUS\\.omnicult\\google.env (or OMNICULT_GOOGLE_ENV) for GEMINI_API_KEY and GOOGLE_CLOUD_PROJECT without
overriding the real environment; Vertex AI uses Application Default Credentials. Without --run it only prints the plan.

What it does: probes candidate Gemini ids at one location (a call that returns text counts as reachable), then drives the
production gateway and adapters once each: structured output with realistic agent schemas (all three tiers), embeddings
(batch and dimensions), vision (a generated test PNG), image generation, text to speech, and Google Search grounding.
Every request goes through the gateway's meter, so a budget guard capped at --max-usd stops the run before it overspends.
The `video` step (one 4 s Veo 3.1 Fast clip through the production adapter, about $0.32) is opt-in: it is not in the default
--steps. Run it alone:  --steps video --max-usd 0.5
Cost figures are estimates from app/llm/registry.py, not billed amounts. Error lines show the HTTP status and the API's
status word only, never request bodies or credentials.
"""

import argparse
import asyncio
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

ENV_FILE = Path(os.environ.get("OMNICULT_GOOGLE_ENV", r"C:\Users\ASUS\.omnicult\google.env"))
CHAT_CANDIDATES = [
    ("flash-lite", "gemini-3.5-flash-lite"),
    ("flash-lite", "gemini-3.1-flash-lite"),
    ("flash", "gemini-3.8-flash"),
    ("flash", "gemini-3.7-flash"),
    ("flash", "gemini-3.6-flash"),
    ("flash", "gemini-3.5-flash"),
    ("pro", "gemini-4-carbon"),
    ("pro", "gemini-4-argon"),
    ("pro", "gemini-3.1-pro-preview"),
    ("pro", "gemini-2.5-pro"),
]
IMAGE_CANDIDATES = ["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1"]
TTS_CANDIDATES = ["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
EMBED_CANDIDATES = ["gemini-embedding-001", "gemini-embedding-2"]
EMBED_TEXTS = ["Weekend hiking gear for autumn trails.", "Pongal festival gifting ideas.", "Minimal design for city commuters."]


def load_env_file(path: Path) -> list[str]:
    """Export KEY=VALUE lines that are not already set. Returns the names loaded (never the values)."""
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name and value.strip() and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")
            loaded.append(name)
    return loaded


Row = dict[str, Any]


class Report:
    def __init__(self, backend: str, location: str, project: str | None) -> None:
        self.rows: list[Row] = []
        self.backend, self.location, self.project = backend, location, project

    def add(self, capability: str, model: str, status: str, *, location: str | None = None, latency_ms: int | None = None,
            usage: Any = None, note: str = "") -> None:
        row = {
            "capability": capability, "model": model, "location": location or self.location, "status": status,
            "latency_ms": latency_ms, "in": getattr(usage, "input_tokens", None), "out": getattr(usage, "output_tokens", None),
            "think": getattr(usage, "thinking_tokens", None), "usd": getattr(usage, "estimated_cost_usd", None),
            "note": self.scrub(note),
        }
        self.rows.append(row)
        print(f"{capability:<18} {model:<32} {row['location']:<12} {status:<8} {latency_ms if latency_ms is not None else '-':>6} ms "
              f"in={row['in']} out={row['out']} think={row['think']} ${row['usd']}  {row['note']}", flush=True)

    def scrub(self, text: str) -> str:
        text = " ".join(str(text).split())
        if self.project:
            text = text.replace(self.project, "<project>")
        return text[:220]

    def markdown(self, total_usd: float, max_usd: float) -> str:
        lines = [
            f"Backend `{self.backend}`, text location `{self.location}`. Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by "
            f"`backend/scripts/verify_google_models.py`. Costs are estimates from the price table, not billed amounts.", "",
            "| Capability | Model id | Location | Status | Latency | Tokens in/out (thinking) | Est. USD | Note |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            tokens = f"{r['in']}/{r['out']}" + (f" ({r['think']})" if r["think"] else "") if r["in"] is not None or r["out"] is not None else "-"
            usd = f"{r['usd']:.5f}" if r["usd"] is not None else "-"
            lines.append(f"| {r['capability']} | `{r['model']}` | {r['location']} | {r['status']} | "
                         f"{str(r['latency_ms']) + ' ms' if r['latency_ms'] is not None else '-'} | {tokens} | {usd} | {r['note']} |")
        lines += ["", f"Estimated spend for this run: ${total_usd:.4f} (ceiling ${max_usd:.2f})."]
        return "\n".join(lines)


def _status_of(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", None) or ""
    detail = f"HTTP {code} {status}" if code else type(exc).__name__
    return f"{detail}: {message[:140]}" if message else detail


async def probe_chat(gateway: Any, report: Report, settings: Any) -> dict[str, str]:
    """Reachability of each candidate chat model. Returns {family: first reachable id}."""
    from app.llm.gateway import ChatRequest, priced
    from app.llm.google import map_exception
    from app.llm.registry import estimate_cost, thinking_level_for

    working: dict[str, str] = {}
    provider = gateway._primary
    for family, model in CHAT_CANDIDATES:
        request = ChatRequest(
            model=model, messages=[{"role": "system", "content": "Answer in one short sentence."},
                                   {"role": "user", "content": "Name the capital of India."}],
            temperature=0.0, seed=None, max_tokens=700, json_schema=None, prompt_version="verify-probe-v1",
            thinking_level=thinking_level_for(model, "fast"),
        )
        started = time.perf_counter()
        try:
            async with gateway.meter.call(capability="chat", model=model, stage="verify", agent="probe",
                                          estimate_usd=estimate_cost(model, input_tokens=30, output_tokens=700).usd) as record:
                completion = await provider.complete(request)
                record.usage = completion.usage
        except Exception as exc:  # noqa: BLE001 - report every failure, then continue
            error = map_exception(exc)
            report.add("chat probe", model, "fail", latency_ms=int((time.perf_counter() - started) * 1000),
                       note=_status_of(exc) if hasattr(exc, "code") else str(error))
            continue
        latency = int((time.perf_counter() - started) * 1000)
        usage = priced(completion.usage, model)
        text = completion.text.strip()
        report.add("chat probe", model, "ok" if text else "empty", latency_ms=latency, usage=usage,
                   note=f"{family}; answered {text[:40]!r}")
        working.setdefault(family, model)
    return working


async def structured(gateway: Any, report: Report) -> None:
    """The three tiers through the production path, with realistic schemas (nested, enums, bounded lists, optionals)."""
    from typing import Annotated, ClassVar

    from pydantic import Field

    from app.agents._common import Strict, untrusted
    from app.agents.voice import variants_schema
    from app.llm.gateway import LLMError

    class Option(Strict):
        label: Annotated[str, Field(min_length=2, max_length=60)]
        reason: Annotated[str, Field(max_length=200)]
        stance: Literal["supports", "neutral", "concerns"]
        confidence: Annotated[float, Field(ge=0, le=1)] = 0.5
        note: str | None = None

    class Review(Strict):
        schema_version: ClassVar[str] = "verify-review-v1"
        sentiment: Literal["positive", "neutral", "negative", "mixed"]
        options: Annotated[list[Option], Field(min_length=2, max_length=3)]
        summary: Annotated[str, Field(max_length=240)]

    for task, tier in (("extraction", "fast"), ("creative_adaptation", "default"), ("risk_analysis", "reasoning")):
        try:
            result = await gateway.generate_structured(
                task=task, stage="verify", agent="verify", schema=Review, prompt_version="verify-review-v1", temperature=0.2,
                system="Review how a reader in Tamil Nadu might react to an outdoor-apparel headline. Give 2 or 3 options.",
                user=untrusted("headline", "Find your next great escape"),
            )
        except LLMError as exc:
            report.add(f"structured ({tier})", exc.trace.model_id or "-", "fail", latency_ms=exc.trace.latency_ms, usage=exc.trace.usage,
                       note=f"{exc.code}: {exc.message[:120]}")
            continue
        t = result.trace
        report.add(f"structured ({tier})", t.model_id or "-", "ok", latency_ms=t.latency_ms, usage=t.usage,
                   note=f"schema valid, retries={t.retries}, fallback={t.fallback_used}")
    # An actual agent schema: dynamic item bounds, $defs, nested models, forbidden extra keys.
    try:
        result = await gateway.generate_structured(
            task="creative_adaptation", stage="verify", agent="verify", schema=variants_schema(1),
            prompt_version="verify-variants-v1", temperature=0.2, max_tokens=1500,
            system="Return exactly one variant object following the schema. Use placeholder-free realistic copy.",
            user=untrusted("campaign", "Headline: Find your next great escape. Body: Light gear for weekend trails."),
        )
        t = result.trace
        report.add("structured (agent)", t.model_id or "-", "ok", latency_ms=t.latency_ms, usage=t.usage,
                   note=f"{variants_schema(1).__name__} valid, retries={t.retries}")
    except LLMError as exc:
        report.add("structured (agent)", exc.trace.model_id or "-", "fail", latency_ms=exc.trace.latency_ms, usage=exc.trace.usage,
                   note=f"{exc.code}: {exc.message[:120]}")


async def embeddings(gateway: Any, report: Report, settings: Any) -> None:
    from app.llm.gateway import LLMError

    for model in EMBED_CANDIDATES:
        local = settings.model_copy(update={"gemini_embedding_model": model})
        from app.llm.embeddings import EmbeddingClient

        adapter = EmbeddingClient(local, client=gateway._client, meter=gateway.meter, backoff_seconds=0.5)
        if not adapter.is_configured():
            report.add("embeddings", model, "skip", note="not configured")
            continue
        try:
            result = await adapter.embed(EMBED_TEXTS, kind="query", stage="verify", agent="verify")
        except LLMError as exc:
            report.add("embeddings", model, "fail", latency_ms=exc.trace.latency_ms, note=f"{exc.code}: {exc.message[:120]}")
            continue
        dims = sorted({len(v) for v in result.vectors})
        norms = [round(math.sqrt(sum(x * x for x in v)), 3) for v in result.vectors]
        ok = len(result.vectors) == len(EMBED_TEXTS) and dims == [settings.gemini_embedding_dimensions]
        report.add("embeddings", model, "ok" if ok else "shape", latency_ms=result.trace.latency_ms, usage=result.trace.usage,
                   note=f"{len(result.vectors)} vectors dims={dims} norms={norms} max_batch={adapter.max_batch} "
                        f"task_types={adapter._task_types}")


async def vision(gateway: Any, report: Report) -> None:
    from scripts.verify_inference import test_png

    client = gateway.capability("vision")
    if client is None:
        report.add("vision", "-", "skip", note="not configured")
        return
    result = await client.observe(uuid4(), test_png(), "image/png", stage="verify", agent="verify")
    status = result.status
    usage = result.trace.usage if result.trace else None
    seen = "; ".join(f"{o.kind}: {o.description[:40]}" for o in result.observations[:3])
    report.add("vision", status.model_id or "-", "ok" if status.status == "analyzed" and result.observations else status.status,
               latency_ms=result.trace.latency_ms if result.trace else None, usage=usage, note=status.message or seen)


async def image_generation(gateway: Any, report: Report, settings: Any) -> None:
    from app.llm.gateway import LLMError
    from app.llm.media import IMAGE_LOCATION, ImageGenerationClient

    for model in IMAGE_CANDIDATES:
        adapter = ImageGenerationClient(settings.model_copy(update={"gemini_model_image": model}), client=None,
                                        meter=gateway.meter)
        try:
            image = await adapter.generate("A plain pastel-green background with one small round marigold flower in the corner.",
                                           aspect_ratio="1:1", stage="verify", agent="verify")
        except LLMError as exc:
            report.add("image generation", model, "fail", location=IMAGE_LOCATION, latency_ms=exc.trace.latency_ms,
                       note=f"{exc.code}: {exc.message[:120]}")
            continue
        report.add("image generation", model, "ok", location=IMAGE_LOCATION, latency_ms=image.trace.latency_ms,
                   usage=image.trace.usage, note=f"{image.mime_type} {image.width}x{image.height} {len(image.image)} bytes")
        return  # one working image model is enough; each call costs several cents


async def tts(gateway: Any, report: Report, settings: Any) -> None:
    from app.llm.gateway import LLMError
    from app.llm.media import TTSClient

    for model in TTS_CANDIDATES:
        adapter = TTSClient(settings.model_copy(update={"gemini_model_tts": model}), client=None, meter=gateway.meter)
        try:
            audio = await adapter.synthesize("Namaste. Welcome to Omnicult.", language="hi", stage="verify", agent="verify")
        except LLMError as exc:
            report.add("tts", model, "fail", latency_ms=exc.trace.latency_ms, note=f"{exc.code}: {exc.message[:120]}")
            continue
        report.add("tts", model, "ok", latency_ms=audio.trace.latency_ms, usage=audio.trace.usage,
                   note=f"{audio.duration_seconds}s {audio.sample_rate} Hz WAV {len(audio.wav)} bytes, language {audio.language_code}")
        return


async def grounding(gateway: Any, report: Report) -> None:
    from app.llm.gateway import LLMError

    client = gateway.capability("grounded_research")
    if client is None:
        report.add("grounded research", "-", "skip", note="not configured")
        return
    try:
        answer = await client.research("Which festival marks the harvest season in Tamil Nadu in January? One sentence.",
                                       stage="verify", agent="verify")
    except LLMError as exc:
        report.add("grounded research", client.model or "-", "fail", latency_ms=exc.trace.latency_ms, note=f"{exc.code}: {exc.message[:120]}")
        return
    hosts = sorted({c.title for c in answer.citations if c.title})[:3]
    report.add("grounded research", answer.model, "ok" if answer.citations else "no-sources", latency_ms=answer.trace.latency_ms,
               usage=answer.trace.usage, note=f"{len(answer.citations)} citations, {len(answer.web_search_queries)} queries; {hosts}")


async def music(gateway: Any, report: Report, settings: Any, location: str) -> None:
    """One Lyria 2 clip over REST (`predict`, 30 s WAV). Not a gateway adapter: music generation stays out of scope."""
    import base64

    import google.auth
    import google.auth.transport.requests
    import httpx

    from app.llm.registry import estimate_cost

    model = "lyria-002"
    project = settings.google_cloud_project
    if settings.google_genai_backend != "vertex" or not project:
        report.add("music", model, "skip", location=location, note="Vertex AI only")
        return
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(google.auth.transport.requests.Request())
    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}"
           f"/publishers/google/models/{model}:predict")
    body = {"instances": [{"prompt": "A short, warm instrumental with mridangam and veena, festive harvest mood.",
                           "negative_prompt": "vocals"}], "parameters": {"sample_count": 1}}
    started = time.perf_counter()
    try:
        async with gateway.meter.call(capability="music", model=model, stage="verify", agent="verify",
                                      estimate_usd=estimate_cost(model, audio_seconds=30).usd) as record:
            async with httpx.AsyncClient(timeout=120) as http:
                response = await http.post(url, json=body, headers={"Authorization": f"Bearer {credentials.token}"})
            if response.status_code != 200:
                error = response.json().get("error", {}) if response.headers.get("content-type", "").startswith("application/json") else {}
                raise RuntimeError(f"HTTP {response.status_code} {error.get('status', '')}: {str(error.get('message', ''))[:140]}")
            prediction = response.json()["predictions"][0]
            record.audio_seconds = 30.0  # the clip was generated (and billed) once the API answered 200
            field = next((k for k in ("audioContent", "bytesBase64Encoded") if k in prediction), None)
            if field is None:
                raise RuntimeError(f"unexpected prediction fields: {sorted(prediction)}")
            audio = base64.b64decode(prediction[field])
    except Exception as exc:  # noqa: BLE001
        report.add("music", model, "fail", location=location, latency_ms=int((time.perf_counter() - started) * 1000), note=str(exc))
        return
    report.add("music", model, "ok", location=location, latency_ms=int((time.perf_counter() - started) * 1000),
               note=f"{prediction.get('mimeType')} {len(audio)} bytes (about 30 s, 48 kHz), field {field}")


async def video(gateway: Any, report: Report, settings: Any) -> None:
    """One 4 s, 720p, text-only Veo clip through the production adapter (`predictLongRunning`, then polling). Opt-in."""
    from app.llm.gateway import LLMError
    from app.llm.media import VideoClient

    client = VideoClient(settings, meter=gateway.meter)
    if not client.is_configured():
        report.add("video", settings.gemini_model_video, "skip", location=settings.google_video_location, note="Vertex AI only")
        return
    started = time.perf_counter()
    try:
        clip = await client.generate("A brass lamp flickers on a teal wooden table at dusk, a slow camera push-in. No people, no text.",
                                     seconds=4, aspect_ratio="9:16", stage="verify", agent="verify")
    except LLMError as exc:
        report.add("video", client.model or "-", "fail", location=settings.google_video_location, usage=exc.trace.usage,
                   latency_ms=int((time.perf_counter() - started) * 1000), note=f"{exc.code}: {exc.message}")
        return
    report.add("video", clip.model, "ok", location=clip.location, latency_ms=int((time.perf_counter() - started) * 1000),
               usage=clip.trace.usage, note=f"{clip.mime_type} {len(clip.video)} bytes, {clip.seconds} s at {clip.resolution}, operation {clip.operation_id}")


async def run(args: argparse.Namespace) -> int:
    from app.core.config import Settings
    from app.llm import google
    from app.llm.budget import BudgetGuard, InMemoryUsageSink
    from app.llm.gateway import LLMGateway

    values: dict[str, Any] = {"google_genai_backend": args.backend, "llm_max_retries": 1}
    if args.project:
        values["google_cloud_project"] = args.project
    if args.location:
        values["google_cloud_location"] = args.location
    settings = Settings(_env_file=None, **values)
    if not google.is_configured(settings):
        print("NOT CONFIGURED: pass --project (Vertex AI with ADC) or use --backend gemini_api with GEMINI_API_KEY set.")
        return 2
    sink = InMemoryUsageSink()
    guard = BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=args.max_usd)
    gateway = LLMGateway(settings, usage_sink=sink, budget=guard, client=google.build_client(settings, timeout_seconds=90))
    report = Report(settings.google_genai_backend, settings.google_cloud_location, settings.google_cloud_project)

    steps = set(args.steps.split(","))
    working = await probe_chat(gateway, report, settings) if "chat" in steps else {}
    # Point the tiers at what actually answered, so the gateway checks below use verified ids.
    tiers = {
        "gemini_model_fast": working.get("flash-lite") or working.get("flash"),
        "gemini_model_default": working.get("flash") or working.get("flash-lite"),
        "gemini_model_reasoning": working.get("pro") or working.get("flash") or working.get("flash-lite"),
    }
    if args.tiers:
        fast, default, reasoning = args.tiers.split(",")
        tiers = {"gemini_model_fast": fast, "gemini_model_default": default, "gemini_model_reasoning": reasoning}
    settings = settings.model_copy(update={k: v for k, v in tiers.items() if v})
    gateway = LLMGateway(settings, usage_sink=sink, budget=guard, client=gateway._client)
    print(f"tiers: {tiers}", flush=True)
    plan = {"structured": lambda: structured(gateway, report), "embeddings": lambda: embeddings(gateway, report, settings),
            "vision": lambda: vision(gateway, report), "image": lambda: image_generation(gateway, report, settings),
            "tts": lambda: tts(gateway, report, settings), "grounding": lambda: grounding(gateway, report),
            "music": lambda: music(gateway, report, settings, args.music_location),
            "video": lambda: video(gateway, report, settings)}
    for name, step in plan.items():
        if name not in steps:
            continue
        try:
            await step()
        except Exception as exc:  # noqa: BLE001 - one broken capability must not hide the others
            report.add("step", "-", "error", note=_status_of(exc))
    total = await sink.spent_usd()
    print(f"\nestimated spend ${total:.4f} of ${args.max_usd:.2f}")
    if args.out:
        Path(args.out).write_text(report.markdown(total, args.max_usd), encoding="utf-8")
        print(f"report written to {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="make the real calls (without it, print the plan only)")
    parser.add_argument("--backend", choices=["vertex", "gemini_api"], default="vertex")
    parser.add_argument("--project", default=None, help="Google Cloud project (default: GOOGLE_CLOUD_PROJECT)")
    parser.add_argument("--location", default=None, help="Vertex location for text models (default: global)")
    parser.add_argument("--max-usd", type=float, default=0.25, help="estimated-spend ceiling for the whole run")
    parser.add_argument("--out", default=None, help="write the markdown table here")
    parser.add_argument("--steps", default="chat,structured,embeddings,vision,image,tts,grounding,music",
                        help="comma-separated subset to run (each step costs money; `video` is opt-in and costs about $0.32)")
    parser.add_argument("--music-location", default="us-central1", help="Vertex location for the Lyria clip")
    parser.add_argument("--tiers", default=None, help="skip the chat probe: fast,default,reasoning model ids")
    args = parser.parse_args()
    loaded = load_env_file(ENV_FILE)
    args.project = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    print(f"env file {'found' if ENV_FILE.is_file() else 'missing'}; variables loaded: {', '.join(loaded) or 'none'}")
    if not args.run:
        print("Plan: probe chat ids "
              + ", ".join(m for _, m in CHAT_CANDIDATES)
              + "; then structured output, embeddings, vision, image, tts, grounding. Re-run with --run to make the calls.")
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
