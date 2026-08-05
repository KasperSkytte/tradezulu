"""Which clock a timestamp is on, once it has left the API.

Two clocks are stored in columns that look identical: ours, and the broker's.
A naive timestamp in JSON is read by every browser as *local* time, so which
of the two a field is on decides whether it survives the trip.

This is not a formatting preference. Reading one of our UTC instants as local
made a terminal that had reported five seconds earlier show as "quiet 2 hours
ago" for a reader in Copenhagen -- and, in the other direction, would have
made a terminal that died an hour ago look like it had just checked in.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import AccountOut, CandleOut, CopyEventOut, ExecutionOut, SlaveAccountOut


def offset_of(payload: str, field: str) -> str:
    """The tail of a serialised timestamp: 'Z', '+00:00', or nothing at all."""
    value = payload.split(f'"{field}":"', 1)[1].split('"', 1)[0]
    return value[19:]  # everything after YYYY-MM-DDTHH:MM:SS


class TestOurClock:
    """Recorded from this machine in UTC, so it must say so."""

    def test_a_terminals_last_report_carries_its_offset(self):
        account = AccountOut(
            id=1, login="1", name="", broker="", server="", currency="USD", leverage=0,
            balance=0.0, equity=0.0, initial_balance=0.0, is_default=True,
            last_sync_at=datetime(2026, 8, 5, 7, 28, 48), last_sync_source="agent",
        )
        assert offset_of(account.model_dump_json(), "last_sync_at") in ("Z", "+00:00")

    def test_it_is_the_instant_that_is_kept_not_the_digits(self):
        """A reader two hours east must see 09:28, not 07:28."""
        account = AccountOut(
            id=1, login="1", name="", broker="", server="", currency="USD", leverage=0,
            balance=0.0, equity=0.0, initial_balance=0.0, is_default=True,
            last_sync_at=datetime(2026, 8, 5, 7, 28, 48), last_sync_source="agent",
        )
        assert account.last_sync_at == datetime(2026, 8, 5, 7, 28, 48, tzinfo=timezone.utc)

    def test_an_already_aware_value_is_left_alone(self):
        account = AccountOut(
            id=1, login="1", name="", broker="", server="", currency="USD", leverage=0,
            balance=0.0, equity=0.0, initial_balance=0.0, is_default=True,
            last_sync_at=datetime(2026, 8, 5, 7, 28, 48, tzinfo=timezone.utc),
            last_sync_source="agent",
        )
        assert account.last_sync_at.utcoffset().total_seconds() == 0

    def test_nothing_reported_stays_nothing(self):
        account = AccountOut(
            id=1, login="1", name="", broker="", server="", currency="USD", leverage=0,
            balance=0.0, equity=0.0, initial_balance=0.0, is_default=True,
            last_sync_at=None, last_sync_source="",
        )
        assert account.last_sync_at is None

    def test_the_copiers_log_is_on_it_too(self):
        event = CopyEventOut(
            id=1, slave_account_id=2, master_position_id=99, action="open",
            outcome="ok", symbol="EURUSD", direction="long", volume=0.1, price=1.1,
            rule="", message="", latency_ms=12,
            created_at=datetime(2026, 8, 5, 7, 28, 48),
        )
        assert offset_of(event.model_dump_json(), "created_at") in ("Z", "+00:00")

    def test_a_halted_slave_reports_when(self):
        slave = _slave(copy_halted_at=datetime(2026, 8, 5, 7, 0))
        assert offset_of(slave.model_dump_json(), "copy_halted_at") in ("Z", "+00:00")


class TestTheBrokersClock:
    """Passed through exactly as MetaTrader wrote it.

    There is no offset that would be true for every account, and attaching the
    wrong one would move a fill onto a bar it did not happen in. The chart puts
    these on one clock itself.
    """

    def test_a_fill_keeps_the_time_the_terminal_shows(self):
        execution = ExecutionOut(
            id=1, ticket=1, kind="in", side="buy", volume=0.02, price=4175.1,
            time=datetime(2026, 8, 5, 9, 37, 40), profit=0.0, commission=0.0, swap=0.0,
        )
        assert offset_of(execution.model_dump_json(), "time") == ""

    def test_a_candle_keeps_it_as_well(self):
        """The bar and the fill on it have to be on the same clock.

        They were not: candles went out marked UTC and fills went out unmarked,
        so a browser two hours from UTC drew the entry arrow two hours from its
        own candle.
        """
        candle = CandleOut(
            time=datetime(2026, 8, 5, 9, 35), open=1.0, high=1.0, low=1.0,
            close=1.0, volume=1.0,
        )
        assert offset_of(candle.model_dump_json(), "time") == ""


def _slave(**kwargs) -> SlaveAccountOut:
    base = {
        "id": 1, "login": "1", "name": "", "broker": "", "server": "",
        "currency": "USD", "role": "slave", "balance": 0.0, "equity": 0.0,
        "is_default": False, "last_sync_at": None, "copy_enabled": False,
        "copy_dry_run": True, "copy_halted": False, "copy_halt_reason": "",
        "copy_halted_at": None, "has_password": False, "symbol_prefix": "",
        "symbol_suffix": "", "symbol_map": {}, "settings": {}, "open_copies": 0,
    }
    base.update(kwargs)
    return SlaveAccountOut(**base)
