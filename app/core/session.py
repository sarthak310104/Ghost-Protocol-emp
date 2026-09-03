"""
Browser session tokens, distinct from the bearer API keys used for
ingestion. Deliberately not a DB-backed session table -- a Fernet token
already carries its own creation timestamp and supports TTL-based
expiry natively (`Fernet.decrypt(token, ttl=seconds)`), so a signed,
self-contained cookie is enough and reuses crypto infra that already
exists in this codebase rather than adding a new dependency or table
just for sessions.

The cookie holds nothing but the workspace_id -- no permissions, no
user identity beyond "this browser proved it had a valid API key for
this workspace at login time." That's deliberately all a session needs
to carry, matching the platform's existing workspace-is-the-tenant
model rather than introducing a separate user/account concept.

One real tradeoff of a stateless signed token: it can't be revoked
before its own expiry just by deleting a server-side record, since
there is no server-side record. A stolen token would stay valid for up
to _SESSION_TTL_SECONDS even after the legitimate user "logs out" on
their own browser. To close that gap, logout adds the token's hash to
a short Redis denylist (see revoke_session_token / is_session_revoked)
-- this reintroduces a small amount of server-side state, but only for
the "has this specific token been explicitly logged out" question, not
for session validity in general.
"""
import hashlib

from app.core.crypto import _fernet
from app.core.redis_client import get_redis

_SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours
_REVOCATION_PREFIX = "revoked_session:"


def create_session_token(workspace_id: str) -> str:
    return _fernet().encrypt(workspace_id.encode("utf-8")).decode("utf-8")


def read_session_token(token: str) -> str | None:
    """Returns the workspace_id if the token is valid and unexpired, else None."""
    try:
        return _fernet().decrypt(token.encode("utf-8"), ttl=_SESSION_TTL_SECONDS).decode("utf-8")
    except Exception:
        return None


def _token_key(token: str) -> str:
    # Store a hash of the token, not the token itself -- no reason for
    # Redis (or anyone with read access to it) to hold live session
    # credentials in plaintext, even in a denylist.
    return _REVOCATION_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


async def revoke_session_token(token: str) -> None:
    await get_redis().set(_token_key(token), "1", ex=_SESSION_TTL_SECONDS)


async def is_session_revoked(token: str) -> bool:
    return bool(await get_redis().exists(_token_key(token)))