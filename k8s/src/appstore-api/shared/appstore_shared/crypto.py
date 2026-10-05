"""Symmetric encryption shared by the API and the worker.

Both processes hold the same Fernet key (``CREDENTIAL_ENCRYPTION_KEY``): the API
encrypts what it stores, the worker decrypts what it needs for a job. The logic
lives here once so the two copies the original project kept "in step by hand"
cannot drift; each process only decides where its key comes from.

Key rotation: the setting takes a comma-separated list. The first key encrypts,
every key decrypts (``MultiFernet``). Rotate by putting a new key in front,
rolling out, and dropping the old one once nothing encrypted with it is left.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

GENERATE_HINT = (
    "Generate one with: python -c 'from cryptography.fernet import Fernet; "
    "print(Fernet.generate_key().decode())'"
)


class Cipher:
    """Encrypts strings to Fernet tokens and back."""

    def __init__(self, fernet: Fernet | MultiFernet) -> None:
        self._fernet = fernet

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a string. Returns Fernet ciphertext as bytes (store as BYTEA)."""
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        """Decrypt Fernet ciphertext. Raises InvalidToken on tampering or a wrong key."""
        return self._fernet.decrypt(token).decode("utf-8")

    def encrypt_b64(self, plaintext: str) -> str:
        """Encrypt and base64-encode, for transport inside JSON."""
        return base64.b64encode(self.encrypt(plaintext)).decode("ascii")

    def decrypt_b64(self, token_b64: str) -> str:
        """Inverse of :meth:`encrypt_b64`. Raises InvalidToken on bad input."""
        return self.decrypt(base64.b64decode(token_b64.encode("ascii")))


def build_cipher(key: str | bytes | None) -> Cipher:
    """Build a cipher from the configured key, failing loudly when it is unusable.

    A RuntimeError at start-up is the point: a process that cannot decrypt would
    otherwise only notice on the first credential it touches.
    """
    if not key:
        raise RuntimeError(f"CREDENTIAL_ENCRYPTION_KEY is not set. {GENERATE_HINT}")
    text = key.decode() if isinstance(key, bytes) else key
    keys = [k.strip() for k in text.split(",") if k.strip()]
    if not keys:
        raise RuntimeError(f"CREDENTIAL_ENCRYPTION_KEY is not set. {GENERATE_HINT}")
    try:
        # Fernet validates the 32-byte url-safe-base64 key shape itself.
        return Cipher(MultiFernet([Fernet(k.encode()) for k in keys]))
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"CREDENTIAL_ENCRYPTION_KEY is malformed: {e}") from e


__all__ = ["Cipher", "build_cipher", "InvalidToken", "GENERATE_HINT"]
