"""Turn raw MT5 deals into trades, and derive risk / R multiples.

MetaTrader 5 does not have a "trade" concept — it has *deals*. A position is
opened by one or more deals with ``DEAL_ENTRY_IN`` and closed by one or more
``DEAL_ENTRY_OUT`` deals, all sharing the same ``position_id``. Everything in
this module exists to fold those rows back into something a human recognises as
one trade, and then to answer "how much was I risking and what did I get back".
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Deal, Execution, Trade

log = logging.getLogger(__name__)

# DEAL_ENTRY_*
ENTRY_IN = 0
ENTRY_OUT = 1
ENTRY_INOUT = 2
ENTRY_OUT_BY = 3

# DEAL_TYPE_*
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1

VOLUME_EPS = 1e-9


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def _as_naive_utc(dt: datetime) -> datetime:
    """SQLite stores naive datetimes; normalise everything to naive UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@dataclass
class AggregatedTrade:
    """Pure-data result of folding a position's deals together."""

    position_id: int
    symbol: str
    direction: str
    opened_at: datetime
    closed_at: datetime | None
    volume: float
    closed_volume: float
    entry_price: float
    exit_price: float | None
    gross_profit: float
    commission: float
    swap: float
    fee: float
    value_per_unit: float
    digits: int
    initial_stop: float | None
    initial_target: float | None
    magic: int
    comment: str
    executions: list[dict[str, Any]] = field(default_factory=list)


def aggregate_deals(deals: Sequence[Deal]) -> list[AggregatedTrade]:
    """Group deals by position and fold each group into an :class:`AggregatedTrade`."""
    by_position: dict[int, list[Deal]] = {}
    for deal in deals:
        # Balance/credit/commission bookkeeping deals carry no position.
        if deal.deal_type > DEAL_TYPE_SELL:
            continue
        if deal.position_id <= 0:
            continue
        by_position.setdefault(deal.position_id, []).append(deal)

    result: list[AggregatedTrade] = []
    for position_id, group in by_position.items():
        trade = _fold_position(position_id, group)
        if trade is not None:
            result.append(trade)
    result.sort(key=lambda t: t.opened_at)
    return result


def _fold_position(position_id: int, group: list[Deal]) -> AggregatedTrade | None:
    group = sorted(group, key=lambda d: (d.time, d.ticket))

    in_deals: list[Deal] = []
    out_deals: list[Deal] = []
    for deal in group:
        if deal.entry == ENTRY_IN:
            in_deals.append(deal)
        elif deal.entry in (ENTRY_OUT, ENTRY_OUT_BY):
            out_deals.append(deal)
        elif deal.entry == ENTRY_INOUT:
            # Netting reversal: the part that offsets the open volume closes the
            # position, the remainder opens a new one in the other direction.
            # We keep it simple and treat it as a close, since the opposite leg
            # gets its own position_id from the terminal.
            out_deals.append(deal)

    if not in_deals:
        # Only exits known (partial history window) — fall back to treating the
        # earliest deal as the entry so the trade is still visible.
        if not out_deals:
            return None
        in_deals = [out_deals.pop(0)]

    first_in = in_deals[0]
    direction = "long" if first_in.deal_type == DEAL_TYPE_BUY else "short"

    in_volume = sum(d.volume for d in in_deals)
    out_volume = sum(d.volume for d in out_deals)
    entry_price = _vwap(in_deals)
    exit_price = _vwap(out_deals) if out_deals else None

    gross_profit = sum(d.profit for d in group)
    commission = sum(d.commission for d in group)
    swap = sum(d.swap for d in group)
    fee = sum(d.fee for d in group)

    is_closed = out_volume >= in_volume - VOLUME_EPS and out_volume > 0
    closed_at = max(d.time for d in out_deals) if (out_deals and is_closed) else None

    value_per_unit = next((d.value_per_unit for d in group if d.value_per_unit > 0), 0.0)
    if value_per_unit <= 0:
        value_per_unit = _infer_value_per_unit(
            direction, entry_price, exit_price, out_volume, gross_profit
        )

    digits = next((d.digits for d in group if d.digits), 5)
    initial_stop = next((d.sl for d in in_deals if d.sl and d.sl > 0), None)
    initial_target = next((d.tp for d in in_deals if d.tp and d.tp > 0), None)

    executions = [
        {
            "ticket": d.ticket,
            "kind": "in" if d in in_deals else "out",
            "side": "buy" if d.deal_type == DEAL_TYPE_BUY else "sell",
            "volume": d.volume,
            "price": d.price,
            "time": d.time,
            "profit": d.profit,
            "commission": d.commission,
            "swap": d.swap,
        }
        for d in group
    ]

    return AggregatedTrade(
        position_id=position_id,
        symbol=first_in.symbol,
        direction=direction,
        opened_at=first_in.time,
        closed_at=closed_at,
        volume=round(in_volume, 6),
        closed_volume=round(out_volume, 6),
        entry_price=entry_price,
        exit_price=exit_price,
        gross_profit=gross_profit,
        commission=commission,
        swap=swap,
        fee=fee,
        value_per_unit=value_per_unit,
        digits=digits,
        initial_stop=initial_stop,
        initial_target=initial_target,
        magic=next((d.magic for d in group if d.magic), 0),
        comment=(first_in.comment or "").strip(),
        executions=executions,
    )


