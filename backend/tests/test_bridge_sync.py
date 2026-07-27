"""Credential storage and the credentials-based pull sync.

The Wine container cannot run here, so the bridge is replaced by a stub that
speaks the same HTTP contract. Everything on the TradeZulu side of that
contract — credential encryption, the connect handshake, deal ingestion and
the error messages — is exercised for real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.credentials import (
    clear_credentials,
    credentials_status,
    get_credentials,
    save_credentials,
)
from app.services.crypto import decrypt, encrypt, is_readable

BASE = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


class TestEncryption:
    def test_round_trip(self):
        assert decrypt(encrypt("investor-password")) == "investor-password"

    def test_ciphertext_is_not_the_plaintext(self):
        token = encrypt("investor-password")
        assert "investor-password" not in token
        assert token.startswith("tzv1:")

    def test_same_value_encrypts_differently_each_time(self):
        assert encrypt("same") != encrypt("same")

    def test_empty_stays_empty(self):
        assert encrypt("") == ""
        assert decrypt("") == ""

    def test_a_corrupt_value_does_not_raise(self):
        assert decrypt("tzv1:not-valid-base64!!") == ""
        assert is_readable("tzv1:not-valid-base64!!") is False

    def test_a_wrong_key_yields_nothing(self, monkeypatch):
        token = encrypt("investor-password")
        from app.services import crypto

        monkeypatch.setattr(crypto.settings, "secret_key", "a-completely-different-key")
        assert crypto.decrypt(token) == ""


class TestCredentialStore:
    def test_save_and_read_back(self, db):
        save_credentials(db, "Broker-Live", "5000123", "investor-password")
        db.commit()
        assert get_credentials(db) == {
            "server": "Broker-Live",
            "login": "5000123",
            "password": "investor-password",
        }

    def test_status_never_exposes_the_password(self, db):
        save_credentials(db, "Broker-Live", "5000123", "investor-password")
        db.commit()
        status = credentials_status(db)
        assert status == {
            "configured": True,
            "server": "Broker-Live",
            "login": "5000123",
            "password_readable": True,
        }
        assert "password" not in status

    def test_password_is_stored_encrypted(self, db):
        from app.models import Setting

        save_credentials(db, "Broker-Live", "5000123", "investor-password")
        db.commit()
        raw = db.get(Setting, "mt5_credentials").value
        assert raw["password"].startswith("tzv1:")
        assert "investor-password" not in raw["password"]

    def test_omitting_the_password_keeps_it(self, db):
        save_credentials(db, "Broker-Live", "5000123", "investor-password")
        save_credentials(db, "Broker-Live-2", "5000124", None)
        db.commit()
        creds = get_credentials(db)
        assert creds["server"] == "Broker-Live-2"
        assert creds["login"] == "5000124"
        assert creds["password"] == "investor-password"

    def test_clearing(self, db):
        save_credentials(db, "Broker-Live", "5000123", "investor-password")
        clear_credentials(db)
        db.commit()
        assert credentials_status(db)["configured"] is False


class TestCredentialsApi:
    def test_requires_a_session(self, client):
        assert client.get("/api/mt5/credentials").status_code == 401
        assert client.put("/api/mt5/credentials", json={}).status_code == 401

    def test_unset_by_default(self, auth_client):
        body = auth_client.get("/api/mt5/credentials").json()
        assert body["configured"] is False
        assert body["login"] == ""

    def test_store_and_report(self, auth_client):
        response = auth_client.put(
            "/api/mt5/credentials",
            json={"server": "Broker-Live", "login": 5000123, "password": "investor-password"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "configured": True,
            "server": "Broker-Live",
            "login": "5000123",
            "password_readable": True,
        }

    def test_the_password_is_never_returned_anywhere(self, auth_client):
        auth_client.put(
            "/api/mt5/credentials",
            json={"server": "Broker-Live", "login": "5000123", "password": "s3cr3t-investor"},
        )
        for path in ("/api/mt5/credentials", "/api/settings", "/api/mt5/status"):
            assert "s3cr3t-investor" not in auth_client.get(path).text, path

    def test_updating_without_a_password_keeps_it(self, auth_client):
        auth_client.put(
            "/api/mt5/credentials",
            json={"server": "Broker-Live", "login": "5000123", "password": "investor-password"},
        )
        body = auth_client.put(
            "/api/mt5/credentials", json={"server": "Broker-Demo", "login": "5000999"}
        ).json()
        assert body["server"] == "Broker-Demo"
        assert body["configured"] is True

    def test_delete(self, auth_client):
        auth_client.put(
            "/api/mt5/credentials",
            json={"server": "Broker-Live", "login": "5000123", "password": "investor-password"},
        )
        assert auth_client.delete("/api/mt5/credentials").json()["configured"] is False


# --- a stub standing in for the Wine container ------------------------------


class FakeBridge:
    """Speaks the bridge's HTTP contract, without Wine or MetaTrader."""

    def __init__(self, *, deals=None, reachable=True, accept_login=True):
        self.deals = deals or []
        self.reachable = reachable
        self.accept_login = accept_login
        self.connected = False
        self.received_credentials: dict | None = None
        self.connect_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("connection refused", request=request)

        path = request.url.path
        if path == "/connect":
            self.connect_calls += 1
            import json as _json

            self.received_credentials = _json.loads(request.content)
            if not self.accept_login:
                return httpx.Response(
                    502,
                    json={
                        "ok": False,
                        "error": "Invalid account (-6). The broker rejected the login.",
                    },
                )
            self.connected = True
            return httpx.Response(200, json={"ok": True, "account": self.account()})

        if path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok" if self.connected else "disconnected",
                    "connected": self.connected,
                    "configured": self.received_credentials is not None,
                    "error": "",
                },
            )

        if not self.connected:
            return httpx.Response(503, json={"error": "not connected"})

        if path == "/account":
            return httpx.Response(200, json=self.account())
        if path == "/deals":
            return httpx.Response(200, json=self.deals)
        if path == "/candles":
            return httpx.Response(200, json={"candles": []})
        return httpx.Response(404, json={"error": "not found"})

    @staticmethod
    def account() -> dict:
        return {
            "login": "5000123",
            "name": "Investor",
            "server": "Broker-Live",
            "company": "Test Broker",
            "currency": "USD",
            "leverage": 100,
            "balance": 10_400.0,
            "equity": 10_400.0,
            "trade_allowed": False,
        }


