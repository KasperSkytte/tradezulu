"""Working out how far a broker's clock runs from UTC.

Everything MetaTrader reports is on that clock and says nothing about it, so
this one number is what stands between "09:37" and a real moment. Getting it
wrong moves every time the journal shows by whole hours, which is exactly the
kind of wrong that looks right.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brokerclock import offset_minutes

#: A fixed "now" to measure against, so the tests do not depend on when they run.
NOW = datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc)


def epoch(*, hours: float) -> int:
    """The broker's clock, ``hours`` ahead of our UTC, as MetaTrader sends it."""
    return int((NOW + timedelta(hours=hours)).timestamp())


class TestOffset:
    def test_a_broker_three_hours_ahead(self):
        """The common case: an EET broker in summer."""
        assert offset_minutes(epoch(hours=3), now=NOW) == 180

    def test_a_broker_behind_utc(self):
        assert offset_minutes(epoch(hours=-5), now=NOW) == -300

    def test_a_broker_on_utc(self):
        assert offset_minutes(epoch(hours=0), now=NOW) == 0

    def test_time_in_flight_does_not_invent_an_offset(self):
        """A request takes a moment, and a terminal polls on its own schedule.

        Rounding to the quarter hour absorbs that. Without it a broker three
        hours ahead would be recorded as 2h59m ahead and every label would be
        a minute out, differently on every poll.
        """
        assert offset_minutes(epoch(hours=3) - 4, now=NOW) == 180
        assert offset_minutes(epoch(hours=3) + 40, now=NOW) == 180

    def test_a_half_hour_broker_survives_the_rounding(self):
        """India and Nepal exist, and so do brokers who serve them."""
        assert offset_minutes(epoch(hours=5.5), now=NOW) == 330
        assert offset_minutes(epoch(hours=-4.5) + 20, now=NOW) == -270


class TestNothingUsable:
    """Anything that is not an offset leaves the known one alone.

    The caller only writes a result when this returns a number, so ``None`` is
    how the clock keeps whatever it last learned instead of being replaced by
    a guess.
    """

    def test_a_terminal_that_has_not_synchronised(self):
        """MetaTrader reports 1970 before it has spoken to the broker."""
        assert offset_minutes(0, now=NOW) is None

    def test_an_absurd_clock(self):
        assert offset_minutes(epoch(hours=30), now=NOW) is None

    def test_nothing_sent_at_all(self):
        """An older Expert Advisor does not send the field."""
        assert offset_minutes(None, now=NOW) is None

    def test_rubbish(self):
        assert offset_minutes("not a time", now=NOW) is None
        assert offset_minutes({}, now=NOW) is None
        assert offset_minutes(True, now=NOW) is None


class TestOtherShapes:
    """The field is an epoch from the EA, but the endpoint is public."""

    def test_an_iso_string(self):
        assert offset_minutes("2026-08-05T10:00:00", now=NOW) == 180

    def test_a_zone_is_honoured_rather_than_read_off_the_digits(self):
        """Both of these are the same instant, so both mean the same offset.

        What is being measured is how far the broker's *clock* is from ours,
        which is a question about the moment it sent, not about how it chose
        to write it down.
        """
        assert offset_minutes("2026-08-05T10:00:00+00:00", now=NOW) == 180
        assert offset_minutes("2026-08-05T12:00:00+02:00", now=NOW) == 180

    def test_a_datetime(self):
        assert offset_minutes(datetime(2026, 8, 5, 10, 0), now=NOW) == 180