def _vwap(deals: Iterable[Deal]) -> float:
    deals = list(deals)
    total_volume = sum(d.volume for d in deals)
    if total_volume <= VOLUME_EPS:
        return deals[0].price if deals else 0.0
    return sum(d.price * d.volume for d in deals) / total_volume


def _infer_value_per_unit(
    direction: str,
    entry_price: float,
    exit_price: float | None,
    closed_volume: float,
    gross_profit: float,
) -> float:
    """Recover "money per 1.0 of price move, per lot" from a realised result.

    Imports that lack contract specifications (plain CSV, broker reports) still
    let us do R maths: the realised profit divided by the price distance the
    trade travelled gives exactly the conversion factor we need.
    """
    if exit_price is None or closed_volume <= VOLUME_EPS or gross_profit == 0:
        return 0.0
    sign = 1.0 if direction == "long" else -1.0
    move = (exit_price - entry_price) * sign
    if abs(move) < 1e-12:
        return 0.0
    value = gross_profit / (move * closed_volume)
    return value if value > 0 else 0.0


# ---------------------------------------------------------------------------
# Derived fields: risk, R multiples, outcome
# ---------------------------------------------------------------------------


def effective_net_pnl(trade: Trade, risk_cfg: dict[str, Any]) -> float:
    pnl = trade.gross_profit + trade.fee
    if risk_cfg.get("include_commission_in_pnl", True):
        pnl += trade.commission
    if risk_cfg.get("include_swap_in_pnl", True):
        pnl += trade.swap
    return pnl


def compute_risk_amount(
    trade: Trade, risk_cfg: dict[str, Any], account_size: float
) -> tuple[float | None, str]:
    """Return (risk in account currency, how we got there)."""
    if trade.risk_override is not None and trade.risk_override > 0:
        return trade.risk_override, "override"

    if trade.initial_stop and trade.value_per_unit > 0 and trade.volume > 0:
        distance = abs(trade.entry_price - trade.initial_stop)
        if distance > 0:
            return distance * trade.value_per_unit * trade.volume, "stop"

    mode = risk_cfg.get("fallback_risk_mode", "percent_of_balance")
    if mode == "fixed_amount":
        amount = float(risk_cfg.get("fixed_risk_amount") or 0)
        return (amount, "fixed") if amount > 0 else (None, "none")
    if mode == "percent_of_balance":
        pct = float(risk_cfg.get("risk_percent") or 0)
        amount = account_size * pct / 100.0
        return (amount, "percent") if amount > 0 else (None, "none")
    return None, "none"


