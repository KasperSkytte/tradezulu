"""Encryption for the few secrets TradeZulu has to keep at rest.

Only the MetaTrader credentials need this. The key is derived from
``TZ_SECRET_KEY``, so rotating that key makes stored credentials unreadable —
which is the correct behaviour: you re-enter them, you do not silently keep
using a secret protected by a key you no longer trust.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings

_PREFIX = "tzv1:"
_NONCE_BYTES = 12


def _key() -> bytes:
    """A stable 256-bit key derived from the application secret."""
    return hashlib.blake2b(
        settings.secret_key.encode("utf-8"),
        digest_size=32,
        person=b"tradezulu-creds",
    ).digest()


def encrypt(plaintext: str) -> str:
    """Return ``tzv1:<base64(nonce||ciphertext)>``."""
    if not plaintext:
        return ""
    nonce = os.urandom(_NONCE_BYTES)
    blob = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + blob).decode("ascii")


def decrypt(token: str) -> str:
    """Reverse :func:`encrypt`. Returns "" when the value cannot be read."""
    if not token:
        return ""
    if not token.startswith(_PREFIX):
        # Written before encryption existed, or hand-edited. Take it as-is.
        return token
    try:
        raw = base64.b64decode(token[len(_PREFIX) :])
        nonce, blob = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        return AESGCM(_key()).decrypt(nonce, blob, None).decode("utf-8")
    except (ValueError, InvalidTag, UnicodeDecodeError):
        # Wrong key (TZ_SECRET_KEY changed) or corrupt value.
        return ""


def is_readable(token: str) -> bool:
    """Whether a stored secret can still be decrypted with the current key."""
    return bool(token) and bool(decrypt(token))
