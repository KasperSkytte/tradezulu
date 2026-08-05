"""Turning the copier's plan into commands an Expert Advisor can carry out.

This is the same decision engine the rest of the copier uses — nothing is
re-decided here. The only job is translating :class:`Action` objects into the
small, flat commands an EA can execute, and folding the results back in.

Two properties are deliberate:

* **A command is issued once.** Each carries an id, and a link is only written
  after the EA reports success, so a dropped reply costs one cycle rather than
  producing a second position.
* **The master is never sent a command.** It is read from, never written to,
  whatever the configuration says.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Account, CopyEvent, CopyLink, EquityPoint, Trade
from .. import brokerclock
from .config import mirror_stops_enabled, risk_from, sizing_from, symbol_rules_from
from .engine import ActionType, CopiedPosition, MasterPosition, SlaveContext, plan
from .risk import OpenPosition, SlaveSnapshot
from .sizing import AccountState, SymbolSpec

log = logging.getLogger(__name__)

#: How long a freshly opened copy is given to appear in the terminal's own
#: position list before we believe it is gone.
SETTLE_SECONDS = 30.0


def _aware(value: datetime | None) -> datetime:
    """SQLite hands back naive datetimes; compare them in UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def update_account_state(db: Session, account: Account, payload: Any) -> None:
    """Record what the terminal just told us about itself."""
    account.balance = float(payload.balance or 0.0)
    account.equity = float(payload.equity or 0.0)
    if payload.currency:
        account.currency = payload.currency
    if payload.name and not account.name:
        account.name = payload.name

    # Every heartbeat, so a broker moving on or off summer time is picked up
    # within a poll rather than at the next trade.
    offset = brokerclock.offset_minutes(getattr(payload, "server_time", None))
    if offset is not None:
        account.broker_utc_offset_minutes = offset

    today = datetime.now(timezone.utc).date()
    if account.day_start_date != today or not account.day_start_equity:
        account.day_start_date = today
        account.day_start_equity = account.equity
    account.peak_equity = max(account.peak_equity or 0.0, account.equity)

    record_equity_point(db, account, len(getattr(payload, "positions", []) or []))


#: How often to keep a balance/equity sample. A master polls every ten seconds,
#: which would be 8,640 rows a day per account for a line nobody can see that
#: finely. A minute is fine enough to show a position running up and being
#: given back, which is the whole point of drawing equity next to balance.
EQUITY_SAMPLE_SECONDS = 60


