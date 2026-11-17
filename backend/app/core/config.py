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

    # Supabase settings remain only for ASSET_STORAGE_BACKEND=supabase (the infra stream replaces that backend with GCS).
    supabase_url: str | None = None
    # Server-side Storage credential (ASSET_STORAGE_BACKEND=supabase). Never sent to the browser or logged.
    supabase_secret_key: SecretStr | None = None

    database_url: str = "sqlite+aiosqlite:///./nativeproof.db"

    # Provider-neutral call limits. The model gateway itself is configured in the Google block at the end of this class.
    llm_request_timeout_seconds: float = 60
    llm_max_retries: int = 2

    qloo_api_key: SecretStr | None = None
    # Unset = the official default host (https://api.qloo.com). Set it only when the event key belongs to another
    # Qloo host, e.g. https://hackathon.api.qloo.com (docs/04 A.9).
    qloo_base_url: str | None = None
    # auto (unset) = the official harness (`qloo exec`) when Node and the pinned harness exist, else direct REST.
    qloo_transport: Literal["auto", "harness", "rest"] | None = None
    qloo_bin: str = "qloo"
    qloo_timeout_seconds: float = 30

    # Uploaded assets (contracts/README section 13)
    # database: bytes in a table (tests); local: files under storage/assets (development); gcs: a private Cloud Storage
    # bucket (production); supabase: legacy Supabase Storage, removed with the rest of Supabase.
    asset_storage_backend: Literal["database", "supabase", "gcs", "local"] = "database"
    max_image_bytes: int = 5 * 1024 * 1024  # migration 0006 sets the bucket's file_size_limit to the same value

    max_active_runs_per_user: int = 2
    # Work limit for one population study run; a larger request is refused with 422, never silently reduced.
    population_max_participants: int = 600

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

    @field_validator(
        "supabase_url",
        "supabase_secret_key",
        "qloo_api_key",
        "qloo_base_url",
        "qloo_transport",
        "gcs_bucket",
        "firebase_project_id",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `QLOO_API_KEY=` in a .env file means "not configured", not an empty credential.
        return None if isinstance(value, str) and not value.strip() else value

    # A field validator, not a model validator: its error input is just the auth mode, never the full settings
    # input (which holds provider keys), so even `ValidationError.errors()` cannot leak a secret.
    @field_validator("auth_mode")
    @classmethod
    def _dev_auth_outside_production_only(cls, value: str, info: ValidationInfo) -> str:
        if value == "dev" and info.data.get("app_env") == "production":
            raise ValueError("AUTH_MODE=dev is refused when APP_ENV=production.")
        return value

    # Fail at startup, naming only the missing settings (the key is declared above, so info.data holds it).
    @field_validator("asset_storage_backend")
    @classmethod
    def _supabase_storage_needs_credentials(cls, value: str, info: ValidationInfo) -> str:
        if value == "supabase" and not (info.data.get("supabase_url") and info.data.get("supabase_secret_key")):
            raise ValueError("ASSET_STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY.")
        return value

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

    @field_validator("google_cloud_project", "gemini_api_key", mode="before")
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
