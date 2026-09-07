from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.url_utils import to_psycopg2_sync_url

settings = get_settings()

# Celery workers run sync code, so they get a separate sync engine/driver
# (psycopg2) rather than reusing the asyncpg engine FastAPI uses. Both
# point at the same database.
_sync_url = to_psycopg2_sync_url(settings.database_url)

sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, class_=Session)