def compute_derived(
    trade: Trade,
    risk_cfg: dict[str, Any],
    account_size: float,
    tz_name: str = "UTC",
) -> Trade:
    """Recompute net P&L, risk, R multiples, outcome and bucket date in place."""
    trade.net_pnl = round(effective_net_pnl(trade, risk_cfg), 2)

    risk_amount, _source = compute_risk_amount(trade, risk_cfg, account_size)
    # Money, so round it: floating point noise like 120.00000000000001 would
    # otherwise end up in the risk field on the trade page.
    trade.risk_amount = round(risk_amount, 2) if risk_amount is not None else None

    # Planned R needs both a stop and a target.
    if trade.initial_stop and trade.initial_target and trade.entry_price:
        stop_distance = abs(trade.entry_price - trade.initial_stop)
        target_distance = abs(trade.initial_target - trade.entry_price)
        trade.planned_r = round(target_distance / stop_distance, 4) if stop_distance > 0 else None
    else:
        trade.planned_r = None

    pnl_for_r = trade.net_pnl if risk_cfg.get("r_uses_net_pnl", True) else trade.gross_profit
    if trade.risk_amount and trade.risk_amount > 0 and trade.closed_at is not None:
        trade.realized_r = round(pnl_for_r / trade.risk_amount, 4)
    else:
        trade.realized_r = None

    trade.outcome = classify_outcome(trade, risk_cfg, account_size)

    if trade.closed_at is not None:
        trade.duration_seconds = max(0, int((trade.closed_at - trade.opened_at).total_seconds()))
    else:
        trade.duration_seconds = None

    reference = trade.closed_at or trade.opened_at
    local = reference.replace(tzinfo=timezone.utc).astimezone(_tz(tz_name))
    trade.trade_date = local.date()
    return trade


