"""The copier's decision plan: what a slave does about the master's positions."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.copier.engine import (
    ActionType,
    CopiedPosition,
    MasterPosition,
    SlaveContext,
    plan,
)
from app.services.copier.risk import BreachAction, RiskConfig, SlaveSnapshot
from app.services.copier.sizing import AccountState, SizingConfig, SizingMode, SymbolSpec
from app.services.copier.symbols import SymbolRules, candidates, resolve

TODAY = date(2026, 7, 27)
MASTER_ACCOUNT = AccountState(balance=100_000.0, equity=100_000.0)

EURUSD = SymbolSpec("EURUSD", value_per_unit=100_000.0, volume_step=0.01, volume_min=0.01)
SPECS = {"EURUSD": EURUSD, "EURUSD.R": SymbolSpec("EURUSD.r", value_per_unit=100_000.0)}


def master_position(position_id=1, symbol="EURUSD", direction="long", volume=1.0,
                    price=1.1000, sl=1.0980, tp=1.1060):
    return MasterPosition(position_id, symbol, direction, volume, price, sl, tp)


def context(**kwargs) -> SlaveContext:
    defaults = {
        "account_id": 2,
        "account": AccountState(balance=10_000.0, equity=10_000.0),
        "snapshot": SlaveSnapshot(
            balance=10_000.0,
            equity=10_000.0,
            day_start_equity=10_000.0,
            peak_equity=10_000.0,
        ),
        "sizing": SizingConfig(mode=SizingMode.BALANCE_RATIO),
        "risk": RiskConfig(),
        "symbol_rules": SymbolRules(),
        "available_symbols": ["EURUSD", "GBPUSD", "XAUUSD"],
        "specs": dict(SPECS),
        "copied": [],
        "halted": False,
    }
    defaults.update(kwargs)
    return SlaveContext(**defaults)


def types(actions):
    return [a.type for a in actions]


class TestSymbolResolution:
    def test_exact_match(self):
        assert resolve("EURUSD", SymbolRules(), ["EURUSD", "GBPUSD"]) == "EURUSD"

    def test_suffix_broker(self):
        rules = SymbolRules(suffix=".r")
        assert resolve("EURUSD", rules, ["EURUSD.r", "GBPUSD.r"]) == "EURUSD.r"

    def test_prefix_broker(self):
        rules = SymbolRules(prefix="FX_")
        assert resolve("EURUSD", rules, ["FX_EURUSD"]) == "FX_EURUSD"

    def test_explicit_override_wins(self):
        rules = SymbolRules(overrides={"EURUSD": "EURUSD_SB"}, suffix=".r")
        assert resolve("EURUSD", rules, ["EURUSD.r", "EURUSD_SB"]) == "EURUSD_SB"

    def test_master_has_a_suffix_the_slave_lacks(self):
        rules = SymbolRules(suffix=".r")
        assert resolve("EURUSD.r", rules, ["EURUSD"]) == "EURUSD"

    def test_case_insensitive(self):
        assert resolve("eurusd", SymbolRules(), ["EURUSD"]) == "EURUSD"

    def test_unique_prefix_match_as_a_last_resort(self):
        assert resolve("EURUSD", SymbolRules(), ["EURUSDmicro"]) == "EURUSDmicro"

    def test_ambiguous_matches_are_refused(self):
        """Two plausible symbols means we must not pick one."""
        assert resolve("EURUSD", SymbolRules(), ["EURUSD.a", "EURUSD.b"]) is None

    def test_nothing_matches(self):
        assert resolve("EURUSD", SymbolRules(), ["GBPUSD", "USDJPY"]) is None

    def test_never_invents_a_symbol_the_broker_lacks(self):
        assert resolve("EURUSD", SymbolRules(suffix=".r"), []) is None

    def test_candidate_order_puts_the_configured_name_first(self):
        assert candidates("EURUSD", SymbolRules(suffix=".r"))[0] == "EURUSD.r"


class TestOpening:
    def test_a_new_master_trade_is_copied(self):
        actions = plan([master_position()], MASTER_ACCOUNT, context(), TODAY)
        assert types(actions) == [ActionType.OPEN]
        action = actions[0]
        assert action.slave_symbol == "EURUSD"
        assert action.direction == "long"
        assert action.volume == pytest.approx(0.10)  # 10k / 100k
        assert action.stop_loss == pytest.approx(1.0980)
        assert action.take_profit == pytest.approx(1.1060)

    def test_an_already_copied_trade_is_not_reopened(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, 1.1060)
        actions = plan([master_position()], MASTER_ACCOUNT, context(copied=[copied]), TODAY)
        assert ActionType.OPEN not in types(actions)

    def test_an_unmatched_symbol_is_skipped_with_a_reason(self):
        actions = plan(
            [master_position(symbol="US500")], MASTER_ACCOUNT, context(), TODAY
        )
        assert types(actions) == [ActionType.SKIP]
        assert actions[0].rule == "symbol_not_found"

    def test_a_symbol_with_no_spec_is_skipped(self):
        ctx = context(available_symbols=["EURUSD", "GBPUSD"], specs={"EURUSD": EURUSD})
        actions = plan([master_position(symbol="GBPUSD")], MASTER_ACCOUNT, ctx, TODAY)
        assert actions[0].rule == "missing_symbol_spec"

    def test_a_too_small_slave_is_skipped_not_forced(self):
        ctx = context(account=AccountState(100.0, 100.0))
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert types(actions) == [ActionType.SKIP]
        assert actions[0].rule == "below_minimum"

    def test_several_new_trades_are_all_copied(self):
        masters = [master_position(1), master_position(2, symbol="XAUUSD")]
        ctx = context(specs={**SPECS, "XAUUSD": SymbolSpec("XAUUSD", value_per_unit=100.0)})
        actions = plan(masters, MASTER_ACCOUNT, ctx, TODAY)
        assert types(actions) == [ActionType.OPEN, ActionType.OPEN]


class TestConcurrencyWithinOneCycle:
    def test_two_new_trades_cannot_both_pass_a_one_position_limit(self):
        """The limit must account for what this same pass already approved."""
        masters = [master_position(1), master_position(2, symbol="XAUUSD")]
        ctx = context(
            risk=RiskConfig(max_open_positions=1),
            specs={**SPECS, "XAUUSD": SymbolSpec("XAUUSD", value_per_unit=100.0)},
        )
        actions = plan(masters, MASTER_ACCOUNT, ctx, TODAY)
        assert types(actions) == [ActionType.OPEN, ActionType.SKIP]
        assert actions[1].rule == "max_open_positions"

    def test_same_direction_limit_across_one_cycle(self):
        masters = [
            master_position(1, direction="long"),
            master_position(2, symbol="XAUUSD", direction="long"),
        ]
        ctx = context(
            risk=RiskConfig(max_same_direction=1),
            specs={**SPECS, "XAUUSD": SymbolSpec("XAUUSD", value_per_unit=100.0)},
        )
        actions = plan(masters, MASTER_ACCOUNT, ctx, TODAY)
        assert types(actions) == [ActionType.OPEN, ActionType.SKIP]


class TestClosing:
    def test_a_closed_master_position_closes_the_copy(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        actions = plan([], MASTER_ACCOUNT, context(copied=[copied]), TODAY)
        assert types(actions) == [ActionType.CLOSE]
        assert actions[0].slave_position_id == 555
        assert actions[0].rule == "mirror_close"

    def test_closes_come_before_opens(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        masters = [master_position(2, symbol="XAUUSD")]
        ctx = context(
            copied=[copied],
            specs={**SPECS, "XAUUSD": SymbolSpec("XAUUSD", value_per_unit=100.0)},
        )
        actions = plan(masters, MASTER_ACCOUNT, ctx, TODAY)
        assert types(actions) == [ActionType.CLOSE, ActionType.OPEN]


class TestMirroringLevels:
    def test_a_moved_stop_is_mirrored(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, 1.1060)
        moved = master_position(sl=1.1000)  # to breakeven
        actions = plan([moved], MASTER_ACCOUNT, context(copied=[copied]), TODAY)
        assert types(actions) == [ActionType.MODIFY]
        assert actions[0].stop_loss == pytest.approx(1.1000)

    def test_an_unchanged_stop_produces_nothing(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, 1.1060)
        actions = plan([master_position()], MASTER_ACCOUNT, context(copied=[copied]), TODAY)
        assert actions == []

    def test_a_newly_added_stop_is_mirrored(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, None, None)
        actions = plan([master_position(sl=1.0950, tp=None)], MASTER_ACCOUNT,
                       context(copied=[copied]), TODAY)
        assert types(actions) == [ActionType.MODIFY]

    def test_mirroring_can_be_turned_off(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, 1.1060)
        actions = plan([master_position(sl=1.1000)], MASTER_ACCOUNT,
                       context(copied=[copied]), TODAY, mirror_stops=False)
        assert actions == []

    def test_rounding_noise_is_not_a_change(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.09800001, 1.1060)
        actions = plan([master_position()], MASTER_ACCOUNT, context(copied=[copied]), TODAY)
        assert actions == []


class TestPropFirmShaping:
    def test_an_outsized_winner_is_banked(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, profit=1_500.0)
        ctx = context(copied=[copied], risk=RiskConfig(take_profit_at_amount=1_000.0))
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert ActionType.CLOSE in types(actions)
        assert any(a.rule == "take_profit_early" for a in actions)

    def test_it_is_not_closed_twice_when_the_master_also_closed(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, profit=1_500.0)
        ctx = context(copied=[copied], risk=RiskConfig(take_profit_at_amount=1_000.0))
        actions = plan([], MASTER_ACCOUNT, ctx, TODAY)  # master closed it
        closes = [a for a in actions if a.type is ActionType.CLOSE]
        assert len(closes) == 1
        assert closes[0].rule == "mirror_close"


class TestHalting:
    def test_an_equity_stop_halts_and_flattens_by_default(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        ctx = context(
            copied=[copied],
            snapshot=SlaveSnapshot(
                balance=8_000.0, equity=8_000.0, day_start_equity=10_000.0, peak_equity=10_000.0
            ),
            risk=RiskConfig(equity_stop_percent=10.0),
        )
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert ActionType.HALT in types(actions)
        assert ActionType.CLOSE in types(actions)
        assert ActionType.OPEN not in types(actions)

    def test_stop_opening_keeps_positions_running(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        ctx = context(
            copied=[copied],
            snapshot=SlaveSnapshot(
                balance=8_000.0, equity=8_000.0, day_start_equity=10_000.0, peak_equity=10_000.0
            ),
            risk=RiskConfig(
                equity_stop_percent=10.0, breach_action=BreachAction.STOP_OPENING
            ),
        )
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert ActionType.HALT in types(actions)
        assert ActionType.CLOSE not in types(actions)

    def test_flatten_only_on_equity_stop_ignores_a_daily_breach(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        ctx = context(
            copied=[copied],
            snapshot=SlaveSnapshot(
                balance=9_400.0, equity=9_400.0, day_start_equity=10_000.0, peak_equity=10_000.0
            ),
            risk=RiskConfig(
                max_daily_drawdown_percent=5.0,
                breach_action=BreachAction.FLATTEN_ON_EQUITY_STOP,
            ),
        )
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert ActionType.HALT in types(actions)
        assert ActionType.CLOSE not in types(actions)

    def test_the_masters_own_close_still_happens_during_a_halt(self):
        """A halt must never strand a position the master has already exited."""
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000)
        ctx = context(
            copied=[copied],
            snapshot=SlaveSnapshot(
                balance=8_000.0, equity=8_000.0, day_start_equity=10_000.0, peak_equity=10_000.0
            ),
            risk=RiskConfig(
                equity_stop_percent=10.0, breach_action=BreachAction.STOP_OPENING
            ),
        )
        actions = plan([], MASTER_ACCOUNT, ctx, TODAY)
        closes = [a for a in actions if a.type is ActionType.CLOSE]
        assert len(closes) == 1
        assert closes[0].rule == "mirror_close"

    def test_an_already_halted_slave_opens_nothing_but_still_mirrors(self):
        copied = CopiedPosition(1, 555, "EURUSD", "long", 0.10, 1.1000, 1.0980, 1.1060)
        ctx = context(copied=[copied], halted=True)
        actions = plan(
            [master_position(sl=1.1000), master_position(2, symbol="XAUUSD")],
            MASTER_ACCOUNT,
            ctx,
            TODAY,
        )
        assert ActionType.OPEN not in types(actions)
        assert ActionType.MODIFY in types(actions)


class TestSizingModesEndToEnd:
    def test_risk_percent_sizing_through_the_planner(self):
        ctx = context(
            account=AccountState(50_000.0, 50_000.0),
            snapshot=SlaveSnapshot(
                balance=50_000.0, equity=50_000.0,
                day_start_equity=50_000.0, peak_equity=50_000.0,
            ),
            sizing=SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0),
        )
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        # 1% of 50k = 500; 20 pips = 200/lot -> 2.5 lots
        assert actions[0].volume == pytest.approx(2.5)

    def test_a_much_larger_slave_scales_up(self):
        ctx = context(
            account=AccountState(1_000_000.0, 1_000_000.0),
            snapshot=SlaveSnapshot(
                balance=1_000_000.0, equity=1_000_000.0,
                day_start_equity=1_000_000.0, peak_equity=1_000_000.0,
            ),
        )
        actions = plan([master_position()], MASTER_ACCOUNT, ctx, TODAY)
        assert actions[0].volume == pytest.approx(10.0)


class TestAffixDetection:
    """Reading the broker's naming convention off its own symbol list."""

    def test_a_suffix_every_major_shares_is_detected(self):
        from app.services.copier.symbols import detect_affixes

        assert detect_affixes(["EURUSD+", "GBPUSD+", "USDJPY+", "XAUUSD+"]) == ("", "+")

    def test_a_prefix_is_detected(self):
        from app.services.copier.symbols import detect_affixes

        assert detect_affixes(["FX_EURUSD", "FX_GBPUSD", "FX_USDJPY"]) == ("FX_", "")

    def test_plain_names_win_when_the_broker_carries_both(self):
        from app.services.copier.symbols import detect_affixes

        assert detect_affixes(
            ["EURUSD", "EURUSD.r", "GBPUSD", "GBPUSD.r", "USDJPY", "USDJPY.r"]
        ) == ("", "")

    def test_one_odd_instrument_cannot_decide_it(self):
        from app.services.copier.symbols import detect_affixes

        assert detect_affixes(["EURUSD", "GBPUSD", "USDJPY", "XAUUSD.spot"]) == ("", "")

    def test_an_unrecognisable_list_detects_nothing(self):
        from app.services.copier.symbols import detect_affixes

        assert detect_affixes(["SPX500", "GER40"]) == ("", "")

    def test_a_detected_suffix_resolves_the_masters_symbol(self):
        """End to end: nothing configured, and the trade still lands."""
        from app.services.copier.config import symbol_rules_from
        from app.services.copier.symbols import resolve

        available = ["EURUSD+", "GBPUSD+", "USDJPY+", "XAUUSD+"]
        rules = symbol_rules_from("", "", {}, available)
        assert resolve("EURUSD", rules, available) == "EURUSD+"

    def test_a_configured_affix_still_wins(self):
        from app.services.copier.config import symbol_rules_from

        rules = symbol_rules_from("", ".r", {}, ["EURUSD+", "GBPUSD+", "USDJPY+"])
        assert rules.suffix == ".r"
