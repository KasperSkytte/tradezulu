"""Trade listing, detail, journalling and manual entry."""

from __future__ import annotations

import csv
import io
from datetime import timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ..deps import AppConfig, CurrentUser, DateRangeDep, DbSession, get_default_account
from ..models import Account, Tag, Trade, TradeTag
from ..schemas import (
    BulkTagRequest,
    ManualTradeIn,
    TradeDetailOut,
    TradeOut,
    TradePage,
    TradeUpdate,
)
from ..services.aggregation import compute_derived, resolve_account_size
from ..services.balances import balance_before_trades
from ..services.queries import TradeFiltersDep, build_query, fetch_trades

router = APIRouter(prefix="/trades", tags=["trades"])

SORTABLE = {
    "closed_at": Trade.closed_at,
    "opened_at": Trade.opened_at,
    "symbol": Trade.symbol,
    "net_pnl": Trade.net_pnl,
    "realized_r": Trade.realized_r,
    "planned_r": Trade.planned_r,
    "volume": Trade.volume,
    "duration": Trade.duration_seconds,
    "risk": Trade.risk_amount,
}


@router.get("", response_model=TradePage)
def list_trades(
    _user: CurrentUser,
    db: DbSession,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    sort: Annotated[str, Query()] = "closed_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> TradePage:
    filters.start, filters.end = range_.start, range_.end
    base = build_query(filters)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    column = SORTABLE.get(sort, Trade.closed_at)
    ordering = column.desc() if order == "desc" else column.asc()
    stmt = base.order_by(ordering, Trade.id.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.scalars(stmt).unique().all())

    all_matching = list(db.scalars(base).unique().all())
    totals = {
        "net_pnl": round(sum(t.net_pnl for t in all_matching), 2),
        "total_r": round(sum(t.realized_r or 0 for t in all_matching), 2),
        "volume": round(sum(t.volume for t in all_matching), 2),
        "wins": sum(1 for t in all_matching if t.outcome == "win"),
        "losses": sum(1 for t in all_matching if t.outcome == "loss"),
        "breakevens": sum(1 for t in all_matching if t.outcome == "breakeven"),
    }
    # Each trade as a share of the account it was taken on, at the moment it
    # closed. Attached here rather than stored: it depends on everything that
    # closed before it, so it would go stale the moment a trade was edited or
    # a missing one imported.
    before = balance_before_trades(db, {t.account_id for t in items})
    out = []
    for trade in items:
        row = TradeOut.model_validate(trade)
        start = before.get(trade.id, 0.0)
        row.balance_before = start or None
        row.return_pct = round(trade.net_pnl / start * 100.0, 4) if start > 0 else None
        out.append(row)

    return TradePage(items=out, total=total, page=page, page_size=page_size, totals=totals)


@router.get("/symbols")
def list_symbols(_user: CurrentUser, db: DbSession) -> list[str]:
    return [s for s in db.scalars(select(distinct(Trade.symbol)).order_by(Trade.symbol)).all() if s]


@router.get("/setups")
def list_setups(_user: CurrentUser, db: DbSession) -> list[str]:
    rows = db.scalars(select(distinct(Trade.setup)).order_by(Trade.setup)).all()
    return [s for s in rows if s]


@router.get("/export.csv")
def export_csv(
    _user: CurrentUser, db: DbSession, range_: DateRangeDep, filters: TradeFiltersDep
) -> Response:
    filters.start, filters.end = range_.start, range_.end
    trades = fetch_trades(db, filters)

    # Which account each trade belongs to. Without it a file covering several
    # accounts is a pile of numbers with no way to tell them apart -- and this
    # export covers every account unless one was asked for.
    accounts = {
        account.id: (account.name or account.login)
        for account in db.scalars(select(Account))
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "account", "symbol", "direction", "opened_at", "closed_at", "volume",
            "entry_price", "exit_price", "stop_loss", "take_profit",
            "gross_profit", "commission", "swap", "net_pnl", "r_multiple",
            "outcome", "setup", "rating", "tags", "notes",
        ]
    )
    for t in trades:
        writer.writerow(
            [
                accounts.get(t.account_id, t.account_id),
                t.symbol, t.direction,
                t.opened_at.isoformat(), t.closed_at.isoformat() if t.closed_at else "",
                t.volume, t.entry_price, t.exit_price or "", t.initial_stop or "",
                t.initial_target or "", round(t.gross_profit, 2), round(t.commission, 2),
                round(t.swap, 2), round(t.net_pnl, 2),
                t.realized_r if t.realized_r is not None else "", t.outcome,
                t.setup, t.rating or "",
                "|".join(tag.name for tag in t.tags),
                (t.notes or "").replace("\n", " ").replace("\r", " "),
            ]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tradezulu-trades.csv"'},
    )


