"""Bringing an existing database up to the current models.

``create_all`` builds tables that do not exist yet and then leaves them alone
for ever, so a release that adds a column to an existing table breaks every
installation that already has data — the app starts, queries the new column
and dies with ``no such column``.

This module closes that gap without pulling in a migration framework. It is
deliberately **additive only**: it adds missing columns and missing indexes,
and it never drops, renames or retypes anything. The worst it can do to a
database is leave an unused column behind, which means it is safe to run on
every boot, and safe to run against a database written by a *newer* version
than the code doing the running.

Anything beyond adding things — a column that changed type, a table that needs
splitting — is out of scope by design and would need a real migration.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import Column, Table
from sqlalchemy.types import JSON

from .models import Base

log = logging.getLogger(__name__)


def sync_schema(engine: Engine) -> list[str]:
    """Add whatever the models have and the database does not.

    Returns a description of each change, so the caller can log exactly what
    happened to the user's data rather than changing it silently.
    """
    changes: list[str] = []
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                # create_all makes whole tables; nothing to reconcile.
                continue
            changes += _add_missing_columns(connection, table)
            changes += _add_missing_indexes(connection, table)
    return changes


def _add_missing_columns(connection: Connection, table: Table) -> list[str]:
    present = {column["name"] for column in inspect(connection).get_columns(table.name)}
    changes: list[str] = []

    for column in table.columns:
        if column.name in present:
            continue
        connection.execute(
            text(f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(connection, column)}')
        )
        changes.append(f"{table.name}.{column.name}")

    return changes


def _add_missing_indexes(connection: Connection, table: Table) -> list[str]:
    present = {index["name"] for index in inspect(connection).get_indexes(table.name)}
    changes: list[str] = []

    for index in table.indexes:
        if index.name in present:
            continue
        columns = ", ".join(f'"{column.name}"' for column in index.columns)
        unique = "UNIQUE " if index.unique else ""
        connection.execute(
            text(
                f'CREATE {unique}INDEX IF NOT EXISTS "{index.name}" '
                f'ON "{table.name}" ({columns})'
            )
        )
        changes.append(f"index {index.name}")

    return changes


def _column_ddl(connection: Connection, column: Column) -> str:
    """One column definition, with a default that satisfies NOT NULL.

    SQLite refuses to add a NOT NULL column without a default, because it has
    to put *something* in the rows that already exist. Where the model gives a
    default we use it; otherwise we fall back to an empty value of the right
    type, which matches what the ORM would have written anyway.
    """
    dialect = connection.engine.dialect
    parts = [f'"{column.name}" {column.type.compile(dialect=dialect)}']

    default = _default_literal(column)
    if default is not None:
        parts.append(f"DEFAULT {default}")

    if not column.nullable:
        parts.append("NOT NULL")

    return " ".join(parts)


def _default_literal(column: Column) -> str | None:
    """A SQL literal for the column's default, or None when there is none."""
    default = column.default

    if default is not None and getattr(default, "is_scalar", False):
        return _as_sql_literal(default.arg, column)

    if column.nullable:
        # Nothing to supply: existing rows can simply hold NULL, and the ORM
        # fills the Python-side default on every row it writes from now on.
        return None

    # NOT NULL with a callable default (utcnow, dict, ...). The value itself
    # cannot be expressed in DDL, so give existing rows a neutral one.
    return _empty_literal(column)


def _as_sql_literal(value: Any, column: Column) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, (dict, list)):
        return "'{}'" if isinstance(value, dict) else "'[]'"
    return _empty_literal(column)


def _empty_literal(column: Column) -> str:
    type_ = column.type
    if isinstance(type_, JSON):
        return "'{}'"
    if isinstance(type_, Boolean):
        return "0"
    if isinstance(type_, (Integer, Float)):
        return "0"
    if isinstance(type_, (DateTime, Date)):
        # Not CURRENT_TIMESTAMP: SQLite only accepts a *constant* default when
        # adding a column, and rejects anything it has to evaluate. The epoch
        # is a visibly artificial stand-in for rows that predate the column,
        # which beats refusing to start.
        return "'1970-01-01 00:00:00'" if isinstance(type_, DateTime) else "'1970-01-01'"
    return "''"
