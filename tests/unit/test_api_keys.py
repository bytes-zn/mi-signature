"""Tests for API key generation and hashing."""

from app.auth.keys import PREFIX_LENGTH, generate_api_key, hash_api_key, key_prefix


def test_generate_api_key_format() -> None:
    key = generate_api_key()
    assert key.startswith("bss_")
    assert len(key) > 20


def test_generate_api_key_is_unique() -> None:
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_hash_api_key_is_deterministic() -> None:
    key = generate_api_key()
    assert hash_api_key(key) == hash_api_key(key)
    assert len(hash_api_key(key)) == 64
    assert hash_api_key(key) != key


def test_key_prefix() -> None:
    key = generate_api_key()
    prefix = key_prefix(key)
    assert prefix == key[:PREFIX_LENGTH]
    assert prefix.startswith("bss_")
