"""What the copier should do, given a master and a slave.

Still pure: this module decides, it does not execute. The result is a list of
:class:`Action` objects that an executor turns into broker calls, which means
the whole decision surface — including every refusal and every prop-firm rule
— is testable without a broker, a terminal or a network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from .risk import (
    BreachAction,
    Decision,
    OpenPosition,
    RiskConfig,
    SlaveSnapshot,
    Verdict,
    check_account_guards,
    check_consistency,
    check_trade_gates,
    positions_to_close_early,
)
from .sizing import (
    AccountState,
    MasterTrade,
    SizingConfig,
    SymbolSpec,
    compute_volume,
)
from .symbols import SymbolRules, resolve


class ActionType(str, Enum):
    OPEN = "open"
    CLOSE = "close"
    MODIFY = "modify"
    #: Recorded, not executed: a copy that was considered and refused.
    SKIP = "skip"
    #: Account-level stop.
    HALT = "halt"


@dataclass
class Action:
    type: ActionType
    master_position_id: int
    symbol: str = ""
    slave_symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    #: Set on CLOSE/MODIFY for a position we already own.
    slave_position_id: int | None = None
    reason: str = ""
    rule: str = ""

    def as_event(self) -> dict[str, Any]:
        return {
            "action": self.type.value,
            "master_position_id": self.master_position_id,
            "symbol": self.slave_symbol or self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "rule": self.rule,
            "message": self.reason,
        }


@dataclass
class MasterPosition:
    """A live position on the master account."""

    position_id: int
    symbol: str
    direction: str
    volume: float
    open_price: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class CopiedPosition:
    """A position this slave already holds because of the master."""

    master_position_id: int
    slave_position_id: int
    slave_symbol: str
    direction: str
    volume: float
    open_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    profit: float = 0.0


@dataclass
class SlaveContext:
    """Everything about one slave at the moment of a decision."""

    account_id: int
    account: AccountState
    snapshot: SlaveSnapshot
    sizing: SizingConfig
    risk: RiskConfig
    symbol_rules: SymbolRules = field(default_factory=SymbolRules)
    #: Symbols the slave's broker actually offers.
    available_symbols: list[str] = field(default_factory=list)
    #: Contract specs by the *slave's* symbol name.
    specs: dict[str, SymbolSpec] = field(default_factory=dict)
    copied: list[CopiedPosition] = field(default_factory=list)
    halted: bool = False


def _price_changed(a: float | None, b: float | None, digits: int) -> bool:
    """Whether two price levels differ by more than rounding noise."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return round(abs(a - b), digits + 1) > 10 ** -(digits)


def plan(
    master_positions: list[MasterPosition],
    master_account: AccountState,
    context: SlaveContext,
    today: date,
    *,
    mirror_stops: bool = True,
) -> list[Action]:
    """The actions this slave should take right now.

    Order matters. Closes come before opens so freeing a slot can immediately
    admit a new trade, and an account-level halt short-circuits everything
    that would add exposure.
    """
    actions: list[Action] = []
    by_master_id = {p.position_id: p for p in master_positions}
    copied_by_master = {c.master_position_id: c for c in context.copied}

    # --- 1. the master closed something, so we do too --------------------
    for copied in context.copied:
        if copied.master_position_id not in by_master_id:
            actions.append(
                Action(
                    ActionType.CLOSE,
                    copied.master_position_id,
                    slave_symbol=copied.slave_symbol,
                    slave_position_id=copied.slave_position_id,
                    volume=copied.volume,
                    reason="the master closed this position",
                    rule="mirror_close",
                )
            )

    # --- 2. prop-firm shaping: bank outsized winners ---------------------
    open_as_positions = [
        OpenPosition(
            symbol=c.slave_symbol,
            direction=c.direction,
            volume=c.volume,
            entry_price=c.open_price,
            profit=c.profit,
            stop_loss=c.stop_loss,
            master_position_id=c.master_position_id,
        )
        for c in context.copied
    ]
    already_closing = {a.master_position_id for a in actions}
    for position, why in positions_to_close_early(
        open_as_positions, context.risk, context.specs
    ):
        if position.master_position_id in already_closing:
            continue
        copied = copied_by_master.get(position.master_position_id or -1)
        if copied is None:
            continue
        actions.append(
            Action(
                ActionType.CLOSE,
                copied.master_position_id,
                slave_symbol=copied.slave_symbol,
                slave_position_id=copied.slave_position_id,
                volume=copied.volume,
                reason=why,
                rule="take_profit_early",
            )
        )
        already_closing.add(copied.master_position_id)

    # --- 3. account guards ------------------------------------------------
    guard = check_account_guards(context.snapshot, context.risk)
    if guard.allowed:
        guard = check_consistency(context.snapshot, context.risk, today)

    if guard.verdict is Verdict.HALT:
        actions.append(
            Action(
                ActionType.HALT,
                0,
                reason=guard.reason,
                rule=guard.rule,
            )
        )
        if context.risk.breach_action is BreachAction.CLOSE_ALL or (
            context.risk.breach_action is BreachAction.FLATTEN_ON_EQUITY_STOP
            and guard.rule.startswith("equity_stop")
        ):
            for copied in context.copied:
                if copied.master_position_id in already_closing:
                    continue
                actions.append(
                    Action(
                        ActionType.CLOSE,
                        copied.master_position_id,
                        slave_symbol=copied.slave_symbol,
                        slave_position_id=copied.slave_position_id,
                        volume=copied.volume,
                        reason=f"flattening: {guard.reason}",
                        rule=guard.rule,
                    )
                )
                already_closing.add(copied.master_position_id)
        # Nothing below this point may add exposure.
        return actions

    if context.halted:
        # Halted earlier and not yet reset: mirror management, open nothing.
        return actions + _mirror_actions(
            by_master_id, context, already_closing, mirror_stops
        )

    # --- 4. mirror stop/target changes on what we hold --------------------
    actions += _mirror_actions(by_master_id, context, already_closing, mirror_stops)

    # --- 5. the master opened something new ------------------------------
    # Track the effect of this same pass, so two new master trades cannot both
    # slip past a "max 1 open position" limit in one cycle.
    pending = list(context.snapshot.open_positions)
    for master in master_positions:
        if master.position_id in copied_by_master:
            continue

        action = _plan_open(master, master_account, context, pending, today)
        actions.append(action)
        if action.type is ActionType.OPEN:
            pending.append(
                OpenPosition(
                    symbol=action.slave_symbol,
                    direction=action.direction,
                    volume=action.volume,
                    entry_price=master.open_price,
                    stop_loss=action.stop_loss,
                )
            )

    return actions


