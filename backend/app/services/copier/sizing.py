"""How big a copied trade should be.

Pure functions: no database, no network, no broker. Everything the caller
needs to decide a volume is passed in, so every rule here is exercised by the
test suite rather than discovered in production with real money.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class SizingMode(str, Enum):
    """How a slave's volume is derived from the master's."""

    #: Always the same lot size, whatever the master did.
    FIXED_LOT = "fixed_lot"
    #: Master volume times a constant.
    MULTIPLIER = "multiplier"
    #: Scale by the ratio of account balances.
    BALANCE_RATIO = "balance_ratio"
    #: Scale by the ratio of account equity.
    EQUITY_RATIO = "equity_ratio"
    #: Risk a fixed percentage of the slave's equity on the master's stop
    #: distance. Falls back to balance ratio when there is no stop.
    RISK_PERCENT = "risk_percent"
    #: The same, measured against balance. Balance ignores open positions, so
    #: the size risked does not shrink while a trade is under water and grow
    #: while it is ahead -- which is what most people mean by "risk 1%".
    RISK_PERCENT_BALANCE = "risk_percent_balance"


@dataclass(frozen=True)
class SymbolSpec:
    """What the slave's broker will accept for this instrument."""

    symbol: str
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    #: Money per one whole price unit, for one lot (tick_value / tick_size).
    value_per_unit: float = 0.0
    digits: int = 5


@dataclass(frozen=True)
class MasterTrade:
    """The master position being copied."""

    symbol: str
    direction: str  # long | short
    volume: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class AccountState:
    balance: float
    equity: float


@dataclass(frozen=True)
class SizingConfig:
    mode: SizingMode = SizingMode.BALANCE_RATIO
    fixed_lot: float = 0.01
    multiplier: float = 1.0
    risk_percent: float = 1.0
    #: Hard ceiling regardless of what the mode computes. 0 disables.
    max_lot: float = 0.0
    #: Never send an order smaller than this; 0 means the broker's minimum.
    min_lot: float = 0.0


@dataclass(frozen=True)
class SizingResult:
    volume: float
    reason: str
    #: Set when the requested size had to be reduced or refused.
    capped_by: str | None = None

    @property
    def tradable(self) -> bool:
        return self.volume > 0


def round_to_step(volume: float, step: float) -> float:
    """Round *down* to the broker's lot step.

    Down, not nearest: rounding up would size above what the risk rules just
    approved, which is the one direction that must never happen silently.
    """
    if step <= 0:
        return volume
    steps = math.floor(round(volume / step, 8))
    # Lot steps are decimal (0.01, 0.1, 1); derive the precision from the step
    # so 0.1 + 0.2 style noise never reaches the broker.
    precision = max(0, -math.floor(math.log10(step))) if step < 1 else 0
    return round(steps * step, precision)


def compute_volume(
    master: MasterTrade,
    master_account: AccountState,
    slave_account: AccountState,
    spec: SymbolSpec,
    config: SizingConfig,
) -> SizingResult:
    """The lot size to send to the slave, or 0 with a reason not to."""
    raw, reason = _raw_volume(master, master_account, slave_account, spec, config)

    if raw <= 0:
        return SizingResult(0.0, reason, capped_by="sizing")

    capped_by: str | None = None
    if config.max_lot > 0 and raw > config.max_lot:
        raw = config.max_lot
        capped_by = "max_lot"
    if raw > spec.volume_max:
        raw = spec.volume_max
        capped_by = "broker_volume_max"

    volume = round_to_step(raw, spec.volume_step)

    floor = max(config.min_lot, spec.volume_min)
    if volume < floor:
        # Rounding down took it under the minimum the broker will accept.
        # Sending the minimum anyway would silently over-risk, so it is only
        # done when a minimum was explicitly configured -- that setting is the
        # user saying "round a small size up to this rather than skipping it".
        #
        # The threshold is half the floor, not a hair under it. A slave a
        # fraction smaller than its master computes 0.00998 lots against a 0.01
        # minimum, and a 0.1% tolerance refused exactly that -- so the one
        # setting meant to solve the problem never did. Below half, the request
        # is a different size rather than a rounding artefact, and refusing is
        # still right.
        if config.min_lot > 0 and raw >= config.min_lot * 0.5:
            volume = round_to_step(floor, spec.volume_step)
        else:
            return SizingResult(
                0.0,
                f"{reason}; {raw:.4f} lots is below the {floor:g} minimum",
                capped_by="below_minimum",
            )

    return SizingResult(volume, reason, capped_by)


def _raw_volume(
    master: MasterTrade,
    master_account: AccountState,
    slave_account: AccountState,
    spec: SymbolSpec,
    config: SizingConfig,
) -> tuple[float, str]:
    mode = config.mode

    if mode == SizingMode.FIXED_LOT:
        return config.fixed_lot, f"fixed {config.fixed_lot:g} lots"

    if mode == SizingMode.MULTIPLIER:
        return (
            master.volume * config.multiplier,
            f"{master.volume:g} x {config.multiplier:g}",
        )

    if mode == SizingMode.BALANCE_RATIO:
        if master_account.balance <= 0:
            return 0.0, "master balance is unknown"
        ratio = slave_account.balance / master_account.balance
        return master.volume * ratio, f"balance ratio {ratio:.3f}"

    if mode == SizingMode.EQUITY_RATIO:
        if master_account.equity <= 0:
            return 0.0, "master equity is unknown"
        ratio = slave_account.equity / master_account.equity
        return master.volume * ratio, f"equity ratio {ratio:.3f}"

    if mode in (SizingMode.RISK_PERCENT, SizingMode.RISK_PERCENT_BALANCE):
        on_balance = mode is SizingMode.RISK_PERCENT_BALANCE
        base = slave_account.balance if on_balance else slave_account.equity
        against = "balance" if on_balance else "equity"

        if master.stop_loss is None or master.stop_loss <= 0:
            # No stop means no risk to size against; fall back rather than
            # guess, and say so in the reason so the log explains itself.
            if master_account.balance > 0:
                ratio = slave_account.balance / master_account.balance
                return (
                    master.volume * ratio,
                    f"no stop on the master, fell back to balance ratio {ratio:.3f}",
                )
            return 0.0, "no stop on the master and no balance to scale by"

        distance = abs(master.entry_price - master.stop_loss)
        if distance <= 0 or spec.value_per_unit <= 0:
            return 0.0, "stop distance or contract value is unusable"

        budget = base * (config.risk_percent / 100.0)
        volume = budget / (distance * spec.value_per_unit)
        return volume, f"{config.risk_percent:g}% of {base:,.0f} {against}"

    return 0.0, f"unknown sizing mode {mode}"


def money_at_risk(volume: float, entry: float, stop: float | None, spec: SymbolSpec) -> float | None:
    """What this position would lose at its stop, in account currency."""
    if stop is None or stop <= 0 or spec.value_per_unit <= 0 or volume <= 0:
        return None
    return abs(entry - stop) * spec.value_per_unit * volume
