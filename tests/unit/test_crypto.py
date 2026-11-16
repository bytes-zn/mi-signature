"""Tests for the encryption of tenant secrets at rest."""

import base64

import pytest

from app.core.crypto import (
    DecryptionError,
    SecretCipher,
    decrypt_secret,
    encrypt_secret,
    generate_master_key,
    is_encrypted,
)


def _master_key() -> bytes:
    """Return a fresh 32-byte master key."""
    encoded = generate_master_key()
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))


def test_encrypt_decrypt_round_trip() -> None:
    cipher = SecretCipher(_master_key())
    token = cipher.encrypt("super-secret-value")

    assert token != "super-secret-value"
    assert is_encrypted(token)
    assert cipher.decrypt(token) == "super-secret-value"


def test_ciphertext_is_not_deterministic() -> None:
    cipher = SecretCipher(_master_key())

    first = cipher.encrypt("same-value")
    second = cipher.encrypt("same-value")

    assert first != second
    assert cipher.decrypt(first) == cipher.decrypt(second) == "same-value"


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = SecretCipher(_master_key())
    token = cipher.encrypt("super-secret-value")

    prefix, _, rest = token.split(":", 2)
    nonce, payload, tag = rest.split(":")
    tampered = f"{prefix}:v1:{nonce}:{payload[:-2]}XY:{tag}"

    with pytest.raises(DecryptionError):
        cipher.decrypt(tampered)


def test_wrong_key_cannot_decrypt() -> None:
    token = SecretCipher(_master_key()).encrypt("super-secret-value")

    with pytest.raises(DecryptionError):
        SecretCipher(_master_key()).decrypt(token)


def test_legacy_plaintext_is_returned_unchanged() -> None:
    cipher = SecretCipher(_master_key())

    assert cipher.decrypt("plain-legacy-value") == "plain-legacy-value"
    assert not is_encrypted("plain-legacy-value")


def test_malformed_ciphertext_is_rejected() -> None:
    cipher = SecretCipher(_master_key())

    with pytest.raises(DecryptionError):
        cipher.decrypt("enc:v1:not-base64")


def test_short_master_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        SecretCipher(b"too-short")


def test_helpers_pass_none_through() -> None:
    assert encrypt_secret(None) is None
    assert decrypt_secret(None) is None


def test_generated_master_key_has_expected_length() -> None:
    assert len(_master_key()) == 32
