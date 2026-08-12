"""Statistics: win rate, profit factor, drawdown, Sharpe, Zulu Score."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models import Trade
from app.services.appsettings import DEFAULT_SETTINGS
from app.services.metrics import (
    PF_INFINITE,
    breakdowns,
    compute_drawdown,
    compute_sharpe,
    compute_streaks,
    consistency_score,
    daily_breakdown,
    distributions,
    equity_curve,
    period_bounds,
    split_trades,
    summarize,
    zulu_score,
)

RISK = DEFAULT_SETTINGS["risk"]
STATS = DEFAULT_SETTINGS["stats"]
SCORE = DEFAULT_SETTINGS["zulu_score"]
BASE = datetime(2026, 6, 1, 10, 0)


def trade(
    net: float,
    *,
    r: float | None = None,
    outcome: str | None = None,
    day: int = 1,
    symbol: str = "EURUSD",
    direction: str = "long",
    excluded: bool = False,
    planned_r: float | None = None,
    duration: int = 3600,
) -> Trade:
    when = BASE.replace(day=day)
    if outcome is None:
        outcome = "win" if net > 0 else ("loss" if net < 0 else "breakeven")
    return Trade(
        account_id=1,
        position_id=day * 100 + int(abs(net)),
        symbol=symbol,
        direction=direction,
        opened_at=when,
        closed_at=when + timedelta(seconds=duration),
        trade_date=date(2026, 6, day),
        volume=1.0,
        closed_volume=1.0,
        entry_price=1.1,
        exit_price=1.11,
        gross_profit=net,
        commission=0.0,
        swap=0.0,
        fee=0.0,
        risk_amount=abs(net / r) if r else None,
        net_pnl=net,
        realized_r=r,
        planned_r=planned_r,
        outcome=outcome,
        excluded=excluded,
        duration_seconds=duration,
    )


class TestSplit:
    def test_breakevens_are_excluded_by_default(self):
        sets = split_trades([trade(100, r=1.0), trade(-100, r=-1.0), trade(5, r=0.05, outcome="breakeven")])
        assert len(sets.scored) == 2
        assert len(sets.breakevens) == 1
        assert len(sets.all_closed) == 3

    def test_breakevens_can_count_as_losses(self):
        sets = split_trades(
            [trade(100, r=1.0), trade(5, r=0.05, outcome="breakeven")], "loss"
        )
        assert len(sets.losses) == 1
        assert len(sets.scored) == 2

    def test_breakevens_can_count_as_wins(self):
        sets = split_trades([trade(5, r=0.05, outcome="breakeven")], "win")
        assert len(sets.wins) == 1

    def test_excluded_trades_never_appear(self):
        sets = split_trades([trade(100, r=1.0), trade(-500, r=-5.0, excluded=True)])
        assert len(sets.all_closed) == 1
        assert len(sets.excluded) == 1


class TestSummary:
    def test_headline_numbers(self):
        trades = [
            trade(200, r=2.0, day=1),
            trade(300, r=3.0, day=2),
            trade(-100, r=-1.0, day=3),
            trade(-100, r=-1.0, day=4),
            trade(5, r=0.05, outcome="breakeven", day=5),
        ]
        s = summarize(
            trades, risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0
        )
        assert s["counts"] == {
            "total": 5, "scored": 4, "wins": 2, "losses": 2,
            "breakevens": 1, "open": 0, "excluded": 0,
            # These fixtures carry no stop; the count is there to be noticed.
            "no_stop": 5,
        }
        assert s["win_rate"] == 50.0
        assert s["net_pnl"] == 305.0
        assert s["gross_profit"] == 500.0
        assert s["gross_loss"] == 200.0
        assert s["profit_factor"] == 2.5
        assert s["avg_win"] == 250.0
        assert s["avg_loss"] == -100.0
        assert s["payoff_ratio"] == 2.5
        assert s["expectancy_r"] == pytest.approx(0.75)
        assert s["total_r"] == 3.0

    def test_breakeven_does_not_move_the_win_rate(self):
        without = summarize(
            [trade(100, r=1.0), trade(-100, r=-1.0)],
            risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0,
        )
        with_be = summarize(
            [trade(100, r=1.0), trade(-100, r=-1.0), trade(2, r=0.02, outcome="breakeven")],
            risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0,
        )
        assert without["win_rate"] == with_be["win_rate"] == 50.0
        assert with_be["counts"]["breakevens"] == 1
        assert with_be["breakeven_rate"] == pytest.approx(33.3)

    def test_profit_factor_is_capped_when_there_are_no_losses(self):
        s = summarize(
            [trade(100, r=1.0), trade(50, r=0.5)],
            risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0,
        )
        assert s["profit_factor"] == PF_INFINITE

    def test_empty_period_is_safe(self):
        s = summarize([], risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0)
        assert s["counts"]["total"] == 0
        assert s["win_rate"] is None
        assert s["net_pnl"] == 0
        assert s["zulu_score"]["score"] == 0.0

    def test_plan_adherence(self):
        trades = [
            trade(200, r=2.0, planned_r=3.0, day=1),
            trade(-100, r=-1.0, planned_r=3.0, day=2),
        ]
        s = summarize(
            trades, risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0
        )
        assert s["avg_planned_r"] == 3.0
        assert s["avg_realized_r"] == 0.5
        assert s["plan_adherence"] == pytest.approx(16.7)

    def test_open_trades_are_counted_but_not_scored(self):
        open_trade = trade(0, day=6)
        open_trade.closed_at = None
        open_trade.outcome = "open"
        s = summarize(
            [trade(100, r=1.0), open_trade],
            risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0,
        )
        assert s["counts"]["open"] == 1
        assert s["counts"]["total"] == 1


class TestDrawdown:
    def test_peak_to_trough(self):
        max_dd, pct, _ = compute_drawdown([100, 200, -400, 50], 10_000.0)
        # equity peaks at 10_300 then falls to 9_900
        assert max_dd == pytest.approx(400.0)
        assert pct == pytest.approx(400 / 10_300 * 100)

    def test_no_drawdown_on_a_monotonic_curve(self):
        max_dd, pct, _ = compute_drawdown([10, 20, 30], 1_000.0)
        assert max_dd == 0.0
        assert pct == 0.0

    def test_percentage_is_omitted_without_an_account_size(self):
        _, pct, _ = compute_drawdown([100, -50], 0.0)
        assert pct is None

    def test_recovery_factor(self):
        trades = [trade(500, r=5.0, day=1), trade(-200, r=-2.0, day=2), trade(300, r=3.0, day=3)]
        s = summarize(
            trades, risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0
        )
        assert s["max_drawdown"] == 200.0
        assert s["recovery_factor"] == pytest.approx(600 / 200)


class TestSharpe:
    def test_needs_two_observations(self):
        assert compute_sharpe([100.0], 10_000.0, 0.0, 252) == (None, None)

    def test_flat_series_has_no_sharpe(self):
        sharpe, _ = compute_sharpe([10.0, 10.0, 10.0], 10_000.0, 0.0, 252)
        assert sharpe is None

    def test_positive_series(self):
        sharpe, sortino = compute_sharpe([100.0, -50.0, 150.0, 25.0], 10_000.0, 0.0, 252)
        assert sharpe is not None and sharpe > 0
        assert sortino is not None and sortino > sharpe

    def test_scale_invariance_without_account_size(self):
        a, _ = compute_sharpe([100.0, -50.0, 150.0], 0.0, 0.0, 252)
        b, _ = compute_sharpe([1000.0, -500.0, 1500.0], 0.0, 0.0, 252)
        assert a == pytest.approx(b)


class TestStreaksAndDays:
    def test_streaks(self):
        trades = [
            trade(10, day=1), trade(10, day=2), trade(10, day=3),
            trade(-10, day=4), trade(-10, day=5), trade(10, day=6),
        ]
        result = compute_streaks(trades)
        assert result["max_win_streak"] == 3
        assert result["max_loss_streak"] == 2
        assert result["current_streak"] == 1

    def test_daily_breakdown_groups_by_trade_date(self):
        rows = daily_breakdown([trade(100, day=1), trade(-40, day=1), trade(60, day=2)])
        assert len(rows) == 2
        assert rows[0]["net_pnl"] == 60.0
        assert rows[0]["trades"] == 2
        assert rows[0]["win_rate"] == 50.0

    def test_day_counters(self):
        s = summarize(
            [trade(100, day=1), trade(-40, day=2), trade(60, day=3)],
            risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0,
        )
        assert s["days"] == {
            "total": 3, "green": 2, "red": 1, "flat": 0,
            "win_rate": pytest.approx(66.7), "best": 100.0, "worst": -40.0, "avg": 40.0,
        }

    def test_equity_curve_accumulates(self):
        points = equity_curve([trade(100, r=1.0, day=1), trade(-40, r=-0.4, day=2)], 1_000.0)
        assert [p["cum_pnl"] for p in points] == [100.0, 60.0]
        assert points[-1]["equity"] == 1_060.0
        assert points[-1]["drawdown"] == 40.0


class TestConsistency:
    def test_one_big_day_scores_zero(self):
        assert consistency_score([{"net_pnl": 1000.0}, {"net_pnl": -50.0}]) == 0.0

    def test_evenly_spread_days_score_high(self):
        daily = [{"net_pnl": 100.0} for _ in range(10)]
        assert consistency_score(daily) == pytest.approx(90.0)

    def test_no_winning_days(self):
        assert consistency_score([{"net_pnl": -10.0}]) == 0.0


class TestZuluScore:
    def test_a_perfect_account_scores_100(self):
        summary = {
            "win_rate": 60.0,
            "profit_factor": 3.0,
            "payoff_ratio": 2.5,
            "max_drawdown_pct": 0.0,
            "recovery_factor": 5.0,
            "consistency": 100.0,
        }
        result = zulu_score(summary, SCORE)
        assert result["score"] == 100.0

    def test_components_are_clamped(self):
        result = zulu_score(
            {"win_rate": 100.0, "profit_factor": 99.0, "payoff_ratio": 10.0,
             "worst_loss_multiple": 12.0, "max_drawdown_pct": 90.0,
             "recovery_factor": 20.0, "consistency": 100.0},
            _with_weights(loss_consistency=1.0),
        )
        assert result["components"]["win_rate"] == 100.0
        # A worst loss twelve times a typical one is as bad as the scale goes.
        assert result["components"]["loss_consistency"] == 0.0
        assert result["components"]["max_drawdown"] == 0.0

    def test_weights_are_respected(self):
        summary = {
            "win_rate": 55.0, "profit_factor": 0.0, "payoff_ratio": 0.0,
            "max_drawdown_pct": 20.0, "recovery_factor": 0.0, "consistency": 0.0,
        }
        config = {
            "targets": SCORE["targets"],
            "weights": {"win_rate": 1.0, "profit_factor": 0.0, "avg_win_loss": 0.0,
                        "max_drawdown": 0.0, "recovery_factor": 0.0, "consistency": 0.0},
        }
        assert zulu_score(summary, config)["score"] == 100.0

    def test_a_missing_component_is_skipped_not_zeroed(self):
        """Too few losses to have a typical one; the score uses the rest."""
        summary = {
            "win_rate": 55.0, "profit_factor": 2.0, "payoff_ratio": 2.0,
            "worst_loss_multiple": None, "max_drawdown_pct": 0.0,
            "recovery_factor": 3.0, "consistency": 100.0,
        }
        result = zulu_score(summary, _with_weights(loss_consistency=1.0))
        assert result["components"]["loss_consistency"] is None
        assert result["score"] == 100.0

    def test_even_losses_score_full_marks(self):
        summary = {
            "win_rate": 55.0, "profit_factor": 2.0, "payoff_ratio": 2.0,
            "worst_loss_multiple": 1.0, "recovery_factor": 3.0, "consistency": 100.0,
        }
        config = _with_weights(loss_consistency=1.0)
        assert zulu_score(summary, config)["components"]["loss_consistency"] == 100.0


class TestScoreComponentsAreOptional:
    """Every component can be switched off, including all of them."""

    SUMMARY = {
        "win_rate": 55.0, "profit_factor": 2.0, "payoff_ratio": 2.0,
        "max_drawdown_pct": 10.0, "worst_loss_multiple": 1.0,
        "recovery_factor": 3.0, "consistency": 100.0,
    }

    def test_a_drawdown_half_the_target_scores_half(self):
        """The measure people mean by risk, back where it was.

        Ten percent below the high-water mark against a target of twenty is
        half the allowance spent, so it is half marks -- no inversion tricks.
        """
        result = zulu_score(self.SUMMARY, SCORE)
        assert result["components"]["max_drawdown"] == pytest.approx(50.0)

    def test_even_losses_is_off_unless_asked_for(self):
        """It measures something real, but it is not what risk usually means."""
        assert SCORE["weights"]["loss_consistency"] == 0.0
        assert zulu_score(self.SUMMARY, SCORE)["components"]["loss_consistency"] is None

    def test_a_switched_off_component_is_not_drawn(self):
        """Blanked rather than left at its value.

        A component with no weight contributes nothing to the score, so
        showing it on the radar would put a shape on the page that the number
        beside it does not come from.
        """
        result = zulu_score(self.SUMMARY, _with_weights(win_rate=0.0))
        assert result["components"]["win_rate"] is None
        assert result["score"] is not None

    def test_all_of_them_off_is_not_a_score_of_zero(self):
        """Nothing measured is not the same statement as measured badly."""
        config = {"targets": SCORE["targets"], "weights": dict.fromkeys(SCORE["weights"], 0.0)}
        result = zulu_score(self.SUMMARY, config)
        assert result["score"] is None
        assert "no components" in result["unavailable_reason"]
        assert all(value is None for value in result["components"].values())


def _with_weights(**overrides: float) -> dict:
    """The default score settings with some weights changed."""
    return {"targets": SCORE["targets"], "weights": {**SCORE["weights"], **overrides}}


class TestTradeSpecificFigures:
    """A number about one trade should be able to point at it."""

    def test_the_largest_win_and_loss_name_their_trades(self):
        trades = [
            trade(200, r=2.0, day=1),
            trade(900, r=9.0, day=2),
            trade(-100, r=-1.0, day=3),
            trade(-450, r=-4.5, day=4),
        ]
        s = summarize(
            trades, risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0
        )

        biggest = next(t for t in trades if t.net_pnl == 900)
        worst = next(t for t in trades if t.net_pnl == -450)
        assert s["largest_win"] == 900.0
        assert s["largest_win_id"] == biggest.id
        assert s["largest_loss"] == -450.0
        assert s["largest_loss_id"] == worst.id

    def test_nothing_to_point_at_is_not_an_error(self):
        s = summarize([], risk_cfg=RISK, stats_cfg=STATS, score_cfg=SCORE, account_size=10_000.0)
        assert s["largest_win_id"] is None
        assert s["largest_loss_id"] is None


class TestBreakdowns:
    def test_grouped_by_symbol_and_direction(self):
        trades = [
            trade(100, r=1.0, symbol="EURUSD", direction="long", day=1),
            trade(-50, r=-0.5, symbol="EURUSD", direction="short", day=2),
            trade(300, r=3.0, symbol="XAUUSD", direction="long", day=3),
        ]
        result = breakdowns(trades, "excluded")
        symbols = {row["key"]: row for row in result["by_symbol"]}
        assert symbols["XAUUSD"]["net_pnl"] == 300.0
        assert symbols["EURUSD"]["trades"] == 2
        assert symbols["EURUSD"]["win_rate"] == 50.0

        directions = {row["key"]: row for row in result["by_direction"]}
        assert directions["long"]["trades"] == 2

    def test_setups_come_from_tags_when_the_field_is_empty(self):
        """Tagging is how most people label a plan.

        The breakdown read only the free-text setup field, so a journal where
        every setup is a tag showed an empty card -- which reads as "no edge
        to see here" rather than "looking in the wrong place".
        """
        from app.models import Tag

        breakout = Tag(name="Breakout", category="setup", color="#fff")
        fomo = Tag(name="FOMO trade", category="emotion", color="#fff")

        first = trade(300, r=3.0, day=1)
        first.tags = [breakout, fomo]
        second = trade(-100, r=-1.0, day=2)
        second.tags = [breakout]

        rows = {row["key"]: row for row in breakdowns([first, second], "excluded")["by_setup"]}

        assert rows["Breakout"]["trades"] == 2
        assert rows["Breakout"]["net_pnl"] == 200.0
        assert "FOMO trade" not in rows, "that is a behaviour, not a plan"

    def test_the_setup_field_wins_where_it_is_filled_in(self):
        """Otherwise a trade with both would be counted twice, in two rows."""
        from app.models import Tag

        entry = trade(150, r=1.5, day=1)
        entry.setup = "London breakout"
        entry.tags = [Tag(name="Breakout", category="setup", color="#fff")]

        rows = {row["key"]: row for row in breakdowns([entry], "excluded")["by_setup"]}

        assert list(rows) == ["London breakout"]

    def test_a_trade_with_two_setup_tags_is_in_both_rows(self):
        from app.models import Tag

        entry = trade(200, r=2.0, day=1)
        entry.tags = [
            Tag(name="Breakout", category="setup", color="#fff"),
            Tag(name="Trend pullback", category="setup", color="#fff"),
        ]

        rows = {row["key"]: row for row in breakdowns([entry], "excluded")["by_setup"]}

        assert rows["Breakout"]["trades"] == 1
        assert rows["Trend pullback"]["trades"] == 1

    def test_r_multiple_buckets(self):
        trades = [trade(300, r=2.5, day=1), trade(-100, r=-1.0, day=2)]
        buckets = {row["key"]: row["trades"] for row in breakdowns(trades, "excluded")["by_r_multiple"]}
        assert buckets["2R..3R"] == 1
        assert buckets["-1R..0R"] == 1

    def test_duration_buckets(self):
        trades = [trade(10, day=1, duration=30), trade(10, day=2, duration=7200)]
        buckets = {row["key"] for row in breakdowns(trades, "excluded")["by_duration"]}
        assert buckets == {"< 1 min", "1-4 h"}


class TestPeriodBounds:
    TODAY = date(2026, 6, 17)  # a Wednesday

    def test_last_30_days(self):
        start, end = period_bounds("last_30_days", self.TODAY)
        assert (start, end) == (date(2026, 5, 19), self.TODAY)

    def test_this_week_monday_start(self):
        start, end = period_bounds("this_week", self.TODAY, "monday")
        assert (start, end) == (date(2026, 6, 15), date(2026, 6, 21))

    def test_this_week_sunday_start(self):
        start, end = period_bounds("this_week", self.TODAY, "sunday")
        assert (start, end) == (date(2026, 6, 14), date(2026, 6, 20))

    def test_last_month(self):
        start, end = period_bounds("last_month", self.TODAY)
        assert (start, end) == (date(2026, 5, 1), date(2026, 5, 31))

    def test_this_month(self):
        start, end = period_bounds("this_month", self.TODAY)
        assert (start, end) == (date(2026, 6, 1), date(2026, 6, 30))

    def test_this_quarter(self):
        start, end = period_bounds("this_quarter", self.TODAY)
        assert (start, end) == (date(2026, 4, 1), date(2026, 6, 30))

    def test_this_year(self):
        start, end = period_bounds("this_year", self.TODAY)
        assert (start, end) == (date(2026, 1, 1), date(2026, 12, 31))

    def test_a_named_period_runs_to_its_own_end_not_to_today(self):
        """The whole point: on a Wednesday, this week still ends on Sunday.

        Nothing is double-counted for it -- there are no trades in the future
        -- and the days still to come are visible instead of having to be
        typed in by hand.
        """
        for name in ("this_week", "this_month", "this_quarter", "this_year"):
            assert period_bounds(name, self.TODAY)[1] > self.TODAY, name

    def test_a_december_quarter_does_not_run_into_next_year(self):
        start, end = period_bounds("this_quarter", date(2026, 11, 4))
        assert (start, end) == (date(2026, 10, 1), date(2026, 12, 31))

    def test_a_december_month_ends_on_the_last_of_december(self):
        start, end = period_bounds("this_month", date(2026, 12, 4))
        assert (start, end) == (date(2026, 12, 1), date(2026, 12, 31))

    def test_february_in_a_leap_year(self):
        start, end = period_bounds("this_month", date(2028, 2, 3))
        assert (start, end) == (date(2028, 2, 1), date(2028, 2, 29))

    def test_all(self):
        start, _ = period_bounds("all", self.TODAY)
        assert start.year == 1970

    def test_unknown_falls_back_to_30_days(self):
        assert period_bounds("nonsense", self.TODAY) == period_bounds("last_30_days", self.TODAY)


class TestCrossAccountFigures:
    """A summary spanning several accounts withholds what it cannot know.

    Mixing accounts used to produce authoritative-looking nonsense: the
    combined profit of every account divided by whichever single balance
    happened to be handy, and a drawdown stitched from an equity curve nobody
    ever held.
    """

    def _mixed(self):
        first = trade(net=100.0, r=2.0, day=1)
        second = trade(net=-50.0, r=-1.0, day=2)
        second.account_id = 2
        return [first, second]

    def _summary(self, trades, single):
        return summarize(
            trades,
            risk_cfg={"breakeven_handling": "excluded"},
            stats_cfg={},
            score_cfg={"targets": {}, "weights": {}},
            account_size=10_000.0,
            single_account=single,
        )

    def test_the_per_account_figures_are_withheld(self):
        out = self._summary(self._mixed(), single=False)
        assert out["single_account"] is False
        for key in ("account_size", "max_drawdown", "max_drawdown_pct",
                    "recovery_factor", "sharpe", "sortino"):
            assert out[key] is None, f"{key} should be withheld across accounts"
        assert out["equity_curve"] == []
        assert out["zulu_score"]["score"] is None

    def test_what_genuinely_adds_up_survives(self):
        out = self._summary(self._mixed(), single=False)
        assert out["net_pnl"] == 50.0
        assert out["counts"]["total"] == 2
        assert out["win_rate"] is not None
        assert out["profit_factor"] is not None

    def test_a_daily_return_is_withheld_too(self):
        out = self._summary(self._mixed(), single=False)
        assert all(day["return_pct"] is None for day in out["daily"])

    def test_one_account_keeps_everything(self):
        single = [trade(net=100.0, r=2.0, day=1), trade(net=-50.0, r=-1.0, day=2)]
        out = self._summary(single, single_account := True)
        assert out["single_account"] is single_account
        assert out["account_size"] == 10_000.0
        assert out["max_drawdown"] is not None
        assert out["zulu_score"]["score"] is not None


class TestOversizedLosses:
    """What closed trades can say about risk, in place of a drawdown.

    A drawdown belongs to an equity curve sampled continuously. Built from
    closed trades it only sees the account when positions happened to end, so a
    position that ran deep against you and recovered leaves no trace -- and
    calling the result "maximum drawdown" claims something the data cannot
    support. Whether the losses were all the same size, it can answer.
    """

    def test_even_losses_are_a_multiple_of_one(self):
        from app.services.metrics import compute_oversize

        trades = [trade(-100, day=d) for d in range(1, 6)]
        worst, count, share = compute_oversize(trades)
        assert worst == pytest.approx(1.0)
        assert count == 0
        assert share == pytest.approx(0.0)

    def test_one_outsized_loss_is_found(self):
        from app.services.metrics import compute_oversize

        trades = [trade(-100, day=1), trade(-100, day=2), trade(-100, day=3),
                  trade(-500, day=4)]
        worst, count, share = compute_oversize(trades)
        assert worst == pytest.approx(5.0)
        assert count == 1
        assert share == pytest.approx(25.0)

    def test_winners_do_not_count(self):
        from app.services.metrics import compute_oversize

        trades = [trade(-100, day=1), trade(-100, day=2), trade(-100, day=3),
                  trade(9000, day=4)]
        assert compute_oversize(trades)[0] == pytest.approx(1.0)

    def test_too_few_losses_to_have_a_typical_one(self):
        from app.services.metrics import compute_oversize

        assert compute_oversize([trade(-100, day=1)]) == (None, 0, None)


class TestDistributions:
    """The box plots on the reports page.

    A series used to be dropped whenever it held fewer than four trades, which
    is right about quartiles and wrong about the card: a day with two winners
    and seven losers drew the losers on their own, with nothing to say the
    winners had been left out, while the win rate at the top of the same page
    said 22%.
    """

    def _series(self, trades):
        return {s["key"]: s for s in distributions(trades, "excluded")}

    def test_two_winners_are_still_shown(self):
        trades = [trade(200, r=2.0, day=1), trade(300, r=3.0, day=2)] + [
            trade(-100, r=-1.0, day=d) for d in range(3, 10)
        ]
        series = self._series(trades)
        assert "winners" in series
        assert series["winners"]["count"] == 2
        # Two trades, as the two trades they are -- not as quartiles of two.
        assert series["winners"]["points"] == [2.0, 3.0]
        assert "median" not in series["winners"]

    def test_four_is_enough_for_a_box(self):
        trades = [trade(100 * n, r=float(n), day=n) for n in range(1, 5)]
        winners = self._series(trades)["winners"]
        assert winners["count"] == 4
        assert "points" not in winners
        assert winners["median"] == pytest.approx(2.5)

    def test_the_few_are_reported_in_money_as_well(self):
        trades = [trade(200, r=2.0, day=1), trade(-100, r=-1.0, day=2)]
        winners = self._series(trades)["winners"]
        assert winners["points"] == [2.0]
        assert winners["money"]["points"] == [200.0]

    def test_a_series_survives_having_no_r_at_all(self):
        """Realised R needs a defined risk on every trade and net profit does
        not, so a journal kept without stops has a money form and no R one."""
        trades = [trade(net, day=day) for day, net in enumerate((50, -20, 30, -10, 90), start=1)]
        realised = self._series(trades)["realised"]
        assert realised["count"] == 0
        assert realised["money"]["count"] == 5

    def test_nothing_at_all_is_no_series(self):
        assert distributions([], "excluded") == []
