"""Building the timeframes nobody collected out of the one that was.

A terminal sends one timeframe. Everything above it is arithmetic, and the
arithmetic has to be exact -- somebody reads their entry off these bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.candles import (
    Bar,
    aggregate,
    available,
    bars_in,
    source_for,
    window_padding,
)


def bars(count: int, *, span: int = 300, start: datetime | None = None) -> list[Bar]:
    """A run of bars, each one point higher than the last."""
    begin = start or datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    return [
        Bar(
            time=begin + timedelta(seconds=span * index),
            open=100.0 + index,
            high=100.5 + index,
            low=99.5 + index,
            close=100.2 + index,
            volume=10.0,
        )
        for index in range(count)
    ]


class TestWhatCanBeBuilt:
    def test_a_longer_timeframe_comes_from_a_shorter_one(self):
        assert source_for("H1", ["M5"]) == "M5"

    def test_a_shorter_one_cannot_be_invented(self):
        """M1 is not recoverable from M5, and interpolating it would be a lie."""
        assert source_for("M1", ["M5"]) is None

    def test_it_has_to_divide_exactly(self):
        """Two M5 bars are not an M15 bar."""
        assert source_for("M15", ["M10"]) is None
        assert source_for("H4", ["M30"]) == "M30"

    def test_the_largest_usable_source_wins(self):
        """Folding 4 H1 bars beats folding 48 M5 ones for the same answer."""
        assert source_for("H4", ["M5", "M15", "H1"]) == "H1"

    def test_what_is_offered_is_what_can_be_drawn(self):
        assert available(["M5"]) == ["M5", "M15", "M30", "H1", "H4", "D1", "W1"]
        assert available(["H1"]) == ["H1", "H4", "D1", "W1"]
        assert available([]) == []


class TestFolding:
    def test_three_five_minute_bars_make_a_quarter_hour(self):
        folded = aggregate(bars(3), "M15")

        assert len(folded) == 1
        assert folded[0].open == 100.0, "the first open"
        assert folded[0].close == 102.2, "the last close"
        assert folded[0].high == 102.5, "the highest high"
        assert folded[0].low == 99.5, "the lowest low"
        assert folded[0].volume == 30.0, "every bar's volume"

    def test_buckets_are_aligned_to_the_clock_not_to_the_first_bar(self):
        """Otherwise the same trade drawn twice puts its candles in
        different places, depending on where the window happened to start."""
        folded = aggregate(bars(12, start=datetime(2026, 6, 1, 8, 10, tzinfo=timezone.utc)), "H1")

        assert [bar.time.minute for bar in folded] == [0, 0]
        assert folded[0].time == datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)

    def test_a_partial_last_bucket_is_kept(self):
        """It is what the price is doing now.

        Dropping it would leave a chart ending an hour before the trade did,
        which reads as missing data rather than as an hour still in progress.
        """
        folded = aggregate(bars(14), "H1")  # 12 bars, then two into the next

        assert len(folded) == 2
        assert folded[1].volume == 20.0

    def test_a_day_starts_at_midnight(self):
        folded = aggregate(
            bars(288, start=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)), "D1"
        )

        assert len(folded) == 1
        assert folded[0].time == datetime(2026, 6, 1, tzinfo=timezone.utc)

    def test_nothing_in_nothing_out(self):
        assert aggregate([], "H1") == []


class TestWindow:
    """How much is read around a trade, now measured in days.

    It used to be a bar count of the requested timeframe, which meant the same
    setting was twelve hours at M5 and most of a month at H4 -- impossible to
    reason about, and it asked for history no terminal had ever collected. A
    window in days means the same stretch however finely it is drawn.
    """

    def test_days_are_days_at_any_timeframe(self):
        assert window_padding(1, 1) == (timedelta(days=1), timedelta(days=1))

    def test_either_side_is_set_separately(self):
        """The run-up to an entry and what happened afterwards are different
        questions, and people want different amounts of each."""
        before, after = window_padding(5, 0.5)
        assert before == timedelta(days=5)
        assert after == timedelta(hours=12)

    @pytest.mark.parametrize("days", [0, None])
    def test_nothing_asked_for_still_gives_a_usable_window(self, days):
        """An empty box in the settings must not produce an empty chart."""
        before, after = window_padding(days, days)
        assert before == after == timedelta(days=1)

    def test_a_negative_window_is_not_a_negative_window(self):
        before, after = window_padding(-5, -5)
        assert before == after == timedelta(0)


class TestBarsIn:
    """Turning a number of days into the bar count the terminal is asked for."""

    def test_a_day_of_five_minute_bars(self):
        assert bars_in(1, "M5") == 288

    def test_a_week_of_them(self):
        assert bars_in(7, "M5") == 2016

    def test_the_same_day_at_a_longer_timeframe(self):
        assert bars_in(1, "H1") == 24
        assert bars_in(1, "H4") == 6

    def test_a_fraction_of_a_day(self):
        assert bars_in(0.5, "M15") == 48

    def test_never_asks_for_nothing(self):
        assert bars_in(0, "H4") == 1