@pytest.fixture()
def bridge(monkeypatch):
    """Route every httpx call the app makes into a FakeBridge."""
    fake = FakeBridge()
    real_client = httpx.Client

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched)
    return fake


def deal_pair(position_id: int = 7001, profit: float = 400.0) -> list[dict]:
    return [
        {
            "ticket": position_id, "order": position_id, "position_id": position_id,
            "symbol": "EURUSD", "type": 0, "entry": 0, "volume": 1.0, "price": 1.1000,
            "sl": 1.0980, "tp": 1.1060, "time": int(BASE.timestamp()),
            "value_per_unit": 100_000.0, "digits": 5, "profit": 0.0,
            "commission": 0.0, "swap": 0.0, "fee": 0.0, "magic": 0, "comment": "",
        },
        {
            "ticket": position_id + 1, "order": position_id, "position_id": position_id,
            "symbol": "EURUSD", "type": 1, "entry": 1, "volume": 1.0, "price": 1.1040,
            "profit": profit, "commission": -7.0,
            "time": int((BASE + timedelta(hours=2)).timestamp()),
            "value_per_unit": 100_000.0, "digits": 5, "sl": 0.0, "tp": 0.0,
            "swap": 0.0, "fee": 0.0, "magic": 0, "comment": "",
        },
    ]


