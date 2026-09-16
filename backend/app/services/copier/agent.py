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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Account, CopyEvent, CopyLink, EquityPoint, Trade
from .. import brokerclock
from .config import (
    max_copy_delay_ms,
    mirror_stops_enabled,
    risk_from,
    sizing_from,
    symbol_rules_from,
)
from .engine import ActionType, CopiedPosition, MasterPosition, SlaveContext, plan
from .risk import OpenPosition, SlaveSnapshot
from .sizing import AccountState, SymbolSpec

log = logging.getLogger(__name__)

#: How long a freshly opened copy is given to appear in the terminal's own
#: position list before we believe it is gone.
SETTLE_SECONDS = 30.0

#: Below this, an age worked out from the master terminal's own clock is not
#: believed. Both figures it comes from -- the broker's time now and the time
#: the position opened -- are whole seconds, so a fill a tenth of a second old
#: can read as a whole second and trip a one-second deadline that it never
#: actually missed. Anything genuinely stale is stale by minutes, not by this.
BROKER_AGE_GRACE_SECONDS = 5


def _aware(value: datetime | None) -> datetime:
    """SQLite hands back naive datetimes; compare them in UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def reported_figure(reported: float | None, known: float | None) -> float | None:
    """What to store for a balance or an equity, or None to keep what is there.

    A terminal that is running but not logged in reports zero, and it reports
    it every few seconds. Taken at face value it erases what the account is
    worth, and with it every percentage in the journal -- the daily and weekly
    returns, Net ROI, the equity curve -- because they all divide by it.

    Each figure is judged on its own. Rejecting only the pair of zeros was not
    enough: a terminal whose session has dropped keeps reporting the balance it
    last knew and an equity of zero, which passed straight through and left an
    account "worth 176.92 with 0.00 equity" -- a state no funded account can be
    in, and one the copier reads as a total loss.

    A genuine zero on an account that never had a figure is still recorded: it
    is only a *known* figure that a zero cannot overwrite.
    """
    value = float(reported or 0.0)
    if value == 0.0 and known:
        return None
    return value


def update_account_state(db: Session, account: Account, payload: Any) -> None:
    """Record what the terminal just told us about itself."""
    balance = reported_figure(payload.balance, account.balance)
    equity = reported_figure(payload.equity, account.equity)

    if balance is None and equity is None:
        log.debug("account %s reported nothing; keeping what it was worth", account.login)
        return

    # One of the two can be missing on its own -- a session that has just
    # dropped still knows the balance -- and the one that arrived is worth
    # having.
    if balance is not None:
        account.balance = balance
    if equity is not None:
        account.equity = equity
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

    # What the broker offers. Recorded here rather than while planning a copy,
    # because it describes the account rather than the copying: an account that
    # has never been armed still has to be able to say what it can trade, and
    # the mapping the copier works out is checked against this list.
    #
    # It arrives on its own slow cadence -- thousands of entries that change
    # about never -- so a heartbeat without one is not a broker that has
    # stopped offering anything, and the last list stands until replaced.
    reported = [
        entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        for entry in (getattr(payload, "symbols", None) or [])
    ]
    if reported:
        account.symbols = reported

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


def _parse_time(value: Any) -> datetime | None:
    """An ISO timestamp from the snapshot, back as an aware datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
            opened_at=_parse_time(r.get("opened_at")),
        )
        for r in rows
    ]
    return master, positions


def _opened_at(
    position: dict[str, Any], server_time: int | None, now: datetime
) -> datetime:
    """When the master entered this position, in UTC, as well as it is known.

    The terminal reports the position's open time and the broker's clock in
    the same breath, so the age is the difference between two readings of the
    *same* clock and no timezone comes into it -- which matters, because a
    broker two hours from UTC would otherwise make every trade look two hours
    late.

    A terminal too old to report an open time, or a difference small enough to
    be the whole-second rounding, leaves this at "now": the position is being
    seen for the first time, and the first sighting is the best estimate there
    is. See :data:`BROKER_AGE_GRACE_SECONDS`.
    """
    opened = int(position.get("open_time") or 0)
    if opened > 0 and server_time:
        age = int(server_time) - opened
        if age > BROKER_AGE_GRACE_SECONDS:
            return now - timedelta(seconds=age)
    return now


