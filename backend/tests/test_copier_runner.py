"""The copy loop end to end, against a broker that only exists in memory.

Every path a real account would take — opening, mirroring a stop, closing,
being refused, tripping a guard, failing at the broker — runs here without a
terminal, so the behaviour is pinned before any of it touches money.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from app.models import Account, CopyEvent, CopyLink
from app.services.copier.runner import run_cycle

TODAY = date(2026, 7, 28)


class FakeBroker:
    """A broker that records what it was asked to do."""

    def __init__(self, *, equity: float = 10_000.0, balance: float = 10_000.0) -> None:
        self.state = {"equity": equity, "balance": balance}
        self.open_positions: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_ticket = 5000
        self.fail_open = False
        self.raise_on_open = False
        self.available = ["EURUSD", "GBPUSD", "XAUUSD"]

    # -- reads -----------------------------------------------------------
    def account(self, account_id: int) -> dict[str, Any]:
        return dict(self.state)

    def positions(self, account_id: int) -> list[dict[str, Any]]:
        return [dict(row) for row in self.open_positions]

    def symbols(self, account_id: int) -> list[str]:
        return list(self.available)

    def symbol_spec(self, account_id: int, symbol: str) -> dict[str, Any]:
        if symbol.upper() not in {name.upper() for name in self.available}:
            raise RuntimeError(f"no symbol {symbol}")
        return {
            "symbol": symbol,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "value_per_unit": 100_000.0,
            "digits": 5,
        }

    # -- writes ----------------------------------------------------------
    def open(self, account_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("open", kwargs))
        if self.raise_on_open:
            raise RuntimeError("the terminal is not answering")
        if self.fail_open:
            return {"ok": False, "retcode": 10019, "comment": "not enough money"}

        self.next_ticket += 1
        self.open_positions.append(
            {
                "ticket": self.next_ticket,
                "position_id": self.next_ticket,
                "symbol": kwargs["symbol"],
                "direction": kwargs["direction"],
                "volume": kwargs["volume"],
                "open_price": 1.1000,
                "stop_loss": kwargs.get("stop_loss"),
                "take_profit": kwargs.get("take_profit"),
                "profit": 0.0,
            }
        )
        return {"ok": True, "order": self.next_ticket, "deal": self.next_ticket}

    def close(self, account_id: int, ticket: int, volume: float | None = None) -> dict[str, Any]:
        self.calls.append(("close", {"ticket": ticket}))
        self.open_positions = [row for row in self.open_positions if row["ticket"] != ticket]
        return {"ok": True}

    def modify(
        self, account_id: int, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> dict[str, Any]:
        self.calls.append(("modify", {"ticket": ticket, "sl": stop_loss, "tp": take_profit}))
        for row in self.open_positions:
            if row["ticket"] == ticket:
                row["stop_loss"] = stop_loss
                row["take_profit"] = take_profit
        return {"ok": True}

    # -- helpers ---------------------------------------------------------
    def actions(self, kind: str) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == kind]


def master_row(position_id=1, symbol="EURUSD", direction="long", volume=1.0,
               price=1.1000, sl=1.0980, tp=1.1060):
    return {
        "position_id": position_id,
        "ticket": position_id,
        "symbol": symbol,
        "direction": direction,
        "volume": volume,
        "open_price": price,
        "stop_loss": sl,
        "take_profit": tp,
    }


@pytest.fixture()
def accounts(db):
    master = db.scalar(select(Account).where(Account.role == "master"))
    master.balance, master.equity = 100_000.0, 100_000.0
    slave = Account(
        login="9001",
        server="Slave-Server",
        name="Slave",
        role="slave",
        copy_enabled=True,
        copy_dry_run=False,
        copy_settings={"mode": "balance_ratio"},
    )
    db.add(slave)
    db.commit()
    return master, slave


class TestOpening:
    def test_a_master_trade_is_copied_and_scaled(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()

        result = run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert result.executed == 1
        opened = broker.actions("open")
        assert len(opened) == 1
        assert opened[0]["symbol"] == "EURUSD"
        assert opened[0]["volume"] == pytest.approx(0.10)  # 10k / 100k
        assert opened[0]["stop_loss"] == pytest.approx(1.0980)

    def test_a_link_is_recorded(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        link = db.scalar(select(CopyLink).where(CopyLink.slave_account_id == slave.id))
        assert link is not None
        assert link.master_position_id == 1
        assert link.status == "open"
        assert link.slave_position_id > 0

    def test_the_same_trade_is_not_copied_twice(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        rows = [master_row()]

        run_cycle(db, master, slave, broker, rows, TODAY)
        db.commit()
        run_cycle(db, master, slave, broker, rows, TODAY)
        db.commit()

        assert len(broker.actions("open")) == 1

    def test_an_event_is_written(self, db, accounts):
        master, slave = accounts
        run_cycle(db, master, slave, FakeBroker(), [master_row()], TODAY)
        db.commit()

        event = db.scalar(
            select(CopyEvent).where(CopyEvent.slave_account_id == slave.id)
        )
        assert event.action == "open"
        assert event.outcome == "ok"


class TestClosing:
    def test_the_copy_closes_when_the_master_does(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()

        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()
        run_cycle(db, master, slave, broker, [], TODAY)  # master flat
        db.commit()

        assert len(broker.actions("close")) == 1
        assert broker.open_positions == []

    def test_the_link_is_marked_closed(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()
        run_cycle(db, master, slave, broker, [], TODAY)
        db.commit()

        link = db.scalar(select(CopyLink).where(CopyLink.slave_account_id == slave.id))
        assert link.status == "closed"
        assert link.closed_at is not None

    def test_a_position_closed_at_the_broker_is_noticed(self, db, accounts):
        """A stop-out is not our close, but our record must still catch up."""
        master, slave = accounts
        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        broker.open_positions.clear()  # stopped out
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        links = db.scalars(select(CopyLink).where(CopyLink.slave_account_id == slave.id)).all()
        assert any(link.status == "closed" for link in links)


class TestMirroring:
    def test_a_moved_stop_is_pushed_to_the_slave(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        run_cycle(db, master, slave, broker, [master_row(sl=1.1000)], TODAY)
        db.commit()

        modified = broker.actions("modify")
        assert len(modified) == 1
        assert modified[0]["sl"] == pytest.approx(1.1000)

    def test_nothing_happens_when_nothing_moved(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert broker.actions("modify") == []

    def test_mirroring_can_be_switched_off(self, db, accounts):
        master, slave = accounts
        slave.copy_settings = {"mode": "balance_ratio", "mirror_stops": False}
        db.commit()

        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()
        run_cycle(db, master, slave, broker, [master_row(sl=1.1000)], TODAY)
        db.commit()

        assert broker.actions("modify") == []


class TestDryRun:
    def test_nothing_reaches_the_broker(self, db, accounts):
        master, slave = accounts
        slave.copy_dry_run = True
        db.commit()

        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert broker.calls == []

    def test_it_still_records_what_it_would_have_done(self, db, accounts):
        master, slave = accounts
        slave.copy_dry_run = True
        db.commit()

        run_cycle(db, master, slave, FakeBroker(), [master_row()], TODAY)
        db.commit()

        event = db.scalar(select(CopyEvent).where(CopyEvent.slave_account_id == slave.id))
        assert event.action == "open"
        assert event.outcome == "dry_run"
        assert event.volume == pytest.approx(0.10)

    def test_a_dry_run_does_not_repeat_the_same_trade_every_pass(self, db, accounts):
        master, slave = accounts
        slave.copy_dry_run = True
        db.commit()

        rows = [master_row()]
        run_cycle(db, master, slave, FakeBroker(), rows, TODAY)
        db.commit()
        run_cycle(db, master, slave, FakeBroker(), rows, TODAY)
        db.commit()

        events = db.scalars(
            select(CopyEvent).where(
                CopyEvent.slave_account_id == slave.id, CopyEvent.action == "open"
            )
        ).all()
        assert len(events) == 1


class TestRefusals:
    def test_a_symbol_the_broker_lacks_is_skipped(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        broker.available = ["GBPUSD"]

        result = run_cycle(db, master, slave, broker, [master_row(symbol="EURUSD")], TODAY)
        db.commit()

        assert result.skipped == 1
        assert broker.calls == []
        event = db.scalar(select(CopyEvent).where(CopyEvent.slave_account_id == slave.id))
        assert event.outcome == "skipped"
        assert event.rule == "symbol_not_found"

    def test_a_per_trade_limit_is_recorded_with_its_rule(self, db, accounts):
        master, slave = accounts
        slave.copy_settings = {
            "mode": "balance_ratio", "max_lot": 0.01, "max_lot_refuses": True,
        }
        db.commit()

        run_cycle(db, master, slave, FakeBroker(), [master_row()], TODAY)
        db.commit()

        event = db.scalar(select(CopyEvent).where(CopyEvent.slave_account_id == slave.id))
        assert event.outcome == "skipped"
        assert event.rule == "max_lot"


class TestBrokerFailures:
    def test_a_rejected_order_is_recorded_not_raised(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        broker.fail_open = True

        result = run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert result.failed == 1
        event = db.scalar(select(CopyEvent).where(CopyEvent.slave_account_id == slave.id))
        assert event.outcome == "failed"
        assert "not enough money" in event.message

    def test_no_link_is_left_behind_by_a_failed_open(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        broker.fail_open = True
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert db.scalars(select(CopyLink)).all() == []

    def test_an_exception_from_the_terminal_is_contained(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker()
        broker.raise_on_open = True

        result = run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert result.failed == 1
        event = db.scalar(select(CopyEvent).where(CopyEvent.slave_account_id == slave.id))
        assert "not answering" in event.message


class TestGuards:
    def test_an_equity_stop_halts_the_account_and_flattens_it(self, db, accounts):
        master, slave = accounts
        slave.copy_settings = {"mode": "balance_ratio", "equity_stop_percent": 5.0}
        db.commit()

        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        # Equity falls well below the peak recorded on the first pass.
        broker.state["equity"] = 8_000.0
        result = run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert result.halted
        assert slave.copy_halted is True
        assert "peak" in slave.copy_halt_reason
        assert len(broker.actions("close")) == 1

    def test_a_halted_account_opens_nothing_further(self, db, accounts):
        master, slave = accounts
        slave.copy_halted = True
        db.commit()

        broker = FakeBroker()
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert broker.actions("open") == []

    def test_the_days_opening_equity_is_remembered(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker(equity=10_000.0)
        run_cycle(db, master, slave, broker, [], TODAY)
        db.commit()

        assert slave.day_start_equity == pytest.approx(10_000.0)
        assert slave.day_start_date == TODAY

        # Later in the same day, equity moves but the opening figure holds.
        broker.state["equity"] = 9_500.0
        run_cycle(db, master, slave, broker, [], TODAY)
        db.commit()
        assert slave.day_start_equity == pytest.approx(10_000.0)

    def test_a_new_day_resets_it(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker(equity=10_000.0)
        run_cycle(db, master, slave, broker, [], TODAY)
        db.commit()

        broker.state["equity"] = 9_500.0
        run_cycle(db, master, slave, broker, [], date(2026, 7, 29))
        db.commit()
        assert slave.day_start_equity == pytest.approx(9_500.0)


class TestScaling:
    def test_a_larger_slave_trades_larger(self, db, accounts):
        master, slave = accounts
        broker = FakeBroker(balance=500_000.0, equity=500_000.0)

        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert broker.actions("open")[0]["volume"] == pytest.approx(5.0)

    def test_a_broker_suffix_is_resolved(self, db, accounts):
        master, slave = accounts
        slave.symbol_suffix = ".r"
        db.commit()

        broker = FakeBroker()
        broker.available = ["EURUSD.r", "GBPUSD.r"]
        run_cycle(db, master, slave, broker, [master_row()], TODAY)
        db.commit()

        assert broker.actions("open")[0]["symbol"] == "EURUSD.r"