class TestPullSync:
    def _configure(self, auth_client):
        auth_client.put(
            "/api/mt5/credentials",
            json={"server": "Broker-Live", "login": "5000123", "password": "investor-password"},
        )
        auth_client.put("/api/settings", json={"mt5": {"sync_mode": "bridge"}})

    def test_connect_logs_in_and_records_the_account(self, auth_client, bridge):
        self._configure(auth_client)
        response = auth_client.post("/api/mt5/connect")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["account"]["server"] == "Broker-Live"
        assert bridge.received_credentials == {
            "server": "Broker-Live",
            "login": "5000123",
            "password": "investor-password",
        }

        accounts = auth_client.get("/api/accounts").json()
        assert any(a["login"] == "5000123" and a["broker"] == "Test Broker" for a in accounts)

    def test_connect_without_credentials_is_refused(self, auth_client, bridge):
        auth_client.put("/api/settings", json={"mt5": {"sync_mode": "bridge"}})
        response = auth_client.post("/api/mt5/connect")
        assert response.status_code == 400
        assert "No MetaTrader account is configured" in response.json()["detail"]
        assert bridge.connect_calls == 0

    def test_a_rejected_login_surfaces_the_broker_message(self, auth_client, bridge):
        bridge.accept_login = False
        self._configure(auth_client)
        response = auth_client.post("/api/mt5/connect")
        assert response.status_code == 502
        assert "rejected the login" in response.json()["detail"]

    def test_an_unreachable_bridge_says_how_to_start_it(self, auth_client, bridge):
        bridge.reachable = False
        self._configure(auth_client)
        response = auth_client.post("/api/mt5/connect")
        assert response.status_code == 502
        assert "profile bridge" in response.json()["detail"]

    def test_sync_pulls_deals_and_builds_trades(self, auth_client, bridge):
        bridge.deals = deal_pair()
        self._configure(auth_client)

        response = auth_client.post("/api/mt5/sync")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deals_new"] == 2
        assert body["trades_upserted"] == 1

        trades = auth_client.get("/api/trades", params={"period": "all"}).json()["items"]
        assert len(trades) == 1
        trade = trades[0]
        assert trade["symbol"] == "EURUSD"
        assert trade["risk_amount"] == pytest.approx(200.0)
        assert trade["realized_r"] == pytest.approx(1.965)
        assert trade["source"] == "mt5"

    def test_sync_logs_in_first_so_a_cold_bridge_recovers(self, auth_client, bridge):
        bridge.deals = deal_pair()
        self._configure(auth_client)
        auth_client.post("/api/mt5/sync")
        assert bridge.connect_calls >= 1
        assert bridge.connected is True

    def test_syncing_twice_does_not_duplicate(self, auth_client, bridge):
        bridge.deals = deal_pair()
        self._configure(auth_client)
        auth_client.post("/api/mt5/sync")
        second = auth_client.post("/api/mt5/sync").json()
        assert second["deals_new"] == 0
        assert auth_client.get("/api/trades", params={"period": "all"}).json()["total"] == 1

    def test_sync_is_refused_in_push_mode(self, auth_client, bridge):
        self._configure(auth_client)
        auth_client.put("/api/settings", json={"mt5": {"sync_mode": "ea"}})
        response = auth_client.post("/api/mt5/sync")
        assert response.status_code == 400
        assert "Expert Advisor" in response.json()["detail"]

    def test_status_reports_the_bridge_and_credential_state(self, auth_client, bridge):
        self._configure(auth_client)
        status = auth_client.get("/api/mt5/status").json()
        assert status["sync_mode"] == "bridge"
        assert status["credentials_configured"] is True
        assert status["bridge_reachable"] is True
        assert status["bridge_connected"] is False  # not logged in yet
        assert "not logged in" in status["message"]

        auth_client.post("/api/mt5/connect")
        status = auth_client.get("/api/mt5/status").json()
        assert status["bridge_connected"] is True

    def test_status_explains_a_missing_bridge(self, auth_client, bridge):
        bridge.reachable = False
        self._configure(auth_client)
        status = auth_client.get("/api/mt5/status").json()
        assert status["bridge_reachable"] is False
        assert "docker compose" in status["message"]

    def test_status_asks_for_credentials_when_there_are_none(self, auth_client, bridge):
        auth_client.put("/api/settings", json={"mt5": {"sync_mode": "bridge"}})
        status = auth_client.get("/api/mt5/status").json()
        assert status["credentials_configured"] is False
        assert "Settings" in status["message"]
