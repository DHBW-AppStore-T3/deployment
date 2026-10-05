"""Tests for the shared Fernet wrapper."""

from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from appstore_shared.crypto import InvalidToken, build_cipher


@pytest.fixture
def cipher():
    return build_cipher(Fernet.generate_key().decode())


def test_roundtrip(cipher) -> None:
    token = cipher.encrypt("héllo wörld 🚀")
    assert isinstance(token, bytes)
    assert cipher.decrypt(token) == "héllo wörld 🚀"


def test_b64_roundtrip_is_ascii(cipher) -> None:
    token_b64 = cipher.encrypt_b64("payload")
    base64.b64decode(token_b64.encode("ascii"))
    assert cipher.decrypt_b64(token_b64) == "payload"


def test_tampered_token_is_rejected(cipher) -> None:
    token = bytearray(cipher.encrypt("payload"))
    token[len(token) // 2] ^= 0xFF
    with pytest.raises(InvalidToken):
        cipher.decrypt(bytes(token))


def test_other_key_cannot_decrypt(cipher) -> None:
    other = build_cipher(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        other.decrypt(cipher.encrypt("payload"))


@pytest.mark.parametrize("key", ["", None])
def test_missing_key_names_the_variable_and_the_fix(key) -> None:
    with pytest.raises(RuntimeError) as exc:
        build_cipher(key)
    assert "CREDENTIAL_ENCRYPTION_KEY" in str(exc.value)
    assert "Fernet.generate_key" in str(exc.value)


def test_malformed_key_is_reported() -> None:
    with pytest.raises(RuntimeError, match="malformed"):
        build_cipher("not-a-valid-key")


def test_key_rotation_decrypts_old_and_encrypts_with_the_first_key() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = build_cipher(old).encrypt("secret")

    rotated = build_cipher(f"{new}, {old}")

    assert rotated.decrypt(stored) == "secret"
    assert build_cipher(new).decrypt(rotated.encrypt("fresh")) == "fresh"
