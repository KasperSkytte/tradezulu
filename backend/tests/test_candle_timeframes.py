"""Building the timeframes nobody collected out of the one that was.

A terminal sends one timeframe. Everything above it is arithmetic, and the
arithmetic has to be exact -- somebody reads their entry off these bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.candles import Bar, aggregate, available, source_for, window_padding


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
    def test_the_window_widens_with_the_timeframe(self):
        """A hundred bars of H4 is a fortnight; a hundred of M5 is eight hours.

        Padding measured in bars of the *requested* timeframe is what makes
        zooming out actually show more, rather than the same eight hours drawn
        as two candles.
        """
        before_m5, _ = window_padding("M5", 120, 60)
        before_h4, _ = window_padding("H4", 120, 60)

        assert before_m5 == timedelta(hours=10)
        assert before_h4 == timedelta(days=20)

    @pytest.mark.parametrize("count", [0, -5])
    def test_a_silly_padding_still_leaves_one_bar(self, count):
        before, after = window_padding("M5", count, count)
        assert before == after == timedelta(minutes=5)
