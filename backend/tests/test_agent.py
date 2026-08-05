"""The Expert Advisor protocol: report state, receive commands, report results.

This is the copier's execution path with no MetaTrader anywhere — the EA is
just an HTTP client, so the entire loop can be driven from a test.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.models import Account, CopyEvent, CopyLink


def account_payload(login, server, **kwargs):
    body = {
        "login": login,
        "server": server,
        "name": "Test",
        "currency": "USD",
        "balance": 10_000.0,
        "equity": 10_000.0,
        "positions": [],
        "symbols": [
            {
                "symbol": "EURUSD",
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "value_per_unit": 100_000.0,
                "digits": 5,
            }
        ],
        "results": [],
    }
    body.update(kwargs)
    return body


def master_payload(**kwargs):
    """The master is ten times the slave, so a copy is a tenth of the size."""
    return account_payload("5000", "Master-Server", balance=100_000.0, equity=100_000.0, **kwargs)


def position(position_id=1, ticket=1, symbol="EURUSD", direction="long",
             volume=1.0, price=1.1000, sl=1.0980, tp=1.1060):
    return {
        "position_id": position_id,
        "ticket": ticket,
        "symbol": symbol,
        "direction": direction,
        "volume": volume,
        "open_price": price,
        "stop_loss": sl,
        "take_profit": tp,
        "profit": 0.0,
    }


@pytest.fixture()
def master(db):
    account = db.scalar(select(Account).where(Account.role == "master"))
    account.login = "5000"
    account.server = "Master-Server"
    account.balance = account.equity = 100_000.0
    db.commit()
    return account


@pytest.fixture()
def slave(db, auth_client):
    created = auth_client.post(
        "/api/accounts",
        json={"login": "9001", "server": "Slave-Server", "name": "Slave",
              "password": "trade-password"},
    ).json()
    account = db.get(Account, created["id"])
    account.copy_settings = {**(account.copy_settings or {}), "mode": "balance_ratio"}
    db.commit()
    return account


def arm(auth_client, slave, *, dry_run=False):
    return auth_client.post(
        f"/api/accounts/{slave.id}/arm", json={"enabled": True, "dry_run": dry_run}
    )


class TestIdentification:
    def test_an_unknown_terminal_is_refused(self, auth_client):
        response = auth_client.post(
            "/api/agent/poll", json=account_payload("999999", "Nowhere-Live")
        )
        assert response.status_code == 404
        assert "Accounts" in response.json()["detail"]

    def test_the_master_is_recognised(self, auth_client, master):
        response = auth_client.post("/api/agent/poll", json=account_payload("5000", "Master-Server"))
        assert response.status_code == 200
        assert response.json()["role"] == "master"

    def test_a_server_name_matches_case_insensitively(self, auth_client, master):
        response = auth_client.post("/api/agent/poll", json=account_payload("5000", "master-server"))
        assert response.status_code == 200

    def test_the_same_login_at_a_different_broker_is_not_confused(self, auth_client, master, db):
        db.add(Account(login="5000", server="Other-Broker", role="slave"))
        db.commit()
        response = auth_client.post("/api/agent/poll", json=account_payload("5000", "Other-Broker"))
        assert response.json()["role"] == "slave"


class TestMaster:
    def test_the_master_is_never_given_commands(self, auth_client, master, slave):
        arm(auth_client, slave)
        response = auth_client.post(
            "/api/agent/poll",
            json=account_payload("5000", "Master-Server", positions=[position()]),
        )
        assert response.json()["commands"] == []

    def test_its_positions_are_recorded_for_the_slaves(self, auth_client, master, db):
        auth_client.post(
            "/api/agent/poll",
            json=account_payload("5000", "Master-Server", positions=[position()]),
        )
        db.refresh(master)
        stored = (master.copy_settings or {}).get("_positions")
        assert stored and stored[0]["symbol"] == "EURUSD"

    def test_account_state_is_updated(self, auth_client, master, db):
        auth_client.post(
            "/api/agent/poll",
            json=account_payload("5000", "Master-Server", balance=123_456.0, equity=123_000.0),
        )
        db.refresh(master)
        assert master.balance == pytest.approx(123_456.0)


class TestSlaveCommands:
    def test_a_master_trade_becomes_an_open_command(self, auth_client, master, slave):
        arm(auth_client, slave)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))

        response = auth_client.post("/api/agent/poll",
                                    json=account_payload("9001", "Slave-Server"))
        commands = response.json()["commands"]
        assert len(commands) == 1
        assert commands[0]["action"] == "open"
        assert commands[0]["symbol"] == "EURUSD"
        assert commands[0]["volume"] == pytest.approx(0.10)  # 10k / 100k
        assert commands[0]["id"]

    def test_nothing_is_sent_while_disabled(self, auth_client, master, slave):
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        response = auth_client.post("/api/agent/poll",
                                    json=account_payload("9001", "Slave-Server"))
        assert response.json()["commands"] == []

    def test_dry_run_sends_no_commands_but_records_the_decision(self, auth_client, master, slave, db):
        arm(auth_client, slave, dry_run=True)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        response = auth_client.post("/api/agent/poll",
                                    json=account_payload("9001", "Slave-Server"))

        assert response.json()["commands"] == []
        events = db.scalars(
            select(CopyEvent).where(CopyEvent.slave_account_id == slave.id,
                                    CopyEvent.action == "open")
        ).all()
        assert any(e.outcome == "dry_run" for e in events)

    def test_a_halted_account_gets_nothing(self, auth_client, master, slave, db):
        arm(auth_client, slave)
        slave.copy_halted = True
        db.commit()
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        response = auth_client.post("/api/agent/poll",
                                    json=account_payload("9001", "Slave-Server"))
        assert response.json()["commands"] == []

    def test_a_slave_polls_faster_than_a_master(self, auth_client, master, slave):
        arm(auth_client, slave)
        fast = auth_client.post("/api/agent/poll",
                                json=account_payload("9001", "Slave-Server")).json()
        slow = auth_client.post("/api/agent/poll",
                                json=account_payload("5000", "Master-Server")).json()
        assert fast["poll_seconds"] < slow["poll_seconds"]


class TestResults:
    def test_a_successful_open_creates_the_link(self, auth_client, master, slave, db):
        arm(auth_client, slave)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        command = auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        ).json()["commands"][0]

        auth_client.post("/api/agent/poll", json=account_payload(
            "9001", "Slave-Server",
            results=[{
                "id": command["id"], "action": "open", "ok": True, "ticket": 777,
                "master_position_id": 1, "symbol": "EURUSD", "direction": "long",
                "volume": 0.10, "price": 1.1001, "message": "filled",
            }],
            positions=[position(ticket=777, volume=0.10)],
        ))

        link = db.scalar(select(CopyLink).where(CopyLink.slave_account_id == slave.id))
        assert link is not None
        assert link.slave_position_id == 777
        assert link.status == "open"

    def test_a_failed_open_creates_no_link(self, auth_client, master, slave, db):
        arm(auth_client, slave)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        command = auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        ).json()["commands"][0]

        auth_client.post("/api/agent/poll", json=account_payload(
            "9001", "Slave-Server",
            results=[{
                "id": command["id"], "action": "open", "ok": False,
                "master_position_id": 1, "retcode": 10019,
                "message": "not enough money",
            }],
        ))

        assert db.scalars(select(CopyLink)).all() == []
        event = db.scalar(
            select(CopyEvent).where(CopyEvent.slave_account_id == slave.id,
                                    CopyEvent.outcome == "failed")
        )
        assert "not enough money" in event.message

    def test_the_same_trade_is_not_sent_twice(self, auth_client, master, slave):
        arm(auth_client, slave)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        first = auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        ).json()["commands"]

        auth_client.post("/api/agent/poll", json=account_payload(
            "9001", "Slave-Server",
            results=[{
                "id": first[0]["id"], "action": "open", "ok": True, "ticket": 777,
                "master_position_id": 1, "symbol": "EURUSD", "direction": "long",
                "volume": 0.10, "price": 1.1001,
            }],
            positions=[position(ticket=777, volume=0.10)],
        ))

        second = auth_client.post(
            "/api/agent/poll",
            json=account_payload("9001", "Slave-Server", positions=[position(ticket=777, volume=0.10)]),
        ).json()["commands"]
        assert [c for c in second if c["action"] == "open"] == []

    def test_a_closed_master_position_produces_a_close(self, auth_client, master, slave):
        arm(auth_client, slave)
        auth_client.post("/api/agent/poll", json=master_payload(positions=[position()]))
        command = auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        ).json()["commands"][0]
        auth_client.post("/api/agent/poll", json=account_payload(
            "9001", "Slave-Server",
            results=[{"id": command["id"], "action": "open", "ok": True, "ticket": 777,
                      "master_position_id": 1, "symbol": "EURUSD", "direction": "long",
                      "volume": 0.10, "price": 1.1001}],
            positions=[position(ticket=777, volume=0.10)],
        ))

        # Master goes flat.
        auth_client.post("/api/agent/poll", json=master_payload(positions=[]))
        commands = auth_client.post(
            "/api/agent/poll",
            json=account_payload("9001", "Slave-Server", positions=[position(ticket=777, volume=0.10)]),
        ).json()["commands"]

        assert any(c["action"] == "close" and c["ticket"] == 777 for c in commands)


class TestAuth:
    def test_the_endpoint_needs_a_token(self, client):
        response = client.post("/api/agent/poll", json=account_payload("5000", "Master-Server"))
        assert response.status_code == 401

    def test_the_ingest_token_is_accepted(self, client, master):
        response = client.post(
            "/api/agent/poll",
            json=account_payload("5000", "Master-Server"),
            headers={"X-API-Key": "test-ingest-token"},
        )
        assert response.status_code == 200


class TestTheProvisioningPlan:
    """What the machine running MetaTrader is told to have."""

    def _plan(self, client):
        return client.get(
            "/api/agent/terminals", headers={"X-API-Key": "test-ingest-token"}
        ).json()

    def test_an_account_with_no_password_gets_no_terminal(self, client, db, master):
        """A terminal that cannot log in sits at a prompt looking like it works."""
        assert self._plan(client)["terminals"] == []

    def test_every_account_is_named_whether_or_not_it_has_one(self, client, db, master, slave):
        """The list that says what has been forgotten and what merely has no password.

        Without it the provisioner cannot tell the two apart, and the only safe
        reading of "no terminal asked for" is to leave the MetaTrader install
        alone — which is how a forgotten account's terminal kept running for
        good, polling an account this server no longer had.
        """
        plan = self._plan(client)
        assert plan["known_accounts"] == [master.id, slave.id]
        assert [t["account_id"] for t in plan["terminals"]] == [slave.id]

    def test_a_forgotten_account_leaves_the_list(self, auth_client, client, db, master, slave):
        auth_client.delete(f"/api/accounts/{slave.id}")
        assert self._plan(client)["known_accounts"] == [master.id]


class TestEquityPoints:
    """Balance and equity are only knowable as they happen."""

    def test_a_sample_is_recorded_on_the_first_report(self, db):
        from app.models import Account, EquityPoint
        from app.services.copier.agent import record_equity_point

        account = Account(login="1", server="X", balance=1000.0, equity=1010.0)
        db.add(account)
        db.flush()

        record_equity_point(db, account, open_positions=2)
        db.flush()
        rows = db.query(EquityPoint).all()
        assert len(rows) == 1
        assert rows[0].balance == 1000.0
        assert rows[0].equity == 1010.0
        assert rows[0].open_positions == 2

    def test_samples_are_not_kept_for_every_poll(self, db):
        """A master polls every ten seconds; that is 8,640 rows a day for a
        line nobody can read that finely."""
        from app.models import Account, EquityPoint
        from app.services.copier.agent import record_equity_point

        account = Account(login="2", server="X", balance=1000.0, equity=1000.0)
        db.add(account)
        db.flush()

        for _ in range(5):
            record_equity_point(db, account)
            db.flush()
        assert db.query(EquityPoint).count() == 1


class TestLinkReuse:
    """A closed link must not stop a new one being recorded."""

    def test_a_closed_link_does_not_block_the_next_copy(self, db):
        """The bug this guards: one master trade became a hundred orders.

        record_result looked up the link by master position id alone, so a
        *closed* link -- left by a dry run, or by a position closed and taken
        again -- matched forever. The link for the real fill was never written,
        the planner kept seeing an uncopied position, and it opened another
        order on every single poll.
        """
        from types import SimpleNamespace

        from app.models import Account, CopyLink
        from app.services.copier.agent import record_result

        account = Account(login="9", server="X", role="slave")
        db.add(account)
        db.flush()

        db.add(
            CopyLink(
                slave_account_id=account.id,
                master_position_id=777,
                slave_position_id=0,
                symbol="EURUSD",
                slave_symbol="EURUSD",
                direction="long",
                slave_volume=0.01,
                status="closed",
                dry_run=True,
            )
        )
        db.flush()

        record_result(
            db,
            account,
            SimpleNamespace(
                ok=True, action="open", master_position_id=777, ticket=12345,
                symbol="EURUSD", direction="long", volume=0.01, price=1.1,
                stop_loss=0.0, take_profit=0.0, id="cmd", message="filled",
            ),
        )
        db.flush()

        live = db.query(CopyLink).filter(
            CopyLink.master_position_id == 777, CopyLink.status == "open"
        ).all()
        assert len(live) == 1, "the fill should have produced exactly one open link"
        assert live[0].slave_position_id == 12345


class TestRepeatedSkips:
    """A standing reason not to copy is recorded once, not on every poll."""

    def _poll(self, auth_client, slave):
        auth_client.post(
            "/api/agent/poll",
            json=account_payload("5000", "Master-Server", positions=[position()]),
        )
        return auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        )

    def _skips(self, db, slave):
        return db.scalars(
            select(CopyEvent).where(
                CopyEvent.slave_account_id == slave.id, CopyEvent.outcome == "skipped"
            )
        ).all()

    def test_the_same_reason_is_not_written_again(self, auth_client, master, slave, db):
        """The bug: an armed slave polls every two seconds, and a master
        position it will never copy was skipped -- and recorded -- every single
        time. Left alone that is tens of thousands of identical rows a day."""
        slave.copy_settings = {**slave.copy_settings, "blocked_symbols": ["EURUSD"]}
        db.commit()
        arm(auth_client, slave)

        for _ in range(5):
            self._poll(auth_client, slave)

        skips = self._skips(db, slave)
        assert len(skips) == 1
        assert "EURUSD" in skips[0].message

    def test_a_different_reason_is_new_information(self, auth_client, master, slave, db):
        slave.copy_settings = {**slave.copy_settings, "blocked_symbols": ["EURUSD"]}
        db.commit()
        arm(auth_client, slave)
        self._poll(auth_client, slave)

        # Same position, a different reason to leave it alone.
        db.refresh(slave)
        slave.copy_settings = {
            **slave.copy_settings, "blocked_symbols": [], "max_open_positions": -1,
            "allowed_symbols": ["GBPUSD"],
        }
        db.commit()
        self._poll(auth_client, slave)

        skips = self._skips(db, slave)
        assert len(skips) == 2
        assert skips[0].rule != skips[1].rule


class TestMasterIdentityChanges:
    """A different account number gets its own row, not the last one's history."""

    def _credentials(self, auth_client, login, server="Master-Server"):
        return auth_client.put(
            "/api/mt5/credentials",
            json={"login": login, "server": server, "password": "investor-password"},
        )

    def test_a_new_account_number_does_not_inherit_the_old_history(
        self, auth_client, master, db
    ):
        """The bug: one row held two broker accounts.

        Repointing login and server in place left every trade and equity sample
        of the previous account filed under the new one -- so a 250 account and
        a 10,000 account shared a row, and its equity curve jumped between them
        mid-series.
        """
        from app.models import EquityPoint

        db.add(EquityPoint(account_id=master.id, time=datetime(2026, 6, 1, 12),
                           balance=250.0, equity=250.0))
        db.commit()
        old_id = master.id

        assert self._credentials(auth_client, "7777").status_code in (200, 204)
        response = auth_client.post(
            "/api/agent/poll", json=account_payload("7777", "Master-Server")
        )
        assert response.status_code == 200

        db.expire_all()
        fresh = db.scalar(select(Account).where(Account.role == "master"))
        assert fresh.id != old_id, "the new account number needs its own row"
        assert fresh.login == "7777"

        previous = db.get(Account, old_id)
        assert previous.role == "archived"
        assert previous.login == "5000"
        # Its history stays with it, and is still reachable.
        assert db.scalar(
            select(func.count()).select_from(EquityPoint).where(
                EquityPoint.account_id == old_id
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(EquityPoint).where(
                EquityPoint.account_id == fresh.id
            )
        ) >= 0

    def test_the_new_master_becomes_the_default(self, auth_client, master, db):
        from app.models import Trade

        db.add(Trade(account_id=master.id, position_id=1, symbol="EURUSD", direction="long",
                     opened_at=datetime(2026, 6, 1, 9), closed_at=datetime(2026, 6, 1, 10),
                     trade_date=date(2026, 6, 1), volume=1.0, closed_volume=1.0,
                     entry_price=1.1, exit_price=1.11, net_pnl=10.0))
        master.is_default = True
        db.commit()

        self._credentials(auth_client, "7777")
        auth_client.post("/api/agent/poll", json=account_payload("7777", "Master-Server"))

        db.expire_all()
        fresh = db.scalar(select(Account).where(Account.role == "master"))
        assert fresh.is_default is True

    def test_an_empty_row_is_reused_rather_than_left_behind(self, auth_client, master, db):
        """Nothing filed under it yet, so there is nothing to protect."""
        old_id = master.id
        self._credentials(auth_client, "7777")
        auth_client.post("/api/agent/poll", json=account_payload("7777", "Master-Server"))

        db.expire_all()
        fresh = db.scalar(select(Account).where(Account.role == "master"))
        assert fresh.id == old_id
        assert db.scalar(select(func.count()).select_from(Account)) == 1

    def test_a_corrected_server_keeps_the_same_row(self, auth_client, master, db):
        """Same number, different server: a typo being fixed, not a new account."""
        from app.models import EquityPoint

        db.add(EquityPoint(account_id=master.id, time=datetime(2026, 6, 1, 12),
                           balance=250.0, equity=250.0))
        db.commit()
        old_id = master.id

        self._credentials(auth_client, "5000", server="Master-Server-2")
        auth_client.post("/api/agent/poll", json=account_payload("5000", "Master-Server-2"))

        db.expire_all()
        fresh = db.scalar(select(Account).where(Account.role == "master"))
        assert fresh.id == old_id
        assert fresh.server == "Master-Server-2"


class TestRestoringAnArchivedMaster:
    """Pointing the credentials back at an archived account brings it back."""

    def _credentials(self, auth_client, login, server="Master-Server"):
        return auth_client.put(
            "/api/mt5/credentials",
            json={"login": login, "server": server, "password": "investor-password"},
        )

    @pytest.fixture(autouse=True)
    def _with_history(self, master, db):
        """An empty row is reused rather than archived, so give it something."""
        from app.models import EquityPoint

        db.add(EquityPoint(account_id=master.id, time=datetime(2026, 6, 1, 12),
                           balance=250.0, equity=250.0))
        db.commit()

    def test_it_becomes_the_master_again(self, auth_client, master, db):
        # Point somewhere else, which archives the original.
        self._credentials(auth_client, "7777")
        auth_client.post("/api/agent/poll", json=account_payload("7777", "Master-Server"))
        db.expire_all()
        assert db.scalar(select(Account).where(Account.login == "5000")).role == "archived"

        # Point back.
        self._credentials(auth_client, "5000")
        response = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        )
        assert response.json()["role"] == "master"

        db.expire_all()
        assert db.scalar(select(Account).where(Account.login == "5000")).role == "master"
        assert db.scalar(select(Account).where(Account.login == "7777")).role == "archived"
        assert db.scalar(select(func.count()).select_from(Account).where(
            Account.role == "master")) == 1

    def test_an_archived_account_is_not_promoted_without_the_credentials(
        self, auth_client, master, db
    ):
        """A terminal reporting in proves it is running, not that it is the master."""
        self._credentials(auth_client, "7777")
        auth_client.post("/api/agent/poll", json=account_payload("7777", "Master-Server"))

        # 5000 is archived and the credentials still name 7777.
        response = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        )
        assert response.json()["role"] == "archived"
        db.expire_all()
        assert db.scalar(select(Account).where(Account.login == "7777")).role == "master"


