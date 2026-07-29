"""Whether a copy is allowed, and what to do about positions already open.

Two kinds of rule live here:

* **gates** — asked before opening a copy. A gate that refuses stops that one
  trade; it never touches anything already running.
* **guards** — evaluated continuously against the slave's whole account. A
  guard that trips is an account-level event: by default it flattens the
  account and stops copying until the next trading day.

Both are pure functions over a snapshot, so the entire rule set is covered by
tests rather than by finding out on a live account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .sizing import MasterTrade, SymbolSpec, money_at_risk


class Verdict(str, Enum):
    ALLOW = "allow"
    #: Refuse this trade, carry on copying others.
    SKIP = "skip"
    #: Account-level stop: no more opening today.
    HALT = "halt"


class BreachAction(str, Enum):
    #: Stop opening but keep mirroring stops and closes on what is open.
    STOP_OPENING = "stop_opening"
    #: Close every copied position at once, then stop opening.
    CLOSE_ALL = "close_all"
    #: Only the equity stop flattens; the softer limits merely stop opening.
    FLATTEN_ON_EQUITY_STOP = "flatten_on_equity_stop"


@dataclass(frozen=True)
class OpenPosition:
    """A position already open on the slave."""

    symbol: str
    direction: str
    volume: float
    entry_price: float
    profit: float = 0.0
    stop_loss: float | None = None
    master_position_id: int | None = None


@dataclass(frozen=True)
class SlaveSnapshot:
    """Everything the rules need to know about the slave right now."""

    balance: float
    equity: float
    #: Equity at the start of the current trading day.
    day_start_equity: float
    #: Highest equity ever seen, for a trailing-style equity stop.
    peak_equity: float
    open_positions: list[OpenPosition] = field(default_factory=list)
    #: Realised profit so far today.
    day_realised_pnl: float = 0.0
    #: Realised profit per day, used by the consistency rule.
    realised_by_day: dict[date, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskConfig:
    """Per-slave limits. Zero means "no limit" throughout."""

    # -- per trade --------------------------------------------------------
    #: Refuse a copy whose stop-loss risk exceeds this share of equity.
    max_risk_percent_per_trade: float = 0.0
    #: Refuse a copy larger than this, in lots.
    max_lot_per_trade: float = 0.0
    #: Refuse a copy with no stop loss at all.
    require_stop_loss: bool = False

    # -- concurrency ------------------------------------------------------
    max_open_positions: int = 0
    #: Cap positions facing the same way, across all symbols.
    max_same_direction: int = 0
    #: Cap positions in one instrument.
    max_positions_per_symbol: int = 0
    #: Cap total lots open at once.
    max_total_lots: float = 0.0

    # -- account guards ---------------------------------------------------
    #: Stop for the day after losing this share of the day's opening equity.
    max_daily_drawdown_percent: float = 0.0
    #: Stop for good below this share of peak equity.
    equity_stop_percent: float = 0.0
    #: Absolute equity floor, in account currency.
    equity_stop_amount: float = 0.0
    breach_action: BreachAction = BreachAction.CLOSE_ALL

    # -- prop-firm shaping ------------------------------------------------
    #: Close a winner once it is this far in profit, in account currency.
    take_profit_at_amount: float = 0.0
    #: Same, expressed in R multiples of the trade's own risk.
    take_profit_at_r: float = 0.0
    #: Stop opening once the day's profit reaches this share of opening equity.
    daily_profit_target_percent: float = 0.0
    #: No single day may be more than this share of total profit. Blocks new
    #: trades once today's profit would break it.
    max_day_share_of_profit_percent: float = 0.0

    # -- instruments ------------------------------------------------------
    allowed_symbols: list[str] = field(default_factory=list)
    blocked_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    rule: str = ""

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


ALLOWED = Decision(Verdict.ALLOW, "allowed")


def check_account_guards(snapshot: SlaveSnapshot, config: RiskConfig) -> Decision:
    """Account-level limits. Checked before every copy and on a timer."""
    equity = snapshot.equity

    if config.equity_stop_amount > 0 and equity <= config.equity_stop_amount:
        return Decision(
            Verdict.HALT,
            f"equity {equity:,.2f} is at or below the {config.equity_stop_amount:,.2f} floor",
            "equity_stop_amount",
        )

    if config.equity_stop_percent > 0 and snapshot.peak_equity > 0:
        floor = snapshot.peak_equity * (1 - config.equity_stop_percent / 100.0)
        if equity <= floor:
            return Decision(
                Verdict.HALT,
                f"equity {equity:,.2f} is {config.equity_stop_percent:g}% below the "
                f"{snapshot.peak_equity:,.2f} peak",
                "equity_stop_percent",
            )

    if config.max_daily_drawdown_percent > 0 and snapshot.day_start_equity > 0:
        floor = snapshot.day_start_equity * (1 - config.max_daily_drawdown_percent / 100.0)
        if equity <= floor:
            return Decision(
                Verdict.HALT,
                f"down {config.max_daily_drawdown_percent:g}% from the day's opening "
                f"equity of {snapshot.day_start_equity:,.2f}",
                "max_daily_drawdown_percent",
            )

    if config.daily_profit_target_percent > 0 and snapshot.day_start_equity > 0:
        target = snapshot.day_start_equity * (config.daily_profit_target_percent / 100.0)
        if snapshot.day_realised_pnl >= target:
            return Decision(
                Verdict.HALT,
                f"the day's profit target of {target:,.2f} is met",
                "daily_profit_target_percent",
            )

    return ALLOWED


def check_consistency(snapshot: SlaveSnapshot, config: RiskConfig, today: date) -> Decision:
    """Prop-firm consistency: no one day may dominate the total profit."""
    limit = config.max_day_share_of_profit_percent
    if limit <= 0:
        return ALLOWED

    total = sum(value for value in snapshot.realised_by_day.values())
    total += snapshot.day_realised_pnl - snapshot.realised_by_day.get(today, 0.0)
    if total <= 0:
        return ALLOWED

    share = snapshot.day_realised_pnl / total * 100.0
    if share >= limit:
        return Decision(
            Verdict.HALT,
            f"today is {share:.1f}% of total profit, over the {limit:g}% consistency cap",
            "max_day_share_of_profit_percent",
        )
    return ALLOWED


def check_trade_gates(
    master: MasterTrade,
    volume: float,
    spec: SymbolSpec,
    snapshot: SlaveSnapshot,
    config: RiskConfig,
) -> Decision:
    """Per-trade limits, evaluated once the volume is known."""
    symbol = master.symbol.upper()

    if config.blocked_symbols and symbol in {s.upper() for s in config.blocked_symbols}:
        return Decision(Verdict.SKIP, f"{symbol} is on the blocked list", "blocked_symbols")

    if config.allowed_symbols and symbol not in {s.upper() for s in config.allowed_symbols}:
        return Decision(Verdict.SKIP, f"{symbol} is not on the allowed list", "allowed_symbols")

    if config.require_stop_loss and not master.stop_loss:
        return Decision(
            Verdict.SKIP, "the master trade has no stop loss", "require_stop_loss"
        )

    if config.max_lot_per_trade > 0 and volume > config.max_lot_per_trade:
        return Decision(
            Verdict.SKIP,
            f"{volume:g} lots is over the {config.max_lot_per_trade:g} per-trade cap",
            "max_lot_per_trade",
        )

    if config.max_risk_percent_per_trade > 0:
        risk = money_at_risk(volume, master.entry_price, master.stop_loss, spec)
        if risk is not None and snapshot.equity > 0:
            share = risk / snapshot.equity * 100.0
            # A trade sitting exactly on the limit is not over it. Without the
            # tolerance, floating point turns "risk 2% of equity, cap 2%" into
            # a refusal, which reads as a bug to anyone who set both numbers.
            if share > config.max_risk_percent_per_trade * (1 + 1e-9):
                return Decision(
                    Verdict.SKIP,
                    f"risking {share:.2f}% of equity, over the "
                    f"{config.max_risk_percent_per_trade:g}% cap",
                    "max_risk_percent_per_trade",
                )

    positions = snapshot.open_positions

    if config.max_open_positions > 0 and len(positions) >= config.max_open_positions:
        return Decision(
            Verdict.SKIP,
            f"{len(positions)} positions already open, at the "
            f"{config.max_open_positions} limit",
            "max_open_positions",
        )

    if config.max_same_direction > 0:
        same = sum(1 for p in positions if p.direction == master.direction)
        if same >= config.max_same_direction:
            return Decision(
                Verdict.SKIP,
                f"{same} {master.direction} positions already open, at the "
                f"{config.max_same_direction} limit",
                "max_same_direction",
            )

    if config.max_positions_per_symbol > 0:
        same_symbol = sum(1 for p in positions if p.symbol.upper() == symbol)
        if same_symbol >= config.max_positions_per_symbol:
            return Decision(
                Verdict.SKIP,
                f"{same_symbol} {symbol} positions already open, at the "
                f"{config.max_positions_per_symbol} limit",
                "max_positions_per_symbol",
            )

    if config.max_total_lots > 0:
        exposure = sum(p.volume for p in positions)
        if exposure + volume > config.max_total_lots:
            return Decision(
                Verdict.SKIP,
                f"{exposure:g} + {volume:g} lots would pass the "
                f"{config.max_total_lots:g} total exposure cap",
                "max_total_lots",
            )

    return ALLOWED


def positions_to_close_early(
    positions: list[OpenPosition], config: RiskConfig, specs: dict[str, SymbolSpec]
) -> list[tuple[OpenPosition, str]]:
    """Winners that prop-firm shaping says to bank now.

    A trade that runs to an unusually large win is exactly what trips a
    consistency rule, so the option exists to take it off before it gets
    there — by money, or in R multiples of what the trade was risking.
    """
    out: list[tuple[OpenPosition, str]] = []
    for position in positions:
        if config.take_profit_at_amount > 0 and position.profit >= config.take_profit_at_amount:
            out.append(
                (
                    position,
                    f"profit {position.profit:,.2f} reached the "
                    f"{config.take_profit_at_amount:,.2f} cap",
                )
            )
            continue

        if config.take_profit_at_r > 0 and position.stop_loss:
            spec = specs.get(position.symbol.upper())
            if spec is None:
                continue
            risk = money_at_risk(position.volume, position.entry_price, position.stop_loss, spec)
            if risk and risk > 0:
                r_multiple = position.profit / risk
                if r_multiple >= config.take_profit_at_r:
                    out.append(
                        (
                            position,
                            f"up {r_multiple:.2f}R, at the {config.take_profit_at_r:g}R cap",
                        )
                    )
    return out


def evaluate(
    master: MasterTrade,
    volume: float,
    spec: SymbolSpec,
    snapshot: SlaveSnapshot,
    config: RiskConfig,
    today: date,
) -> Decision:
    """The whole rule set for opening one copy, in precedence order."""
    for check in (
        check_account_guards(snapshot, config),
        check_consistency(snapshot, config, today),
    ):
        if not check.allowed:
            return check
    return check_trade_gates(master, volume, spec, snapshot, config)
