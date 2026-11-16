"""Generate the secrets required for a production deployment.

Usage::

    python scripts/generate_secrets.py

Prints ready-to-use values for ``OPERATOR_API_KEY`` and
``SECRET_ENCRYPTION_KEY``. The encryption key cannot be recovered - if it
is lost, the stored tenant secrets cannot be decrypted any more.
"""

import base64
import os
import secrets

OPERATOR_KEY_PREFIX = "bss_op_"
KEY_BYTES = 32


def generate_operator_key() -> str:
    """Return a new random operator API key."""
    return f"{OPERATOR_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_encryption_key() -> str:
    """Return a new base64-encoded master key for secret encryption."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii").rstrip("=")


def main() -> None:
    """Print the generated secrets."""
    print(f"OPERATOR_API_KEY={generate_operator_key()}")
    print(f"SECRET_ENCRYPTION_KEY={generate_encryption_key()}")
    print(f"REDIS_PASSWORD={secrets.token_urlsafe(24)}")
    print(f"METRICS_TOKEN={secrets.token_urlsafe(24)}")


if __name__ == "__main__":
    main()
