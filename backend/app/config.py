"""Runtime configuration for TradeZulu, sourced from environment variables."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    """Process-wide settings. Everything user-facing lives in the DB instead."""

    def __init__(self) -> None:
        self.app_name: str = "TradeZulu"
        self.version: str = os.getenv("TZ_VERSION", "0.0.0-dev")

        # Where the SQLite database and uploaded files live.
        self.data_dir: Path = Path(os.getenv("TZ_DATA_DIR", "./data")).resolve()
        self.database_url: str = os.getenv(
            "TZ_DATABASE_URL", f"sqlite:///{self.data_dir / 'tradezulu.db'}"
        )

        # Directory holding the compiled frontend (index.html, assets/...).
        static_dir = os.getenv("TZ_STATIC_DIR", "")
        self.static_dir: Path | None = Path(static_dir).resolve() if static_dir else None

        # Auth ------------------------------------------------------------
        self.secret_key: str = os.getenv("TZ_SECRET_KEY", "").strip()
        self.secret_key_is_ephemeral = not self.secret_key
        if self.secret_key_is_ephemeral:
            # Sessions will not survive a restart, which is acceptable for a
            # first run but loudly warned about at startup.
            self.secret_key = secrets.token_urlsafe(48)

        self.admin_username: str = os.getenv("TZ_ADMIN_USER", "admin").strip() or "admin"
        self.admin_password: str = os.getenv("TZ_ADMIN_PASSWORD", "").strip()
        self.session_days: int = _env_int("TZ_SESSION_DAYS", 30)
        self.cookie_name: str = "tz_session"
        self.cookie_secure: bool = _env_bool("TZ_COOKIE_SECURE", False)
        self.login_max_attempts: int = _env_int("TZ_LOGIN_MAX_ATTEMPTS", 10)
        self.login_lockout_seconds: int = _env_int("TZ_LOGIN_LOCKOUT_SECONDS", 300)
        # Lowered only by the test suite; 12 is the sensible production value.
        self.bcrypt_rounds: int = max(4, min(16, _env_int("TZ_BCRYPT_ROUNDS", 12)))

        # MT5 ------------------------------------------------------------
        # Expert Advisors authenticate with this key instead of a session cookie.
        self.ingest_token: str = os.getenv("TZ_INGEST_TOKEN", "").strip()
        # Shared secret for the bridge container, which lives on the internal
        # compose network and is never published.
        self.bridge_token: str = os.getenv("TZ_BRIDGE_TOKEN", "").strip()

        # Misc ------------------------------------------------------------
        self.cors_origins: list[str] = [
            o.strip() for o in os.getenv("TZ_CORS_ORIGINS", "").split(",") if o.strip()
        ]
        self.demo_mode: bool = _env_bool("TZ_DEMO", False)
        self.log_level: str = os.getenv("TZ_LOG_LEVEL", "INFO").upper()

    @property
    def sqlite_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url[len("sqlite:///") :])
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