def record_equity_point(db: Session, account: Account, open_positions: int = 0) -> None:
    """Keep a balance/equity sample, so the account has a real curve.

    Balance alone is a step function: it only moves when something closes, so
    a trade that ran to +3R and was given back to +0.2R looks identical to one
    that crawled there. Equity is what was actually on the table at the time,
    and the gap between the two lines is the part worth seeing.

    This can only be recorded as it happens -- there is nothing to reconstruct
    it from afterwards -- so it starts from the first poll and does not
    backfill.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    latest = db.scalar(
        select(EquityPoint.time)
        .where(EquityPoint.account_id == account.id)
        .order_by(EquityPoint.time.desc())
        .limit(1)
    )
    if latest is not None:
        age = (now - _aware(latest)).total_seconds()
        if age < EQUITY_SAMPLE_SECONDS:
            return

    db.add(
        EquityPoint(
            account_id=account.id,
            time=now.replace(tzinfo=None),
            balance=account.balance,
            equity=account.equity,
            open_positions=open_positions,
        )
    )


def _master_snapshot(db: Session) -> tuple[Account | None, list[MasterPosition]]:
    """The master account and whatever it last reported holding."""
    master = db.scalar(select(Account).where(Account.role == "master"))
    if master is None:
        return None, []

    rows = (master.copy_settings or {}).get("_positions") or []
    positions = [
        MasterPosition(
            position_id=int(r["position_id"]),
            symbol=r["symbol"],
            direction=r["direction"],
            volume=float(r["volume"]),
            open_price=float(r["open_price"]),
            stop_loss=r.get("stop_loss"),
            take_profit=r.get("take_profit"),
        )
        for r in rows
    ]
    return master, positions


def store_master_positions(account: Account, positions: list[dict[str, Any]]) -> None:
    """Keep the master's open positions where every slave's poll can see them.

    They live on the account row rather than in their own table because they
    are a snapshot, not history: only the latest matters, and it is replaced
    wholesale on every heartbeat.
    """
    settings = dict(account.copy_settings or {})
    settings["_positions"] = [
        {
            "position_id": int(p["position_id"]),
            "symbol": p["symbol"],
            "direction": p["direction"],
            "volume": float(p["volume"]),
            "open_price": float(p["open_price"]),
            "stop_loss": p.get("stop_loss"),
            "take_profit": p.get("take_profit"),
        }
        for p in positions
    ]
    settings["_positions_at"] = datetime.now(timezone.utc).isoformat()
    account.copy_settings = settings


def _spec_from(payload: dict[str, Any]) -> SymbolSpec:
    return SymbolSpec(
        symbol=payload.get("symbol", ""),
        volume_min=float(payload.get("volume_min", 0.01)),
        volume_max=float(payload.get("volume_max", 100.0)),
        volume_step=float(payload.get("volume_step", 0.01)),
        value_per_unit=float(payload.get("value_per_unit", 0.0)),
        digits=int(payload.get("digits", 5)),
    )


def commands_for(db: Session, account: Account, payload: Any) -> list[dict[str, Any]]:
    """What this terminal should do next."""
    positions = [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in payload.positions]

    if account.role == "master":
        # The master is only ever read from.
        store_master_positions(account, positions)
        return []

    if not account.copy_enabled or account.copy_halted:
        return []

    master, master_positions = _master_snapshot(db)
    if master is None or not master_positions and not payload.positions:
        return []

    context = _context_for(db, account, payload, positions)
    actions = plan(
        master_positions,
        AccountState(balance=master.balance, equity=master.equity),
        context,
        datetime.now(timezone.utc).date(),
        mirror_stops=mirror_stops_enabled(account.copy_settings or {}),
    )

    _remember_symbols(account, actions)

    commands: list[dict[str, Any]] = []
    for action in actions:
        if action.type is ActionType.SKIP:
            if _is_new_skip(db, account, action):
                _event(db, account, action, "skipped")
            continue

        if action.type is ActionType.HALT:
            account.copy_halted = True
            account.copy_halt_reason = action.reason[:255]
            account.copy_halted_at = datetime.now(timezone.utc)
            _event(db, account, action, "halted")
            continue

        if account.copy_dry_run:
            _event(db, account, action, "dry_run")
            if action.type is ActionType.OPEN:
                _link(db, account, action, ticket=0, dry_run=True)
            elif action.type is ActionType.CLOSE:
                _close_link(db, account, action, "dry run")
            continue

        commands.append(_command(db, account, action))

    return commands


def _context_for(
    db: Session, account: Account, payload: Any, positions: list[dict[str, Any]]
) -> SlaveContext:
    by_ticket = {int(p["ticket"]): p for p in positions}
    links = db.scalars(
        select(CopyLink).where(
            CopyLink.slave_account_id == account.id, CopyLink.status == "open"
        )
    ).all()

    copied: list[CopiedPosition] = []
    for link in links:
        if link.dry_run:
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
            # A position the broker has only just filled may not be in the
            # snapshot the terminal sent with this very poll. Treating that as
            # "closed" would re-open the trade on the next pass, which is how a
            # copier ends up with two positions where the master has one. So a
            # link is only reconciled away once it has had time to show up.
            age = (datetime.now(timezone.utc) - _aware(link.opened_at)).total_seconds()
            if age < SETTLE_SECONDS:
                continue
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

    symbols = [
        s.model_dump() if hasattr(s, "model_dump") else dict(s)
        for s in (payload.symbols or [])
    ]
    specs = {s["symbol"].upper(): _spec_from(s) for s in symbols}
    settings = account.copy_settings or {}

    # What the account is actually exposed to, straight from the terminal. The
    # limits that count positions -- max_open_positions, max_same_direction,
    # max_positions_per_symbol, max_total_lots -- are all measured against this,
    # and it has to be everything the account holds rather than only what the
    # copier opened: a cap that ignores half the book is not a cap. Dry-run
    # links are included because nothing was really opened for them, so the
    # terminal cannot report them and a rehearsal would otherwise look like an
    # account with no exposure at all.
    master_id_by_ticket = {
        link.slave_position_id: link.master_position_id for link in links if not link.dry_run
    }
    held = [
        OpenPosition(
            symbol=str(row.get("symbol", "")),
            direction=str(row.get("direction", "")),
            volume=float(row.get("volume", 0.0)),
            entry_price=float(row.get("open_price", 0.0)),
            profit=float(row.get("profit", 0.0)),
            stop_loss=row.get("stop_loss"),
            master_position_id=master_id_by_ticket.get(int(row["ticket"])),
        )
        for row in positions
    ]
    held += [
        OpenPosition(
            symbol=link.slave_symbol,
            direction=link.direction,
            volume=link.slave_volume,
            entry_price=link.open_price or 0.0,
            stop_loss=link.stop_loss,
            master_position_id=link.master_position_id,
        )
        for link in links
        if link.dry_run
    ]

    realised_by_day = _realised_by_day(db, account)
    today = datetime.now(timezone.utc).date()

    return SlaveContext(
        account_id=account.id,
        account=AccountState(balance=account.balance, equity=account.equity),
        snapshot=SlaveSnapshot(
            balance=account.balance,
            equity=account.equity,
            day_start_equity=account.day_start_equity or account.equity,
            peak_equity=account.peak_equity or account.equity,
            open_positions=held,
            day_realised_pnl=realised_by_day.get(today, 0.0),
            realised_by_day=realised_by_day,
        ),
        sizing=sizing_from(settings),
        risk=risk_from(settings),
        symbol_rules=symbol_rules_from(
            account.symbol_prefix,
            account.symbol_suffix,
            account.symbol_map,
            [s["symbol"] for s in symbols],
            account.symbol_learned,
        ),
        available_symbols=[s["symbol"] for s in symbols],
        specs=specs,
        copied=copied,
        halted=account.copy_halted,
    )


def _remember_symbols(account: Account, actions: list[Any]) -> None:
    """Keep what the search worked out, so it is only worked out once.

    Resolution walks the broker's whole symbol list -- a couple of thousand
    names at some brokers -- and it was doing that for every position on every
    heartbeat. Writing the answer down turns all but the first into a lookup.

    Only what was actually resolved is kept. A symbol that could not be matched
    is not recorded as unmatchable: the instrument may simply not have been
    trading yet, and a remembered failure would outlive the reason for it.
    """
    learned = dict(account.symbol_learned or {})
    for action in actions:
        if action.type is ActionType.SKIP or not action.symbol or not action.slave_symbol:
            continue
        if learned.get(action.symbol) != action.slave_symbol:
            learned[action.symbol] = action.slave_symbol
    if learned != (account.symbol_learned or {}):
        account.symbol_learned = learned


def _realised_by_day(db: Session, account: Account) -> dict[date, float]:
    """Banked profit per day for this account, from its own closed trades.

    Two rules are measured against this and neither could fire without it: the
    daily profit target, and the prop-firm consistency cap that refuses to let
    one day be most of the profit. Both are about money actually taken, not
    what is on the table -- a position running at +500 has been banked by
    nobody -- so this reads closed trades rather than equity.

    The whole account is summed rather than a window. A consistency rule asks
    what share of *total* profit one day is, so it has no window by
    construction, and the daily target only ever looks at today.
    """
    rows = db.execute(
        select(Trade.trade_date, func.sum(Trade.net_pnl))
        .where(
            Trade.account_id == account.id,
            Trade.closed_at.is_not(None),
            Trade.trade_date.is_not(None),
        )
        .group_by(Trade.trade_date)
    ).all()
    return {day: float(total or 0.0) for day, total in rows}


def _command(db: Session, account: Account, action: Any) -> dict[str, Any]:
    command_id = uuid.uuid4().hex[:16]
    db.add(
        CopyEvent(
            slave_account_id=account.id,
            master_position_id=action.master_position_id,
            action=action.type.value,
            outcome="ok",
            symbol=action.slave_symbol or action.symbol,
            direction=action.direction,
            volume=action.volume,
            rule=command_id,
            message=f"sent to the terminal: {action.reason}"[:2000],
        )
    )
    return {
        "id": command_id,
        "action": action.type.value,
        "symbol": action.slave_symbol,
        "direction": action.direction,
        "volume": round(action.volume, 2),
        "stop_loss": action.stop_loss or 0.0,
        "take_profit": action.take_profit or 0.0,
        "ticket": action.slave_position_id or 0,
        "master_position_id": action.master_position_id,
        "comment": f"TZ {action.master_position_id}",
    }


def record_result(db: Session, account: Account, result: Any) -> None:
    """Fold an executed command's outcome back into the record."""
    ok = bool(getattr(result, "ok", False))
    action = getattr(result, "action", "") or ""
    master_id = int(getattr(result, "master_position_id", 0) or 0)
    ticket = int(getattr(result, "ticket", 0) or 0)
    message = str(getattr(result, "message", "") or "")

    db.add(
        CopyEvent(
            slave_account_id=account.id,
            master_position_id=master_id,
            action=action or "result",
            outcome="ok" if ok else "failed",
            symbol=str(getattr(result, "symbol", "") or ""),
            volume=float(getattr(result, "volume", 0.0) or 0.0),
            rule=str(getattr(result, "id", "") or ""),
            message=message[:2000],
        )
    )

    if not ok:
        return

    if action == "open" and master_id and ticket:
        # One link per master position per slave -- the schema enforces it --
        # so a fill updates whatever link is already there rather than adding
        # another. Skipping when one exists was the bug: a *closed* link, left
        # by a dry run or by a position taken a second time, matched forever.
        # The fill was then never recorded, the planner kept seeing an uncopied
        # position, and it opened again on every poll. One master trade became a
        # hundred orders on the slave.
        link = db.scalar(
            select(CopyLink).where(
                CopyLink.slave_account_id == account.id,
                CopyLink.master_position_id == master_id,
            )
        )
        if link is None:
            link = CopyLink(
                slave_account_id=account.id,
                master_position_id=master_id,
                symbol=str(getattr(result, "symbol", "") or ""),
            )
            db.add(link)

        link.slave_position_id = ticket
        link.slave_symbol = str(getattr(result, "symbol", "") or "")
        link.direction = str(getattr(result, "direction", "") or "")
        link.slave_volume = float(getattr(result, "volume", 0.0) or 0.0)
        link.open_price = float(getattr(result, "price", 0.0) or 0.0)
        link.status = "open"
        link.opened_at = datetime.now(timezone.utc)
        link.closed_at = None
        link.close_reason = ""
        # A real fill, not a rehearsal. The column defaults to True, and leaving
        # it would make a live position look like a dry run -- so it would never
        # be matched to its real ticket.
        link.dry_run = False

    elif action == "close" and master_id:
        link = db.scalar(
            select(CopyLink).where(
                CopyLink.slave_account_id == account.id,
                CopyLink.master_position_id == master_id,
                CopyLink.status == "open",
            )
        )
        if link is not None:
            link.status = "closed"
            link.closed_at = datetime.now(timezone.utc)
            link.close_reason = message[:255] or "closed by the terminal"