@router.post("/bulk")
def bulk_update(payload: BulkTagRequest, _user: CurrentUser, db: DbSession) -> dict[str, int]:
    if not payload.trade_ids:
        return {"updated": 0}
    trades = list(
        db.scalars(select(Trade).where(Trade.id.in_(payload.trade_ids))).unique().all()
    )
    add_tags = (
        list(db.scalars(select(Tag).where(Tag.id.in_(payload.add_tag_ids))).all())
        if payload.add_tag_ids
        else []
    )
    remove_ids = set(payload.remove_tag_ids)

    for trade in trades:
        if payload.excluded is not None:
            trade.excluded = payload.excluded
        current = {tag.id: tag for tag in trade.tags}
        for tag in add_tags:
            current[tag.id] = tag
        for tag_id in remove_ids:
            current.pop(tag_id, None)
        trade.tags = list(current.values())
    db.commit()
    return {"updated": len(trades)}


@router.get("/{trade_id}", response_model=TradeDetailOut)
def get_trade(trade_id: int, _user: CurrentUser, db: DbSession) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
    return trade


@router.patch("/{trade_id}", response_model=TradeDetailOut)
def update_trade(
    trade_id: int, payload: TradeUpdate, _user: CurrentUser, db: DbSession, config: AppConfig
) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")

    data = payload.model_dump(exclude_unset=True)

    if "notes" in data and data["notes"] is not None:
        trade.notes = data["notes"]
    if "setup" in data and data["setup"] is not None:
        trade.setup = data["setup"]
    if "rating" in data:
        trade.rating = data["rating"]
    if "excluded" in data and data["excluded"] is not None:
        trade.excluded = data["excluded"]

    if payload.reset_stop:
        trade.initial_stop = None
        trade.stop_source = "none"
    elif "initial_stop" in data:
        trade.initial_stop = data["initial_stop"]
        trade.stop_source = "manual" if data["initial_stop"] else "none"

    if payload.reset_target:
        trade.initial_target = None
        trade.target_source = "none"
    elif "initial_target" in data:
        trade.initial_target = data["initial_target"]
        trade.target_source = "manual" if data["initial_target"] else "none"

    if payload.reset_risk:
        trade.risk_override = None
    elif "risk_override" in data:
        trade.risk_override = data["risk_override"]

    if payload.tag_ids is not None:
        trade.tags = list(db.scalars(select(Tag).where(Tag.id.in_(payload.tag_ids))).all())

    _recompute(db, trade, config)
    db.commit()
    db.refresh(trade)
    return trade


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trade(trade_id: int, _user: CurrentUser, db: DbSession) -> None:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
    if not trade.is_manual:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Synced trades cannot be deleted; exclude them from statistics instead.",
        )
    db.execute(TradeTag.__table__.delete().where(TradeTag.trade_id == trade_id))
    db.delete(trade)
    db.commit()


@router.post("", response_model=TradeDetailOut, status_code=status.HTTP_201_CREATED)
def create_manual_trade(
    payload: ManualTradeIn, _user: CurrentUser, db: DbSession, config: AppConfig
) -> Trade:
    account_id = payload.account_id
    if account_id is None:
        account = get_default_account(db)
        if account is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No account exists yet")
        account_id = account.id

    next_position = (
        db.scalar(
            select(func.min(Trade.position_id)).where(Trade.account_id == account_id)
        )
        or 0
    )
    # Manual trades get negative synthetic position ids so they never collide
    # with MT5 tickets.
    position_id = min(next_position, 0) - 1

    trade = Trade(
        account_id=account_id,
        position_id=position_id,
        symbol=payload.symbol.upper(),
        direction=payload.direction,
        opened_at=_naive(payload.opened_at),
        closed_at=_naive(payload.closed_at) if payload.closed_at else None,
        volume=payload.volume,
        closed_volume=payload.volume if payload.closed_at else 0.0,
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        gross_profit=payload.gross_profit,
        commission=payload.commission,
        swap=payload.swap,
        fee=payload.fee,
        value_per_unit=payload.value_per_unit,
        initial_stop=payload.initial_stop,
        initial_target=payload.initial_target,
        stop_source="manual" if payload.initial_stop else "none",
        target_source="manual" if payload.initial_target else "none",
        risk_override=payload.risk_override,
        notes=payload.notes,
        setup=payload.setup,
        rating=payload.rating,
        source="manual",
        is_manual=True,
    )
    if payload.tag_ids:
        trade.tags = list(db.scalars(select(Tag).where(Tag.id.in_(payload.tag_ids))).all())

    # Derive P&L from prices when the user did not supply it.
    if trade.gross_profit == 0 and trade.exit_price and trade.value_per_unit > 0:
        sign = 1 if trade.direction == "long" else -1
        trade.gross_profit = (
            (trade.exit_price - trade.entry_price) * sign * trade.value_per_unit * trade.volume
        )

    db.add(trade)
    _recompute(db, trade, config)
    db.commit()
    db.refresh(trade)
    return trade


def _naive(value: Any):
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _recompute(db: Session, trade: Trade, config: dict[str, Any]) -> None:
    account = trade.account if trade.account is not None else get_default_account(db)
    account_size = resolve_account_size(account, config["risk"])
    compute_derived(
        trade,
        config["risk"],
        account_size,
        config["general"]["timezone"],
        times_mode=config["general"].get("times", "broker"),
        broker_offset_minutes=account.broker_utc_offset_minutes if account else None,
    )
