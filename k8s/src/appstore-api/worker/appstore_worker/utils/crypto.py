"""Fernet encryption with this process's key.

The logic lives in :mod:`appstore_shared.crypto`; this module only binds it to
``settings.CREDENTIAL_ENCRYPTION_KEY`` at import time, so a missing or malformed
key stops the process at start-up instead of at the first credential it touches.
"""

from __future__ import annotations

from appstore_shared.crypto import InvalidToken, build_cipher
from appstore_worker.config import settings

_cipher = build_cipher(settings.CREDENTIAL_ENCRYPTION_KEY)
# For code that takes a Cipher (e.g. appstore_shared.jobs).
cipher = _cipher

encrypt = _cipher.encrypt
decrypt = _cipher.decrypt
encrypt_b64 = _cipher.encrypt_b64
decrypt_b64 = _cipher.decrypt_b64

__all__ = ["cipher", "encrypt", "decrypt", "encrypt_b64", "decrypt_b64", "InvalidToken"]
