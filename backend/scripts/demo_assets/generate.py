# /// script
# requires-python = ">=3.12"
# dependencies = ["google-genai>=3.4.0", "pillow>=11", "fonttools>=4.50"]
# ///
"""Paid Vertex AI calls for the demo creative. Every call is budget-guarded and logged with its estimated cost.

    uv run --script backend/scripts/demo_assets/generate.py pack            # 1 image (product tin, white background)
    uv run --script backend/scripts/demo_assets/render.py pack              # cut-out + logo -> brand/pack*.png
    uv run --script backend/scripts/demo_assets/generate.py scenes kv       # 4 scene plates + key-visual plate
    uv run --script backend/scripts/demo_assets/generate.py tts music asr   # voice-over lines, music bed, ASR check

Outputs go to the cache (`OMNICULT_DEMO_CACHE`, default ~/.cache/omnicult-demo-assets/raw); render.py turns them into
the committed fixtures. A step whose output exists is skipped unless --force is given. Uses Application Default
Credentials; set GOOGLE_CLOUD_PROJECT to the paying Vertex AI project. Images, TTS and ASR at location `global`,
Lyria at `us-central1`. Spend is logged to omnicult-docs/DEMO_ASSETS_LOG.md (outside git), hard cap USD 2.00.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec  # noqa: E402
from common import CACHE, FIXTURES, GCP_PROJECT, Timer, guard, record, say  # noqa: E402

RAW = CACHE / "raw"
IMAGE_GUARD_USD = 0.16  # worst case for one 2K image with references and thinking
IMAGE_OUT_PER_TOKEN = 60e-6  # USD 0.067 per 1K image (1,120 tokens)
IMAGE_IN_PER_TOKEN, THINK_PER_TOKEN = 0.50e-6, 3.00e-6


_CLIENTS: dict = {}


def client(location: str = "global"):
    """One client per location, kept alive: a temporary Client closes its HTTP session when garbage-collected."""
    from google import genai

    if not GCP_PROJECT:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT to the Vertex AI project that should pay for these calls.")
    if location not in _CLIENTS:
        _CLIENTS[location] = genai.Client(vertexai=True, project=GCP_PROJECT, location=location)
    return _CLIENTS[location]


def _tokens(resp) -> tuple[int, int, int]:
    u = resp.usage_metadata
    return (u.prompt_token_count or 0, u.candidates_token_count or 0, u.thoughts_token_count or 0) if u else (0, 0, 0)


def image(step: str, prompt: str, out: Path, aspect: str, size: str, refs: list[Path], force: bool) -> None:
    from google.genai import types

    if out.exists() and not force:
        return say(f"skip {step}: {out.name} exists")
    text = f"{prompt}\n\n{spec.NO_TEXT}"
    parts = [types.Part.from_text(text=text)]
    for ref in refs:
        mime = "image/png" if ref.suffix == ".png" else "image/jpeg"
        parts.append(types.Part.from_bytes(data=ref.read_bytes(), mime_type=mime))
    for image_size in (size, "1K") if size != "1K" else ("1K",):
        guard(IMAGE_GUARD_USD)
        params = f"{aspect} {image_size} refs={len(refs)} {spec.PROMPT_VERSION} sha={hashlib.sha256(text.encode()).hexdigest()[:10]}"
        config = types.GenerateContentConfig(response_modalities=["IMAGE"],
                                             image_config=types.ImageConfig(aspect_ratio=aspect, image_size=image_size))
        with Timer() as t:
            try:
                resp = client().models.generate_content(model=spec.IMAGE_MODEL, contents=[types.Content(role="user", parts=parts)],
                                                        config=config)
            except Exception as exc:  # noqa: BLE001 - logged, then retried at 1K or raised
                record(step, spec.IMAGE_MODEL, "global", params, f"error {type(exc).__name__}: {exc}", t.ms, "-", 0.0, "-")
                if image_size == "1K":
                    raise
                continue
        tin, tout, think = _tokens(resp)
        usd = tin * IMAGE_IN_PER_TOKEN + tout * IMAGE_OUT_PER_TOKEN + think * THINK_PER_TOKEN
        data = next((p.inline_data.data for c in resp.candidates or [] for p in (c.content.parts if c.content else []) or []
                     if p.inline_data and str(p.inline_data.mime_type).startswith("image/")), None)
        if data is None:
            reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
            record(step, spec.IMAGE_MODEL, "global", params, f"no image ({reason})", t.ms, f"{tin}/{tout}+{think}", usd, "-")
            raise SystemExit(f"{step}: the model returned no image ({reason}).")
        out.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        Image.open(io.BytesIO(data)).save(out)  # normalise to PNG whatever the returned mime type
        w, h = Image.open(out).size
        total = record(step, spec.IMAGE_MODEL, "global", params, f"ok {w}x{h}", t.ms, f"{tin}/{tout}+{think}", usd, out.name)
        return say(f"{step}: {out.name} {w}x{h}, est. USD {usd:.4f}, running {total:.4f}")


def pack(force: bool) -> None:
    image("pack", spec.PACK_PROMPT, RAW / "pack_raw.png", "1:1", "1K", [], force)


def reference(ref_id: str) -> Path:
    """A raw image, or a crop of one declared in spec.CROPS (made on first use)."""
    path = RAW / f"{ref_id}.png"
    if ref_id in spec.CROPS and not path.exists():
        from PIL import Image

        src, (x0, y0, x1, y1) = spec.CROPS[ref_id]
        im = Image.open(RAW / f"{src}.png")
        im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height))).save(path)
    return path


def scenes(force: bool, only: list[str] | None = None) -> None:
    ref = FIXTURES / "brand" / "pack_reference.png"
    if not ref.exists():
        raise SystemExit("Run `render.py pack` first: scenes use brand/pack_reference.png as the product reference.")
    for scene in spec.SCENES:
        if only and scene["id"] not in only:
            continue
        extra = [reference(s) for s in scene["refs"]]
        prompt = f"{scene['prompt']} {spec.STYLE}\n\n{spec.PACK_REF}"
        image(f"scene {scene['id']}", prompt, RAW / f"{scene['id']}.png", "9:16", "2K", [ref, *extra], force)


def kv(force: bool) -> None:
    image("key visual plate", spec.KV_PROMPT, RAW / "kv.png", "4:5", "2K", [], force)


def tts(force: bool) -> None:
    from google.genai import types

    for line in spec.VO_LINES:
        out = RAW / f"{line['id']}.wav"
        if out.exists() and not force:
            say(f"skip tts {line['id']}")
            continue
        guard(0.01)
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code="mr-IN",
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=spec.VOICE))),
        )
        params = f"mr-IN voice={spec.VOICE} {spec.PROMPT_VERSION}"
        with Timer() as t:
            try:
                text = f"{spec.TTS_STYLE}\n{line['text']}" if spec.TTS_STYLE else line["text"]
                resp = client().models.generate_content(model=spec.TTS_MODEL, contents=text, config=config)
            except Exception as exc:  # noqa: BLE001
                record(f"tts {line['id']}", spec.TTS_MODEL, "global", params, f"error {type(exc).__name__}: {exc}", t.ms, "-", 0.0, "-")
                raise
        tin, tout, _ = _tokens(resp)
        blob = next(p.inline_data for p in resp.candidates[0].content.parts if p.inline_data)
        rate = next((int(x.split("=")[1]) for x in str(blob.mime_type).split(";") if x.strip().startswith("rate=")), 24000)
        seconds = len(blob.data) / (rate * 2)
        usd = tin * 0.50e-6 + (tout or seconds * 25) * 9.00e-6
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1), wav.setsampwidth(2), wav.setframerate(rate), wav.writeframes(blob.data)
        total = record(f"tts {line['id']}", spec.TTS_MODEL, "global", params, f"ok {seconds:.2f}s {rate}Hz", t.ms,
                       f"{tin}/{tout}", usd, out.name)
        say(f"tts {line['id']}: {seconds:.2f}s, est. USD {usd:.4f}, running {total:.4f}")


def music(force: bool) -> None:
    import json
    import urllib.error
    import urllib.request

    import google.auth
    import google.auth.transport.requests

    out = RAW / "music.wav"
    if out.exists() and not force:
        return say("skip music")
    guard(0.06)
    client()  # fails early without GOOGLE_CLOUD_PROJECT
    location = "us-central1"
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}/locations/{location}"
           f"/publishers/google/models/{spec.MUSIC_MODEL}:predict")
    body = {"instances": [{"prompt": spec.MUSIC_PROMPT, "negative_prompt": spec.MUSIC_NEGATIVE, "seed": 2027}],
            "parameters": {}}
    params = f"seed=2027 {spec.PROMPT_VERSION}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"})
    with Timer() as t:
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:  # noqa: S310 - fixed Vertex AI endpoint
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            record("music", spec.MUSIC_MODEL, location, params, f"error HTTP {exc.code}: {exc.read()[:120]!r}", t.ms, "-", 0.0, "-")
            raise SystemExit(f"Lyria failed: HTTP {exc.code}; render.py falls back to voice-over only.") from exc
    prediction = payload["predictions"][0]
    field = next(k for k in ("bytesBase64Encoded", "audioContent") if k in prediction)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(prediction[field]))
    with wave.open(str(out)) as wav:  # Lyria's header frame count is unreliable: derive the length from the bytes
        seconds = (out.stat().st_size - 44) / (wav.getframerate() * wav.getnchannels() * wav.getsampwidth())
    total = record("music", spec.MUSIC_MODEL, location, params, f"ok {seconds:.1f}s", t.ms, "-", 0.06, out.name)
    say(f"music: {seconds:.1f}s, est. USD 0.06, running {total:.4f}")


def asr(force: bool) -> None:
    """Transcribe each voice-over line with a Gemini text model and compare with the script (pronunciation check)."""
    from google.genai import types

    guard(0.02)
    parts = [types.Part.from_text(text="Transcribe each audio clip exactly, in the script of its language (Marathi in "
                                       "Devanagari, English in Latin). Answer with one line per clip, in order, "
                                       "nothing else.")]
    for line in spec.VO_LINES:
        parts.append(types.Part.from_bytes(data=(RAW / f"{line['id']}.wav").read_bytes(), mime_type="audio/wav"))
    config = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="LOW"), temperature=0)
    with Timer() as t:
        resp = client().models.generate_content(model=spec.ASR_MODEL, contents=[types.Content(role="user", parts=parts)],
                                                config=config)
    tin, tout, think = _tokens(resp)
    usd = tin * 1.00e-6 + (tout + think) * 4.00e-6  # audio input priced conservatively
    heard = [h.strip() for h in (resp.text or "").strip().splitlines() if h.strip()]
    scores = []
    for line, got in zip(spec.VO_LINES, heard + [""] * len(spec.VO_LINES)):
        norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum() or "ऀ" <= ch <= "ॿ")  # noqa: E731
        scores.append(round(difflib.SequenceMatcher(None, norm(line["text"]), norm(got)).ratio(), 2))
        say(f"{line['id']}: {scores[-1]:.2f}  script={line['text']}  heard={got}")
    out = RAW / "asr_check.txt"
    out.write_text("\n".join(f"{l['id']}\t{s}\t{h}" for l, s, h in zip(spec.VO_LINES, scores, heard + [""] * 6)), encoding="utf-8")
    record("asr check", spec.ASR_MODEL, "global", "thinking=LOW", f"ok similarity {min(scores):.2f}-{max(scores):.2f}",
           t.ms, f"{tin}/{tout}+{think}", usd, out.name)


STEPS = {"pack": pack, "scenes": scenes, "kv": kv, "tts": tts, "music": music, "asr": asr}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("steps", nargs="+", choices=list(STEPS))
    parser.add_argument("--force", action="store_true", help="regenerate even if the output exists (costs money)")
    parser.add_argument("--only", nargs="*", help="scene ids to (re)generate, for the scenes step")
    args = parser.parse_args()
    for name in args.steps:
        STEPS[name](args.force, args.only) if name == "scenes" else STEPS[name](args.force)
