"""Application settings from environment variables or backend/.env.

Shared by every backend module. Fields change only through the integration owner;
names match backend/.env.example. Secrets are SecretStr so they never print by accident.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: a validation error at startup must never echo a provider key into the logs.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    frontend_origins: str = "http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./omnicult.db"

    # Provider-neutral call limits. The model gateway itself is configured in the Google block at the end of this class.
    llm_request_timeout_seconds: float = 60
    llm_max_retries: int = 2

    # Uploaded assets (contracts/README section 13)
    # database: bytes in a table (tests); local: files under storage/assets (development); gcs: a private Cloud Storage
    # bucket (production).
    asset_storage_backend: Literal["database", "gcs", "local"] = "database"
    max_image_bytes: int = 5 * 1024 * 1024  # migration 0006 sets the bucket's file_size_limit to the same value

    max_active_runs_per_user: int = 2

    # --- infra (ops/deploy/) ---
    # Cloud Storage bucket for ASSET_STORAGE_BACKEND=gcs. Credentials come from the runtime service account (ADC),
    # never from a key in this file. validate_default so that an unset bucket fails at startup, not at first upload.
    gcs_bucket: str | None = Field(default=None, validate_default=True)

    # --- data-auth stream (Phase 1 contract section 1) ---
    # dev: `dev-<label>` tokens, refused in production. firebase: Firebase Authentication ID tokens.
    auth_mode: Literal["dev", "firebase"] = "dev"
    firebase_project_id: str | None = None

    # --- audience stream (Audience Lab: Quick Read, Audience Study, Ask the Panel, Risk Check) ---
    # Work limits. A request above a limit is refused with 422, never silently reduced.
    audience_quick_read_max_participants: int = Field(default=24, ge=6)
    audience_study_max_participants: int = Field(default=60, ge=20)
    audience_ask_max_participants: int = Field(default=60, ge=1)  # participants answering one question
    audience_run_timeout_seconds: int = Field(default=900, ge=30)
    # --- media stream (Phase 2 contract): video and audio uploads, ffmpeg processing, Creative X-Ray ---
    # Largest video or audio upload and longest clip. Images keep MAX_IMAGE_BYTES.
    max_media_bytes: int = 50 * 1024 * 1024
    max_media_seconds: float = 60.0
    # ffmpeg and ffprobe: a name found on PATH or an absolute path. Detected at startup; a missing binary makes video and
    # audio uploads and Creative X-Ray fail with a clear PROVIDER_NOT_CONFIGURED error (images still work).
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    media_probe_timeout_seconds: float = 20
    media_tool_timeout_seconds: float = 90  # one ffmpeg command (scene detection, one frame, audio extraction)
    # Keyframes: scene changes at least KEYFRAME_MIN_GAP_MS apart, plus a frame whenever KEYFRAME_MAX_GAP_MS would pass
    # without one, at most KEYFRAME_MAX_COUNT in all (each frame is one vision call).
    keyframe_scene_threshold: float = 0.3
    keyframe_min_gap_ms: int = 1000
    keyframe_max_gap_ms: int = 4000
    keyframe_max_count: int = 16
    keyframe_max_width: int = 768
    media_signed_url_seconds: int = 600  # lifetime of a Cloud Storage signed URL (ASSET_STORAGE_BACKEND=gcs only)
    # --- culture data layer (docs/CONTRACTS_PHASE1.md section 1; backend/app/integrations/culture/) ---
    culture_http_timeout_seconds: float = 15
    # Wikimedia asks every client for a descriptive User-Agent with a way to reach the operator. The default names
    # no person or organisation: set WIKIMEDIA_USER_AGENT to "<app>/<version> (<contact URL or email>)" in deployment.
    wikimedia_user_agent: str = "CultureDataClient/0.1 (cultural research client; operator contact not configured)"
    # Both optional: the adapters that need them are reported as not configured, never faked.
    data_gov_in_api_key: SecretStr | None = None
    youtube_api_key: SecretStr | None = None
    # Comment Pulse reads public YouTube comments with this key (YouTube Data API v3, commentThreads.list: 1 quota unit a page of
    # 100, 10,000 units a day for the whole app). A fetch stops at this many pages, and the same video is not fetched again
    # before the interval has passed.
    youtube_max_pages: int = Field(default=5, ge=1, le=10)
    youtube_min_fetch_interval_seconds: int = Field(default=900, ge=0)
    # --- proof stream (Phase 2 contract) ---
    # How long a report export's download link works. The link carries a random token (only its hash is stored).
    proof_export_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator(
        "gcs_bucket",
        "firebase_project_id",
        "data_gov_in_api_key",
        "youtube_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `GCS_BUCKET=` in a .env file means "not configured", not an empty value.
        return None if isinstance(value, str) and not value.strip() else value

    # A field validator, not a model validator: its error input is just the auth mode, never the full settings
    # input (which holds provider keys), so even `ValidationError.errors()` cannot leak a secret.
    @field_validator("auth_mode")
    @classmethod
    def _dev_auth_outside_production_only(cls, value: str, info: ValidationInfo) -> str:
        if value == "dev" and info.data.get("app_env") == "production":
            raise ValueError("AUTH_MODE=dev is refused when APP_ENV=production.")
        return value

    # Fail at startup, naming only the missing settings (the backend is declared above, so info.data holds it).
    @field_validator("gcs_bucket")
    @classmethod
    def _gcs_storage_needs_bucket(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("asset_storage_backend") == "gcs" and not value:
            raise ValueError("ASSET_STORAGE_BACKEND=gcs needs GCS_BUCKET.")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    # --- gateway (Google Gen AI) ---------------------------------------------------------------------------------
    # Vertex AI (ADC on Cloud Run or `gcloud auth application-default login` locally; billed to the project) or the
    # Gemini Developer API (API key; its free tier may use prompts to improve Google products, so never real brand data).
    google_genai_backend: Literal["vertex", "gemini_api"] = "vertex"
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"  # image generation always uses `global`
    gemini_api_key: SecretStr | None = None
    # Model ids are configuration. Defaults are the ids verified through scripts/verify_google_models.py on 2026-11-17.
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    gemini_model_default: str = "gemini-3.8-flash"
    gemini_model_reasoning: str = "gemini-4-argon"
    gemini_model_image: str = "gemini-3.1-flash-image"
    gemini_model_tts: str = "gemini-3.8-flash-tts"
    gemini_model_live: str = "gemini-live-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimensions: int = 768
    # Hard ceilings (USD, estimated from the price table in app/llm/registry.py). A call that would cross either one
    # is refused before it is sent.
    ai_run_budget_usd: float = 0.50
    ai_daily_budget_usd: float = 5.0

    # --- demo journey -------------------------------------------------------------------------------------------------
    # What POST /projects/demo seeds. "aamod" is the Omnicult journey (app/services/demo_journey.py). "legacy" keeps the
    # earlier Northstar / Japan seed that the older workflow tests are written for (tests/conftest.py pins
    # it); it is not offered in any deployment.
    demo_seed: Literal["aamod", "legacy"] = "aamod"
    # --- lens (Market Lens) ---------------------------------------------------------------------------------------
    # A live build calls free public APIs (Wikidata, Wikipedia pageviews), so the same region is not rebuilt more often
    # than this, and one build is cut off after the timeout (its partial result is not stored).
    lens_live_build_min_interval_seconds: int = 300
    lens_build_timeout_seconds: int = 90
    # --- launch-t3 (Review Links, Region Plan, Asset Pack) ---------------------------------------------------------
    # Public review endpoints take no sign-in, so they are rate limited: requests per minute per client address, and
    # per link in total (a forged X-Forwarded-For cannot lift the per-link cap). One link also accepts a bounded
    # number of reviewer responses. Counters live in process memory (one value per running instance).
    review_rate_per_minute: int = Field(default=30, ge=1, le=600)
    review_max_responses_per_link: int = Field(default=200, ge=1, le=5000)
    # How long an Asset Pack download link works, and the largest ZIP the server will build.
    asset_pack_url_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    asset_pack_max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024 * 1024)
    # --- Remake: Visuals and Sound (Lyria jingle; the image and speech models are the gemini_model_* ids above) ---------
    gemini_model_music: str = "lyria-002"  # Vertex AI only; reached over REST `predict`, not the Gen AI SDK
    google_music_location: str = "us-central1"  # Lyria is offered in us-central1 (verified 2026-11-17)
    remake_max_voice_lines: int = 8  # speech calls one Remake: Sound run may make (one per line), a hard bound
    # Remake: Video. Veo 3.1 Fast is GA and offered in us-central1 only (verified 2026-11-18, docs/remake-video NOTES); the
    # Gen AI SDK is not used: the adapter calls REST `predictLongRunning` and `fetchPredictOperation` like the music adapter.
    gemini_model_video: str = "veo-3.1-fast-generate-001"
    google_video_location: str = "us-central1"

    # --- pulse-t3 (Live Pulse Tier 3: Alerts run by Cloud Scheduler) ---
    # POST /api/v1/internal/pulse/evaluate-alerts accepts only a Google OIDC ID token minted for this service account and
    # this audience (the service's own URL). Either one unset: the endpoint is refused. Never open, never a shared secret.
    scheduler_service_account: str | None = None
    scheduler_audience: str | None = None
    # One scheduled evaluation per campaign per period (UTC): 24 is one per day, 1 is one per hour.
    pulse_alert_period_hours: int = Field(default=24, ge=1, le=24)

    @field_validator("scheduler_service_account", "scheduler_audience", mode="before")
    @classmethod
    def _blank_scheduler_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    # --- digest (Weekly Digest, Cloud Scheduler): POST /api/v1/internal/digest/generate-weekly uses the same
    # scheduler_service_account and scheduler_audience as the alerts job above; either unset refuses every call.
    # --- lens tier 3 (Trend Radar, Category Shelf) ---------------------------------------------------------------
    # Both read free public APIs (Wikimedia pageviews, Wikidata): bounded terms and states per refresh, and a minimum
    # interval between live refreshes of the same state or category.
    lens_trend_max_terms: int = 5  # festival articles read per state; the category's own topics are added
    lens_trend_max_regions_live: int = 3
    lens_trend_min_interval_seconds: int = 300
    lens_shelf_max_attention: int = 6  # items whose Wikipedia pageviews are read per shelf refresh
    lens_shelf_min_interval_seconds: int = 300

    # --- lab-t3 (Audience Lab: Live Focus Group, Buzz Simulator, Message Check) ---------------------------------------
    # Bounds on what one session may ask of the model. Demo runs replay deterministic fixtures; the pause only paces the
    # replay so a session streams turn by turn the way a live one does (tests set it to 0).
    lab_t3_focus_max_speakers: int = Field(default=8, ge=2)
    lab_t3_focus_max_guide_questions: int = Field(default=6, ge=1)
    lab_t3_focus_max_interjections: int = Field(default=5, ge=0)
    lab_t3_demo_turn_delay_seconds: float = Field(default=0.35, ge=0)
    lab_t3_buzz_max_participants: int = Field(default=40, ge=12)
    lab_t3_buzz_max_rounds: int = Field(default=4, ge=1)
    lab_t3_message_check_max_per_region: int = Field(default=12, ge=3)
    lab_t3_message_check_max_regions: int = Field(default=4, ge=1)
    # --- search pulse (Google Trends public dataset in BigQuery; Market Lens) ----------------------------------------
    bigquery_project: str | None = None  # project the query jobs run in (needs roles/bigquery.jobUser); falls back to GOOGLE_CLOUD_PROJECT
    search_pulse_weeks: int = Field(default=12, ge=2, le=52)  # latest week plus the weeks before it that are kept
    search_pulse_max_bytes: int = Field(default=2_000_000_000, ge=10_000_000)  # hard maximum_bytes_billed per query
    search_pulse_timeout_seconds: float = Field(default=90, gt=0)

    @field_validator("google_cloud_project", "bigquery_project", "gemini_api_key", mode="before")
    @classmethod
    def _blank_google_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "google_cloud_location", "gemini_model_fast", "gemini_model_default", "gemini_model_reasoning",
        "gemini_model_image", "gemini_model_tts", "gemini_model_live", "gemini_embedding_model", mode="after",
    )
    @classmethod
    def _blank_google_model_uses_default(cls, value: str, info: ValidationInfo) -> str:
        # `GEMINI_MODEL_FAST=` in a copied .env means "use the default", not an empty id.
        return value.strip() or cls.model_fields[info.field_name].default


@lru_cache
def get_settings() -> Settings:
    return Settings()
