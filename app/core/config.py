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

    # --- Public demo (optional) ---
    # If set, seed_demo_workspace (see app/workers/tasks.py) generates
    # synthetic traffic and periodic incidents for this one workspace on
    # a schedule, so a public-facing demo deployment always has
    # something real to look at. Left unset ("") on every other
    # deployment, where the task becomes a no-op immediately.
    ghost_demo_workspace_id: str = ""

    # --- Free-tier deployment mode (optional) ---
    # When true, every place that would normally enqueue a Celery task
    # via .delay() instead calls it directly and synchronously in the
    # same request -- see app/core/dispatch.py. This exists because no
    # mainstream host offers a genuinely free persistent background
    # worker process in 2026; running everything synchronously removes
    # the need for one entirely. Fine for a low-traffic public demo,
    # not something you'd want for a real production deployment under
    # real load, which is exactly why this defaults to False and stays
    # an explicit opt-in.
    ghost_sync_mode: bool = False

    # Shared secret an external cron service must present (as
    # X-Internal-Secret) to call POST /internal/tick, the periodic-
    # maintenance endpoint that substitutes for Celery beat when there's
    # no persistent worker process. Required whenever GHOST_SYNC_MODE is
    # on; leaving it unset in sync mode means the endpoint accepts
    # nothing (fails closed, not open).
    ghost_internal_secret: str = ""

    # --- Ingestion abuse protection ---
    # Per-workspace, per-minute, same Redis INCR+EXPIRE pattern as the
    # login rate limiter. The demo workspace gets its own, much
    # stricter limit -- its API key necessarily lives client-side (the
    # "View live demo" button), so it's the one workspace where
    # "someone extracted the key and is hammering ingestion" is a real,
    # expected threat, not a hypothetical one. 200/min comfortably
    # covers the seeder's own ~18/min with headroom for real visitors
    # poking at the demo, while still bounding the damage if the key
    # gets scraped and abused.
    ghost_ingest_rate_limit_per_minute: int = 6000
    ghost_demo_ingest_rate_limit_per_minute: int = 200
    # Hard reject (413) above this many spans/metrics in a single
    # request body, independent of the per-minute counter above --
    # stops one oversized payload from doing in a single call what the
    # rate limit exists to prevent across many.
    ghost_max_spans_per_request: int = 5000
    ghost_max_metrics_per_request: int = 5000

    # --- Telemetry retention ---
    # Raw spans/metrics older than this get pruned by
    # app/ingestion/retention.py, called from /internal/tick. Exists
    # because the demo workspace writes data forever with no other
    # cleanup, and Neon's free Postgres tier caps out at 0.5GB --
    # without this, a long-lived free demo deployment eventually fills
    # its own database and starts failing writes.
    ghost_telemetry_retention_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()