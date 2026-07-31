"""The copy loop: read the master, decide per slave, execute, record.

The decisions live in :mod:`engine`; this module is the part with side
effects. It is deliberately thin, because everything interesting has already
been decided by a pure function that the tests can drive directly.

The execution rules that matter:

* **Dry-run executes nothing.** It runs the identical plan and records what
  each action would have been, so the log of a dry-run slave and a live one
  differ only in the outcome column.
* **A failed action is recorded and skipped, not retried in a tight loop.** A
  broker refusing an order is information, and hammering it is how an account
  gets throttled.
* **Closes are attempted even when opens are refused.** Reducing exposure must
  never be blocked by the same conditions that stop new exposure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Account, CopyEvent, CopyLink
from .config import (
    mirror_stops_enabled,
    risk_from,
    sizing_from,
    symbol_rules_from,
)
from .engine import Action, ActionType, CopiedPosition, MasterPosition, SlaveContext, plan
from .risk import SlaveSnapshot
from .sizing import AccountState, SymbolSpec

log = logging.getLogger(__name__)


class Broker(Protocol):
    """What the copier needs from a terminal.

    Implemented by the Expert Advisor protocol in ``agent.py``.
    """

    def positions(self, account_id: int) -> list[dict[str, Any]]: ...
    def account(self, account_id: int) -> dict[str, Any]: ...
    def symbols(self, account_id: int) -> list[str]: ...
    def symbol_spec(self, account_id: int, symbol: str) -> dict[str, Any]: ...
    def open(self, account_id: int, **kwargs: Any) -> dict[str, Any]: ...
    def close(self, account_id: int, ticket: int, volume: float | None = None) -> dict[str, Any]: ...
    def modify(
        self, account_id: int, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> dict[str, Any]: ...


@dataclass
class CycleResult:
    planned: int = 0
    executed: int = 0
    skipped: int = 0
    failed: int = 0
    halted: bool = False

    def record(self, action: Action, outcome: str) -> None:
        self.planned += 1
        if outcome in {"ok", "dry_run"}:
            self.executed += 1
        elif outcome == "failed":
            self.failed += 1
        else:
            self.skipped += 1
        if action.type is ActionType.HALT:
            self.halted = True


def _spec_from(payload: dict[str, Any]) -> SymbolSpec:
    return SymbolSpec(
        symbol=payload.get("symbol", ""),
        volume_min=float(payload.get("volume_min", 0.01)),
        volume_max=float(payload.get("volume_max", 100.0)),
        volume_step=float(payload.get("volume_step", 0.01)),
        value_per_unit=float(payload.get("value_per_unit", 0.0)),
        digits=int(payload.get("digits", 5)),
    )


def _master_positions(rows: list[dict[str, Any]]) -> list[MasterPosition]:
    return [
        MasterPosition(
            position_id=int(row["position_id"]),
            symbol=row["symbol"],
            direction=row["direction"],
            volume=float(row["volume"]),
            open_price=float(row["open_price"]),
            stop_loss=row.get("stop_loss"),
            take_profit=row.get("take_profit"),
        )
        for row in rows
    ]


def _day_bounds(account: Account, equity: float, today: date) -> tuple[float, float]:
    """The day's opening equity and the running peak, kept on the account."""
    if account.day_start_date != today or not account.day_start_equity:
        account.day_start_date = today
        account.day_start_equity = equity
    account.peak_equity = max(account.peak_equity or 0.0, equity)
    return account.day_start_equity, account.peak_equity


