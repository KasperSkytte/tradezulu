"""Risk gates and account guards for copied trading."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.copier.risk import (
    BreachAction,
    OpenPosition,
    RiskConfig,
    SlaveSnapshot,
    Verdict,
    check_account_guards,
    check_consistency,
    check_trade_gates,
    evaluate,
    positions_to_close_early,
)
from app.services.copier.sizing import MasterTrade, SymbolSpec

EURUSD = SymbolSpec("EURUSD", value_per_unit=100_000.0)
SPECS = {"EURUSD": EURUSD}
TODAY = date(2026, 7, 27)

TRADE = MasterTrade("EURUSD", "long", 1.0, 1.1000, stop_loss=1.0980)


def snapshot(**kwargs) -> SlaveSnapshot:
    defaults = {
        "balance": 50_000.0,
        "equity": 50_000.0,
        "day_start_equity": 50_000.0,
        "peak_equity": 50_000.0,
        "open_positions": [],
        "day_realised_pnl": 0.0,
        "realised_by_day": {},
    }
    defaults.update(kwargs)
    return SlaveSnapshot(**defaults)


def position(symbol="EURUSD", direction="long", volume=1.0, profit=0.0, stop=1.0980):
    return OpenPosition(
        symbol=symbol,
        direction=direction,
        volume=volume,
        entry_price=1.1000,
        profit=profit,
        stop_loss=stop,
    )


class TestNoLimits:
    def test_an_empty_config_allows_everything(self):
        assert evaluate(TRADE, 1.0, EURUSD, snapshot(), RiskConfig(), TODAY).allowed


class TestEquityStops:
    def test_absolute_floor(self):
        config = RiskConfig(equity_stop_amount=45_000.0)
        result = check_account_guards(snapshot(equity=44_999.0), config)
        assert result.verdict is Verdict.HALT
        assert result.rule == "equity_stop_amount"

    def test_absolute_floor_is_inclusive(self):
        config = RiskConfig(equity_stop_amount=45_000.0)
        assert check_account_guards(snapshot(equity=45_000.0), config).verdict is Verdict.HALT

    def test_above_the_floor_is_fine(self):
        config = RiskConfig(equity_stop_amount=45_000.0)
        assert check_account_guards(snapshot(equity=45_001.0), config).allowed

    def test_percentage_below_peak(self):
        config = RiskConfig(equity_stop_percent=10.0)
        state = snapshot(equity=53_900.0, peak_equity=60_000.0)  # -10.2%
        result = check_account_guards(state, config)
        assert result.verdict is Verdict.HALT
        assert "peak" in result.reason

    def test_just_inside_the_percentage_is_fine(self):
        config = RiskConfig(equity_stop_percent=10.0)
        assert check_account_guards(snapshot(equity=54_100.0, peak_equity=60_000.0), config).allowed


class TestDailyDrawdown:
    def test_trips_at_the_limit(self):
        config = RiskConfig(max_daily_drawdown_percent=5.0)
        state = snapshot(equity=47_400.0, day_start_equity=50_000.0)  # -5.2%
        result = check_account_guards(state, config)
        assert result.verdict is Verdict.HALT
        assert result.rule == "max_daily_drawdown_percent"

    def test_a_smaller_loss_is_fine(self):
        config = RiskConfig(max_daily_drawdown_percent=5.0)
        assert check_account_guards(snapshot(equity=48_000.0), config).allowed

    def test_measures_from_the_days_open_not_the_balance(self):
        """Yesterday's losses must not count against today's limit."""
        config = RiskConfig(max_daily_drawdown_percent=5.0)
        state = snapshot(equity=39_000.0, day_start_equity=40_000.0, peak_equity=50_000.0)
        assert check_account_guards(state, config).allowed  # only -2.5% today


class TestDailyProfitTarget:
    def test_stops_once_the_target_is_met(self):
        config = RiskConfig(daily_profit_target_percent=3.0)
        state = snapshot(day_realised_pnl=1_600.0)  # 3.2% of 50k
        result = check_account_guards(state, config)
        assert result.verdict is Verdict.HALT
        assert result.rule == "daily_profit_target_percent"

    def test_below_the_target_keeps_trading(self):
        config = RiskConfig(daily_profit_target_percent=3.0)
        assert check_account_guards(snapshot(day_realised_pnl=1_000.0), config).allowed


class TestConsistency:
    def test_one_dominant_day_blocks_new_trades(self):
        config = RiskConfig(max_day_share_of_profit_percent=40.0)
        state = snapshot(
            day_realised_pnl=3_000.0,
            realised_by_day={date(2026, 7, 25): 1_000.0, date(2026, 7, 26): 1_000.0},
        )
        # 3000 of 5000 total is 60%.
        result = check_consistency(state, config, TODAY)
        assert result.verdict is Verdict.HALT
        assert "consistency" in result.reason

    def test_an_evenly_spread_week_is_fine(self):
        config = RiskConfig(max_day_share_of_profit_percent=40.0)
        state = snapshot(
            day_realised_pnl=1_000.0,
            realised_by_day={date(2026, 7, 2 + i): 1_000.0 for i in range(5)},
        )
        assert check_consistency(state, config, TODAY).allowed

    def test_no_profit_yet_is_not_a_breach(self):
        config = RiskConfig(max_day_share_of_profit_percent=40.0)
        assert check_consistency(snapshot(), config, TODAY).allowed

    def test_a_losing_total_is_not_a_breach(self):
        config = RiskConfig(max_day_share_of_profit_percent=40.0)
        state = snapshot(day_realised_pnl=500.0, realised_by_day={date(2026, 7, 26): -2_000.0})
        assert check_consistency(state, config, TODAY).allowed

    def test_todays_entry_is_not_counted_twice(self):
        config = RiskConfig(max_day_share_of_profit_percent=60.0)
        state = snapshot(
            day_realised_pnl=1_000.0,
            # Already recorded for today; must not be added on top.
            realised_by_day={TODAY: 1_000.0, date(2026, 7, 26): 1_000.0},
        )
        # Total is 2000, today is 1000 = 50%, under the 60% cap.
        assert check_consistency(state, config, TODAY).allowed

    def test_disabled_by_default(self):
        state = snapshot(day_realised_pnl=10_000.0, realised_by_day={})
        assert check_consistency(state, RiskConfig(), TODAY).allowed


class TestPerTradeGates:
    def test_risk_percent_cap(self):
        config = RiskConfig(max_risk_percent_per_trade=1.0)
        # 2 lots x 20 pips = 400 on 50k equity = 0.8%, allowed.
        assert check_trade_gates(TRADE, 2.0, EURUSD, snapshot(), config).allowed
        # 3 lots = 600 = 1.2%, refused.
        result = check_trade_gates(TRADE, 3.0, EURUSD, snapshot(), config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "max_risk_percent_per_trade"

    def test_max_lot_per_trade(self):
        config = RiskConfig(max_lot_per_trade=1.5)
        assert check_trade_gates(TRADE, 1.5, EURUSD, snapshot(), config).allowed
        assert check_trade_gates(TRADE, 1.6, EURUSD, snapshot(), config).verdict is Verdict.SKIP

    def test_require_stop_loss(self):
        config = RiskConfig(require_stop_loss=True)
        naked = MasterTrade("EURUSD", "long", 1.0, 1.1000, None)
        result = check_trade_gates(naked, 1.0, EURUSD, snapshot(), config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "require_stop_loss"

    def test_a_trade_with_no_stop_skips_the_risk_cap_rather_than_failing(self):
        config = RiskConfig(max_risk_percent_per_trade=0.1)
        naked = MasterTrade("EURUSD", "long", 1.0, 1.1000, None)
        assert check_trade_gates(naked, 1.0, EURUSD, snapshot(), config).allowed


class TestConcurrency:
    def test_max_open_positions(self):
        config = RiskConfig(max_open_positions=2)
        state = snapshot(open_positions=[position(), position()])
        result = check_trade_gates(TRADE, 1.0, EURUSD, state, config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "max_open_positions"

    def test_max_same_direction(self):
        config = RiskConfig(max_same_direction=2)
        state = snapshot(
            open_positions=[
                position(direction="long", symbol="EURUSD"),
                position(direction="long", symbol="GBPUSD"),
                position(direction="short", symbol="USDJPY"),
            ]
        )
        # Two longs already; a third long is refused.
        result = check_trade_gates(TRADE, 1.0, EURUSD, state, config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "max_same_direction"

        # A short is still fine, only one is open.
        short = MasterTrade("EURUSD", "short", 1.0, 1.1000, 1.1020)
        assert check_trade_gates(short, 1.0, EURUSD, state, config).allowed

    def test_max_positions_per_symbol(self):
        config = RiskConfig(max_positions_per_symbol=1)
        state = snapshot(open_positions=[position(symbol="EURUSD")])
        assert check_trade_gates(TRADE, 1.0, EURUSD, state, config).verdict is Verdict.SKIP

        other = MasterTrade("GBPUSD", "long", 1.0, 1.27, 1.265)
        assert check_trade_gates(other, 1.0, EURUSD, state, config).allowed

    def test_max_total_lots_counts_the_incoming_trade(self):
        config = RiskConfig(max_total_lots=3.0)
        state = snapshot(open_positions=[position(volume=2.0)])
        assert check_trade_gates(TRADE, 1.0, EURUSD, state, config).allowed
        assert check_trade_gates(TRADE, 1.5, EURUSD, state, config).verdict is Verdict.SKIP


class TestSymbolLists:
    def test_blocked(self):
        config = RiskConfig(blocked_symbols=["XAUUSD", "EURUSD"])
        assert check_trade_gates(TRADE, 1.0, EURUSD, snapshot(), config).verdict is Verdict.SKIP

    def test_allowed_list_excludes_everything_else(self):
        config = RiskConfig(allowed_symbols=["GBPUSD"])
        assert check_trade_gates(TRADE, 1.0, EURUSD, snapshot(), config).verdict is Verdict.SKIP

    def test_allowed_list_permits_its_members(self):
        config = RiskConfig(allowed_symbols=["EURUSD", "GBPUSD"])
        assert check_trade_gates(TRADE, 1.0, EURUSD, snapshot(), config).allowed

    def test_matching_is_case_insensitive(self):
        config = RiskConfig(blocked_symbols=["eurusd"])
        assert check_trade_gates(TRADE, 1.0, EURUSD, snapshot(), config).verdict is Verdict.SKIP


class TestEarlyProfitTaking:
    def test_closes_at_a_money_amount(self):
        config = RiskConfig(take_profit_at_amount=1_000.0)
        closes = positions_to_close_early([position(profit=1_200.0)], config, SPECS)
        assert len(closes) == 1
        assert "1,000.00 cap" in closes[0][1]

    def test_leaves_smaller_winners_alone(self):
        config = RiskConfig(take_profit_at_amount=1_000.0)
        assert positions_to_close_early([position(profit=900.0)], config, SPECS) == []

    def test_closes_at_an_r_multiple(self):
        # 1 lot risking 20 pips = 200; 3R is 600.
        config = RiskConfig(take_profit_at_r=3.0)
        closes = positions_to_close_early([position(profit=650.0)], config, SPECS)
        assert len(closes) == 1
        assert "3.25R" in closes[0][1]

    def test_below_the_r_multiple_is_left_running(self):
        config = RiskConfig(take_profit_at_r=3.0)
        assert positions_to_close_early([position(profit=500.0)], config, SPECS) == []

    def test_r_rule_needs_a_stop(self):
        config = RiskConfig(take_profit_at_r=1.0)
        assert positions_to_close_early([position(profit=5_000.0, stop=None)], config, SPECS) == []

    def test_losers_are_never_closed_by_this_rule(self):
        config = RiskConfig(take_profit_at_amount=100.0, take_profit_at_r=1.0)
        assert positions_to_close_early([position(profit=-500.0)], config, SPECS) == []

    def test_disabled_by_default(self):
        assert positions_to_close_early([position(profit=99_999.0)], RiskConfig(), SPECS) == []


class TestPrecedence:
    def test_an_account_halt_beats_a_healthy_trade(self):
        config = RiskConfig(equity_stop_amount=60_000.0, max_open_positions=99)
        result = evaluate(TRADE, 0.01, EURUSD, snapshot(), config, TODAY)
        assert result.verdict is Verdict.HALT
        assert result.rule == "equity_stop_amount"

    def test_consistency_is_checked_before_per_trade_rules(self):
        config = RiskConfig(max_day_share_of_profit_percent=10.0, max_lot_per_trade=0.001)
        state = snapshot(day_realised_pnl=5_000.0, realised_by_day={date(2026, 7, 26): 100.0})
        assert evaluate(TRADE, 1.0, EURUSD, state, config, TODAY).verdict is Verdict.HALT

    def test_a_skip_is_not_a_halt(self):
        """A refused trade must not stop the account from copying others."""
        config = RiskConfig(max_lot_per_trade=0.5)
        assert evaluate(TRADE, 1.0, EURUSD, snapshot(), config, TODAY).verdict is Verdict.SKIP


class TestBreachAction:
    def test_the_default_flattens(self):
        assert RiskConfig().breach_action is BreachAction.CLOSE_ALL

    @pytest.mark.parametrize("action", list(BreachAction))
    def test_every_action_is_a_valid_setting(self, action):
        assert RiskConfig(breach_action=action).breach_action is action


class TestAnUnknownContractValue:
    """The cap cannot be applied, so the trade does not go.

    money_at_risk returns None when the terminal never reported what a lot of
    the instrument is worth, and the per-trade cap used to fall straight past
    the check -- so the one rule standing between a mis-sized order and the
    account stopped applying in exactly the case where sizing is least
    trustworthy. Nothing here can tell 0.1 lots from 10 without that number.

    A missing stop is a different matter: require_stop_loss is the setting for
    that, and this cap deliberately stays out of it.
    """

    NO_VALUE = SymbolSpec("XAUUSD+", value_per_unit=0.0, digits=2)

    def test_it_is_refused_when_a_cap_is_set(self):
        config = RiskConfig(max_risk_percent_per_trade=1.0)
        trade = MasterTrade("XAUUSD+", "long", 1.0, 4000.0, 3990.0)

        result = check_trade_gates(trade, 1.0, self.NO_VALUE, snapshot(), config)

        assert result.verdict is Verdict.SKIP
        assert result.rule == "contract_value_unknown"
        assert "worth" in result.reason

    def test_no_cap_means_no_opinion(self):
        """Nothing was asked for, so nothing is enforced."""
        config = RiskConfig(max_risk_percent_per_trade=0)
        trade = MasterTrade("XAUUSD+", "long", 1.0, 4000.0, 3990.0)

        assert check_trade_gates(trade, 1.0, self.NO_VALUE, snapshot(), config).allowed

    def test_a_known_value_is_measured_as_before(self):
        config = RiskConfig(max_risk_percent_per_trade=1.0)
        spec = SymbolSpec("XAUUSD+", value_per_unit=100.0, digits=2)
        trade = MasterTrade("XAUUSD+", "long", 1.0, 4000.0, 3990.0)

        # 10 points x 100 per unit x 1 lot = 1,000 against 10,000 equity = 10%.
        result = check_trade_gates(trade, 1.0, spec, snapshot(), config)

        assert result.verdict is Verdict.SKIP
        assert result.rule == "max_risk_percent_per_trade"


class TestAnEquityNobodyCanRead:
    """Zero equity from a terminal that has lost its session.

    Every guard below divides by, or compares against, the equity. A zero
    walks straight through all of them as a total loss and halts the account
    for good -- a latch that survives the terminal logging back in and has to
    be cleared by hand. An account that is worth something and reports nothing
    has a broken terminal, not a blown balance.
    """

    def test_zero_equity_is_refused_rather_than_halted(self):
        config = RiskConfig(equity_stop_amount=45_000.0)
        result = check_account_guards(snapshot(equity=0.0), config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "equity_unknown"
        assert "not logged in" in result.reason

    def test_it_beats_every_equity_rule_to_the_verdict(self):
        config = RiskConfig(
            equity_stop_amount=45_000.0,
            equity_stop_percent=10.0,
            max_daily_drawdown_percent=5.0,
        )
        assert check_account_guards(snapshot(equity=0.0), config).verdict is Verdict.SKIP

    def test_an_account_that_never_had_anything_is_not_second_guessed(self):
        """Nothing to contradict: no balance, no peak, no opening equity."""
        state = snapshot(equity=0.0, balance=0.0, day_start_equity=0.0, peak_equity=0.0)
        config = RiskConfig(equity_stop_amount=45_000.0)
        result = check_account_guards(state, config)
        assert result.verdict is Verdict.HALT
        assert result.rule == "equity_stop_amount"

    def test_a_real_drawdown_still_halts(self):
        config = RiskConfig(equity_stop_amount=45_000.0)
        result = check_account_guards(snapshot(equity=44_999.0), config)
        assert result.verdict is Verdict.HALT


class TestMinimumStopDistance:
    """A stop too tight to survive being copied to another broker.

    Size comes from the master's entry-to-stop distance and the copy is filled
    at its own price with the master's stop. Fill it a little worse and the
    real distance is wider than the one it was sized for, so the loss is wider
    by the same proportion -- nothing on a wide stop, everything on a tight one.
    """

    def _trade(self, stop):
        return MasterTrade(
            symbol="EURUSD", direction="long", volume=1.0,
            entry_price=1.1000, stop_loss=stop, take_profit=1.1100,
        )

    def test_a_stop_inside_the_minimum_is_refused(self):
        config = RiskConfig(min_stop_distance_points=100.0)  # 10 pips on a 5-digit pair
        result = check_trade_gates(self._trade(1.0995), 1.0, EURUSD, snapshot(), config)
        assert result.verdict is Verdict.SKIP
        assert result.rule == "min_stop_distance"
        assert "50 points" in result.reason

    def test_a_stop_at_the_minimum_is_allowed(self):
        config = RiskConfig(min_stop_distance_points=100.0)
        assert check_trade_gates(self._trade(1.0990), 1.0, EURUSD, snapshot(), config).allowed

    def test_a_wide_stop_is_untouched(self):
        config = RiskConfig(min_stop_distance_points=100.0)
        assert check_trade_gates(self._trade(1.0900), 1.0, EURUSD, snapshot(), config).allowed

    def test_zero_means_no_minimum(self):
        assert check_trade_gates(self._trade(1.09999), 1.0, EURUSD, snapshot(), RiskConfig()).allowed

    def test_a_trade_with_no_stop_is_left_to_require_stop_loss(self):
        """This rule is about how far away a stop is, not whether there is one."""
        config = RiskConfig(min_stop_distance_points=100.0)
        assert check_trade_gates(self._trade(None), 1.0, EURUSD, snapshot(), config).allowed
