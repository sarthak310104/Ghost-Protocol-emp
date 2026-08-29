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
