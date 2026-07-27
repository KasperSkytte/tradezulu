"""The accounts API, and the guard rails around arming a slave."""

from __future__ import annotations

import pytest
from sqlalchemy import select

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
        assert auth_client.delete(f"/api/accounts/{slave['id']}").status_code == 204
        assert all(a["id"] != slave["id"] for a in auth_client.get("/api/accounts").json())

    def test_the_master_cannot_be_removed(self, auth_client, db):
        master = db.scalar(select(Account).where(Account.role == "master"))
        response = auth_client.delete(f"/api/accounts/{master.id}")
        assert response.status_code == 400


class TestAuth:
    def test_the_endpoints_need_a_session(self, client):
        """`client` has not logged in."""
        assert client.get("/api/accounts").status_code == 401
        assert client.post("/api/accounts", json={"login": "9", "server": "s"}).status_code == 401