def _mirror_actions(
    by_master_id: dict[int, MasterPosition],
    context: SlaveContext,
    already_closing: set[int],
    mirror_stops: bool,
) -> list[Action]:
    if not mirror_stops:
        return []

    out: list[Action] = []
    for copied in context.copied:
        if copied.master_position_id in already_closing:
            continue
        master = by_master_id.get(copied.master_position_id)
        if master is None:
            continue

        spec = context.specs.get(copied.slave_symbol.upper())
        digits = spec.digits if spec else 5
        stop_moved = _price_changed(master.stop_loss, copied.stop_loss, digits)
        target_moved = _price_changed(master.take_profit, copied.take_profit, digits)
        if not (stop_moved or target_moved):
            continue

        changes = []
        if stop_moved:
            changes.append("stop")
        if target_moved:
            changes.append("target")
        out.append(
            Action(
                ActionType.MODIFY,
                copied.master_position_id,
                slave_symbol=copied.slave_symbol,
                slave_position_id=copied.slave_position_id,
                stop_loss=master.stop_loss,
                take_profit=master.take_profit,
                reason=f"the master moved its {' and '.join(changes)}",
                rule="mirror_levels",
            )
        )
    return out


def _plan_open(
    master: MasterPosition,
    master_account: AccountState,
    context: SlaveContext,
    pending: list[OpenPosition],
    today: date,
) -> Action:
    slave_symbol = resolve(master.symbol, context.symbol_rules, context.available_symbols)
    if slave_symbol is None:
        return Action(
            ActionType.SKIP,
            master.position_id,
            symbol=master.symbol,
            direction=master.direction,
            reason=f"this broker has no symbol matching {master.symbol}",
            rule="symbol_not_found",
        )

    spec = context.specs.get(slave_symbol.upper())
    if spec is None:
        return Action(
            ActionType.SKIP,
            master.position_id,
            symbol=master.symbol,
            slave_symbol=slave_symbol,
            direction=master.direction,
            reason=f"no contract specification for {slave_symbol}",
            rule="missing_symbol_spec",
        )

    trade = MasterTrade(
        symbol=master.symbol,
        direction=master.direction,
        volume=master.volume,
        entry_price=master.open_price,
        stop_loss=master.stop_loss,
        take_profit=master.take_profit,
    )

    sized = compute_volume(trade, master_account, context.account, spec, context.sizing)
    if not sized.tradable:
        return Action(
            ActionType.SKIP,
            master.position_id,
            symbol=master.symbol,
            slave_symbol=slave_symbol,
            direction=master.direction,
            reason=sized.reason,
            rule=sized.capped_by or "sizing",
        )

    snapshot = SlaveSnapshot(
        balance=context.snapshot.balance,
        equity=context.snapshot.equity,
        day_start_equity=context.snapshot.day_start_equity,
        peak_equity=context.snapshot.peak_equity,
        open_positions=pending,
        day_realised_pnl=context.snapshot.day_realised_pnl,
        realised_by_day=context.snapshot.realised_by_day,
    )
    gate: Decision = check_trade_gates(trade, sized.volume, spec, snapshot, context.risk)
    if not gate.allowed:
        return Action(
            ActionType.SKIP,
            master.position_id,
            symbol=master.symbol,
            slave_symbol=slave_symbol,
            direction=master.direction,
            volume=sized.volume,
            reason=gate.reason,
            rule=gate.rule,
        )

    return Action(
        ActionType.OPEN,
        master.position_id,
        symbol=master.symbol,
        slave_symbol=slave_symbol,
        direction=master.direction,
        volume=sized.volume,
        stop_loss=master.stop_loss,
        take_profit=master.take_profit,
        reason=sized.reason,
        rule="copy_open",
    )
