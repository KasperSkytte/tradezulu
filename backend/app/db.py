"""Database engine, session handling and first-run bootstrap."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .migrations import sync_schema
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


def _warn_if_admin_env_is_ignored(db: Session, existing: User | None) -> None:
    """Say plainly when TZ_ADMIN_USER cannot log in.

    The admin user is seeded once and then owned by the database, so editing
    the variable later has no effect. Silently ignoring it strands people on a
    login screen that only says the username is wrong, so name the mismatch
    and give the command that fixes it.
    """
    if existing is None or not settings.admin_username:
        return

    wanted = settings.admin_username
    if db.scalar(select(User).where(func.lower(User.username) == wanted.lower())):
        return

    names = ", ".join(sorted(user.username for user in db.scalars(select(User))))
    log.warning(
        "TZ_ADMIN_USER is %r but this database has no such user (it has: %s). "
        "The admin user is only created on the first start, so changing the "
        "variable afterwards has no effect. To take over that name, run: "
        "docker compose exec tradezulu set-password --username %s "
        "--rename-from %s --password '<new password>'",
        wanted,
        names,
        wanted,
        names.split(", ")[0],
    )


def init_db() -> None:
    """Create tables and seed the first user, default account and tag list."""
    sqlite_path = settings.sqlite_path
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)

    # create_all leaves existing tables untouched, so a release that adds a
    # column has to reconcile them itself or every upgrade breaks on startup.
    for change in sync_schema(engine):
        log.info("Schema: added %s", change)

    from .security import hash_password  # imported late to avoid a cycle

    with SessionLocal() as db:
        user = db.scalar(select(User).limit(1))
        _warn_if_admin_env_is_ignored(db, user)
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
