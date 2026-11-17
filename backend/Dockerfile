# syntax=docker/dockerfile:1
# Omnicult API image (FastAPI + the in-process run engine). Build context: backend/.
# Runs the API by default; the migration job overrides the command (`alembic upgrade head`), never the app at start.
#   gcloud builds submit backend --config ops/cloudbuild/backend.yaml   (see ops/deploy/)

# backend/.python-version pins 3.13 (the version every test runs on); requires-python is >=3.12.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv==0.12.20
WORKDIR /app
# Dependencies first so this layer is cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:${PYTHON_VERSION}-slim AS runtime
# ffmpeg: video and audio work (Creative X-Ray, voice-over). Fonts: Noto covers Devanagari, Tamil, Malayalam, Bengali
# and Latin; libraqm (with fribidi and harfbuzz) gives Pillow correct shaping for Indic scripts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-core fonts-noto-ui-core \
        libraqm0 libfribidi0 libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/* \
    # Fail the build, not a render at run time, if an Indic script has no font.
    && for lang in hi mr ta ml bn; do fc-list ":lang=$lang" family | grep -q Noto || { echo "no Noto font for $lang" >&2; exit 1; }; done

ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Fail the build, not a render at run time, if Pillow cannot shape Indic scripts (libraqm, FriBiDi, HarfBuzz) or ffmpeg is unusable.
RUN python -c "from PIL import features; assert features.check('raqm'), 'Pillow has no raqm: Indic text would be refused'" \
    && ffmpeg -version > /dev/null && ffprobe -version > /dev/null
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
USER app
EXPOSE 8080
# Cloud Run terminates TLS and forwards the client address in X-Forwarded-*; it sends SIGTERM 10 s before it stops us.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10"]
