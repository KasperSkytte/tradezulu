"""Volume sizing for copied trades."""

from __future__ import annotations

import pytest

from app.services.copier.sizing import (
    AccountState,
    MasterTrade,
    SizingConfig,
    SizingMode,
    SymbolSpec,
    compute_volume,
    money_at_risk,
    round_to_step,
)

EURUSD = SymbolSpec(
    symbol="EURUSD",
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
    value_per_unit=100_000.0,
    digits=5,
)

# A broker that only deals in whole lots, which is where rounding gets sharp.
FUTURES = SymbolSpec(
    symbol="NAS100",
    volume_min=1.0,
    volume_max=50.0,
    volume_step=1.0,
    value_per_unit=1.0,
    digits=1,
)

MASTER = AccountState(balance=100_000.0, equity=100_000.0)
TRADE = MasterTrade(
    symbol="EURUSD", direction="long", volume=1.0, entry_price=1.1000, stop_loss=1.0980
)


def size(config: SizingConfig, slave: AccountState, trade=TRADE, spec=EURUSD, master=MASTER):
    return compute_volume(trade, master, slave, spec, config)


class TestRounding:
    def test_rounds_down_to_the_step(self):
        assert round_to_step(0.147, 0.01) == 0.14
        assert round_to_step(1.99, 1.0) == 1.0
        assert round_to_step(0.6, 0.5) == 0.5

    def test_never_rounds_up(self):
        """Rounding up would exceed the size the risk rules just approved."""
        for raw in (0.019, 0.0199, 0.099, 2.999):
            assert round_to_step(raw, 0.01) <= raw

    def test_exact_multiples_survive(self):
        assert round_to_step(0.10, 0.01) == 0.10
        assert round_to_step(3.0, 1.0) == 3.0

    def test_no_floating_point_dust(self):
        assert round_to_step(0.3, 0.1) == 0.3
        assert round_to_step(0.7, 0.1) == 0.7

    def test_zero_step_is_a_no_op(self):
        assert round_to_step(0.123, 0) == 0.123


class TestFixedLot:
    def test_ignores_the_master_size(self):
        config = SizingConfig(mode=SizingMode.FIXED_LOT, fixed_lot=0.05)
        big = MasterTrade("EURUSD", "long", 10.0, 1.1, 1.098)
        assert size(config, AccountState(5_000, 5_000), trade=big).volume == 0.05


class TestMultiplier:
    def test_scales_the_master_volume(self):
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=0.25)
        assert size(config, AccountState(5_000, 5_000)).volume == 0.25

    def test_can_scale_up(self):
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=3.0)
        assert size(config, AccountState(5_000, 5_000)).volume == 3.0


class TestBalanceRatio:
    def test_a_smaller_slave_trades_smaller(self):
        config = SizingConfig(mode=SizingMode.BALANCE_RATIO)
        result = size(config, AccountState(10_000, 10_000))
        assert result.volume == pytest.approx(0.10)
        assert "0.100" in result.reason

    def test_a_bigger_slave_trades_bigger(self):
        config = SizingConfig(mode=SizingMode.BALANCE_RATIO)
        assert size(config, AccountState(250_000, 250_000)).volume == pytest.approx(2.5)

    def test_an_unknown_master_balance_refuses(self):
        config = SizingConfig(mode=SizingMode.BALANCE_RATIO)
        result = size(config, AccountState(10_000, 10_000), master=AccountState(0, 0))
        assert result.volume == 0
        assert not result.tradable


class TestEquityRatio:
    def test_uses_equity_not_balance(self):
        config = SizingConfig(mode=SizingMode.EQUITY_RATIO)
        # Balance says 1:1, equity says half.
        slave = AccountState(balance=100_000.0, equity=50_000.0)
        assert size(config, slave).volume == pytest.approx(0.5)


class TestRiskPercent:
    def test_sizes_from_the_stop_distance(self):
        # 1% of 50,000 = 500 to risk; 20 pips on EURUSD is 200/lot -> 2.5 lots.
        config = SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0)
        result = size(config, AccountState(50_000, 50_000))
        assert result.volume == pytest.approx(2.5)

    def test_a_wider_stop_gives_a_smaller_size(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0)
        wide = MasterTrade("EURUSD", "long", 1.0, 1.1000, 1.0900)  # 100 pips
        assert size(config, AccountState(50_000, 50_000), trade=wide).volume == pytest.approx(0.5)

    def test_falls_back_when_the_master_has_no_stop(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0)
        no_stop = MasterTrade("EURUSD", "long", 1.0, 1.1000, None)
        result = size(config, AccountState(10_000, 10_000), trade=no_stop)
        assert result.volume == pytest.approx(0.10)  # balance ratio
        assert "no stop" in result.reason

    def test_refuses_without_contract_data(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0)
        spec = SymbolSpec(symbol="EURUSD", value_per_unit=0.0)
        assert size(config, AccountState(50_000, 50_000), spec=spec).volume == 0


