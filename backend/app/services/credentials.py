"""Storage for the MetaTrader 5 account a terminal is logged into.

Kept out of the main settings document on purpose: that document is returned
to the browser wholesale, and the password must never be part of it. The
password is encrypted at rest and leaves this process exactly once -- to the
provisioner, which starts a terminal with it and then removes its copy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting
from .crypto import decrypt, encrypt, is_readable

CREDENTIALS_KEY = "mt5_credentials"


def get_credentials(db: Session) -> dict[str, str]:
    """The stored credentials, decrypted. Empty strings when unset."""
    row = db.get(Setting, CREDENTIALS_KEY)
    stored: dict[str, Any] = row.value if row and isinstance(row.value, dict) else {}
    return {
        "server": str(stored.get("server") or ""),
        "login": str(stored.get("login") or ""),
        "password": decrypt(str(stored.get("password") or "")),
    }


def save_credentials(db: Session, server: str, login: str, password: str | None) -> None:
    """Store credentials. ``password=None`` keeps the existing one."""
    row = db.get(Setting, CREDENTIALS_KEY)
    stored: dict[str, Any] = dict(row.value) if row and isinstance(row.value, dict) else {}

    stored["server"] = server.strip()
    stored["login"] = login.strip()
    if password is not None:
        stored["password"] = encrypt(password) if password else ""

    if row is None:
        db.add(Setting(key=CREDENTIALS_KEY, value=stored))
    else:
        row.value = stored
    db.flush()


def clear_credentials(db: Session) -> None:
    row = db.get(Setting, CREDENTIALS_KEY)
    if row is not None:
        db.delete(row)
        db.flush()


def credentials_status(db: Session) -> dict[str, Any]:
    """What the UI is allowed to know: everything except the password."""
    row = db.get(Setting, CREDENTIALS_KEY)
    stored: dict[str, Any] = row.value if row and isinstance(row.value, dict) else {}
    encrypted = str(stored.get("password") or "")
    return {
        "configured": bool(stored.get("login") and stored.get("server") and encrypted),
        "server": str(stored.get("server") or ""),
        "login": str(stored.get("login") or ""),
        # False when TZ_SECRET_KEY changed since the password was saved.
        "password_readable": is_readable(encrypted),
    }
