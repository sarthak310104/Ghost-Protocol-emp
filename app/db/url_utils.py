"""
Both Alembic (alembic/env.py) and the sync Celery-task session
(app/db/sync_session.py) need a psycopg2-compatible connection string
derived from the app's real DATABASE_URL, which is written for the
runtime asyncpg engine. This exists in one place because the same bug
(asyncpg wants `ssl=require`, psycopg2 wants `sslmode=require` -- same
underlying requirement, incompatible query-param name) showed up
independently in both of those files before this was factored out.
Fixing it twice in two places is exactly how it would have silently
drifted back out of sync the next time either file changed.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def to_psycopg2_sync_url(database_url: str) -> str:
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

    parts = urlsplit(sync_url)
    query = dict(parse_qsl(parts.query))
    if "ssl" in query:
        query["sslmode"] = query.pop("ssl")
    return urlunsplit(parts._replace(query=urlencode(query)))