def classify_outcome(
    trade: Trade, risk_cfg: dict[str, Any], account_size: float = 0.0
) -> str:
    """win / loss / breakeven / open.

    A breakeven is a trade that moved the account by so little that it was, in
    the user's words, a wasted effort. It is still recorded and shown, but by
    default it does not dilute the win rate.

    Three ways to say how little "so little" is, because people do not all
    think about it the same way: in R, in account currency, or as a share of
    the account. Any of them saying breakeven is enough -- they are alternative
    spellings of one idea, not conditions to satisfy together.
    """
    if trade.closed_at is None:
        return "open"

    r_threshold = float(risk_cfg.get("breakeven_threshold_r") or 0)
    money_threshold = float(risk_cfg.get("breakeven_threshold_money") or 0)
    percent_threshold = float(risk_cfg.get("breakeven_threshold_percent") or 0)

    # Checked first and independently of R: a percentage of the account is a
    # statement about the account, and it holds whether or not the trade had a
    # stop to measure R against.
    if percent_threshold > 0 and account_size > 0:
        if abs(trade.net_pnl) / account_size * 100.0 < percent_threshold:
            return "breakeven"

    if trade.realized_r is not None:
        if abs(trade.realized_r) < r_threshold:
            return "breakeven"
    elif abs(trade.net_pnl) < money_threshold:
        return "breakeven"

    if trade.net_pnl > 0:
        return "win"
    if trade.net_pnl < 0:
        return "loss"
    return "breakeven"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def upsert_deals(db: Session, account_id: int, deals: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """Insert deals we have not seen before. Returns (received, newly inserted)."""
    if not deals:
        return 0, 0

    tickets = [int(d["ticket"]) for d in deals if d.get("ticket") is not None]
    existing = set(
        db.scalars(
            select(Deal.ticket).where(Deal.account_id == account_id, Deal.ticket.in_(tickets))
        ).all()
    )

    inserted = 0
    for raw in deals:
        ticket = int(raw.get("ticket") or 0)
        if ticket <= 0 or ticket in existing:
            continue
        existing.add(ticket)
        db.add(
            Deal(
                account_id=account_id,
                ticket=ticket,
                order_id=int(raw.get("order") or raw.get("order_id") or 0),
                position_id=int(raw.get("position_id") or 0),
                symbol=str(raw.get("symbol") or ""),
                deal_type=int(raw.get("type") or raw.get("deal_type") or 0),
                entry=int(raw.get("entry") or 0),
                volume=float(raw.get("volume") or 0),
                price=float(raw.get("price") or 0),
                profit=float(raw.get("profit") or 0),
                commission=float(raw.get("commission") or 0),
                swap=float(raw.get("swap") or 0),
                fee=float(raw.get("fee") or 0),
                sl=float(raw.get("sl") or 0),
                tp=float(raw.get("tp") or 0),
                magic=int(raw.get("magic") or 0),
                comment=str(raw.get("comment") or "")[:255],
                time=_as_naive_utc(_parse_time(raw.get("time"))),
                value_per_unit=float(raw.get("value_per_unit") or 0),
                digits=int(raw.get("digits") or 5),
            )
        )
        inserted += 1

    db.flush()
    return len(deals), inserted


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    raise ValueError(f"Unrecognised timestamp: {value!r}")


def rebuild_trades(
    db: Session,
    account_id: int,
    risk_cfg: dict[str, Any],
    tz_name: str,
    position_ids: Sequence[int] | None = None,
) -> int:
    """Re-fold deals into trades, preserving all user-entered journal fields."""
    stmt = select(Deal).where(Deal.account_id == account_id)
    if position_ids:
        stmt = stmt.where(Deal.position_id.in_(list(position_ids)))
    deals = list(db.scalars(stmt).all())
    if not deals:
        return 0

    account = db.get(Account, account_id)
    account_size = resolve_account_size(account, risk_cfg)

    aggregated = aggregate_deals(deals)
    existing = {
        t.position_id: t
        for t in db.scalars(
            select(Trade).where(
                Trade.account_id == account_id,
                Trade.position_id.in_([a.position_id for a in aggregated]),
            )
        ).all()
    }

    count = 0
    for agg in aggregated:
        trade = existing.get(agg.position_id)
        if trade is None:
            trade = Trade(account_id=account_id, position_id=agg.position_id, source="mt5")
            db.add(trade)

        # Market data always comes from the broker.
        trade.symbol = agg.symbol
        trade.direction = agg.direction
        trade.opened_at = agg.opened_at
        trade.closed_at = agg.closed_at
        trade.volume = agg.volume
        trade.closed_volume = agg.closed_volume
        trade.entry_price = agg.entry_price
        trade.exit_price = agg.exit_price
        trade.gross_profit = agg.gross_profit
        trade.commission = agg.commission
        trade.swap = agg.swap
        trade.fee = agg.fee
        trade.value_per_unit = agg.value_per_unit
        trade.digits = agg.digits
        trade.magic = agg.magic
        trade.comment = agg.comment

        # The plan is only filled from MT5 while the user has not overridden it.
        if trade.stop_source != "manual":
            trade.initial_stop = agg.initial_stop
            trade.stop_source = "mt5" if agg.initial_stop else "none"
        if trade.target_source != "manual":
            trade.initial_target = agg.initial_target
            trade.target_source = "mt5" if agg.initial_target else "none"

        compute_derived(trade, risk_cfg, account_size, tz_name)
        _sync_executions(db, trade, agg.executions)
        count += 1

    db.flush()
    return count


def _sync_executions(db: Session, trade: Trade, executions: list[dict[str, Any]]) -> None:
    known = {e.ticket for e in trade.executions}
    for item in executions:
        if item["ticket"] in known:
            continue
        db.add(Execution(trade=trade, **item))


def resolve_account_size(account: Account | None, risk_cfg: dict[str, Any]) -> float:
    configured = float(risk_cfg.get("account_size") or 0)
    if configured > 0:
        return configured
    if account is None:
        return 0.0
    if account.initial_balance > 0:
        return account.initial_balance
    return account.balance or 0.0


def recompute_all(db: Session, risk_cfg: dict[str, Any], tz_name: str) -> int:
    """Apply current settings to every stored trade (called after settings change)."""
    accounts = {a.id: a for a in db.scalars(select(Account)).all()}
    trades = list(db.scalars(select(Trade)).all())
    for trade in trades:
        account_size = resolve_account_size(accounts.get(trade.account_id), risk_cfg)
        compute_derived(trade, risk_cfg, account_size, tz_name)
    db.flush()
    return len(trades)
