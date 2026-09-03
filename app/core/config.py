"""
Central application configuration.

Everything here is loaded from environment variables (see .env.example).
Nothing in this file should hardcode a workspace, a monitored service, or
any customer-specific value -- Ghost Protocol is ingestion-based, so the
only things that are "global" are infrastructure connection settings.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    ghost_env: str = "local"
    ghost_log_level: str = "INFO"
    ghost_secret_key: str = ""  # Fernet key; required before storing any workspace's reasoning-service API key

    # --- Security ---
    # Comma-separated list of origins allowed to make credentialed
    # (cookie-bearing) requests -- e.g. "http://localhost:3000" in dev,
    # "https://app.yourcompany.com" in production. Never "*" -- a
    # wildcard origin is incompatible with credentialed CORS requests
    # by browser design, and would defeat the point of an httpOnly
    # session cookie anyway.
    ghost_allowed_origins: str = "http://localhost:3000"
    # Session cookies get the `Secure` flag (HTTPS-only) whenever this
    # isn't "local" -- set GHOST_ENV=production once TLS is terminated
    # in front of the app. Left insecure by default only so local dev
    # over plain http://localhost actually works.
    ghost_login_rate_limit_per_minute: int = 10

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ghost_allowed_origins.split(",") if o.strip()]

    @property
    def cookies_secure(self) -> bool:
        return self.ghost_env != "local"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://ghost:ghost@localhost:5432/ghost_protocol"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Behavioral graph baselines ---
    baseline_window_minutes: int = 30
    baseline_ewma_alpha: float = 0.2
    anomaly_zscore_threshold: float = 3.0

    # --- Ingestion ---
    max_ingest_batch_size: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()