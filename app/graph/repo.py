import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.graph import ServiceEdge, ServiceNode


def get_or_create_node(db: Session, workspace_id: uuid.UUID, name: str) -> ServiceNode:
    node = db.execute(
        select(ServiceNode).where(ServiceNode.workspace_id == workspace_id, ServiceNode.name == name)
    ).scalar_one_or_none()
    if node is None:
        node = ServiceNode(workspace_id=workspace_id, name=name)
        try:
            # Savepoint, not the outer transaction: a plain db.add()
            # + db.flush() here would poison the whole transaction on
            # a unique-violation (every statement after an aborted
            # Postgres transaction fails until rollback), which would
            # also undo this same call's edge/baseline work below it.
            # The savepoint confines the race's blast radius to just
            # this insert attempt.
            with db.begin_nested():
                db.add(node)
                db.flush()
        except IntegrityError:
            # Two concurrent batches can both select "no row for this
            # (workspace_id, name)" before either commits, then both
            # try to insert -- the loser hits uq_service_workspace_name
            # here rather than a lock-order deadlock (sorting the
            # caller's iteration order, see update_graph_and_baselines,
            # fixes deadlocks on *existing* rows but can't fix a race
            # between two first-time creates of the same new row).
            # The savepoint rollback above already discarded our failed
            # insert; re-select picks up whichever row actually won.
            node = db.execute(
                select(ServiceNode).where(ServiceNode.workspace_id == workspace_id, ServiceNode.name == name)
            ).scalar_one()
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
        try:
            # Same race as get_or_create_node above, against
            # uq_edge_workspace_pair instead.
            with db.begin_nested():
                db.add(edge)
                db.flush()
        except IntegrityError:
            edge = db.execute(
                select(ServiceEdge).where(
                    ServiceEdge.workspace_id == workspace_id,
                    ServiceEdge.caller == caller,
                    ServiceEdge.callee == callee,
                )
            ).scalar_one()
    return edge