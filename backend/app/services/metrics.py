"""Performance statistics over a set of trades.

All numbers here are computed from already-derived trade rows (see
``aggregation.compute_derived``), so a settings change only requires a
recompute pass, never a re-import.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ..models import Trade

# Sentinel used when profit factor is infinite (losses == 0).
PF_INFINITE = 999.0


def _r(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(value, digits)


@dataclass
class TradeSets:
    """Trades split by how they should be treated statistically."""

    all_closed: list[Trade]
    scored: list[Trade]  # counted in win rate / averages
    wins: list[Trade]
    losses: list[Trade]
    breakevens: list[Trade]
    open_trades: list[Trade]
    excluded: list[Trade]


def split_trades(trades: Iterable[Trade], breakeven_handling: str = "excluded") -> TradeSets:
    all_closed: list[Trade] = []
    open_trades: list[Trade] = []
    excluded: list[Trade] = []
    breakevens: list[Trade] = []
    wins: list[Trade] = []
    losses: list[Trade] = []

    for trade in trades:
        if trade.excluded:
            excluded.append(trade)
            continue
        if trade.closed_at is None or trade.outcome == "open":
            open_trades.append(trade)
            continue
        all_closed.append(trade)
        if trade.outcome == "breakeven":
            breakevens.append(trade)
        elif trade.outcome == "win":
            wins.append(trade)
        else:
            losses.append(trade)

    if breakeven_handling == "win":
        wins = wins + breakevens
        scored = all_closed
    elif breakeven_handling == "loss":
        losses = losses + breakevens
        scored = all_closed
    else:  # excluded -- the default: a breakeven was a wasted effort, not a result
        scored = wins + losses

    scored = sorted(scored, key=lambda t: (t.closed_at or t.opened_at))
    return TradeSets(
        all_closed=sorted(all_closed, key=lambda t: (t.closed_at or t.opened_at)),
        scored=scored,
        wins=wins,
        losses=losses,
        breakevens=breakevens,
        open_trades=open_trades,
        excluded=excluded,
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_drawdown(
    pnls: Sequence[float], account_size: float
) -> tuple[float, float | None, list[float]]:
    """Peak-to-trough drawdown over the running equity curve.

    Returns (max drawdown in money, max drawdown in percent, per-point drawdown).
    """
    equity = account_size if account_size > 0 else 0.0
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    series: list[float] = []
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        series.append(dd)
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak * 100.0)
    pct = max_dd_pct if account_size > 0 else None
    return max_dd, pct, series


def compute_sharpe(
    daily_pnl: Sequence[float],
    account_size: float,
    risk_free_rate: float,
    periods_per_year: int,
) -> tuple[float | None, float | None]:
    """Annualised Sharpe and Sortino from a daily P&L series."""
    if len(daily_pnl) < 2:
        return None, None

    if account_size > 0:
        returns = [p / account_size for p in daily_pnl]
        rf_per_period = (risk_free_rate / 100.0) / periods_per_year
    else:
        # Sharpe is scale invariant, so raw P&L works when no account size is
        # known -- but a risk-free rate cannot be expressed without one.
        returns = list(daily_pnl)
        rf_per_period = 0.0

    excess = [r - rf_per_period for r in returns]
    mean_excess = statistics.fmean(excess)
    stdev = statistics.stdev(excess)
    sharpe = (mean_excess / stdev) * math.sqrt(periods_per_year) if stdev > 0 else None

    downside = [min(0.0, r) for r in excess]
    downside_dev = math.sqrt(sum(d * d for d in downside) / len(downside))
    sortino = (mean_excess / downside_dev) * math.sqrt(periods_per_year) if downside_dev > 0 else None

    return sharpe, sortino


def compute_streaks(trades: Sequence[Trade]) -> dict[str, Any]:
    max_win = max_loss = 0
    run_win = run_loss = 0
    current = 0
    for trade in trades:
        if trade.outcome == "win":
            run_win += 1
            run_loss = 0
            max_win = max(max_win, run_win)
            current = run_win
        elif trade.outcome == "loss":
            run_loss += 1
            run_win = 0
            max_loss = max(max_loss, run_loss)
            current = -run_loss
    return {
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
        "current_streak": current,
    }


def daily_breakdown(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    buckets: dict[date, dict[str, Any]] = {}
    for trade in trades:
        day = trade.trade_date or (trade.closed_at or trade.opened_at).date()
        bucket = buckets.setdefault(
            day,
            {
                "date": day,
                "net_pnl": 0.0,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "r": 0.0,
                "volume": 0.0,
                "commission": 0.0,
                "swap": 0.0,
            },
        )
        bucket["net_pnl"] += trade.net_pnl or 0.0
        bucket["trades"] += 1
        bucket["volume"] += trade.volume or 0.0
        bucket["commission"] += trade.commission or 0.0
        bucket["swap"] += trade.swap or 0.0
        if trade.realized_r is not None:
            bucket["r"] += trade.realized_r
        if trade.outcome == "win":
            bucket["wins"] += 1
        elif trade.outcome == "loss":
            bucket["losses"] += 1
        elif trade.outcome == "breakeven":
            bucket["breakevens"] += 1

    out = []
    for bucket in sorted(buckets.values(), key=lambda b: b["date"]):
        scored = bucket["wins"] + bucket["losses"]
        bucket["net_pnl"] = round(bucket["net_pnl"], 2)
        bucket["r"] = round(bucket["r"], 3)
        bucket["win_rate"] = round(bucket["wins"] / scored * 100, 1) if scored else None
        out.append(bucket)
    return out


def equity_curve(trades: Sequence[Trade], account_size: float) -> list[dict[str, Any]]:
    cum_pnl = 0.0
    cum_r = 0.0
    peak = account_size if account_size > 0 else 0.0
    points: list[dict[str, Any]] = []
    for trade in trades:
        cum_pnl += trade.net_pnl
        cum_r += trade.realized_r or 0.0
        equity = (account_size if account_size > 0 else 0.0) + cum_pnl
        peak = max(peak, equity)
        points.append(
            {
                "trade_id": trade.id,
                "time": (trade.closed_at or trade.opened_at),
                "symbol": trade.symbol,
                "net_pnl": round(trade.net_pnl, 2),
                "cum_pnl": round(cum_pnl, 2),
                "cum_r": round(cum_r, 3),
                "equity": round(equity, 2),
                "drawdown": round(peak - equity, 2),
            }
        )
    return points


def consistency_score(daily: Sequence[dict[str, Any]]) -> float:
    """How much of the profit came from more than one lucky day.

    100 means profit was spread perfectly evenly across all winning days; 0
    means a single day carried everything.
    """
    winning = [d["net_pnl"] for d in daily if d["net_pnl"] > 0]
    if not winning:
        return 0.0
    total = sum(winning)
    if total <= 0:
        return 0.0
    largest = max(winning)
    return max(0.0, min(100.0, (1.0 - largest / total) * 100.0))


def zulu_score(
    summary: dict[str, Any],
    config: dict[str, Any],
    sample_size: int | None = None,
    min_trades: int = 0,
) -> dict[str, Any]:
    """A single 0-100 read on the account, built from six weighted components."""
    targets = config.get("targets", {})
    weights = config.get("weights", {})

    if sample_size == 0:
        return {
            "score": 0.0,
            "components": dict.fromkeys(
                ("win_rate", "profit_factor", "avg_win_loss", "max_drawdown",
                 "recovery_factor", "consistency")
            ),
            "targets": targets,
            "weights": weights,
            "sample_size": 0,
            "min_trades": min_trades,
            "sufficient": False,
        }

    def ratio_component(value: float | None, target: float) -> float:
        if value is None or target <= 0:
            return 0.0
        return max(0.0, min(100.0, value / target * 100.0))

    profit_factor = summary.get("profit_factor")
    if profit_factor is not None and profit_factor >= PF_INFINITE:
        pf_component = 100.0
    else:
        pf_component = ratio_component(profit_factor, float(targets.get("profit_factor", 2.0)))

    drawdown_pct = summary.get("max_drawdown_pct")
    dd_target = float(targets.get("max_drawdown", 20.0))
    if drawdown_pct is None:
        dd_component = None
    elif dd_target <= 0:
        dd_component = 0.0
    else:
        dd_component = max(0.0, min(100.0, (1.0 - drawdown_pct / dd_target) * 100.0))

    components = {
        "win_rate": ratio_component(summary.get("win_rate"), float(targets.get("win_rate", 55.0))),
        "profit_factor": pf_component,
        "avg_win_loss": ratio_component(
            summary.get("payoff_ratio"), float(targets.get("avg_win_loss", 2.0))
        ),
        "max_drawdown": dd_component,
        "recovery_factor": ratio_component(
            summary.get("recovery_factor"), float(targets.get("recovery_factor", 3.0))
        ),
        "consistency": ratio_component(
            summary.get("consistency"), float(targets.get("consistency", 100.0))
        ),
    }

    total_weight = 0.0
    weighted = 0.0
    for key, value in components.items():
        if value is None:
            continue
        weight = float(weights.get(key, 1.0) or 0.0)
        if weight <= 0:
            continue
        weighted += value * weight
        total_weight += weight

    score = weighted / total_weight if total_weight else 0.0
    return {
        "score": round(score, 1),
        "components": {k: (None if v is None else round(v, 1)) for k, v in components.items()},
        "targets": targets,
        "weights": weights,
        "sample_size": sample_size,
        "min_trades": min_trades,
        # Below this many trades the score is noise rather than signal.
        "sufficient": sample_size is None or sample_size >= min_trades,
    }


def summarize(
    trades: Sequence[Trade],
    *,
    risk_cfg: dict[str, Any],
    stats_cfg: dict[str, Any],
    score_cfg: dict[str, Any],
    account_size: float,
    period_start: date | None = None,
    period_end: date | None = None,
    single_account: bool = True,
) -> dict[str, Any]:
    """The full statistics payload for one period.

    ``single_account`` says whether every trade belongs to the same account.
    When it does not, the figures that need one account's money or one
    account's equity curve are withheld rather than computed -- see
    :func:`_withhold_cross_account`.
    """
    sets = split_trades(trades, risk_cfg.get("breakeven_handling", "excluded"))

    scored = sets.scored
    wins, losses, breakevens = sets.wins, sets.losses, sets.breakevens

    win_pnls = [t.net_pnl for t in wins]
    loss_pnls = [t.net_pnl for t in losses]
    gross_profit = sum(p for p in win_pnls if p > 0)
    gross_loss = abs(sum(p for p in loss_pnls if p < 0))

    net_pnl = sum(t.net_pnl for t in sets.all_closed)
    scored_net = sum(t.net_pnl for t in scored)

    n_scored = len(scored)
    n_wins, n_losses = len(wins), len(losses)
    decided = n_wins + n_losses
    win_rate = (n_wins / decided * 100.0) if decided else None

    avg_win = _mean(win_pnls)
    avg_loss = _mean(loss_pnls)
    payoff = (avg_win / abs(avg_loss)) if (avg_win and avg_loss and avg_loss != 0) else None

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = PF_INFINITE
    else:
        profit_factor = None

    win_rs = [t.realized_r for t in wins if t.realized_r is not None]
    loss_rs = [t.realized_r for t in losses if t.realized_r is not None]
    all_rs = [t.realized_r for t in scored if t.realized_r is not None]
    planned_rs = [t.planned_r for t in sets.all_closed if t.planned_r is not None]

    curve = equity_curve(sets.all_closed, account_size)
    max_dd, max_dd_pct, _ = compute_drawdown([t.net_pnl for t in sets.all_closed], account_size)
    recovery_factor = (net_pnl / max_dd) if max_dd > 0 and net_pnl > 0 else (0.0 if max_dd > 0 else None)

    daily = daily_breakdown(sets.all_closed)
    daily_pnls = [d["net_pnl"] for d in daily]
    sharpe, sortino = compute_sharpe(
        daily_pnls,
        account_size,
        float(stats_cfg.get("risk_free_rate", 0.0) or 0.0),
        int(stats_cfg.get("trading_days_per_year", 252) or 252),
    )
    if stats_cfg.get("sharpe_basis") == "trade":
        sharpe, sortino = compute_sharpe(
            [t.net_pnl for t in sets.all_closed],
            account_size,
            0.0,
            int(stats_cfg.get("trading_days_per_year", 252) or 252),
        )

    green_days = sum(1 for d in daily if d["net_pnl"] > 0)
    red_days = sum(1 for d in daily if d["net_pnl"] < 0)
    flat_days = len(daily) - green_days - red_days

    durations = [t.duration_seconds for t in sets.all_closed if t.duration_seconds is not None]
    win_durations = [t.duration_seconds for t in wins if t.duration_seconds is not None]
    loss_durations = [t.duration_seconds for t in losses if t.duration_seconds is not None]

    kelly = None
    if win_rate is not None and payoff and payoff > 0:
        w = win_rate / 100.0
        kelly = (w - (1 - w) / payoff) * 100.0

    consistency = consistency_score(daily)

    summary: dict[str, Any] = {
        "period": {
            "start": period_start,
            "end": period_end,
        },
        "counts": {
            "total": len(sets.all_closed),
            "scored": n_scored,
            "wins": n_wins,
            "losses": n_losses,
            "breakevens": len(breakevens),
            "open": len(sets.open_trades),
            "excluded": len(sets.excluded),
        },
        "net_pnl": _r(net_pnl),
        "scored_net_pnl": _r(scored_net),
        "gross_profit": _r(gross_profit),
        "gross_loss": _r(gross_loss),
        "commission": _r(sum(t.commission for t in sets.all_closed)),
        "swap": _r(sum(t.swap for t in sets.all_closed)),
        "breakeven_pnl": _r(sum(t.net_pnl for t in breakevens)),
        "breakeven_rate": _r(
            len(breakevens) / len(sets.all_closed) * 100 if sets.all_closed else None, 1
        ),
        "win_rate": _r(win_rate, 1),
        "loss_rate": _r(100 - win_rate if win_rate is not None else None, 1),
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "avg_trade": _r(scored_net / n_scored if n_scored else None),
        "payoff_ratio": _r(payoff),
        "profit_factor": _r(profit_factor),
        "expectancy": _r(scored_net / n_scored if n_scored else None),
        "largest_win": _r(max(win_pnls) if win_pnls else None),
        "largest_loss": _r(min(loss_pnls) if loss_pnls else None),
        "avg_win_r": _r(_mean(win_rs), 2),
        "avg_loss_r": _r(_mean(loss_rs), 2),
        "expectancy_r": _r(_mean(all_rs), 3),
        "total_r": _r(sum(all_rs) if all_rs else None, 2),
        "avg_planned_r": _r(_mean(planned_rs), 2),
        "avg_realized_r": _r(_mean(all_rs), 2),
        "plan_adherence": _r(
            (_mean(all_rs) / _mean(planned_rs) * 100)
            if (all_rs and planned_rs and _mean(planned_rs))
            else None,
            1,
        ),
        "avg_risk": _r(_mean([t.risk_amount for t in sets.all_closed if t.risk_amount])),
        "max_drawdown": _r(max_dd),
        "max_drawdown_pct": _r(max_dd_pct, 2),
        "recovery_factor": _r(recovery_factor),
        "sharpe": _r(sharpe),
        "sortino": _r(sortino),
        "kelly": _r(kelly, 1),
        "consistency": _r(consistency, 1),
        "volume": _r(sum(t.volume for t in sets.all_closed)),
        "streaks": compute_streaks(sets.all_closed),
        "durations": {
            "avg": int(_mean(durations) or 0) if durations else None,
            "avg_win": int(_mean(win_durations) or 0) if win_durations else None,
            "avg_loss": int(_mean(loss_durations) or 0) if loss_durations else None,
        },
        "days": {
            "total": len(daily),
            "green": green_days,
            "red": red_days,
            "flat": flat_days,
            "win_rate": _r(green_days / (green_days + red_days) * 100, 1)
            if (green_days + red_days)
            else None,
            "best": _r(max(daily_pnls) if daily_pnls else None),
            "worst": _r(min(daily_pnls) if daily_pnls else None),
            "avg": _r(_mean(daily_pnls)),
        },
        "account_size": _r(account_size),
    }

    summary["zulu_score"] = zulu_score(
        summary,
        score_cfg,
        sample_size=len(sets.all_closed),
        min_trades=int(stats_cfg.get("min_trades_for_score", 0) or 0),
    )
    summary["equity_curve"] = curve
    summary["daily"] = daily
    summary["single_account"] = single_account
    if not single_account:
        _withhold_cross_account(summary)
    return summary


#: Figures that describe one account and mean nothing across several. Each
#: either divides by a balance -- and there is no single balance to divide by --
#: or reads an equity curve, which cannot be built by interleaving the trades of
#: accounts that were never one pool of money.
CROSS_ACCOUNT_UNDEFINED = (
    "account_size",
    "max_drawdown",
    "max_drawdown_pct",
    "recovery_factor",
    "sharpe",
    "sortino",
)


def _withhold_cross_account(summary: dict[str, Any]) -> None:
    """Blank the per-account figures on a summary spanning several accounts.

    Withheld rather than wrong. A drawdown stitched together from two accounts
    describes a portfolio nobody held, and a return measured by dividing the
    combined profit by whichever balance happened to be handy is worse than no
    number at all -- it looks authoritative and is off by whatever the other
    accounts are worth.

    What survives is everything that is a plain count or sum: net P&L, win rate,
    profit factor, expectancy, the R totals. Those add up across accounts
    honestly.
    """
    for key in CROSS_ACCOUNT_UNDEFINED:
        summary[key] = None
    summary["equity_curve"] = []
    # The score is a single read on one account, and two of its six components
    # have just been withheld. A number built from the rest would not be
    # comparable with any per-account score.
    summary["zulu_score"] = {
        "score": None,
        "components": dict.fromkeys(
            ("win_rate", "profit_factor", "avg_win_loss", "max_drawdown",
             "recovery_factor", "consistency")
        ),
        "targets": {},
        "weights": {},
        "sample_size": None,
        "min_trades": 0,
        "sufficient": False,
        "unavailable_reason": "several accounts",
    }
    for day in summary.get("daily") or []:
        day["return_pct"] = None
        day.pop("start_balance", None)


# ---------------------------------------------------------------------------
# Breakdowns for the reports page
# ---------------------------------------------------------------------------

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DURATION_BUCKETS: list[tuple[str, int]] = [
    ("< 1 min", 60),
    ("1-5 min", 300),
    ("5-15 min", 900),
    ("15-60 min", 3600),
    ("1-4 h", 14400),
    ("4-24 h", 86400),
    ("> 1 day", 10**9),
]

R_BUCKETS: list[tuple[str, float, float]] = [
    ("< -2R", -1e9, -2.0),
    ("-2R..-1R", -2.0, -1.0),
    ("-1R..0R", -1.0, 0.0),
    ("0R..1R", 0.0, 1.0),
    ("1R..2R", 1.0, 2.0),
    ("2R..3R", 2.0, 3.0),
    ("> 3R", 3.0, 1e9),
]


def _group_stats(trades: Sequence[Trade], breakeven_handling: str) -> dict[str, Any]:
    sets = split_trades(trades, breakeven_handling)
    wins, losses = sets.wins, sets.losses
    decided = len(wins) + len(losses)
    gross_profit = sum(t.net_pnl for t in wins if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in losses if t.net_pnl < 0))
    rs = [t.realized_r for t in sets.all_closed if t.realized_r is not None]
    return {
        "trades": len(sets.all_closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(sets.breakevens),
        "net_pnl": _r(sum(t.net_pnl for t in sets.all_closed)),
        "win_rate": _r(len(wins) / decided * 100 if decided else None, 1),
        "profit_factor": _r(
            gross_profit / gross_loss
            if gross_loss > 0
            else (PF_INFINITE if gross_profit > 0 else None)
        ),
        "total_r": _r(sum(rs) if rs else None, 2),
        "avg_r": _r(_mean(rs), 3),
        "volume": _r(sum(t.volume for t in sets.all_closed), 2),
    }


def breakdowns(
    trades: Sequence[Trade], breakeven_handling: str, tz_offsets: bool = True
) -> dict[str, Any]:
    """Group trades along the dimensions the reports page visualises."""
    closed = [t for t in trades if t.closed_at is not None and not t.excluded]

    def grouped(key_fn, order: list[str] | None = None) -> list[dict[str, Any]]:
        buckets: dict[str, list[Trade]] = defaultdict(list)
        for trade in closed:
            key = key_fn(trade)
            if key is None:
                continue
            buckets[str(key)].append(trade)
        rows = [
            {"key": key, **_group_stats(items, breakeven_handling)}
            for key, items in buckets.items()
        ]
        if order:
            index = {name: i for i, name in enumerate(order)}
            rows.sort(key=lambda row: index.get(row["key"], len(order)))
        else:
            rows.sort(key=lambda row: row["net_pnl"] or 0, reverse=True)
        return rows

    def duration_bucket(trade: Trade) -> str | None:
        if trade.duration_seconds is None:
            return None
        for name, limit in DURATION_BUCKETS:
            if trade.duration_seconds < limit:
                return name
        return DURATION_BUCKETS[-1][0]

    def r_bucket(trade: Trade) -> str | None:
        if trade.realized_r is None:
            return None
        for name, low, high in R_BUCKETS:
            if low <= trade.realized_r < high:
                return name
        return R_BUCKETS[-1][0]

    tag_buckets: dict[str, list[Trade]] = defaultdict(list)
    for trade in closed:
        for tag in trade.tags:
            tag_buckets[tag.name].append(trade)
    tags = [{"key": k, **_group_stats(v, breakeven_handling)} for k, v in tag_buckets.items()]
    tags.sort(key=lambda row: row["net_pnl"] or 0)

    return {
        "by_symbol": grouped(lambda t: t.symbol),
        "by_direction": grouped(lambda t: t.direction, ["long", "short"]),
        "by_weekday": grouped(
            lambda t: WEEKDAYS[(t.trade_date or t.closed_at.date()).weekday()], WEEKDAYS
        ),
        "by_hour": grouped(lambda t: f"{t.opened_at.hour:02d}:00", [f"{h:02d}:00" for h in range(24)]),
        "by_duration": grouped(duration_bucket, [name for name, _ in DURATION_BUCKETS]),
        "by_r_multiple": grouped(r_bucket, [name for name, _, _ in R_BUCKETS]),
        "by_setup": grouped(lambda t: t.setup or None),
        "by_tag": tags,
    }


def rolling_metrics(daily: Sequence[dict[str, Any]], window: int = 20) -> list[dict[str, Any]]:
    """Rolling win rate and expectancy for the reports page."""
    out = []
    for i in range(len(daily)):
        chunk = daily[max(0, i - window + 1) : i + 1]
        wins = sum(c["wins"] for c in chunk)
        losses = sum(c["losses"] for c in chunk)
        decided = wins + losses
        out.append(
            {
                "date": daily[i]["date"],
                "win_rate": round(wins / decided * 100, 1) if decided else None,
                "net_pnl": round(sum(c["net_pnl"] for c in chunk), 2),
            }
        )
    return out


def period_bounds(period: str, today: date, week_starts_on: str = "monday") -> tuple[date, date]:
    """Translate the UI's period presets into concrete dates."""
    if period == "today":
        return today, today
    if period == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if period == "this_week":
        offset = today.weekday() if week_starts_on == "monday" else (today.weekday() + 1) % 7
        return today - timedelta(days=offset), today
    if period == "last_week":
        offset = today.weekday() if week_starts_on == "monday" else (today.weekday() + 1) % 7
        start_this = today - timedelta(days=offset)
        return start_this - timedelta(days=7), start_this - timedelta(days=1)
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if period == "last_7_days":
        return today - timedelta(days=6), today
    if period == "last_30_days":
        return today - timedelta(days=29), today
    if period == "last_90_days":
        return today - timedelta(days=89), today
    if period == "last_180_days":
        return today - timedelta(days=179), today
    if period == "this_quarter":
        quarter_start_month = 3 * ((today.month - 1) // 3) + 1
        return today.replace(month=quarter_start_month, day=1), today
    if period == "this_year":
        return today.replace(month=1, day=1), today
    if period == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if period == "all":
        return date(1970, 1, 1), today
    return today - timedelta(days=29), today


def symbol_counter(trades: Iterable[Trade]) -> list[tuple[str, int]]:
    return Counter(t.symbol for t in trades).most_common()


def to_naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value
