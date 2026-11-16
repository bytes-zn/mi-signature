"""Custom SQLAlchemy column types."""

from typing import Any

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt_secret, encrypt_secret


class EncryptedString(TypeDecorator[str]):
    """A string column whose value is encrypted at rest.

    The database only ever sees ciphertext; the value is encrypted on write
    and decrypted on read. Legacy plaintext rows stay readable - the
    decryption helper returns values without the ciphertext prefix unchanged.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512) -> None:
        super().__init__(length=length)

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return encrypt_secret(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return decrypt_secret(str(value))