def store_master_positions(
    account: Account,
    positions: list[dict[str, Any]],
    server_time: int | None = None,
) -> None:
    """Keep the master's open positions where every slave's poll can see them.

    They live on the account row rather than in their own table because they
    are a snapshot, not history: only the latest matters, and it is replaced
    wholesale on every heartbeat.

    One thing does survive the replacement: when each position was opened. A
    copy is only worth placing while it is still the master's trade at roughly
    the master's price, so every slave needs to know how old a position is --
    and an entry rewritten from scratch on every heartbeat would say "just
    now" for ever, which is how a halt cleared at lunchtime opened a position
    the master took at breakfast.
    """
    settings = dict(account.copy_settings or {})
    known = {
        int(entry.get("position_id", 0)): entry
        for entry in (settings.get("_positions") or [])
    }
    now = datetime.now(timezone.utc)

    stored = []
    for p in positions:
        position_id = int(p["position_id"])
        previous = known.get(position_id) or {}
        opened_at = previous.get("opened_at") or _opened_at(p, server_time, now).isoformat()
        stored.append(
            {
                "position_id": position_id,
                "symbol": p["symbol"],
                "direction": p["direction"],
                "volume": float(p["volume"]),
                "open_price": float(p["open_price"]),
                "stop_loss": p.get("stop_loss"),
                "take_profit": p.get("take_profit"),
                "opened_at": opened_at,
            }
        )

    settings["_positions"] = stored
    settings["_positions_at"] = now.isoformat()
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
        store_master_positions(account, positions, getattr(payload, "server_time", None))
        return []

    if not account.copy_enabled or account.copy_halted:
        return []

    master, master_positions = _master_snapshot(db)
    if master is None or not master_positions and not payload.positions:
        return []

    now = datetime.now(timezone.utc)
    context = _context_for(db, account, payload, positions)
    # Building the context may have settled a link that was still in flight --
    # adopted it, or given up on it. The session runs with autoflush off, so
    # push that before the query below reads the statuses back.
    db.flush()

    # A master position this slave has already dealt with does not come back.
    # Its link says what happened -- filled and since closed, refused by the
    # broker, or an order that never reported back -- and every one of those
    # is an answer. Only a position with no link at all is still uncopied, so
    # only that one is put in front of the planner; anything else would be
    # entered a second time, long after the fact, at a price nobody chose.
    #
    # Never anything the slave actually holds, whatever the links say: a
    # position withheld from the planner reads as one the master has closed,
    # and the copy would be closed with it.
    held = {c.master_position_id for c in context.copied}
    settled = _settled_master_ids(db, account, [p.position_id for p in master_positions])
    master_positions = [
        p for p in master_positions if p.position_id not in settled or p.position_id in held
    ]

    actions = plan(
        master_positions,
        AccountState(balance=master.balance, equity=master.equity),
        context,
        now.date(),
        mirror_stops=mirror_stops_enabled(account.copy_settings or {}),
        now=now,
    )

    _remember_symbols(account, actions)

    # How much of each copy's deadline has already gone: the master's fill to
    # this moment. The terminal is handed the remainder with the command.
    deadline = context.max_copy_delay_ms
    ages = {
        position.position_id: position.age_ms(now) or 0.0
        for position in master_positions
        if position.age_ms(now) is not None
    }

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

        commands.append(_command(db, account, action, _budget_ms(action, deadline, ages)))

    return commands


def _settled_master_ids(db: Session, account: Account, ids: list[int]) -> set[int]:
    """Master positions this slave has a finished or in-flight link for.

    Anything but ``open``: a copy that has been closed, one the broker refused,
    and one whose command is still out with the terminal. The first two are
    done with, and the third is not something to send twice while waiting.

    Rehearsals are not answers. A dry run only ever wrote a row, so a link left
    behind by one says nothing about what this account holds and must not stop
    the trade being copied for real when it is armed.
    """
    if not ids:
        return set()
    return set(
        db.scalars(
            select(CopyLink.master_position_id).where(
                CopyLink.slave_account_id == account.id,
                CopyLink.master_position_id.in_(ids),
                CopyLink.status != "open",
                CopyLink.dry_run.is_(False),
            )
        ).all()
    )


def _budget_ms(action: Any, deadline: int, ages: dict[int, float]) -> int:
    """What is left of this copy's deadline by the time the order is sent.

    The terminal spends the rest of it: the reply still has to reach it, and it
    still has to place the order. It refuses anything arriving with the budget
    already gone rather than filling it late -- which is the only part of the
    round trip this server cannot measure for itself. Zero means no deadline,
    and the terminal falls back to what it was told at the poll.
    """
    if action.type is not ActionType.OPEN or deadline <= 0:
        return 0
    return max(1, int(deadline - ages.get(action.master_position_id, 0.0)))


def _context_for(
    db: Session, account: Account, payload: Any, positions: list[dict[str, Any]]
) -> SlaveContext:
    by_ticket = {int(p["ticket"]): p for p in positions}
    # What the terminal holds, by the master position each one was opened for.
    # The copier writes that into the order's comment, which is what lets a
    # fill be recognised even when the reply that announced it never arrived.
    by_comment = _by_master_comment(positions)
    links = db.scalars(
        select(CopyLink).where(
            CopyLink.slave_account_id == account.id,
            CopyLink.status.in_(("open", "pending")),
        )
    ).all()

    copied: list[CopiedPosition] = []
    for link in links:
        if link.status == "pending":
            _settle_pending(link, by_comment)
            if link.status != "open":
                # Still out with the terminal, or given up on. Either way there
                # is no position to manage and nothing to re-send: the planner
                # never sees this master position again.
                continue
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

    symbols = list(account.symbols or [])
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
        link.slave_position_id: link.master_position_id
        for link in links
        if not link.dry_run and link.slave_position_id
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
        max_copy_delay_ms=max_copy_delay_ms(settings),
    )


