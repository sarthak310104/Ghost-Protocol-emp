from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_api_key
from app.db.session import get_db
from app.models.deployment import Deployment
from app.models.workspace import Workspace

router = APIRouter()


class RecordDeploymentIn(BaseModel):
    service_name: str
    version: str
    notes: str | None = None
    deployed_at: datetime | None = None  # defaults to now if omitted


@router.post("/v1/deployments")
async def record_deployment(
    payload: RecordDeploymentIn,
    workspace: Workspace = Depends(get_workspace_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    A CI/CD pipeline step calls this right after a deploy completes. This
    is deliberately explicit rather than inferred from telemetry --
    reliably detecting "a deployment happened" from span/metric data
    alone isn't something Ghost Protocol attempts.
    """
    deployment = Deployment(
        workspace_id=workspace.id,
        service_name=payload.service_name,
        version=payload.version,
        notes=payload.notes,
        deployed_at=payload.deployed_at or datetime.now(timezone.utc),
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)
    return {"id": str(deployment.id), "service_name": deployment.service_name, "version": deployment.version,
            "deployed_at": deployment.deployed_at.isoformat()}
