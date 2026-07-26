"""Statistics, breakdowns and the calendar feed."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import AppConfig, CurrentUser, DateRangeDep, DbSession, get_default_account
from ..models import DayNote, Trade
from ..services.aggregation import resolve_account_size
from ..services.metrics import breakdowns, rolling_metrics, summarize
from ..services.queries import TradeFilters, TradeFiltersDep, fetch_trades

router = APIRouter(prefix="/stats", tags=["stats"])


def _account_size(db, config: dict[str, Any], account_id: int | None) -> float:
    from ..models import Account

    account = db.get(Account, account_id) if account_id else get_default_account(db)
    return resolve_account_size(account, config["risk"])


@router.get("/summary")
def summary(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
) -> dict[str, Any]:
    filters.start, filters.end = range_.start, range_.end
    filters.include_open = True
    # Excluded trades are still fetched so they can be counted and reported;
    # the metrics layer keeps them out of every calculation.
    filters.include_excluded = True
    trades = fetch_trades(db, filters)
    return summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=_account_size(db, config, filters.account_id),
        period_start=range_.start,
        period_end=range_.end,
    )


@router.get("/compare")
def compare_to_previous(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
) -> dict[str, Any]:
    """Same statistics for the equally long window immediately before this one."""
    span = (range_.end - range_.start).days + 1
    prev_end = range_.start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    account_size = _account_size(db, config, filters.account_id)
    result = {}
    for label, (start, end) in {
        "current": (range_.start, range_.end),
        "previous": (prev_start, prev_end),
    }.items():
        window = TradeFilters(**{**filters.__dict__, "start": start, "end": end})
        window.include_open = False
        window.include_excluded = True
        trades = fetch_trades(db, window)
        stats = summarize(
            trades,
            risk_cfg=config["risk"],
            stats_cfg=config["stats"],
            score_cfg=config["zulu_score"],
            account_size=account_size,
            period_start=start,
            period_end=end,
        )
        stats.pop("equity_curve", None)
        stats.pop("daily", None)
        result[label] = stats
    return result


@router.get("/breakdowns")
def get_breakdowns(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
) -> dict[str, Any]:
    filters.start, filters.end = range_.start, range_.end
    trades = fetch_trades(db, filters)
    return breakdowns(trades, config["risk"].get("breakeven_handling", "excluded"))


@router.get("/rolling")
def get_rolling(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
    window: Annotated[int, Query(ge=2, le=200)] = 20,
) -> list[dict[str, Any]]:
    from ..services.metrics import daily_breakdown

    filters.start, filters.end = range_.start, range_.end
    trades = fetch_trades(db, filters)
    return rolling_metrics(daily_breakdown(trades), window)


@router.get("/calendar")
def calendar(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    filters: TradeFiltersDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> dict[str, Any]:
    """Per-day figures for a calendar month, plus per-week roll-ups."""
    today = date.today()
    if month:
        year, mon = (int(part) for part in month.split("-"))
    else:
        year, mon = today.year, today.month

    first = date(year, mon, 1)
    last = date(year + (mon == 12), (mon % 12) + 1, 1) - timedelta(days=1)

    filters.start, filters.end = first, last
    filters.include_excluded = True
    trades = fetch_trades(db, filters)

    stats = summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=_account_size(db, config, filters.account_id),
        period_start=first,
        period_end=last,
    )
    days = {str(d["date"]): d for d in stats["daily"]}

    notes = db.scalars(select(DayNote).where(DayNote.day >= first, DayNote.day <= last)).all()
    for note in notes:
        key = str(note.day)
        day = days.setdefault(
            key,
            {
                "date": note.day,
                "net_pnl": 0.0,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "r": 0.0,
                "win_rate": None,
                "volume": 0.0,
                "commission": 0.0,
                "swap": 0.0,
            },
        )
        day["note"] = note.content
        day["mood"] = note.mood

    week_start_monday = config["general"].get("week_starts_on", "monday") == "monday"
    weeks: dict[str, dict[str, Any]] = {}
    for day in days.values():
        d: date = day["date"] if isinstance(day["date"], date) else date.fromisoformat(day["date"])
        offset = d.weekday() if week_start_monday else (d.weekday() + 1) % 7
        week_key = str(d - timedelta(days=offset))
        bucket = weeks.setdefault(
            week_key,
            {"week_start": week_key, "net_pnl": 0.0, "trades": 0, "days": 0, "r": 0.0},
        )
        bucket["net_pnl"] += day["net_pnl"]
        bucket["trades"] += day["trades"]
        bucket["r"] += day.get("r") or 0.0
        if day["trades"]:
            bucket["days"] += 1

    for bucket in weeks.values():
        bucket["net_pnl"] = round(bucket["net_pnl"], 2)
        bucket["r"] = round(bucket["r"], 2)

    return {
        "month": f"{year:04d}-{mon:02d}",
        "start": first,
        "end": last,
        "days": sorted(days.values(), key=lambda d: str(d["date"])),
        "weeks": sorted(weeks.values(), key=lambda w: w["week_start"]),
        "summary": {
            key: stats[key]
            for key in (
                "net_pnl", "win_rate", "profit_factor", "counts", "total_r", "days", "expectancy"
            )
        },
    }


@router.get("/day/{day}")
def day_detail(
    day: date,
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    filters: TradeFiltersDep,
) -> dict[str, Any]:
    filters.start, filters.end = day, day
    filters.include_open = True
    filters.include_excluded = True
    trades = fetch_trades(db, filters)
    stats = summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=_account_size(db, config, filters.account_id),
        period_start=day,
        period_end=day,
    )
    note = db.scalar(select(DayNote).where(DayNote.day == day))
    return {
        "date": day,
        "summary": {k: v for k, v in stats.items() if k not in ("equity_curve", "daily")},
        "equity_curve": stats["equity_curve"],
        "trade_ids": [t.id for t in trades],
        "note": {"content": note.content, "mood": note.mood} if note else None,
    }


@router.get("/streaks")
def streak_detail(
    _user: CurrentUser, db: DbSession, config: AppConfig, filters: TradeFiltersDep
) -> dict[str, Any]:
    """All-time context that is deliberately independent of the date picker."""
    filters.start = filters.end = None
    filters.include_excluded = True
    trades = fetch_trades(db, filters)
    stats = summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=_account_size(db, config, filters.account_id),
    )
    first_trade = db.scalar(select(Trade.opened_at).order_by(Trade.opened_at.asc()).limit(1))
    return {
        "all_time": {k: v for k, v in stats.items() if k not in ("equity_curve", "daily")},
        "first_trade_at": first_trade,
    }
