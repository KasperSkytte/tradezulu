"""Statistics, breakdowns and the calendar feed."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import AppConfig, CurrentUser, DateRangeDep, DbSession, get_default_account
from ..models import DayNote, EquityPoint, Trade
from ..services.aggregation import resolve_account_size
from ..services.balances import attach_daily_returns, opening_balance
from ..services.metrics import breakdowns, distributions, rolling_metrics, summarize
from ..services.queries import TradeFilters, TradeFiltersDep, fetch_trades

router = APIRouter(prefix="/stats", tags=["stats"])


def _account_size(db, config: dict[str, Any], account_id: int | None) -> float:
    from ..models import Account

    account = db.get(Account, account_id) if account_id else get_default_account(db)
    return resolve_account_size(account, config["risk"])


def _scoped_account(db, filters, trades: Sequence[Any]) -> int | None:
    """Which account the figures are about, when there is only one.

    Taken from the trades in scope before the filter, because an unfiltered
    view of an installation with a single account is still about that account
    -- and its balance is what every percentage on the page divides by.
    """
    if filters.account_id:
        return int(filters.account_id)
    ids = {t.account_id for t in trades}
    if len(ids) == 1:
        return int(next(iter(ids)))
    account = get_default_account(db)
    return account.id if account is not None else None


def _one_account(trades: Sequence[Any]) -> bool:
    """Whether every trade in scope belongs to the same account.

    Decided from the trades rather than from the filter, so an unfiltered view
    of an installation with one account still gets its balance-relative
    figures. It is having several accounts in the pile that makes a return or a
    drawdown undefined, not having left the filter empty.
    """
    return len({t.account_id for t in trades}) <= 1


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

    # Measured against what the account was worth when the period began, not
    # against its starting deposit. A period is a window on an account that
    # has been growing or shrinking all along, and judging this month against
    # January's balance describes a different month.
    single = _one_account(trades)
    account_id = _scoped_account(db, filters, trades) if single else None
    opening = opening_balance(db, account_id, range_.start) or 0.0
    out = summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=opening,
        period_start=range_.start,
        period_end=range_.end,
        single_account=single,
    )
    out["opening_balance"] = round(opening, 2) if single else None
    out["return_pct"] = (
        round((out.get("net_pnl") or 0.0) / opening * 100.0, 4)
        if single and opening > 0
        else None
    )
    return out


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
            single_account=_one_account(trades),
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
    out = breakdowns(trades, config["risk"].get("breakeven_handling", "excluded"))
    # Lets the page express a row as a share of the account as well as in money
    # or R. Sent rather than assumed, because 0 means "unknown" and the UI has
    # to leave the percentage out rather than divide by it.
    out["account_size"] = _account_size(db, config, filters.account_id)
    return out


@router.get("/distributions")
def get_distributions(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    range_: DateRangeDep,
    filters: TradeFiltersDep,
) -> dict[str, Any]:
    """The shape of planned and realised R, as box plots."""
    filters.start, filters.end = range_.start, range_.end
    trades = fetch_trades(db, filters)
    return {
        "series": distributions(trades, config["risk"].get("breakeven_handling", "excluded"))
    }


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

    # What the account was worth on the morning of the first of the month, so
    # each day can be read against where the account actually stood rather than
    # against a fixed number. Winning 50 on a 200 account is +25%, and saying
    # +0.2% of some configured size describes a different account.
    single = _one_account(trades)
    account_id = _scoped_account(db, filters, trades) if single else None
    opening = opening_balance(db, account_id, first) or 0.0

    stats = summarize(
        trades,
        risk_cfg=config["risk"],
        stats_cfg=config["stats"],
        score_cfg=config["zulu_score"],
        account_size=_account_size(db, config, filters.account_id) if single else 0.0,
        period_start=first,
        period_end=last,
        single_account=single,
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

    # Days first: each one carries the balance it opened with, and a week opens
    # with whatever its earliest day did.
    dated = attach_daily_returns(
        db, account_id, sorted(days.values(), key=lambda d: str(d["date"]))
    )

    week_start_monday = config["general"].get("week_starts_on", "monday") == "monday"
    weeks: dict[str, dict[str, Any]] = {}
    for day in dated:
        d: date = day["date"] if isinstance(day["date"], date) else date.fromisoformat(day["date"])
        offset = d.weekday() if week_start_monday else (d.weekday() + 1) % 7
        week_key = str(d - timedelta(days=offset))
        bucket = weeks.setdefault(
            week_key,
            {
                "week_start": week_key,
                "net_pnl": 0.0,
                "trades": 0,
                "days": 0,
                "r": 0.0,
                "start_balance": None,
            },
        )
        bucket["net_pnl"] += day["net_pnl"]
        bucket["trades"] += day["trades"]
        bucket["r"] += day.get("r") or 0.0
        if day["trades"]:
            bucket["days"] += 1
        # The earliest day in the week that has one, since `dated` is sorted.
        if bucket["start_balance"] is None and day.get("start_balance"):
            bucket["start_balance"] = day["start_balance"]

    for bucket in weeks.values():
        bucket["net_pnl"] = round(bucket["net_pnl"], 2)
        bucket["r"] = round(bucket["r"], 2)
        # The week measured against the money it started with, the same way a
        # day is measured against the previous close. Compounding follows on
        # its own: a good week makes the next one a smaller percentage.
        #
        # Deliberately not named `opening`: that is the month's, and is still
        # wanted below.
        week_opening = bucket["start_balance"]
        bucket["return_pct"] = (
            round(bucket["net_pnl"] / week_opening * 100.0, 4) if week_opening else None
        )

    return {
        "month": f"{year:04d}-{mon:02d}",
        "start": first,
        "end": last,
        # So a day can be shown as a share of the account rather than only in
        # currency. 2R at 1% risk is 2% of the account, and that is the number
        # most people actually judge a day by.
        "account_size": _account_size(db, config, filters.account_id) if single else None,
        "opening_balance": round(opening, 2) if single else None,
        "single_account": single,
        "days": dated,
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
    # The day against the balance it opened with, which is the previous day's
    # close. The same figure the calendar cell shows, so opening a day does not
    # quietly change what it is being measured against.
    opening = opening_balance(db, _scoped_account(db, filters, trades), day) if _one_account(
        trades
    ) else None
    net = stats.get("net_pnl") or 0.0
    return {
        "date": day,
        "opening_balance": opening,
        "return_pct": round(net / opening * 100.0, 4) if opening else None,
        "summary": {k: v for k, v in stats.items() if k not in ("equity_curve", "daily")},
        "equity_curve": stats["equity_curve"],
        "trade_ids": [t.id for t in trades],
        "note": {"content": note.content, "mood": note.mood} if note else None,
    }


@router.get("/equity")
def equity(
    _user: CurrentUser,
    db: DbSession,
    account_id: Annotated[int | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Balance and equity over time, as the terminal reported them.

    Balance alone is a step function -- it only moves when something closes --
    so a trade that ran to +3R and was handed back looks exactly like one that
    crawled to its exit. Equity is what was on the table at the time, and the
    gap between the lines is the part worth looking at.

    Samples only exist from the first time a terminal reported in. There is
    nothing to reconstruct them from before that, so the series starts when
    the account did rather than pretending to cover its history.
    """
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    query = select(EquityPoint).where(EquityPoint.time >= since)
    if account_id is not None:
        query = query.where(EquityPoint.account_id == account_id)

    points = list(db.scalars(query.order_by(EquityPoint.time)).all())

    # Every account samples on its own heartbeat, so without an account this
    # query returns them interleaved by time -- one row at 240, the next at
    # 10,000, and a "series" that is really two accounts taking turns. Read as
    # one line that swings by the difference between the accounts on every
    # sample, which is not a curve anyone held.
    single = len({p.account_id for p in points}) <= 1
    if not single:
        points = []

    return {
        "points": [
            {
                "time": p.time.replace(tzinfo=timezone.utc).isoformat(),
                "balance": round(p.balance, 2),
                "equity": round(p.equity, 2),
                "open_positions": p.open_positions,
            }
            for p in points
        ],
        "single_account": single,
        # So the UI can say why it is empty rather than drawing nothing.
        "sampling": (
            "Recorded from each terminal report; not backfilled."
            if single
            else "An equity curve belongs to one account. Pick one to see it."
        ),
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