class TestTheChartWindowReachesTheTerminal:
    """How much history to send with each trade is a setting, not an EA input.

    Sent on every heartbeat so widening it takes effect at the next trade
    rather than at the next terminal restart -- and in seconds, so the terminal
    divides by whatever timeframe it is set to collect rather than the server
    having to know.
    """

    def test_the_default_is_a_day_either_side(self, auth_client, master):
        reply = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        ).json()
        assert reply["history_before_seconds"] == 86_400
        assert reply["history_after_seconds"] == 86_400

    def test_it_follows_the_setting(self, auth_client, master):
        auth_client.put(
            "/api/settings",
            json={"charts": {"history_days_before": 5, "history_days_after": 0.5}},
        )

        reply = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        ).json()

        assert reply["history_before_seconds"] == 5 * 86_400
        assert reply["history_after_seconds"] == 43_200

    def test_an_absurd_window_is_capped(self, auth_client, master):
        """This is the size of every candle upload, on every closed trade.

        Left uncapped, one mistyped number has a terminal posting years of bars
        after each one.
        """
        auth_client.put("/api/settings", json={"charts": {"history_days_before": 100_000}})

        reply = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        ).json()

        assert reply["history_before_seconds"] == 90 * 86_400

    def test_nothing_asked_for_is_nothing_sent(self, auth_client, master):
        auth_client.put("/api/settings", json={"charts": {"history_days_after": 0}})

        reply = auth_client.post(
            "/api/agent/poll", json=account_payload("5000", "Master-Server")
        ).json()

        assert reply["history_after_seconds"] == 0

    def test_a_slave_is_told_as_well(self, auth_client, slave):
        """Slaves upload candles for their own copies, not only the master."""
        reply = auth_client.post(
            "/api/agent/poll", json=account_payload("9001", "Slave-Server")
        ).json()
        assert reply["history_before_seconds"] == 86_400