def _link(db: Session, account: Account, action: Any, ticket: int, dry_run: bool = False) -> None:
    db.add(
        CopyLink(
            slave_account_id=account.id,
            master_position_id=action.master_position_id,
            slave_position_id=ticket,
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


def _close_link(db: Session, account: Account, action: Any, reason: str) -> None:
    link = db.scalar(
        select(CopyLink).where(
            CopyLink.slave_account_id == account.id,
            CopyLink.master_position_id == action.master_position_id,
            CopyLink.status == "open",
        )
    )
    if link is not None:
        link.status = "closed"
        link.closed_at = datetime.now(timezone.utc)
        link.close_reason = reason[:255]


def _is_new_skip(db: Session, account: Account, action: Any) -> bool:
    """Whether this skip says anything the last one did not.

    A skip is a standing condition, not an event: a master position the slave
    is too small to copy is skipped again on every poll, and an armed slave
    polls every two seconds. Recorded blindly that is 43,200 identical rows a
    day per position, which buries the events that do mean something and grows
    the database for no one's benefit.

    The first skip is kept, because the reason a trade was not copied is worth
    knowing. Repeats of it are not. A *different* reason for the same position
    is new information and is recorded.
    """
    previous = db.scalar(
        select(CopyEvent)
        .where(
            CopyEvent.slave_account_id == account.id,
            CopyEvent.master_position_id == action.master_position_id,
        )
        .order_by(CopyEvent.id.desc())
        .limit(1)
    )
    if previous is None or previous.outcome != "skipped":
        return True
    return previous.rule != action.rule or previous.message != action.reason[:2000]


def _event(db: Session, account: Account, action: Any, outcome: str) -> None:
    db.add(
        CopyEvent(
            slave_account_id=account.id,
            master_position_id=action.master_position_id,
            action=action.type.value,
            outcome=outcome,
            symbol=action.slave_symbol or action.symbol,
            direction=action.direction,
            volume=action.volume,
            rule=action.rule,
            message=action.reason[:2000],
        )
    )
