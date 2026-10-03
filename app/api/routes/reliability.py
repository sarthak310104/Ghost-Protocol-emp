from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_workspace_from_session_or_key
from app.db.session import get_db
from app.models.workspace import Workspace
from app.reliability.trends import compute_reliability_trends_async

router = APIRouter()


@router.get("/v1/reliability-trends")
async def reliability_trends(
    weeks: int = Query(default=12, ge=1, le=52),
    workspace: Workspace = Depends(get_workspace_from_session_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Per-service incident frequency and MTTR over a rolling weekly
    lookback -- see app/reliability/trends.py for why this deliberately
    stops short of an uptime percentage.
    """
    trends = await compute_reliability_trends_async(db, workspace.id, weeks=weeks)
    return [t.to_dict() for t in trends]