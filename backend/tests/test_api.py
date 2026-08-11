"""End-to-end API behaviour through the ASGI app."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

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

    def test_a_dropped_session_does_not_erase_the_equity(self, client, auth_client):
        """The ingest path had no guard, unlike the agent heartbeat.

        A terminal whose connection has dropped reports the balance it last
        saw and an equity of zero. Believed here, it left the account "worth
        10,400.00 with 0.00 equity", which the copier reads as everything lost
        and halts on -- for good, and by hand to clear.
        """
        base = datetime(2026, 6, 1, 10)
        client.post("/api/mt5/ingest", json=deal_payload(base), headers=INGEST_HEADERS)

        dropped = deal_payload(base)
        dropped["account"]["equity"] = 0.0
        dropped["deals"] = []
        client.post("/api/mt5/ingest", json=dropped, headers=INGEST_HEADERS)

        account = auth_client.get("/api/accounts").json()[0]
        assert account["equity"] == 10_400.0

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


class TestTradeReturn:
    """A trade is measured against the balance it was actually risking."""

    def test_percent_is_of_the_balance_before_it_closed(self, client, auth_client):
        """Fifty on two hundred is a quarter of the account, not 0.2% of a
        number typed into settings."""
        client.post(
            "/api/mt5/ingest",
            json=deal_payload(datetime(2026, 6, 1, 10), position_id=9100, profit=50.0),
            headers=INGEST_HEADERS,
        )
        rows = auth_client.get(
            "/api/trades", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()["items"]
        assert rows, "the ingest should have produced a trade"
        # The account's starting balance comes from its deposits; with none
        # recorded there is nothing to divide by and the figure is omitted
        # rather than invented.
        for row in rows:
            assert "return_pct" in row
            assert "balance_before" in row


class TestAccountScope:
    """Statistics belong to one account, and say so when they cannot.

    Before this, every page sent no account filter and the API happily
    aggregated every account: the combined profit of all of them divided by
    whichever single balance happened to be handy, and a drawdown built by
    interleaving accounts that were never one pool of money.
    """

    @pytest.fixture()
    def two_accounts(self, client, auth_client, db):
        from app.models import Account, Trade

        for index in range(3):
            client.post(
                "/api/mt5/ingest",
                json=deal_payload(
                    datetime(2026, 6, 1 + index, 10),
                    position_id=7000 + index * 10,
                    profit=400.0 if index != 1 else -250.0,
                ),
                headers=INGEST_HEADERS,
            )
        first = db.scalar(select(Account).where(Account.role == "master"))
        # Deposited 5,000 and up 90 on its one trade, so it is worth 5,090 now.
        # The two have to agree: every balance in the journal is reconstructed
        # backwards from what the account is worth today.
        other = Account(login="9999", server="Other-Server", name="Second", role="slave",
                        initial_balance=5_000.0, balance=5_090.0)
        db.add(other)
        db.flush()
        db.add(Trade(
            account_id=other.id, position_id=8000, symbol="GBPUSD", direction="long",
            opened_at=datetime(2026, 6, 2, 9), closed_at=datetime(2026, 6, 2, 11),
            trade_date=date(2026, 6, 2), volume=1.0, closed_volume=1.0,
            entry_price=1.3, exit_price=1.31, gross_profit=90.0, net_pnl=90.0,
            outcome="win",
        ))
        db.commit()
        return auth_client, first.id, other.id

    def test_the_calendar_is_scoped_to_one_account(self, two_accounts):
        """A slave added on Tuesday must not join the master's trading days.

        The calendar was the one view asking for every account, and it has no
        account picker of its own to explain why -- so adding a second account
        silently changed what every past day was worth.
        """
        client, first, other = two_accounts

        mine = client.get("/api/stats/calendar", params={"month": "2026-06", "account_id": first}).json()
        theirs = client.get("/api/stats/calendar", params={"month": "2026-06", "account_id": other}).json()
        both = client.get("/api/stats/calendar", params={"month": "2026-06"}).json()

        def trades_on(payload, day):
            return next((d["trades"] for d in payload["days"] if d["date"] == day), 0)

        assert trades_on(theirs, "2026-06-02") == 1
        assert trades_on(mine, "2026-06-02") == 1, "its own trade that day, not the other's"
        assert trades_on(both, "2026-06-02") == 2

    def test_a_day_is_scoped_too(self, two_accounts):
        client, first, other = two_accounts

        mine = client.get("/api/stats/day/2026-06-02", params={"account_id": first}).json()
        theirs = client.get("/api/stats/day/2026-06-02", params={"account_id": other}).json()

        assert len(mine["trade_ids"]) == 1
        assert len(theirs["trade_ids"]) == 1
        assert mine["trade_ids"] != theirs["trade_ids"]
        assert mine["summary"]["net_pnl"] != theirs["summary"]["net_pnl"]

    def test_the_symbol_filter_offers_this_accounts_symbols(self, two_accounts):
        """A filter listing instruments the account never traded empties the page."""
        client, first, other = two_accounts

        assert client.get("/api/trades/symbols", params={"account_id": other}).json() == ["GBPUSD"]
        assert "GBPUSD" not in client.get("/api/trades/symbols", params={"account_id": first}).json()
        assert "GBPUSD" in client.get("/api/trades/symbols").json()

    def _summary(self, client, **params):
        return client.get(
            "/api/stats/summary",
            params={"start": "2026-06-01", "end": "2026-06-30", **params},
        ).json()

    def test_several_accounts_withhold_the_per_account_figures(self, two_accounts):
        client, _, _ = two_accounts
        body = self._summary(client)
        assert body["single_account"] is False
        assert body["counts"]["total"] == 4  # everything is still counted
        # Still a plain sum: the master's three trades plus the other's 90.
        alone = self._summary(client, account_id=1)["net_pnl"]
        assert body["net_pnl"] == pytest.approx(alone + 90.0)
        for key in ("account_size", "opening_balance", "return_pct",
                    "max_drawdown", "max_drawdown_pct", "recovery_factor"):
            assert body[key] is None, f"{key} means nothing across accounts"
        assert body["zulu_score"]["score"] is None

    def test_one_account_gets_everything(self, two_accounts):
        client, first, _ = two_accounts
        body = self._summary(client, account_id=first)
        assert body["single_account"] is True
        assert body["counts"]["total"] == 3
        assert body["return_pct"] is not None
        assert body["max_drawdown"] is not None
        assert body["zulu_score"]["score"] is not None

    def test_the_other_account_is_measured_on_its_own(self, two_accounts):
        client, _, other = two_accounts
        body = self._summary(client, account_id=other)
        assert body["counts"]["total"] == 1
        assert body["net_pnl"] == pytest.approx(90.0)
        # 90 on its own 5,000, not on the other account's balance.
        assert body["opening_balance"] == pytest.approx(5_000.0)

    def test_the_calendar_withholds_a_daily_return_too(self, two_accounts):
        client, _, _ = two_accounts
        body = client.get("/api/stats/calendar", params={"month": "2026-06"}).json()
        assert body["single_account"] is False
        assert all(day["return_pct"] is None for day in body["days"])

    def test_a_single_account_installation_is_unaffected(self, client, auth_client):
        """No filter, one account: nothing is withheld, because nothing is mixed."""
        client.post(
            "/api/mt5/ingest",
            json=deal_payload(datetime(2026, 6, 4, 10), position_id=7100),
            headers=INGEST_HEADERS,
        )
        body = self._summary(auth_client)
        assert body["single_account"] is True
        assert body["max_drawdown"] is not None


class TestEquitySeries:
    """An equity curve belongs to one account, or to none."""

    @pytest.fixture()
    def sampled(self, auth_client, db):
        from app.models import Account, EquityPoint

        first = db.scalar(select(Account).where(Account.role == "master"))
        other = Account(login="4321", server="Other-Server", name="Small", role="slave",
                        initial_balance=240.0, balance=240.0)
        db.add(other)
        db.flush()
        now = datetime(2026, 6, 10, 12)
        for minute in range(3):
            db.add(EquityPoint(account_id=first.id, time=now + timedelta(minutes=minute),
                               balance=10_000.0, equity=10_000.0 + minute))
            db.add(EquityPoint(account_id=other.id, time=now + timedelta(minutes=minute, seconds=30),
                               balance=240.0, equity=240.0 + minute))
        db.commit()
        return auth_client, first.id, other.id

    def test_one_account_gets_its_own_curve(self, sampled):
        client, _, other = sampled
        body = client.get("/api/stats/equity", params={"days": 365, "account_id": other}).json()
        assert body["single_account"] is True
        assert len(body["points"]) == 3
        assert all(point["equity"] < 300 for point in body["points"])

    def test_several_accounts_return_nothing_rather_than_a_zigzag(self, sampled):
        """The bug: samples from every account interleaved by time.

        One row at 240, the next at 10,000, read as a single line -- which then
        shares a y-axis with cumulative P&L and flattens it onto the baseline.
        """
        client, _, _ = sampled
        body = client.get("/api/stats/equity", params={"days": 365}).json()
        assert body["single_account"] is False
        assert body["points"] == []
        assert "one account" in body["sampling"]


class TestForgettingTheAccount:
    """Forgetting the MetaTrader account forgets what it put in the journal."""

    @pytest.fixture()
    def journalled(self, client, auth_client):
        auth_client.put(
            "/api/mt5/credentials",
            json={"login": "5000123", "server": "Test-Server", "password": "investor"},
        )
        for index in range(3):
            client.post(
                "/api/mt5/ingest",
                json=deal_payload(datetime(2026, 6, 1 + index, 10), position_id=9000 + index),
                headers=INGEST_HEADERS,
            )
        return auth_client

    def test_the_trades_go_with_it(self, journalled, db):
        """The bug: only the credentials row was deleted.

        The account disappeared from the interface and its trades stayed in the
        database -- still counted in every total, and inherited by the next
        account added with the same number.
        """
        from app.models import Account, Trade

        assert db.scalar(select(func.count()).select_from(Trade)) == 3

        response = journalled.delete("/api/mt5/credentials")
        assert response.status_code == 200
        assert response.json()["configured"] is False

        db.expire_all()
        assert db.scalar(select(func.count()).select_from(Trade)) == 0
        assert db.scalar(select(func.count()).select_from(Account)) == 0

    def test_the_statistics_forget_it_too(self, journalled, db):
        journalled.delete("/api/mt5/credentials")
        body = journalled.get(
            "/api/stats/summary", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        assert body["counts"]["total"] == 0

    def test_a_readded_account_starts_empty(self, journalled, db):
        """Nothing to inherit, which was the other half of the problem."""
        journalled.delete("/api/mt5/credentials")
        journalled.put(
            "/api/mt5/credentials",
            json={"login": "5000123", "server": "Test-Server", "password": "investor"},
        )
        body = journalled.get(
            "/api/stats/summary", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        assert body["counts"]["total"] == 0


class TestChangingTheStoredAccount:
    """A different account number needs its own password.

    Leaving the field blank means "keep the stored one", which is right when
    fixing a server or a typo and wrong the moment the account changes: the
    terminal would start, be refused by the broker on a display nobody watches,
    and never report in. From the outside that looks like adding an account
    hanging forever.
    """

    def _put(self, client, login, server="Test-Server", password=None):
        body = {"login": login, "server": server}
        if password is not None:
            body["password"] = password
        return client.put("/api/mt5/credentials", json=body)

    @pytest.fixture()
    def stored(self, auth_client):
        assert self._put(auth_client, "5000123", password="first-password").status_code == 200
        return auth_client

    def test_a_new_login_without_a_password_is_refused(self, stored):
        response = self._put(stored, "9999999")
        assert response.status_code == 400
        assert "9999999" in response.json()["detail"]
        assert "5000123" in response.json()["detail"]

    def test_and_nothing_is_stored(self, stored, db):
        self._put(stored, "9999999")
        body = stored.get("/api/mt5/credentials").json()
        assert body["login"] == "5000123", "the refused change must not take effect"

    def test_a_new_login_with_its_own_password_is_fine(self, stored):
        response = self._put(stored, "9999999", password="second-password")
        assert response.status_code == 200
        assert response.json()["login"] == "9999999"

    def test_the_new_password_is_the_one_kept(self, stored, db):
        from app.services.credentials import get_credentials

        self._put(stored, "9999999", password="second-password")
        assert get_credentials(db)["password"] == "second-password"

    def test_the_same_account_still_keeps_its_password(self, stored, db):
        """Correcting the server must not force the password to be retyped."""
        from app.services.credentials import get_credentials

        response = self._put(stored, "5000123", server="Test-Server-2")
        assert response.status_code == 200
        assert get_credentials(db)["password"] == "first-password"
        assert response.json()["server"] == "Test-Server-2"

    def test_the_service_never_carries_a_password_across_accounts(self, db):
        """Belt and braces: the rule holds even if the endpoint is bypassed."""
        from app.services.credentials import get_credentials, save_credentials

        save_credentials(db, "S", "1111", "password-for-1111")
        save_credentials(db, "S", "2222", None)
        assert get_credentials(db)["password"] == "", "2222 must not inherit 1111's password"
