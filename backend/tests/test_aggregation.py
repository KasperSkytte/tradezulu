"""Deal folding, risk and R-multiple maths."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import Deal, Trade
from app.services.aggregation import (
    _infer_value_per_unit,
    aggregate_deals,
    classify_outcome,
    compute_derived,
    compute_risk_amount,
    rebuild_trades,
    upsert_deals,
)
from app.services.appsettings import DEFAULT_SETTINGS

BASE = datetime(2026, 5, 4, 9, 0, 0)
RISK = DEFAULT_SETTINGS["risk"]


def make_deal(**kwargs) -> Deal:
    defaults: dict = dict(  # noqa: C408
        account_id=1,
        ticket=1,
        order_id=1,
        position_id=1000,
        symbol="EURUSD",
        deal_type=0,
        entry=0,
        volume=1.0,
        price=1.1000,
        profit=0.0,
        commission=0.0,
        swap=0.0,
        fee=0.0,
        sl=0.0,
        tp=0.0,
        magic=0,
        comment="",
        time=BASE,
        value_per_unit=100_000.0,
        digits=5,
    )
    defaults.update(kwargs)
    return Deal(**defaults)


def make_trade(**kwargs) -> Trade:
    defaults: dict = dict(  # noqa: C408
        account_id=1,
        position_id=1,
        symbol="EURUSD",
        direction="long",
        opened_at=BASE,
        closed_at=BASE + timedelta(hours=1),
        volume=1.0,
        closed_volume=1.0,
        entry_price=1.1000,
        exit_price=1.1020,
        gross_profit=200.0,
        commission=-7.0,
        swap=0.0,
        fee=0.0,
        value_per_unit=100_000.0,
        digits=5,
        initial_stop=1.0980,
        initial_target=1.1060,
        risk_override=None,
        excluded=False,
    )
    defaults.update(kwargs)
    return Trade(**defaults)


class TestAggregateDeals:
    def test_simple_long_round_trip(self):
        deals = [
            make_deal(ticket=1, entry=0, deal_type=0, price=1.1000, sl=1.0980, tp=1.1060),
            make_deal(
                ticket=2, entry=1, deal_type=1, price=1.1030, profit=300.0,
                time=BASE + timedelta(minutes=45),
            ),
        ]
        trade = aggregate_deals(deals)[0]

        assert trade.direction == "long"
        assert trade.entry_price == pytest.approx(1.1000)
        assert trade.exit_price == pytest.approx(1.1030)
        assert trade.gross_profit == pytest.approx(300.0)
        assert trade.closed_at == BASE + timedelta(minutes=45)
        assert trade.initial_stop == pytest.approx(1.0980)
        assert trade.initial_target == pytest.approx(1.1060)

    def test_short_direction_is_taken_from_the_opening_deal(self):
        deals = [
            make_deal(ticket=1, entry=0, deal_type=1, price=1.2000),
            make_deal(ticket=2, entry=1, deal_type=0, price=1.1950, profit=500.0),
        ]
        assert aggregate_deals(deals)[0].direction == "short"

    def test_scale_in_uses_volume_weighted_entry(self):
        deals = [
            make_deal(ticket=1, entry=0, volume=1.0, price=1.1000),
            make_deal(ticket=2, entry=0, volume=3.0, price=1.1100, time=BASE + timedelta(minutes=5)),
            make_deal(
                ticket=3, entry=1, volume=4.0, price=1.1200, profit=100.0,
                time=BASE + timedelta(minutes=30),
            ),
        ]
        trade = aggregate_deals(deals)[0]
        assert trade.volume == pytest.approx(4.0)
        # (1 * 1.1000 + 3 * 1.1100) / 4
        assert trade.entry_price == pytest.approx(1.1075)

    def test_partial_close_leaves_the_trade_open(self):
        deals = [
            make_deal(ticket=1, entry=0, volume=2.0),
            make_deal(ticket=2, entry=1, volume=1.0, profit=50.0, time=BASE + timedelta(minutes=10)),
        ]
        trade = aggregate_deals(deals)[0]
        assert trade.closed_at is None
        assert trade.closed_volume == pytest.approx(1.0)

    def test_scale_out_closes_when_all_volume_is_out(self):
        deals = [
            make_deal(ticket=1, entry=0, volume=2.0),
            make_deal(ticket=2, entry=1, volume=1.0, price=1.1050, profit=500.0,
                      time=BASE + timedelta(minutes=10)),
            make_deal(ticket=3, entry=1, volume=1.0, price=1.1090, profit=900.0,
                      time=BASE + timedelta(minutes=40)),
        ]
        trade = aggregate_deals(deals)[0]
        assert trade.closed_at == BASE + timedelta(minutes=40)
        assert trade.exit_price == pytest.approx(1.1070)
        assert trade.gross_profit == pytest.approx(1400.0)

    def test_balance_deals_are_ignored(self):
        deals = [
            make_deal(ticket=9, deal_type=2, position_id=0, profit=10_000.0),
            make_deal(ticket=1, entry=0),
            make_deal(ticket=2, entry=1, profit=10.0, time=BASE + timedelta(minutes=1)),
        ]
        trades = aggregate_deals(deals)
        assert len(trades) == 1
        assert trades[0].gross_profit == pytest.approx(10.0)

    def test_separate_positions_produce_separate_trades(self):
        deals = [
            make_deal(ticket=1, position_id=1, entry=0),
            make_deal(ticket=2, position_id=1, entry=1, profit=10.0),
            make_deal(ticket=3, position_id=2, entry=0, symbol="GBPUSD"),
            make_deal(ticket=4, position_id=2, entry=1, symbol="GBPUSD", profit=-20.0),
        ]
        trades = aggregate_deals(deals)
        assert {t.symbol for t in trades} == {"EURUSD", "GBPUSD"}


class TestValuePerUnit:
    def test_inferred_from_realised_profit(self):
        # 20 pips on 1 lot of EURUSD is worth 200 USD -> 100_000 per price unit.
        value = _infer_value_per_unit("long", 1.1000, 1.1020, 1.0, 200.0)
        assert value == pytest.approx(100_000.0)

    def test_inferred_for_a_short(self):
        value = _infer_value_per_unit("short", 1.2000, 1.1950, 1.0, 500.0)
        assert value == pytest.approx(100_000.0)

    def test_zero_when_nothing_to_infer_from(self):
        assert _infer_value_per_unit("long", 1.1, 1.1, 1.0, 0.0) == 0.0


class TestRisk:
    def test_risk_from_stop_distance(self):
        trade = make_trade()
        risk, source = compute_risk_amount(trade, RISK, 10_000.0)
        # 20 pips * 100_000 * 1 lot = 200
        assert risk == pytest.approx(200.0)
        assert source == "stop"

    def test_manual_override_wins(self):
        trade = make_trade(risk_override=75.0)
        risk, source = compute_risk_amount(trade, RISK, 10_000.0)
        assert risk == pytest.approx(75.0)
        assert source == "override"

    def test_percent_fallback_when_no_stop(self):
        trade = make_trade(initial_stop=None)
        risk, source = compute_risk_amount(trade, RISK, 20_000.0)
        assert risk == pytest.approx(200.0)  # 1% of 20k
        assert source == "percent"

    def test_fixed_fallback(self):
        cfg = {**RISK, "fallback_risk_mode": "fixed_amount", "fixed_risk_amount": 42.0}
        trade = make_trade(initial_stop=None)
        risk, source = compute_risk_amount(trade, cfg, 20_000.0)
        assert risk == pytest.approx(42.0)
        assert source == "fixed"


class TestDerived:
    def test_r_multiples(self):
        trade = compute_derived(make_trade(), RISK, 10_000.0)
        assert trade.risk_amount == pytest.approx(200.0)
        # target is 60 pips away, stop 20 pips -> 3R planned
        assert trade.planned_r == pytest.approx(3.0)
        # 200 gross - 7 commission = 193 on 200 risk
        assert trade.net_pnl == pytest.approx(193.0)
        assert trade.realized_r == pytest.approx(0.965)
        assert trade.outcome == "win"

    def test_commission_can_be_excluded_from_pnl(self):
        cfg = {**RISK, "include_commission_in_pnl": False}
        trade = compute_derived(make_trade(), cfg, 10_000.0)
        assert trade.net_pnl == pytest.approx(200.0)

    def test_open_trade_has_no_r(self):
        trade = compute_derived(make_trade(closed_at=None), RISK, 10_000.0)
        assert trade.realized_r is None
        assert trade.outcome == "open"

    def test_duration_seconds(self):
        trade = compute_derived(make_trade(), RISK, 10_000.0)
        assert trade.duration_seconds == 3600

    def test_trade_date_uses_configured_timezone(self):
        # 23:30 UTC on the 4th is already the 5th in Copenhagen (UTC+2 in May).
        trade = make_trade(
            opened_at=datetime(2026, 5, 4, 23, 0),
            closed_at=datetime(2026, 5, 4, 23, 30),
        )
        compute_derived(trade, RISK, 10_000.0, "Europe/Copenhagen")
        assert trade.trade_date.isoformat() == "2026-05-05"

        compute_derived(trade, RISK, 10_000.0, "UTC")
        assert trade.trade_date.isoformat() == "2026-05-04"

    def test_unknown_timezone_falls_back_to_utc(self):
        trade = make_trade()
        compute_derived(trade, RISK, 10_000.0, "Not/AZone")
        assert trade.trade_date is not None


class TestOutcome:
    def test_small_r_is_a_breakeven(self):
        trade = make_trade(gross_profit=15.0, commission=0.0)
        compute_derived(trade, RISK, 10_000.0)
        assert trade.realized_r == pytest.approx(0.075)
        assert trade.outcome == "breakeven"

    def test_threshold_is_configurable(self):
        cfg = {**RISK, "breakeven_threshold_r": 0.5}
        trade = make_trade(gross_profit=80.0, commission=0.0)
        compute_derived(trade, cfg, 10_000.0)
        assert trade.outcome == "breakeven"

    def test_small_negative_r_is_also_a_breakeven(self):
        trade = make_trade(gross_profit=-10.0, commission=0.0)
        compute_derived(trade, RISK, 10_000.0)
        assert trade.outcome == "breakeven"

    def test_loss(self):
        trade = make_trade(gross_profit=-200.0, commission=-7.0)
        compute_derived(trade, RISK, 10_000.0)
        assert trade.outcome == "loss"
        assert trade.realized_r == pytest.approx(-1.035)

    def test_money_threshold_used_when_no_risk_is_known(self):
        cfg = {**RISK, "fallback_risk_mode": "none"}
        trade = make_trade(initial_stop=None, gross_profit=0.4, commission=0.0)
        compute_derived(trade, cfg, 0.0)
        assert trade.risk_amount is None
        assert classify_outcome(trade, cfg) == "breakeven"


class TestPersistence:
    def test_upsert_is_idempotent(self, db):
        payload = [
            {
                "ticket": 501, "position_id": 77, "symbol": "EURUSD", "type": 0, "entry": 0,
                "volume": 1.0, "price": 1.1, "time": "2026-05-04T09:00:00Z",
                "value_per_unit": 100000, "sl": 1.098, "tp": 1.106,
            },
            {
                "ticket": 502, "position_id": 77, "symbol": "EURUSD", "type": 1, "entry": 1,
                "volume": 1.0, "price": 1.104, "profit": 400.0,
                "time": "2026-05-04T10:00:00Z", "value_per_unit": 100000,
            },
        ]
        received, new = upsert_deals(db, 1, payload)
        assert (received, new) == (2, 2)

        received, new = upsert_deals(db, 1, payload)
        assert (received, new) == (2, 0)

    def test_rebuild_preserves_journal_fields(self, db):
        payload = [
            {"ticket": 601, "position_id": 88, "symbol": "GBPUSD", "type": 0, "entry": 0,
             "volume": 1.0, "price": 1.27, "time": "2026-05-04T09:00:00Z",
             "value_per_unit": 100000, "sl": 1.265},
            {"ticket": 602, "position_id": 88, "symbol": "GBPUSD", "type": 1, "entry": 1,
             "volume": 1.0, "price": 1.28, "profit": 1000.0,
             "time": "2026-05-04T11:00:00Z", "value_per_unit": 100000},
        ]
        upsert_deals(db, 1, payload)
        rebuild_trades(db, 1, RISK, "UTC")
        db.commit()

        trade = db.query(Trade).filter_by(position_id=88).one()
        trade.notes = "kept me honest"
        trade.initial_stop = 1.2600
        trade.stop_source = "manual"
        db.commit()

        rebuild_trades(db, 1, RISK, "UTC")
        db.commit()

        trade = db.query(Trade).filter_by(position_id=88).one()
        assert trade.notes == "kept me honest"
        assert trade.initial_stop == pytest.approx(1.2600)
        assert trade.stop_source == "manual"

    def test_rebuild_creates_executions(self, db):
        upsert_deals(
            db,
            1,
            [
                {"ticket": 701, "position_id": 99, "symbol": "XAUUSD", "type": 0, "entry": 0,
                 "volume": 0.5, "price": 2350.0, "time": "2026-05-04T09:00:00Z",
                 "value_per_unit": 100},
                {"ticket": 702, "position_id": 99, "symbol": "XAUUSD", "type": 1, "entry": 1,
                 "volume": 0.5, "price": 2360.0, "profit": 500.0,
                 "time": "2026-05-04T12:00:00Z", "value_per_unit": 100},
            ],
        )
        rebuild_trades(db, 1, RISK, "UTC")
        db.commit()
        trade = db.query(Trade).filter_by(position_id=99).one()
        assert [e.kind for e in trade.executions] == ["in", "out"]
