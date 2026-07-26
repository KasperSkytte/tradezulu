"""Database engine, session handling and first-run bootstrap."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Account, Base, Tag, User
from .services.appsettings import DEFAULT_TAGS

log = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine: Engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver level
    """WAL keeps reads fast while the sync writes, and FKs must be asked for."""
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables and seed the first user, default account and tag list."""
    sqlite_path = settings.sqlite_path
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)

    from .security import hash_password  # imported late to avoid a cycle

    with SessionLocal() as db:
        user = db.scalar(select(User).limit(1))
        if user is None:
            password = settings.admin_password
            if not password:
                raise RuntimeError(
                    "No user exists yet and TZ_ADMIN_PASSWORD is not set. "
                    "Set TZ_ADMIN_PASSWORD (and TZ_ADMIN_USER) and start again."
                )
            db.add(
                User(username=settings.admin_username, password_hash=hash_password(password))
            )
            log.info("Created initial user %r", settings.admin_username)

        if db.scalar(select(Tag).limit(1)) is None:
            for order, tag in enumerate(DEFAULT_TAGS):
                db.add(Tag(sort_order=order, **tag))
            log.info("Seeded %d default tags", len(DEFAULT_TAGS))

        if db.scalar(select(Account).limit(1)) is None:
            db.add(
                Account(
                    login="0",
                    name="Default account",
                    server="",
                    currency="USD",
                    is_default=True,
                )
            )
            log.info("Created placeholder default account")

        db.commit()
