import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.cohort import CohortDimension
from app.models.workspace import Workspace

router = APIRouter()


class RegisterDimensionIn(BaseModel):
    attribute_key: str
    label: str


@router.post("/v1/cohort-dimensions", status_code=status.HTTP_201_CREATED)
async def register_dimension(
    payload: RegisterDimensionIn,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Registers a span attribute key Ghost should track for cohort
    comparison. Nothing else changes at ingestion -- if spans already
    carry this attribute (or start carrying it going forward), it
    becomes queryable via GET /v1/cohort-analysis immediately.
    """
    dimension = CohortDimension(workspace_id=workspace.id, attribute_key=payload.attribute_key, label=payload.label)
    db.add(dimension)
    await db.commit()
    await db.refresh(dimension)
    return {"id": str(dimension.id), "attribute_key": dimension.attribute_key, "label": dimension.label}


@router.get("/v1/cohort-dimensions")
async def list_dimensions(
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    dims = (await db.execute(
        select(CohortDimension).where(CohortDimension.workspace_id == workspace.id).order_by(CohortDimension.created_at)
    )).scalars().all()
    return [{"id": str(d.id), "attribute_key": d.attribute_key, "label": d.label} for d in dims]


@router.get("/v1/cohort-analysis")
async def cohort_analysis(
    caller: str,
    callee: str,
    dimension: str,
    window_minutes: int = 60,
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    On-demand comparison, independent of any open incident -- a company
    can check "how's the canary looking" any time, not just during an
    anomaly. `dimension` is the attribute_key (not the dimension's UUID),
    since that's what's actually on the spans.
    """
    # Async endpoint, but the analysis query itself uses the sync ORM
    # session shape (aliased self-join) -- run it against this request's
    # async session via the sync-style select, same pattern the rest of
    # the async routes use for straightforward queries.
    from app.cohort.analysis import run_cohort_analysis_async
    result = await run_cohort_analysis_async(db, workspace.id, caller, callee, dimension, window_minutes)
    return result.to_dict()