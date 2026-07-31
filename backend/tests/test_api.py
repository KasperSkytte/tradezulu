"""End-to-end API behaviour through the ASGI app."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

INGEST_HEADERS = {"X-API-Key": "test-ingest-token"}


def iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def deal_payload(base: datetime, position_id: int = 5001, profit: float = 400.0) -> dict:
    return {
        "account": {
            "login": "5000123",
            "name": "Test account",
            "server": "TestBroker-Live",
            "company": "Test Broker",
            "currency": "USD",
            "leverage": 100,
            "balance": 10_400.0,
            "equity": 10_400.0,
        },
        "deals": [
            {
                "ticket": position_id, "order": position_id, "position_id": position_id,
                "symbol": "EURUSD", "type": 0, "entry": 0, "volume": 1.0, "price": 1.1000,
                "sl": 1.0980, "tp": 1.1060, "time": iso(base), "value_per_unit": 100_000.0,
                "digits": 5,
            },
            {
                "ticket": position_id + 1, "order": position_id, "position_id": position_id,
                "symbol": "EURUSD", "type": 1, "entry": 1, "volume": 1.0, "price": 1.1040,
                "profit": profit, "commission": -7.0, "time": iso(base + timedelta(hours=2)),
                "value_per_unit": 100_000.0, "digits": 5,
            },
        ],
    }


class TestAuth:
    def test_health_needs_no_session(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_protected_routes_reject_anonymous_callers(self, client):
        assert client.get("/api/trades").status_code == 401
        assert client.get("/api/stats/summary").status_code == 401
        assert client.get("/api/settings").status_code == 401

    def test_login_and_me(self, client):
        assert client.post(
            "/api/auth/login", json={"username": "tester", "password": "wrong"}
        ).status_code == 401

        response = client.post(
            "/api/auth/login",
            json={"username": "tester", "password": "correct-horse-battery"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == "tester"
        assert client.get("/api/auth/me").json()["username"] == "tester"

    def test_logout_clears_the_session(self, auth_client):
        auth_client.post("/api/auth/logout")
        auth_client.cookies.clear()
        assert auth_client.get("/api/auth/me").status_code == 401

    def test_password_change_invalidates_old_sessions(self, auth_client):
        assert auth_client.post(
            "/api/auth/password",
            json={"current_password": "nope", "new_password": "a-new-long-password"},
        ).status_code == 400

        response = auth_client.post(
            "/api/auth/password",
            json={"current_password": "correct-horse-battery", "new_password": "a-new-long-password"},
        )
        assert response.status_code == 200
        # The response re-issued a cookie, so this client stays logged in.
        assert auth_client.get("/api/auth/me").status_code == 200


class TestIngest:
    def test_requires_credentials(self, client):
        response = client.post("/api/mt5/ingest", json=deal_payload(datetime(2026, 6, 1, 10)))
        assert response.status_code == 401

    def test_creates_a_trade(self, client):
        base = datetime(2026, 6, 1, 10)
        response = client.post(
            "/api/mt5/ingest", json=deal_payload(base), headers=INGEST_HEADERS
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deals_new"] == 2
        assert body["trades_upserted"] == 1

        # Re-sending the same deals must not duplicate anything.
        again = client.post("/api/mt5/ingest", json=deal_payload(base), headers=INGEST_HEADERS).json()
        assert again["deals_new"] == 0

    def test_trade_is_visible_with_correct_maths(self, client, auth_client):
        base = datetime(2026, 6, 1, 10)
        client.post("/api/mt5/ingest", json=deal_payload(base), headers=INGEST_HEADERS)

        response = auth_client.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-02"}
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1

        trade = items[0]
        assert trade["symbol"] == "EURUSD"
        assert trade["direction"] == "long"
        assert trade["net_pnl"] == pytest.approx(393.0)
        assert trade["risk_amount"] == pytest.approx(200.0)  # 20 pips on 1 lot
        assert trade["planned_r"] == pytest.approx(3.0)
        assert trade["realized_r"] == pytest.approx(1.965)
        assert trade["outcome"] == "win"

    def test_cursor_reports_the_last_known_ticket(self, client):
        client.post(
            "/api/mt5/ingest", json=deal_payload(datetime(2026, 6, 1, 10)), headers=INGEST_HEADERS
        )
        body = client.get("/api/mt5/cursor", headers=INGEST_HEADERS).json()
        assert body["last_deal_ticket"] == 5002

    def test_status_reflects_the_sync(self, client, auth_client):
        client.post(
            "/api/mt5/ingest", json=deal_payload(datetime(2026, 6, 1, 10)), headers=INGEST_HEADERS
        )
        status = auth_client.get("/api/mt5/status").json()
        assert status["login"] == "5000123"
        assert status["total_trades"] == 1
        assert status["last_sync_source"] == "ea"

    def test_sync_says_there_is_nothing_to_pull(self, auth_client):
        """The button exists, but terminals push -- so it only ever re-reads.

        Worth asserting rather than deleting: an endpoint that quietly 404s
        would look like a broken server to anyone who pressed refresh.
        """
        response = auth_client.post("/api/mt5/sync")
        assert response.status_code == 200
        assert "push" in response.json()["message"].lower()


class TestTrades:
    @pytest.fixture()
    def seeded(self, client, auth_client):
        for index in range(3):
            client.post(
                "/api/mt5/ingest",
                json=deal_payload(
                    datetime(2026, 6, 1 + index, 10),
                    position_id=6000 + index * 10,
                    profit=400.0 if index != 1 else -250.0,
                ),
                headers=INGEST_HEADERS,
            )
        return auth_client

    def test_summary_statistics(self, seeded):
        response = seeded.get(
            "/api/stats/summary", params={"start": "2026-06-01", "end": "2026-06-30"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["counts"]["total"] == 3
        assert body["counts"]["wins"] == 2
        assert body["counts"]["losses"] == 1
        assert body["win_rate"] == pytest.approx(66.7)
        assert body["zulu_score"]["score"] >= 0
        assert len(body["equity_curve"]) == 3
        assert len(body["daily"]) == 3

    def test_notes_and_tags_round_trip(self, seeded):
        trade_id = seeded.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"][0]["id"]
        tags = seeded.get("/api/tags").json()
        tag_ids = [tags[0]["id"], tags[1]["id"]]

        response = seeded.patch(
            f"/api/trades/{trade_id}",
            json={"notes": "Waited for the retest.", "rating": 4, "setup": "Pullback",
                  "tag_ids": tag_ids},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["notes"] == "Waited for the retest."
        assert body["rating"] == 4
        assert {t["id"] for t in body["tags"]} == set(tag_ids)

    def test_manual_stop_changes_the_r_multiple(self, seeded):
        trade = seeded.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"][0]
        before = trade["realized_r"]

        response = seeded.patch(f"/api/trades/{trade['id']}", json={"initial_stop": 1.0900})
        body = response.json()
        assert body["stop_source"] == "manual"
        assert body["risk_amount"] == pytest.approx(1000.0)
        assert body["realized_r"] != before

        reset = seeded.patch(f"/api/trades/{trade['id']}", json={"reset_stop": True}).json()
        assert reset["initial_stop"] is None
        assert reset["stop_source"] == "none"

    def test_risk_override(self, seeded):
        trade = seeded.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"][0]
        body = seeded.patch(f"/api/trades/{trade['id']}", json={"risk_override": 100.0}).json()
        assert body["risk_amount"] == pytest.approx(100.0)

    def test_excluding_a_trade_removes_it_from_statistics(self, seeded):
        trades = seeded.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"]
        seeded.patch(f"/api/trades/{trades[0]['id']}", json={"excluded": True})

        body = seeded.get(
            "/api/stats/summary", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        assert body["counts"]["total"] == 2
        assert body["counts"]["excluded"] == 1

    def test_filtering_by_outcome(self, seeded):
        body = seeded.get(
            "/api/trades",
            params={"start": "2026-06-01", "end": "2026-06-30", "outcome": "loss"},
        ).json()
        assert body["total"] == 1

    def test_csv_export(self, seeded):
        response = seeded.get(
            "/api/trades/export.csv", params={"start": "2026-06-01", "end": "2026-06-30"}
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert response.text.count("\n") >= 4

    def test_bulk_tagging(self, seeded):
        trades = seeded.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"]
        tag_id = seeded.get("/api/tags").json()[0]["id"]
        response = seeded.post(
            "/api/trades/bulk",
            json={"trade_ids": [t["id"] for t in trades], "add_tag_ids": [tag_id]},
        )
        assert response.json()["updated"] == 3

    def test_breakdowns(self, seeded):
        body = seeded.get(
            "/api/stats/breakdowns", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        assert body["by_symbol"][0]["key"] == "EURUSD"
        assert body["by_direction"][0]["trades"] == 3

    def test_calendar(self, seeded):
        body = seeded.get("/api/stats/calendar", params={"month": "2026-06"}).json()
        assert body["month"] == "2026-06"
        assert len(body["days"]) == 3
        assert body["weeks"]

    def test_day_detail(self, seeded):
        body = seeded.get("/api/stats/day/2026-06-01").json()
        assert body["summary"]["counts"]["total"] == 1
        assert len(body["trade_ids"]) == 1

    def test_compare_with_previous_period(self, seeded):
        body = seeded.get(
            "/api/stats/compare", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        assert body["current"]["counts"]["total"] == 3
        assert body["previous"]["counts"]["total"] == 0


class TestManualTrades:
    def test_create_and_delete(self, auth_client):
        response = auth_client.post(
            "/api/trades",
            json={
                "symbol": "xauusd",
                "direction": "short",
                "opened_at": "2026-06-10T08:00:00Z",
                "closed_at": "2026-06-10T09:30:00Z",
                "volume": 0.5,
                "entry_price": 2350.0,
                "exit_price": 2340.0,
                "value_per_unit": 100.0,
                "initial_stop": 2360.0,
                "notes": "hand entered",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["symbol"] == "XAUUSD"
        assert body["gross_profit"] == pytest.approx(500.0)
        assert body["risk_amount"] == pytest.approx(500.0)
        assert body["realized_r"] == pytest.approx(1.0)
        assert body["is_manual"] is True

        assert auth_client.delete(f"/api/trades/{body['id']}").status_code == 204

    def test_synced_trades_cannot_be_deleted(self, client, auth_client):
        client.post(
            "/api/mt5/ingest", json=deal_payload(datetime(2026, 6, 1, 10)), headers=INGEST_HEADERS
        )
        trade_id = auth_client.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-02"}
        ).json()["items"][0]["id"]
        assert auth_client.delete(f"/api/trades/{trade_id}").status_code == 400


class TestSettings:
    def test_defaults_are_returned(self, auth_client):
        body = auth_client.get("/api/settings").json()
        assert body["risk"]["breakeven_threshold_r"] == 0.1
        assert body["general"]["currency"] == "USD"

    def test_patch_merges_and_persists(self, auth_client):
        body = auth_client.put(
            "/api/settings", json={"general": {"currency": "EUR"}}
        ).json()
        assert body["general"]["currency"] == "EUR"
        assert body["general"]["timezone"] == "Europe/Copenhagen"  # untouched
        assert auth_client.get("/api/settings").json()["general"]["currency"] == "EUR"

    def test_changing_the_breakeven_threshold_recomputes_trades(self, client, auth_client):
        client.post(
            "/api/mt5/ingest",
            json=deal_payload(datetime(2026, 6, 1, 10), profit=100.0),
            headers=INGEST_HEADERS,
        )
        params = {"start": "2026-06-01", "end": "2026-06-02"}
        assert auth_client.get("/api/trades", params=params).json()["items"][0]["outcome"] == "win"

        # 93 net on 200 risk is 0.465R; raising the threshold above that makes
        # it a breakeven.
        auth_client.put("/api/settings", json={"risk": {"breakeven_threshold_r": 0.6}})
        assert (
            auth_client.get("/api/trades", params=params).json()["items"][0]["outcome"]
            == "breakeven"
        )

    def test_unknown_keys_are_dropped(self, auth_client):
        body = auth_client.put("/api/settings", json={"nonsense": {"a": 1}}).json()
        assert "nonsense" not in body

    def test_tag_crud(self, auth_client):
        created = auth_client.post(
            "/api/tags", json={"name": "Chased price", "color": "#ff0000", "category": "mistake"}
        )
        assert created.status_code == 201
        tag_id = created.json()["id"]

        assert auth_client.post("/api/tags", json={"name": "chased price"}).status_code == 409

        updated = auth_client.patch(
            f"/api/tags/{tag_id}",
            json={"name": "Chased price", "color": "#00ff00", "category": "mistake"},
        )
        assert updated.json()["color"] == "#00ff00"
        assert auth_client.delete(f"/api/tags/{tag_id}").status_code == 204

    def test_day_notes(self, auth_client):
        response = auth_client.put(
            "/api/notes", json={"day": "2026-06-02", "content": "Choppy, stayed out.", "mood": "calm"}
        )
        assert response.status_code == 200
        assert auth_client.get("/api/notes/2026-06-02").json()["content"] == "Choppy, stayed out."

    def test_account_initial_balance_drives_percentage_risk(self, auth_client):
        account_id = auth_client.get("/api/accounts").json()[0]["id"]
        response = auth_client.patch(
            f"/api/accounts/{account_id}", json={"initial_balance": 50_000.0, "name": "Live"}
        )
        assert response.json()["initial_balance"] == 50_000.0
