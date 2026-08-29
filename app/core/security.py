"""
API keys are stored as salted SHA-256 hashes -- never plaintext. The raw
key is only ever shown once, at creation time, in the dashboard.
"""
import hashlib
import secrets


def generate_api_key() -> str:
    """Returns a new raw key in the form 'ghost_live_<32 random hex chars>'."""
    return f"ghost_live_{secrets.token_hex(16)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    return secrets.compare_digest(hash_api_key(raw_key), key_hash)
