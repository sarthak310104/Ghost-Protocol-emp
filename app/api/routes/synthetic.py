"""
CRUD for registered synthetic checks, plus a status/results read
endpoint -- same route shape as app/api/routes/slos.py. Running checks
happens from app/synthetic/prober.run_due_checks, wired into the
/internal/tick handler, not from here: this module is registration and
read-only status, matching the pattern slos.py already sets (SLO
burn-rate checking itself lives in app/slo/alerts.py, not in the route
module).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.synthetic import SyntheticCheck, SyntheticCheckResult
from app.models.workspace import Workspace
from app.synthetic.prober import validate_check_url

router = APIRouter()


def _check_to_dict(check: SyntheticCheck) -> dict:
    return {
        "id": str(check.id),
        "name": check.name,
        "url": check.url,
        "method": check.method,
        "expected_status_min": check.expected_status_min,
        "expected_status_max": check.expected_status_max,
        "timeout_seconds": check.timeout_seconds,
        "interval_seconds": check.interval_seconds,
        "failure_threshold": check.failure_threshold,
        "created_at": check.created_at.isoformat(),
        "last_probed_at": check.last_probed_at.isoformat() if check.last_probed_at else None,
        "consecutive_failures": check.consecutive_failures,
        "failing": check.open_incident_id is not None,
        "open_incident_id": str(check.open_incident_id) if check.open_incident_id else None,
    }


@router.get("/v1/synthetic-checks")
async def list_synthetic_checks(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    checks = (
        await db.execute(select(SyntheticCheck).where(SyntheticCheck.workspace_id == workspace.id))
    ).scalars().all()
    return [_check_to_dict(c) for c in checks]


class CreateSyntheticCheckIn(BaseModel):
    name: str
    url: str
    method: str = "GET"
    expected_status_min: int = Field(default=200, ge=100, le=599)
    expected_status_max: int = Field(default=299, ge=100, le=599)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    failure_threshold: int = Field(default=2, ge=1, le=10)


@router.post("/v1/synthetic-checks")
async def create_synthetic_check(
    payload: CreateSyntheticCheckIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Rejects a URL that resolves to a link-local address (cloud metadata
    endpoints) before it's ever saved -- see app/synthetic/prober.py's
    module docstring for the threat-model reasoning. Every other
    target, including private/loopback ranges, is allowed: this is a
    self-hosted deployment, and probing a company's own internal
    service is the normal case, not an attack.
    """
    validation_error = validate_check_url(payload.url)
    if validation_error is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, validation_error)
    if payload.expected_status_min > payload.expected_status_max:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "expected_status_min must be <= expected_status_max")

    check = SyntheticCheck(
        workspace_id=workspace.id,
        name=payload.name,
        url=payload.url,
        method=payload.method.upper(),
        expected_status_min=payload.expected_status_min,
        expected_status_max=payload.expected_status_max,
        timeout_seconds=payload.timeout_seconds,
        interval_seconds=payload.interval_seconds,
        failure_threshold=payload.failure_threshold,
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    return _check_to_dict(check)


@router.delete("/v1/synthetic-checks/{check_id}")
async def delete_synthetic_check(
    check_id: str,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    check = (
        await db.execute(
            select(SyntheticCheck).where(
                SyntheticCheck.id == uuid.UUID(check_id), SyntheticCheck.workspace_id == workspace.id
            )
        )
    ).scalar_one_or_none()
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Synthetic check not found")

    await db.delete(check)
    await db.commit()
    return {"id": check_id, "deleted": True}


@router.get("/v1/synthetic-checks/{check_id}/results")
async def synthetic_check_results(
    check_id: str,
    limit: int = 50,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    check = (
        await db.execute(
            select(SyntheticCheck).where(
                SyntheticCheck.id == uuid.UUID(check_id), SyntheticCheck.workspace_id == workspace.id
            )
        )
    ).scalar_one_or_none()
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Synthetic check not found")

    results = (
        await db.execute(
            select(SyntheticCheckResult)
            .where(SyntheticCheckResult.check_id == check.id)
            .order_by(SyntheticCheckResult.ran_at.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "ran_at": r.ran_at.isoformat(),
            "success": r.success,
            "status_code": r.status_code,
            "latency_ms": r.latency_ms,
            "error": r.error,
        }
        for r in results
    ]