class TestRiskPercentOfBalance:
    """The same rule measured against balance rather than equity.

    Balance ignores open positions, so the size risked does not shrink while a
    trade is under water and grow while it is ahead -- which is what most
    people mean when they say they risk 1%.
    """

    def test_ignores_what_open_trades_are_doing(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT_BALANCE, risk_percent=1.0)
        # Balance 50,000 with 10,000 of open loss against it.
        result = size(config, AccountState(50_000, 40_000))
        assert result.volume == pytest.approx(2.5)
        assert "balance" in result.reason

    def test_equity_mode_does_not(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT, risk_percent=1.0)
        result = size(config, AccountState(50_000, 40_000))
        assert result.volume == pytest.approx(2.0)
        assert "equity" in result.reason

    def test_it_still_falls_back_without_a_stop(self):
        config = SizingConfig(mode=SizingMode.RISK_PERCENT_BALANCE, risk_percent=1.0)
        no_stop = MasterTrade("EURUSD", "long", 1.0, 1.1000, None)
        result = size(config, AccountState(10_000, 10_000), trade=no_stop)
        assert "no stop" in result.reason

    def test_every_mode_is_a_valid_setting(self):
        """A mode the form can offer that config.py cannot read is a trap."""
        from app.services.copier.config import sizing_from

        for mode in SizingMode:
            assert sizing_from({"mode": mode.value}).mode is mode


class TestCaps:
    def test_max_lot_clamps(self):
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=10.0, max_lot=2.0)
        result = size(config, AccountState(5_000, 5_000))
        assert result.volume == 2.0
        assert result.capped_by == "max_lot"

    def test_the_brokers_own_maximum_clamps(self):
        spec = SymbolSpec(symbol="EURUSD", volume_max=3.0, value_per_unit=100_000.0)
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=10.0)
        result = size(config, AccountState(5_000, 5_000), spec=spec)
        assert result.volume == 3.0
        assert result.capped_by == "broker_volume_max"


class TestTooSmall:
    def test_refuses_rather_than_rounding_up_to_the_minimum(self):
        """A tiny slave must not be forced into an over-sized minimum lot."""
        config = SizingConfig(mode=SizingMode.BALANCE_RATIO)
        result = size(config, AccountState(200, 200))  # 0.002 lots
        assert result.volume == 0
        assert result.capped_by == "below_minimum"
        assert "below" in result.reason

    def test_whole_lot_broker_refuses_a_fractional_copy(self):
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=0.4)
        trade = MasterTrade("NAS100", "long", 1.0, 18500.0, 18400.0)
        result = size(config, AccountState(10_000, 10_000), trade=trade, spec=FUTURES)
        assert result.volume == 0
        assert result.capped_by == "below_minimum"

    def test_an_explicit_minimum_is_honoured_when_close(self):
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=0.01, min_lot=0.01)
        assert size(config, AccountState(10_000, 10_000)).volume == 0.01

    def test_a_slave_a_fraction_smaller_than_the_master_still_trades(self):
        """The case the setting exists for, which it used not to cover.

        A slave 0.2% smaller computes 0.00998 lots against a 0.01 minimum. The
        old tolerance was 0.1%, so it refused -- and went on refusing every
        trade for as long as the accounts stayed that close.
        """
        config = SizingConfig(mode=SizingMode.BALANCE_RATIO, min_lot=0.01)
        trade = MasterTrade("EURUSD", "long", 0.01, 1.1000, 1.0980)
        result = size(config, AccountState(9_978, 9_978), trade=trade, master=AccountState(10_000, 10_000))
        assert result.volume == 0.01

    def test_a_genuinely_different_size_is_still_refused(self):
        """Half the floor is the line: below it this is not a rounding artefact."""
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=0.004, min_lot=0.01)
        result = size(config, AccountState(10_000, 10_000))
        assert result.volume == 0
        assert result.capped_by == "below_minimum"

    def test_without_a_configured_minimum_it_still_refuses(self):
        """Rounding up is opt-in. Nobody gets silently over-sized."""
        config = SizingConfig(mode=SizingMode.MULTIPLIER, multiplier=0.009)
        assert size(config, AccountState(10_000, 10_000)).volume == 0


class TestMoneyAtRisk:
    def test_computes_the_loss_at_the_stop(self):
        assert money_at_risk(1.0, 1.1000, 1.0980, EURUSD) == pytest.approx(200.0)

    def test_scales_with_volume(self):
        assert money_at_risk(0.25, 1.1000, 1.0980, EURUSD) == pytest.approx(50.0)

    def test_is_none_without_a_stop(self):
        assert money_at_risk(1.0, 1.1000, None, EURUSD) is None

    def test_is_none_without_contract_data(self):
        spec = SymbolSpec(symbol="X", value_per_unit=0.0)
        assert money_at_risk(1.0, 1.1, 1.09, spec) is None
