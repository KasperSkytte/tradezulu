"""Shared trade-filtering logic used by the trades, stats and calendar APIs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from ..models import Trade, TradeTag


@dataclass
class TradeFilters:
    start: date | None = None
    end: date | None = None
    account_id: int | None = None
    symbols: list[str] = field(default_factory=list)
    tag_ids: list[int] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    setups: list[str] = field(default_factory=list)
    search: str | None = None
    min_r: float | None = None
    max_r: float | None = None
    include_open: bool = False
    include_excluded: bool = False
    tagged_only: bool = False
    untagged_only: bool = False


def trade_filters(
    account_id: Annotated[int | None, Query()] = None,
    symbol: Annotated[list[str] | None, Query()] = None,
    tag: Annotated[list[int] | None, Query()] = None,
    direction: Annotated[list[str] | None, Query()] = None,
    outcome: Annotated[list[str] | None, Query()] = None,
    setup: Annotated[list[str] | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    min_r: Annotated[float | None, Query()] = None,
    max_r: Annotated[float | None, Query()] = None,
    include_open: Annotated[bool, Query()] = False,
    include_excluded: Annotated[bool, Query()] = False,
    untagged_only: Annotated[bool, Query()] = False,
) -> TradeFilters:
    return TradeFilters(
        account_id=account_id,
        symbols=symbol or [],
        tag_ids=tag or [],
        directions=direction or [],
        outcomes=outcome or [],
        setups=setup or [],
        search=search,
        min_r=min_r,
        max_r=max_r,
        include_open=include_open,
        include_excluded=include_excluded,
        untagged_only=untagged_only,
    )


TradeFiltersDep = Annotated[TradeFilters, Depends(trade_filters)]


def build_query(filters: TradeFilters) -> Select:
    stmt = select(Trade)
    conditions = []

    if filters.start is not None:
        conditions.append(Trade.trade_date >= filters.start)
    if filters.end is not None:
        conditions.append(Trade.trade_date <= filters.end)
    if filters.account_id:
        conditions.append(Trade.account_id == filters.account_id)
    if filters.symbols:
        conditions.append(Trade.symbol.in_(filters.symbols))
    if filters.directions:
        conditions.append(Trade.direction.in_(filters.directions))
    if filters.outcomes:
        conditions.append(Trade.outcome.in_(filters.outcomes))
    if filters.setups:
        conditions.append(Trade.setup.in_(filters.setups))
    if not filters.include_open:
        conditions.append(Trade.closed_at.is_not(None))
    if not filters.include_excluded:
        conditions.append(Trade.excluded.is_(False))
    if filters.min_r is not None:
        conditions.append(Trade.realized_r >= filters.min_r)
    if filters.max_r is not None:
        conditions.append(Trade.realized_r <= filters.max_r)
    if filters.search:
        needle = f"%{filters.search.strip()}%"
        conditions.append(
            or_(
                Trade.notes.ilike(needle),
                Trade.symbol.ilike(needle),
                Trade.setup.ilike(needle),
                Trade.comment.ilike(needle),
            )
        )
    if filters.tag_ids:
        # Every selected tag must be present (AND semantics).
        for tag_id in filters.tag_ids:
            stmt = stmt.where(
                Trade.id.in_(select(TradeTag.trade_id).where(TradeTag.tag_id == tag_id))
            )
    if filters.untagged_only:
        stmt = stmt.where(~Trade.id.in_(select(TradeTag.trade_id)))

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def fetch_trades(db: Session, filters: TradeFilters) -> Sequence[Trade]:
    stmt = build_query(filters).order_by(Trade.closed_at.asc(), Trade.opened_at.asc())
    return list(db.scalars(stmt).unique().all())
