"""The accounts API, and the guard rails around arming a slave."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Account, CopyEvent
from app.services.crypto import decrypt


@pytest.fixture()
def slave(auth_client, db):
    response = auth_client.post(
        "/api/accounts",
        json={
            "login": "7001",
            "server": "PropFirm-Live",
            "name": "Prop challenge",
            "password": "trade-enabled-secret",
        },
    )
    assert response.status_code == 201
    return response.json()


class TestAdding:
    def test_a_new_slave_is_off_and_in_dry_run(self, slave):
        assert slave["role"] == "slave"
        assert slave["copy_enabled"] is False
        assert slave["copy_dry_run"] is True

    def test_the_password_is_stored_encrypted(self, slave, db):
        account = db.get(Account, slave["id"])
        assert account.password_enc
        assert "trade-enabled-secret" not in account.password_enc
        assert decrypt(account.password_enc) == "trade-enabled-secret"

    def test_the_password_never_comes_back_out(self, auth_client, slave):
        body = auth_client.get("/api/accounts").text
        assert "trade-enabled-secret" not in body

    def test_it_reports_that_a_password_exists(self, slave):
        assert slave["has_password"] is True

    def test_settings_are_filled_in_with_the_defaults(self, slave):
        assert slave["settings"]["mode"] == "balance_ratio"
        assert slave["settings"]["breach_action"] == "close_all"

    def test_the_same_account_twice_is_refused(self, auth_client, slave):
        response = auth_client.post(
            "/api/accounts", json={"login": "7001", "server": "PropFirm-Live"}
        )
        assert response.status_code == 409

    def test_a_slave_cannot_be_created_already_live(self, auth_client):
        """Even if the caller asks for it."""
        response = auth_client.post(
            "/api/accounts",
            json={"login": "7002", "server": "X", "copy_enabled": True, "copy_dry_run": False},
        )
        assert response.json()["copy_enabled"] is False
        assert response.json()["copy_dry_run"] is True


class TestArming:
    def test_dry_run_is_allowed(self, auth_client, slave):
        response = auth_client.post(
            f"/api/accounts/{slave['id']}/arm", json={"enabled": True, "dry_run": True}
        )
        assert response.status_code == 200
        assert response.json()["copy_enabled"] is True
        assert response.json()["copy_dry_run"] is True

    def test_going_live_needs_a_password(self, auth_client, db):
        created = auth_client.post(
            "/api/accounts", json={"login": "7003", "server": "NoPass"}
        ).json()

        response = auth_client.post(
            f"/api/accounts/{created['id']}/arm", json={"enabled": True, "dry_run": False}
        )
        assert response.status_code == 400
        assert "password" in response.json()["detail"].lower()

    def test_going_live_works_with_a_password(self, auth_client, slave):
        response = auth_client.post(
            f"/api/accounts/{slave['id']}/arm", json={"enabled": True, "dry_run": False}
        )
        assert response.status_code == 200
        assert response.json()["copy_dry_run"] is False

    def test_dry_run_is_allowed_without_a_password(self, auth_client):
        """Watching what it would do needs no credentials."""
        created = auth_client.post("/api/accounts", json={"login": "7004", "server": "NoPass2"}).json()
        response = auth_client.post(
            f"/api/accounts/{created['id']}/arm", json={"enabled": True, "dry_run": True}
        )
        assert response.status_code == 200

    def test_arming_clears_a_previous_halt(self, auth_client, slave, db):
        account = db.get(Account, slave["id"])
        account.copy_halted = True
        account.copy_halt_reason = "daily drawdown"
        db.commit()

        response = auth_client.post(
            f"/api/accounts/{slave['id']}/arm", json={"enabled": True, "dry_run": True}
        )
        assert response.json()["copy_halted"] is False

    def test_arming_is_recorded(self, auth_client, slave, db):
        auth_client.post(f"/api/accounts/{slave['id']}/arm", json={"enabled": True, "dry_run": True})
        events = db.scalars(
            select(CopyEvent).where(CopyEvent.slave_account_id == slave["id"])
        ).all()
        assert any("enabled" in event.message for event in events)

    def test_the_master_cannot_be_armed(self, auth_client, db):
        master = db.scalar(select(Account).where(Account.role == "master"))
        response = auth_client.post(
            f"/api/accounts/{master.id}/arm", json={"enabled": True, "dry_run": True}
        )
        assert response.status_code == 400


class TestEditing:
    def test_an_omitted_password_is_kept(self, auth_client, slave, db):
        auth_client.put(
            f"/api/accounts/{slave['id']}",
            json={"login": "7001", "server": "PropFirm-Live", "name": "Renamed"},
        )
        assert decrypt(db.get(Account, slave["id"]).password_enc) == "trade-enabled-secret"

    def test_an_empty_password_clears_it_and_disarms(self, auth_client, slave, db):
        auth_client.post(f"/api/accounts/{slave['id']}/arm", json={"enabled": True, "dry_run": False})

        response = auth_client.put(
            f"/api/accounts/{slave['id']}",
            json={"login": "7001", "server": "PropFirm-Live", "password": ""},
        )
        assert response.json()["has_password"] is False
        # It must not stay live with no way to place an order.
        assert response.json()["copy_enabled"] is False

    def test_risk_settings_round_trip(self, auth_client, slave):
        response = auth_client.put(
            f"/api/accounts/{slave['id']}",
            json={
                "login": "7001",
                "server": "PropFirm-Live",
                "settings": {"mode": "risk_percent", "risk_percent": 0.5, "max_open_positions": 3},
            },
        )
        settings = response.json()["settings"]
        assert settings["mode"] == "risk_percent"
        assert settings["risk_percent"] == 0.5
        assert settings["max_open_positions"] == 3
        # Untouched keys keep their defaults rather than vanishing.
        assert settings["breach_action"] == "close_all"


class TestRemoving:
    def test_a_slave_can_be_removed(self, auth_client, slave):
        response = auth_client.delete(f"/api/accounts/{slave['id']}")
        assert response.status_code == 200
        assert all(a["id"] != slave["id"] for a in auth_client.get("/api/accounts").json())

    def test_removing_it_takes_its_history_with_it(self, auth_client, slave, db):
        """The bug: an account vanished from the interface and stayed in the sums.

        Its trades still counted towards every total, and the next account
        added with the same number inherited them.
        """
        from datetime import date, datetime

        from app.models import CopyEvent, CopyLink, EquityPoint, Trade

        account_id = slave["id"]
        db.add(Trade(account_id=account_id, position_id=1, symbol="EURUSD", direction="long",
                     opened_at=datetime(2026, 6, 1, 9), closed_at=datetime(2026, 6, 1, 10),
                     trade_date=date(2026, 6, 1), volume=1.0, closed_volume=1.0,
                     entry_price=1.1, exit_price=1.11, net_pnl=25.0))
        db.add(EquityPoint(account_id=account_id, time=datetime(2026, 6, 1, 10),
                           balance=1_000.0, equity=1_000.0))
        db.add(CopyLink(slave_account_id=account_id, master_position_id=5, symbol="EURUSD"))
        db.add(CopyEvent(slave_account_id=account_id, action="open", outcome="ok"))
        db.commit()

        removed = auth_client.delete(f"/api/accounts/{account_id}").json()
        assert removed["trades"] == 1
        assert removed["equity_points"] == 1
        assert removed["copy_links"] == 1
        assert removed["copy_events"] == 1

        for model, column in (
            (Trade, Trade.account_id),
            (EquityPoint, EquityPoint.account_id),
            (CopyLink, CopyLink.slave_account_id),
            # No foreign key behind this one, so it needs deleting explicitly --
            # otherwise it survives pointing at an id nobody can resolve.
            (CopyEvent, CopyEvent.slave_account_id),
        ):
            assert db.scalar(
                select(func.count()).select_from(model).where(column == account_id)
            ) == 0, f"{model.__tablename__} rows outlived the account"

    def test_the_master_can_be_removed_too(self, auth_client, db):
        """It could not be, and that left accounts nobody could get rid of.

        Removing it was only possible from the credentials card, which deleted
        whichever account the query returned first -- so an install that had
        somehow grown a second master had one it could never remove.
        """
        master_id = db.scalar(select(Account.id).where(Account.role == "master"))
        assert auth_client.delete(f"/api/accounts/{master_id}").status_code == 200
        db.expire_all()
        assert db.get(Account, master_id) is None

    def test_removing_the_master_forgets_its_credentials(self, auth_client, db):
        """Or the terminal it was provisioned from brings it straight back.

        The provisioner starts a terminal for the stored credentials, that
        terminal reports in, and the account is adopted again -- the one just
        deleted, returning by itself a minute later.
        """
        auth_client.put(
            "/api/mt5/credentials",
            json={"login": "5000123", "server": "Test-Server", "password": "investor"},
        )
        master = db.scalar(select(Account).where(Account.role == "master"))

        auth_client.delete(f"/api/accounts/{master.id}")

        assert auth_client.get("/api/mt5/credentials").json()["configured"] is False


class TestOnlyOneMaster:
    """Exactly one account is the one everything else copies from."""

    def _second_master(self, db):
        account = Account(login="9100", server="Other-Server", name="Imported", role="master")
        db.add(account)
        db.commit()
        return account

    def test_a_second_master_is_archived_on_sight(self, auth_client, db):
        """Two paths created accounts without saying what role they had.

        The column defaults to "master", so a terminal reporting an unknown
        login and a statement dropped on the import page each produced another
        one. Two masters is not cosmetic: the copier reads "the" master, and
        Forget removed whichever came back first.
        """
        second = self._second_master(db)

        listed = auth_client.get("/api/accounts").json()

        masters = [a for a in listed if a["role"] == "master"]
        assert len(masters) == 1
        db.expire_all()
        assert db.get(Account, second.id).role == "archived"

    def test_the_credentialed_account_is_the_one_kept(self, auth_client, db):
        """Not whichever was created first: a terminal is started for that one."""
        auth_client.put(
            "/api/mt5/credentials",
            json={"login": "9100", "server": "Other-Server", "password": "investor"},
        )
        second = self._second_master(db)

        auth_client.get("/api/accounts")

        db.expire_all()
        assert db.get(Account, second.id).role == "master"

    def test_an_archived_account_keeps_its_history_and_can_be_removed(self, auth_client, db):
        second = self._second_master(db)
        auth_client.get("/api/accounts")
        assert auth_client.delete(f"/api/accounts/{second.id}").status_code == 200


class TestTheBrokersClock:
    """How far the broker's clock runs from UTC has to reach the browser.

    The chart is the only thing that can turn a MetaTrader timestamp into a
    real moment, and it needs this number to do it. The response is built field
    by field rather than from the model, so a column that exists everywhere
    else can still arrive as null -- which looks exactly like a terminal that
    has not reported yet, and silently leaves the chart on the broker's clock.
    """

    def test_it_reaches_the_response(self, auth_client, db, slave):
        account = db.get(Account, slave["id"])
        account.broker_utc_offset_minutes = 180
        db.commit()

        listed = auth_client.get("/api/accounts").json()

        assert next(a for a in listed if a["id"] == slave["id"])[
            "broker_utc_offset_minutes"
        ] == 180

    def test_an_account_no_terminal_has_reported_says_nothing(self, slave):
        assert slave["broker_utc_offset_minutes"] is None


class TestAuth:
    def test_the_endpoints_need_a_session(self, client):
        """`client` has not logged in."""
        assert client.get("/api/accounts").status_code == 401
        assert client.post("/api/accounts", json={"login": "9", "server": "s"}).status_code == 401


class TestSymbolMappings:
    """Correcting what the copier decided an instrument is called.

    The copier resolves symbols on its own, which is the one thing about it
    that most deserves to be inspectable: a wrong mapping is not a missed
    trade, it is real money on an instrument nobody chose.
    """

    def test_overrides_are_saved(self, auth_client, slave):
        response = auth_client.put(
            f"/api/accounts/{slave['id']}/symbols",
            json={"overrides": {"XAUUSD+": "GOLD"}},
        )
        assert response.status_code == 200
        assert response.json()["symbol_map"] == {"XAUUSD+": "GOLD"}

    def test_what_the_copier_worked_out_is_visible(self, auth_client, db, slave):
        account = db.get(Account, slave["id"])
        account.symbol_learned = {"XAUUSD+": "XAUUSD"}
        db.commit()

        listed = auth_client.get("/api/accounts").json()

        assert next(a for a in listed if a["id"] == slave["id"])["symbol_learned"] == {
            "XAUUSD+": "XAUUSD"
        }

    def test_forgetting_one_leaves_the_rest(self, auth_client, db, slave):
        """A broker renaming one instrument should not re-resolve every other."""
        account = db.get(Account, slave["id"])
        account.symbol_learned = {"XAUUSD+": "XAUUSD", "EURUSD+": "EURUSD"}
        db.commit()

        response = auth_client.put(
            f"/api/accounts/{slave['id']}/symbols",
            json={"overrides": {}, "forget": ["XAUUSD+"]},
        )

        assert response.json()["symbol_learned"] == {"EURUSD+": "EURUSD"}

    def test_saving_overrides_does_not_wipe_what_was_learned(self, auth_client, db, slave):
        account = db.get(Account, slave["id"])
        account.symbol_learned = {"EURUSD+": "EURUSD"}
        db.commit()

        response = auth_client.put(
            f"/api/accounts/{slave['id']}/symbols",
            json={"overrides": {"XAUUSD+": "GOLD"}},
        )

        assert response.json()["symbol_learned"] == {"EURUSD+": "EURUSD"}

    def test_blank_rows_are_dropped(self, auth_client, slave):
        """The dialog adds an empty pair when you click Add."""
        response = auth_client.put(
            f"/api/accounts/{slave['id']}/symbols",
            json={"overrides": {"XAUUSD+": "GOLD", "": "", "  ": "X"}},
        )
        assert response.json()["symbol_map"] == {"XAUUSD+": "GOLD"}
