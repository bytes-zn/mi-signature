"""Authenticated encryption for tenant secrets stored in the database.

Tenant credentials (currently the Entra ID client secret) are stored in
PostgreSQL. This module encrypts them at rest so that a database dump,
a backup or a stolen disk does not hand out usable Microsoft credentials.

The construction is a stream cipher (HMAC-SHA256 in counter mode) combined
with encrypt-then-MAC. It uses the Python standard library only, so no
additional dependency is pulled into the runtime image.

Ciphertext format::

    enc:v1:<base64url(nonce)>:<base64url(ciphertext)>:<base64url(tag)>

Values without the ``enc:v1:`` prefix are treated as legacy plaintext and
returned unchanged - that keeps existing deployments readable until the
data migration has run.
"""

import base64
import hashlib
import hmac
import os
import struct
from functools import lru_cache

import structlog

from app.config.settings import get_settings

logger = structlog.get_logger(__name__)

ENCRYPTED_PREFIX = "enc:v1:"
_NONCE_BYTES = 16
_TAG_BYTES = 16
_BLOCK_SIZE = 32
_KEY_BYTES = 32

#: Associated data binding a ciphertext to this application and version.
_AAD = b"mi-signature:secret:v1"

#: Fallback key material used when no SECRET_ENCRYPTION_KEY is configured.
#: Only ever active outside production - the production baseline refuses to
#: start without a real key.
_DEVELOPMENT_KEY_MATERIAL = b"mi-signature:insecure-development-key-do-not-use"


class DecryptionError(ValueError):
    """Raised when a ciphertext cannot be authenticated or decrypted."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def is_encrypted(value: str) -> bool:
    """True when the value is a ciphertext produced by this module."""
    return value.startswith(ENCRYPTED_PREFIX)


def generate_master_key() -> str:
    """Return a new base64-encoded master key for ``SECRET_ENCRYPTION_KEY``."""
    return _b64encode(os.urandom(_KEY_BYTES))


class SecretCipher:
    """Encrypts and decrypts short secrets with a master key."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) < _KEY_BYTES:
            raise ValueError(f"Master key must be at least {_KEY_BYTES} bytes long.")
        self._enc_key = hmac.new(master_key, b"mi-signature:enc:v1", hashlib.sha256).digest()
        self._mac_key = hmac.new(master_key, b"mi-signature:mac:v1", hashlib.sha256).digest()

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hmac.new(
                self._enc_key, nonce + struct.pack(">I", counter), hashlib.sha256
            ).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string into a self-describing ciphertext."""
        nonce = os.urandom(_NONCE_BYTES)
        raw = plaintext.encode("utf-8")
        stream = self._keystream(nonce, len(raw))
        ciphertext = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
        tag = hmac.new(self._mac_key, _AAD + nonce + ciphertext, hashlib.sha256).digest()
        return (
            f"{ENCRYPTED_PREFIX}{_b64encode(nonce)}:"
            f"{_b64encode(ciphertext)}:{_b64encode(tag[:_TAG_BYTES])}"
        )

    def decrypt(self, token: str) -> str:
        """Decrypt a ciphertext; legacy plaintext is returned unchanged."""
        if not is_encrypted(token):
            return token

        body = token[len(ENCRYPTED_PREFIX) :]
        parts = body.split(":")
        if len(parts) != 3:
            raise DecryptionError("Malformed secret ciphertext.")

        nonce = _b64decode(parts[0])
        ciphertext = _b64decode(parts[1])
        tag = _b64decode(parts[2])

        expected = hmac.new(self._mac_key, _AAD + nonce + ciphertext, hashlib.sha256).digest()[
            :_TAG_BYTES
        ]
        if not hmac.compare_digest(expected, tag):
            raise DecryptionError("Secret ciphertext failed authentication.")

        stream = self._keystream(nonce, len(ciphertext))
        plain = bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True))
        return plain.decode("utf-8")


def _master_key_from_settings() -> bytes:
    """Return the configured master key, or the development fallback."""
    settings = get_settings()
    raw = settings.secret_encryption_key
    if not raw:
        logger.warning(
            "secret_encryption_key_missing",
            detail=(
                "SECRET_ENCRYPTION_KEY is not configured - falling back to the "
                "insecure development key. Never do this in production."
            ),
        )
        return hashlib.sha256(_DEVELOPMENT_KEY_MATERIAL).digest()

    try:
        key = _b64decode(raw)
    except Exception as exc:  # noqa: BLE001 - configuration error
        raise ValueError(
            "SECRET_ENCRYPTION_KEY must be a base64-encoded key of at least " f"{_KEY_BYTES} bytes."
        ) from exc
    if len(key) < _KEY_BYTES:
        raise ValueError(f"SECRET_ENCRYPTION_KEY must decode to at least {_KEY_BYTES} bytes.")
    return key


@lru_cache
def get_cipher() -> SecretCipher:
    """Return the process-wide cipher instance."""
    return SecretCipher(_master_key_from_settings())


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt a secret value (``None`` passes through)."""
    if value is None:
        return None
    return get_cipher().encrypt(value)


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a secret value; legacy plaintext passes through unchanged."""
    if value is None:
        return None
    return get_cipher().decrypt(value)
