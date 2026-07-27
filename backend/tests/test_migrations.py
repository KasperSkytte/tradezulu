"""Upgrading a database that already holds data.

``create_all`` never touches a table that exists, so without this reconciling
step every release that adds a column breaks existing installations on the
next start. These tests build a database at an older shape, on purpose, and
check that it heals without losing anything.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import Session

from app.migrations import sync_schema
from app.models import Account, Base


@pytest.fixture()
def old_engine():
    """A database holding the `account` table as it looked before the copier."""
    directory = Path(tempfile.mkdtemp(prefix="tz-migration-"))
    engine = create_engine(f"sqlite:///{directory / 'old.db'}")

    metadata = MetaData()
    Table(
        "account",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("login", String(64), nullable=False),
        Column("name", String(120), default=""),
        Column("server", String(120), default=""),
        Column("balance", Integer, default=0),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO account (login, name, server, balance) "
                "VALUES ('5000123', 'Live', 'ICMarketsSC-Live12', 25000)"
            )
        )
    yield engine
    engine.dispose()


def columns(engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {column["name"] for column in inspect(connection).get_columns(table)}


class TestAddingColumns:
    def test_the_missing_columns_appear(self, old_engine):
        assert "role" not in columns(old_engine, "account")

        sync_schema(old_engine)

        present = columns(old_engine, "account")
        for name in ("role", "copy_enabled", "copy_settings", "peak_equity"):
            assert name in present

    def test_it_reports_what_it_changed(self, old_engine):
        changes = sync_schema(old_engine)
        assert "account.role" in changes
        assert any(change.startswith("index ") for change in changes)

    def test_existing_rows_survive(self, old_engine):
        sync_schema(old_engine)

        with engine_session(old_engine) as session:
            account = session.scalar(select(Account))
            assert account is not None
            assert account.login == "5000123"
            assert account.name == "Live"
            assert account.server == "ICMarketsSC-Live12"
            assert account.balance == 25000

    def test_existing_rows_get_the_models_default(self, old_engine):
        """An account that predates the copier is the master, not a slave."""
        sync_schema(old_engine)

        with engine_session(old_engine) as session:
            account = session.scalar(select(Account))
            assert account.role == "master"
            # And nothing is armed by the mere act of upgrading.
            assert account.copy_enabled is False
            assert account.copy_dry_run is True

    def test_not_null_json_columns_get_a_usable_value(self, old_engine):
        sync_schema(old_engine)

        with engine_session(old_engine) as session:
            account = session.scalar(select(Account))
            assert account.copy_settings == {}
            assert account.symbol_map == {}

    def test_the_healed_table_accepts_writes(self, old_engine):
        sync_schema(old_engine)

        with engine_session(old_engine) as session:
            session.add(Account(login="777", name="Prop", role="slave"))
            session.commit()
            assert session.scalar(select(Account).where(Account.login == "777")) is not None


class TestNewTables:
    def test_tables_added_since_are_created(self, old_engine):
        Base.metadata.create_all(old_engine)
        sync_schema(old_engine)

        with old_engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
        for name in ("copy_link", "copy_event", "equity_point"):
            assert name in tables


class TestSafety:
    def test_running_twice_changes_nothing(self, old_engine):
        first = sync_schema(old_engine)
        assert first

        second = sync_schema(old_engine)
        assert second == []

    def test_an_up_to_date_database_is_left_alone(self):
        directory = Path(tempfile.mkdtemp(prefix="tz-migration-current-"))
        engine = create_engine(f"sqlite:///{directory / 'current.db'}")
        Base.metadata.create_all(engine)

        assert sync_schema(engine) == []
        engine.dispose()

    def test_a_column_the_models_dropped_is_left_in_place(self, old_engine):
        """Additive only: never destroy a column, even an unknown one.

        This is what makes the step safe to run against a database written by
        a newer version of the app than the code doing the running.
        """
        with old_engine.begin() as connection:
            connection.execute(text("ALTER TABLE account ADD COLUMN legacy_note TEXT"))

        sync_schema(old_engine)

        assert "legacy_note" in columns(old_engine, "account")

    def test_data_in_an_unknown_column_survives(self, old_engine):
        with old_engine.begin() as connection:
            connection.execute(text("ALTER TABLE account ADD COLUMN legacy_note TEXT"))
            connection.execute(text("UPDATE account SET legacy_note = 'keep me'"))

        sync_schema(old_engine)

        with old_engine.connect() as connection:
            value = connection.execute(text("SELECT legacy_note FROM account")).scalar()
        assert value == "keep me"


def engine_session(engine) -> Session:
    return Session(engine)