def build_context(
    db: Session,
    slave: Account,
    broker: Broker,
    today: date,
) -> tuple[SlaveContext, list[SymbolSpec]]:
    """Everything the planner needs about one slave, read from its terminal."""
    info = broker.account(slave.id)
    equity = float(info.get("equity", 0.0))
    balance = float(info.get("balance", 0.0))
    slave.balance, slave.equity = balance, equity
    day_start, peak = _day_bounds(slave, equity, today)

    live = broker.positions(slave.id)
    by_ticket = {int(row["ticket"]): row for row in live}

    links = db.scalars(
        select(CopyLink).where(
            CopyLink.slave_account_id == slave.id, CopyLink.status == "open"
        )
    ).all()

    copied: list[CopiedPosition] = []
    for link in links:
        if link.dry_run:
            # There is no broker position to reconcile against: a dry run only
            # ever wrote a row. Take it at face value so the plan stays stable
            # instead of re-opening the same trade on every pass.
            copied.append(
                CopiedPosition(
                    master_position_id=link.master_position_id,
                    slave_position_id=0,
                    slave_symbol=link.slave_symbol,
                    direction=link.direction,
                    volume=link.slave_volume,
                    open_price=link.open_price,
                    stop_loss=link.stop_loss,
                    take_profit=link.take_profit,
                )
            )
            continue

        row = by_ticket.get(link.slave_position_id)
        if row is None:
            # Closed at the broker, by a stop or by hand. Our record is stale.
            link.status = "closed"
            link.closed_at = datetime.now(timezone.utc)
            link.close_reason = "no longer open at the broker"
            continue
        copied.append(
            CopiedPosition(
                master_position_id=link.master_position_id,
                slave_position_id=link.slave_position_id,
                slave_symbol=row["symbol"],
                direction=row["direction"],
                volume=float(row["volume"]),
                open_price=float(row["open_price"]),
                stop_loss=row.get("stop_loss"),
                take_profit=row.get("take_profit"),
                profit=float(row.get("profit", 0.0)),
            )
        )

    specs: dict[str, SymbolSpec] = {}
    for symbol in {position.slave_symbol for position in copied}:
        try:
            specs[symbol.upper()] = _spec_from(broker.symbol_spec(slave.id, symbol))
        except Exception as exc:  # noqa: BLE001 - a missing spec is not fatal
            log.debug("no spec for %s on account %s: %s", symbol, slave.id, exc)

    settings = slave.copy_settings or {}
    context = SlaveContext(
        account_id=slave.id,
        account=AccountState(balance=balance, equity=equity),
        snapshot=SlaveSnapshot(
            balance=balance,
            equity=equity,
            day_start_equity=day_start,
            peak_equity=peak,
            open_positions=[],
            day_realised_pnl=0.0,
            realised_by_day={},
        ),
        sizing=sizing_from(settings),
        risk=risk_from(settings),
        symbol_rules=symbol_rules_from(
            slave.symbol_prefix, slave.symbol_suffix, slave.symbol_map
        ),
        available_symbols=broker.symbols(slave.id),
        specs=specs,
        copied=copied,
        halted=slave.copy_halted,
    )
    return context, list(specs.values())


def resolve_specs(context: SlaveContext, broker: Broker, symbols: set[str]) -> None:
    """Fetch contract details for symbols the planner is about to consider."""
    for symbol in symbols:
        key = symbol.upper()
        if key in context.specs:
            continue
        try:
            context.specs[key] = _spec_from(broker.symbol_spec(context.account_id, symbol))
        except Exception as exc:  # noqa: BLE001
            log.debug("no spec for %s: %s", symbol, exc)


def run_cycle(
    db: Session,
    master: Account,
    slave: Account,
    broker: Broker,
    master_rows: list[dict[str, Any]],
    today: date | None = None,
) -> CycleResult:
    """One pass for one slave. Returns what happened, and records all of it."""
    today = today or datetime.now(timezone.utc).date()
    result = CycleResult()

    context, _ = build_context(db, slave, broker, today)
    # build_context may have just marked a link closed after finding its
    # position gone at the broker. The session runs with autoflush off, so
    # that change has to be pushed before the query below can see it.
    db.flush()

    # A master position this slave has already copied and closed does not come
    # back. If the copy was stopped out while the master held on, re-entering
    # would be trading against the stop that just fired -- and the master's
    # own exit will never arrive to close it, because we already saw it.
    finished = set(
        db.scalars(
            select(CopyLink.master_position_id).where(
                CopyLink.slave_account_id == slave.id, CopyLink.status == "closed"
            )
        ).all()
    )
    positions = [
        position
        for position in _master_positions(master_rows)
        if position.position_id not in finished
    ]

    # The planner needs a spec for anything it might open, and those symbols
    # are named by the *master*, so resolve them through this slave's rules.
    from .symbols import resolve as resolve_symbol

    wanted: set[str] = set()
    for position in positions:
        mapped = resolve_symbol(position.symbol, context.symbol_rules, context.available_symbols)
        if mapped:
            wanted.add(mapped)
    resolve_specs(context, broker, wanted)

    actions = plan(
        positions,
        AccountState(balance=master.balance, equity=master.equity),
        context,
        today,
        mirror_stops=mirror_stops_enabled(slave.copy_settings or {}),
    )

    for action in actions:
        outcome = _execute(db, slave, broker, action)
        result.record(action, outcome)

    slave.last_sync_at = datetime.now(timezone.utc)
    return result


