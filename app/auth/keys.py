"""API key generation and hashing.

Key format: ``bss_<urlsafe-token>``. Only the SHA-256 hex digest is stored
in the database; the plaintext key is returned exactly once at creation.
A short, non-secret prefix is kept for identification and lookup support.
"""

import hashlib
import secrets

KEY_PREFIX = "bss"
PREFIX_LENGTH = 12


def generate_api_key() -> str:
    """Generate a new plaintext API key."""
    return f"{KEY_PREFIX}_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """Return the SHA-256 hex digest stored in the database."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str) -> str:
    """Return the non-secret display prefix of a key (e.g. ``bss_ab12cd34``)."""
    return key[:PREFIX_LENGTH]
