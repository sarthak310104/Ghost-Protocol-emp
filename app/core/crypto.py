"""
BYO-tier customers give us their own LLM API key so we can call it on
their behalf; that key is encrypted at rest with a server-side secret
(never logged, never returned by any API response). Fernet (symmetric,
authenticated) is deliberately simple here -- this is protecting one
credential per workspace, not building a KMS.
"""
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.ghost_secret_key:
        raise RuntimeError("GHOST_SECRET_KEY must be set to store BYO reasoning-provider credentials.")
    return Fernet(settings.ghost_secret_key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
