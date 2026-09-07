from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_api_key
from app.core.config import get_settings
from app.core.dispatch import dispatch
from app.core.redis_client import get_redis
from app.db.session import get_db
from app.ingestion.normalize import normalize_metrics, normalize_spans
from app.ingestion.otlp_schemas import MetricsExportRequest, TracesExportRequest
from app.models.workspace import Workspace
from app.workers.tasks import ingest_metrics_batch, ingest_spans_batch

router = APIRouter()
settings = get_settings()


async def _check_ingest_rate_limit(workspace: Workspace) -> None:
    """
    Per-workspace, per-minute -- same Redis INCR+EXPIRE pattern as the
    login rate limiter in auth.py. The demo workspace gets its own,
    much stricter limit: its API key necessarily lives client-side (the
    "View live demo" button on the login page), so it's the one
    workspace where "someone extracted the key and is hammering
    ingestion" is a real, expected threat rather than a hypothetical
    one -- everyone else gets the generous default.
    """
    is_demo = bool(settings.ghost_demo_workspace_id) and str(workspace.id) == settings.ghost_demo_workspace_id
    limit = settings.ghost_demo_ingest_rate_limit_per_minute if is_demo else settings.ghost_ingest_rate_limit_per_minute

    key = f"ingest_rate:{workspace.id}"
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)
    if count > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Ingestion rate limit exceeded for this workspace")


@router.post("/v1/traces")
async def receive_traces(
    payload: TracesExportRequest,
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Point an OTel collector's `otlphttp` exporter here (traces endpoint),
    with `Authorization: Bearer <workspace API key>`. This is the entire
    onboarding step for a new company -- no per-service registration.
    """
    await _check_ingest_rate_limit(workspace)

    spans = normalize_spans(payload, workspace.id)
    if len(spans) > settings.ghost_max_spans_per_request:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Request contains {len(spans)} spans, over the {settings.ghost_max_spans_per_request} limit per call",
        )

    for i in range(0, len(spans), settings.max_ingest_batch_size):
        batch = spans[i:i + settings.max_ingest_batch_size]
        dispatch(ingest_spans_batch, str(workspace.id), batch)
    return {"accepted": len(spans)}


@router.post("/v1/metrics")
async def receive_metrics(
    payload: MetricsExportRequest,
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    await _check_ingest_rate_limit(workspace)

    metrics = normalize_metrics(payload, workspace.id)
    if len(metrics) > settings.ghost_max_metrics_per_request:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Request contains {len(metrics)} metrics, over the {settings.ghost_max_metrics_per_request} limit per call",
        )

    for i in range(0, len(metrics), settings.max_ingest_batch_size):
        batch = metrics[i:i + settings.max_ingest_batch_size]
        dispatch(ingest_metrics_batch, str(workspace.id), batch)
    return {"accepted": len(metrics)}