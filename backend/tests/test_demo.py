"""The throwaway journal behind TZ_DEMO=1.

Only the parts that can fail on their own are tested. The trades themselves are
made up and nothing depends on their shape, but the seeding has to *finish*:
half a demo database is worse than none, and it takes the container down with
it on the way.
"""

from __future__ import annotations

import random
from datetime import date, datetime

from app.demo import NOTES, _seed_notes
from app.models import DayNote, Trade


def trade(day: int) -> Trade:
    when = datetime(2026, 6, day, 10, 0)
    return Trade(
        account_id=1, position_id=day, symbol="EURUSD", direction="long",
        opened_at=when, closed_at=when, trade_date=date(2026, 6, day),
        volume=1.0, closed_volume=1.0, entry_price=1.1, exit_price=1.11,
        gross_profit=1.0, commission=0.0, swap=0.0, fee=0.0, net_pnl=1.0,
        outcome="win",
    )


class OneDayOnly(random.Random):
    """Every draw lands on the same day, which is what collided in the wild."""

    def choice(self, seq):  # type: ignore[override]
        return seq[0]


class TestSeedingNotes:
    def test_two_draws_on_one_day_produce_one_note(self, db):
        """The bug: the duplicate check asked the database, and the session does
        not autoflush -- so a note added a moment earlier in the same loop was
        invisible to it. It surfaced as an IntegrityError at commit, which took
        the whole seed down on whichever dates the draw happened to collide."""
        trades = [trade(1), trade(2), trade(3)]
        _seed_notes(db, OneDayOnly(), trades)
        db.commit()

        assert db.query(DayNote).count() == 1

    def test_notes_land_on_days_that_have_trades(self, db):
        trades = [trade(day) for day in range(1, 12)]
        _seed_notes(db, random.Random(7), trades)
        db.commit()

        days = {note.day for note in db.query(DayNote)}
        assert days and days <= {t.trade_date for t in trades}

    def test_seeding_twice_adds_nothing_new(self, db):
        """It runs on every start, and the second start must be a no-op."""
        trades = [trade(day) for day in range(1, 12)]
        _seed_notes(db, random.Random(7), trades)
        db.commit()
        first = db.query(DayNote).count()

        _seed_notes(db, random.Random(7), trades)
        db.commit()

        assert db.query(DayNote).count() == first

    def test_no_trades_means_no_notes(self, db):
        _seed_notes(db, random.Random(7), [])
        db.commit()
        assert db.query(DayNote).count() == 0

    def test_there_is_something_to_write(self):
        assert NOTES
