from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_api_key
from app.core.config import get_settings
from app.db.session import get_db
from app.ingestion.normalize import normalize_metrics, normalize_spans
from app.ingestion.otlp_schemas import MetricsExportRequest, TracesExportRequest
from app.models.workspace import Workspace
from app.workers.tasks import ingest_metrics_batch, ingest_spans_batch

router = APIRouter()
settings = get_settings()


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
    spans = normalize_spans(payload, workspace.id)
    for i in range(0, len(spans), settings.max_ingest_batch_size):
        batch = spans[i:i + settings.max_ingest_batch_size]
        ingest_spans_batch.delay(str(workspace.id), batch)
    return {"accepted": len(spans)}


@router.post("/v1/metrics")
async def receive_metrics(
    payload: MetricsExportRequest,
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    metrics = normalize_metrics(payload, workspace.id)
    for i in range(0, len(metrics), settings.max_ingest_batch_size):
        batch = metrics[i:i + settings.max_ingest_batch_size]
        ingest_metrics_batch.delay(str(workspace.id), batch)
    return {"accepted": len(metrics)}