def _execute(db: Session, slave: Account, broker: Broker, action: Action) -> str:
    """Carry out one action, or record why it was not carried out."""
    dry = slave.copy_dry_run

    if action.type is ActionType.SKIP:
        _event(db, slave, action, "skipped")
        return "skipped"

    if action.type is ActionType.HALT:
        slave.copy_halted = True
        slave.copy_halt_reason = action.reason[:255]
        slave.copy_halted_at = datetime.now(timezone.utc)
        _event(db, slave, action, "halted")
        return "halted"

    if dry:
        _event(db, slave, action, "dry_run")
        if action.type is ActionType.OPEN:
            # Track it so a dry run does not re-open the same trade every pass
            # and produce a log nobody can read.
            _link(db, slave, action, slave_position_id=0, dry_run=True)
        elif action.type is ActionType.CLOSE:
            _close_link(db, slave, action, "dry run")
        return "dry_run"

    try:
        if action.type is ActionType.OPEN:
            reply = broker.open(
                slave.id,
                symbol=action.slave_symbol,
                direction=action.direction,
                volume=action.volume,
                stop_loss=action.stop_loss,
                take_profit=action.take_profit,
                comment=f"TZ {action.master_position_id}",
            )
            if not reply.get("ok"):
                _event(db, slave, action, "failed", note=_broker_error(reply))
                return "failed"
            _link(db, slave, action, slave_position_id=int(reply.get("order") or reply.get("deal") or 0))

        elif action.type is ActionType.CLOSE:
            reply = broker.close(slave.id, ticket=action.slave_position_id or 0)
            if not reply.get("ok", True):
                _event(db, slave, action, "failed", note=_broker_error(reply))
                return "failed"
            _close_link(db, slave, action, action.reason)

        elif action.type is ActionType.MODIFY:
            reply = broker.modify(
                slave.id,
                ticket=action.slave_position_id or 0,
                stop_loss=action.stop_loss,
                take_profit=action.take_profit,
            )
            if not reply.get("ok", True):
                _event(db, slave, action, "failed", note=_broker_error(reply))
                return "failed"
            _update_link_levels(db, slave, action)

    except Exception as exc:  # noqa: BLE001 - one bad account must not stop the rest
        _event(db, slave, action, "failed", note=str(exc))
        return "failed"

    _event(db, slave, action, "ok")
    return "ok"


def _broker_error(reply: dict[str, Any]) -> str:
    code = reply.get("retcode")
    comment = reply.get("comment") or reply.get("error") or "rejected"
    return f"{comment} (retcode {code})" if code else str(comment)


def _event(db: Session, slave: Account, action: Action, outcome: str, note: str = "") -> None:
    message = action.reason if not note else f"{action.reason}: {note}"
    db.add(
        CopyEvent(
            slave_account_id=slave.id,
            master_position_id=action.master_position_id,
            action=action.type.value,
            outcome=outcome,
            symbol=action.slave_symbol or action.symbol,
            direction=action.direction,
            volume=action.volume,
            rule=action.rule,
            message=message[:2000],
        )
    )


def _link(db: Session, slave: Account, action: Action, slave_position_id: int, dry_run: bool = False) -> None:
    db.add(
        CopyLink(
            slave_account_id=slave.id,
            master_position_id=action.master_position_id,
            slave_position_id=slave_position_id,
            symbol=action.symbol,
            slave_symbol=action.slave_symbol,
            direction=action.direction,
            slave_volume=action.volume,
            stop_loss=action.stop_loss,
            take_profit=action.take_profit,
            sizing_reason=action.reason[:255],
            status="open",
            dry_run=dry_run,
        )
    )


def _existing_link(db: Session, slave: Account, action: Action) -> CopyLink | None:
    return db.scalar(
        select(CopyLink).where(
            CopyLink.slave_account_id == slave.id,
            CopyLink.master_position_id == action.master_position_id,
            CopyLink.status == "open",
        )
    )


def _close_link(db: Session, slave: Account, action: Action, reason: str) -> None:
    link = _existing_link(db, slave, action)
    if link is not None:
        link.status = "closed"
        link.closed_at = datetime.now(timezone.utc)
        link.close_reason = reason[:255]


def _update_link_levels(db: Session, slave: Account, action: Action) -> None:
    link = _existing_link(db, slave, action)
    if link is not None:
        link.stop_loss = action.stop_loss
        link.take_profit = action.take_profit
