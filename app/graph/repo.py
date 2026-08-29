import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.graph import ServiceEdge, ServiceNode


def get_or_create_node(db: Session, workspace_id: uuid.UUID, name: str) -> ServiceNode:
    node = db.execute(
        select(ServiceNode).where(ServiceNode.workspace_id == workspace_id, ServiceNode.name == name)
    ).scalar_one_or_none()
    if node is None:
        node = ServiceNode(workspace_id=workspace_id, name=name)
        db.add(node)
        db.flush()
    else:
        node.last_seen_at = datetime.now(timezone.utc)
    return node


def get_or_create_edge(db: Session, workspace_id: uuid.UUID, caller: str, callee: str) -> ServiceEdge:
    edge = db.execute(
        select(ServiceEdge).where(
            ServiceEdge.workspace_id == workspace_id,
            ServiceEdge.caller == caller,
            ServiceEdge.callee == callee,
        )
    ).scalar_one_or_none()
    if edge is None:
        edge = ServiceEdge(workspace_id=workspace_id, caller=caller, callee=callee)
        db.add(edge)
        db.flush()
    return edge