def _by_master_comment(positions: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Positions the terminal holds, keyed by the master trade they copy.

    Read off the order comment the copier sets when it opens -- ``TZ 12345``.
    Brokers are free to rewrite a comment and some do, so this recognises a
    position when it can rather than being relied on to.
    """
    out: dict[int, dict[str, Any]] = {}
    for row in positions:
        comment = str(row.get("comment") or "").strip()
        if not comment.upper().startswith("TZ "):
            continue
        try:
            master_id = int(comment[3:].strip())
        except ValueError:
            continue
        out.setdefault(master_id, row)
    return out


def _settle_pending(link: CopyLink, by_comment: dict[int, dict[str, Any]]) -> None:
    """Decide what became of an open command that has not reported back.

    Normally the answer arrives with the next heartbeat and this is never
    reached. When it does not -- the terminal was restarted mid-order, the
    reply was lost -- there are only two honest readings, and both of them are
    final. Either the position is there under the copier's own comment, in
    which case it is adopted and managed from here on, or enough time has gone
    by that it never happened, and it is written off.

    What it is never turned into is a fresh attempt. The master's price is long
    gone by now; re-sending it is how one master trade becomes two positions,
    one of them at a price nobody chose.
    """
    row = by_comment.get(link.master_position_id)
    if row is not None:
        link.slave_position_id = int(row.get("ticket") or 0)
        link.slave_symbol = str(row.get("symbol") or link.slave_symbol)
        link.direction = str(row.get("direction") or link.direction)
        link.slave_volume = float(row.get("volume") or link.slave_volume)
        link.open_price = float(row.get("open_price") or 0.0)
        link.status = "open"
        link.dry_run = False
        return

    age = (datetime.now(timezone.utc) - _aware(link.opened_at)).total_seconds()
    if age >= SETTLE_SECONDS:
        link.status = "expired"
        link.closed_at = datetime.now(timezone.utc)
        link.close_reason = "the terminal never said whether this was filled"


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


def _command(db: Session, account: Account, action: Any, budget_ms: int = 0) -> dict[str, Any]:
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
    if action.type is ActionType.OPEN:
        # Written down before the order is even sent, so this master position
        # is spoken for from this moment: no second command while the first is
        # in flight, and no re-entry if it never comes back. The fill fills
        # this row in -- see :func:`record_result`.
        _pending_link(db, account, action)

    command = {
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
    if budget_ms > 0:
        command["max_age_ms"] = budget_ms
    return command


def _pending_link(db: Session, account: Account, action: Any) -> CopyLink:
    """Claim this master position for an order that is on its way out.

    One row per slave and master position -- the schema says so -- so an
    existing one is claimed rather than added beside it.
    """
    link = db.scalar(
        select(CopyLink).where(
            CopyLink.slave_account_id == account.id,
            CopyLink.master_position_id == action.master_position_id,
        )
    )
    if link is None:
        link = CopyLink(
            slave_account_id=account.id,
            master_position_id=action.master_position_id,
        )
        db.add(link)

    link.symbol = action.symbol
    link.slave_symbol = action.slave_symbol
    link.direction = action.direction
    link.slave_volume = action.volume
    link.stop_loss = action.stop_loss
    link.take_profit = action.take_profit
    link.sizing_reason = action.reason[:255]
    link.slave_position_id = 0
    link.status = "pending"
    link.dry_run = False
    link.opened_at = datetime.now(timezone.utc)
    link.closed_at = None
    link.close_reason = ""
    return link


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
        if action == "open" and master_id:
            # The order was refused -- no money, a closed market, or the
            # terminal itself deciding the copy had taken too long to reach it.
            # Whatever the reason, it is an answer: the link is closed out and
            # this master position is never offered to the planner again. A
            # retry would be a new trade at a new price wearing the master's
            # name.
            _give_up(db, account, master_id, message or "the broker refused it")
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


def _give_up(db: Session, account: Account, master_id: int, reason: str) -> None:
    """Mark a copy as never happening, so nothing tries it again."""
    link = db.scalar(
        select(CopyLink).where(
            CopyLink.slave_account_id == account.id,
            CopyLink.master_position_id == master_id,
            CopyLink.status == "pending",
        )
    )
    if link is None:
        return
    link.status = "expired"
    link.closed_at = datetime.now(timezone.utc)
    link.close_reason = reason[:255]


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
