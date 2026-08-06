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


#: Set once the stored trade_date values have been rebuilt under the corrected
#: day boundary. A marker rather than a version check: it is a data repair, it
#: has to happen exactly once, and it must not run again on every boot.
DAY_REPAIR_KEY = "trading_days_rebuilt"


def _refile_trading_days(db: Session) -> None:
    """Rebuild which day each stored trade belongs to, once.

    Trade dates were computed by reading MetaTrader's timestamps as UTC and
    converting them to the configured timezone. They are the broker's clock,
    so that was one conversion too many: on a broker three hours ahead with the
    journal set to Copenhagen, everything after 22:00 was filed on the next
    day, and the calendar, the daily P&L and every "by day" figure inherited
    it.

    Nothing else about a trade changes -- this recomputes the same fields the
    settings page already recomputes on demand -- but it has to happen without
    being asked, because the wrong dates are already stored and nobody would
    know to ask.
    """
    from .models import Setting
    from .services.aggregation import recompute_all
    from .services.appsettings import get_app_settings

    if db.get(Setting, DAY_REPAIR_KEY) is not None:
        return

    config = get_app_settings(db)
    count = recompute_all(
        db,
        config["risk"],
        config["general"]["timezone"],
        config["general"].get("times", "broker"),
    )
    db.add(Setting(key=DAY_REPAIR_KEY, value={"trades": count}))
    db.commit()
    if count:
        log.info("Refiled %d trades onto the corrected trading day", count)


#: Set once trades already stored have been checked for a missing stop.
STOP_TAG_KEY = "unprotected_trades_tagged"


def _tag_unprotected_trades(db: Session) -> None:
    """Put the no-stop tag on trades that arrived before it existed, once.

    New trades are tagged as they are folded, but a journal is mostly history
    by the time anybody wants to search it, and going back through several
    hundred trades looking for an empty stop field is exactly the work the tag
    is meant to save.
    """
    from .models import Setting, Trade
    from .services.aggregation import tag_if_unprotected

    if db.get(Setting, STOP_TAG_KEY) is not None:
        return

    trades = list(db.scalars(select(Trade).where(Trade.closed_at.is_not(None))).all())
    before = sum(len(trade.tags) for trade in trades)
    for trade in trades:
        tag_if_unprotected(db, trade)
    tagged = sum(len(trade.tags) for trade in trades) - before

    db.add(Setting(key=STOP_TAG_KEY, value={"tagged": tagged}))
    db.commit()
    if tagged:
        log.info("Tagged %d trade(s) that were opened without a stop", tagged)


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
                    # Explicit, because everywhere else that creates an account
                    # now says "slave" and this is the one that really is the
                    # master-to-be: the first credentials entered adopt it.
                    role="master",
                )
            )
            log.info("Created placeholder default account")

        db.commit()
        _refile_trading_days(db)
        _tag_unprotected_trades(db)
