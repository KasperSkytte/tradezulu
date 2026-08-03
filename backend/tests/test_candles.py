"""The candle endpoint that feeds the trade replay chart."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

INGEST_HEADERS = {"X-API-Key": "test-ingest-token"}
BASE = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture()
def trade_with_candles(client, auth_client):
    candles = [
        {
            "time": iso(BASE - timedelta(minutes=15 * (30 - index))),
            "open": 1.1000 + index * 0.0001,
            "high": 1.1005 + index * 0.0001,
            "low": 1.0995 + index * 0.0001,
            "close": 1.1002 + index * 0.0001,
            "volume": 100 + index,
        }
        for index in range(60)
    ]
    payload = {
        "account": {"login": "5000123", "server": "TestBroker"},
        "deals": [
            {
                "ticket": 8001, "position_id": 8001, "symbol": "EURUSD", "type": 0,
                "entry": 0, "volume": 1.0, "price": 1.1000, "time": iso(BASE),
                "value_per_unit": 100_000, "sl": 1.0980, "digits": 5,
            },
            {
                "ticket": 8002, "position_id": 8001, "symbol": "EURUSD", "type": 1,
                "entry": 1, "volume": 1.0, "price": 1.1040, "profit": 400.0,
                "time": iso(BASE + timedelta(hours=2)), "value_per_unit": 100_000,
                "digits": 5,
            },
        ],
        "candles": [{"symbol": "EURUSD", "timeframe": "M15", "candles": candles}],
    }
    response = client.post("/api/mt5/ingest", json=payload, headers=INGEST_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["candles_stored"] == 60

    trade_id = auth_client.get(
        "/api/trades", params={"start": "2026-06-01", "end": "2026-06-02"}
    ).json()["items"][0]["id"]
    return auth_client, trade_id


class TestCandles:
    def test_by_trade_id_needs_no_symbol(self, trade_with_candles):
        """This is exactly how the replay chart calls it."""
        auth_client, trade_id = trade_with_candles
        response = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "M15"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["symbol"] == "EURUSD"
        assert body["timeframe"] == "M15"
        assert len(body["candles"]) > 0
        assert body["candles"][0]["open"] > 0

    def test_window_is_taken_from_the_trade(self, trade_with_candles):
        auth_client, trade_id = trade_with_candles
        candles = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id}
        ).json()["candles"]
        times = [candle["time"] for candle in candles]
        assert times == sorted(times)

    def test_by_symbol_and_range(self, trade_with_candles):
        auth_client, _ = trade_with_candles
        response = auth_client.get(
            "/api/mt5/candles",
            params={
                "symbol": "EURUSD",
                "timeframe": "M15",
                "start": "2026-05-31T00:00:00Z",
                "end": "2026-06-02T00:00:00Z",
            },
        )
        assert response.status_code == 200
        assert len(response.json()["candles"]) == 60

    def test_without_a_trade_or_symbol(self, auth_client):
        assert auth_client.get("/api/mt5/candles").status_code == 400

    def test_unknown_trade(self, auth_client):
        assert auth_client.get("/api/mt5/candles", params={"trade_id": 99999}).status_code == 404

    def test_unknown_symbol_returns_an_empty_series(self, auth_client):
        response = auth_client.get("/api/mt5/candles", params={"symbol": "NOPE"})
        assert response.status_code == 200
        assert response.json()["candles"] == []

    def test_candles_are_not_duplicated_on_resend(self, client, trade_with_candles):
        auth_client, trade_id = trade_with_candles
        before = len(
            auth_client.get("/api/mt5/candles", params={"trade_id": trade_id}).json()["candles"]
        )
        client.post(
            "/api/mt5/ingest",
            json={
                "account": {"login": "5000123", "server": "TestBroker"},
                "deals": [],
                "candles": [
                    {
                        "symbol": "EURUSD",
                        "timeframe": "M15",
                        "candles": [
                            {
                                "time": iso(BASE),
                                "open": 1.1,
                                "high": 1.1,
                                "low": 1.1,
                                "close": 1.1,
                            }
                        ],
                    }
                ],
            },
            headers=INGEST_HEADERS,
        )
        after = len(
            auth_client.get("/api/mt5/candles", params={"trade_id": trade_id}).json()["candles"]
        )
        # That bar is already stored, so re-sending it changes nothing.
        assert after == before


class TestDerivedTimeframes:
    """One timeframe is collected; the rest are arithmetic on it."""

    def test_an_hour_is_built_from_the_stored_quarter_hours(self, trade_with_candles):
        auth_client, trade_id = trade_with_candles

        body = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "H1"}
        ).json()

        assert body["candles"], "an empty chart is what this exists to stop"
        assert body["source"] == "M15", "and it says where the bars came from"
        # Four M15 bars to the hour, and every bar starts on one.
        assert all(bar["time"][14:19] == "00:00" for bar in body["candles"])

    def test_the_folded_bars_are_the_stored_ones(self, trade_with_candles):
        """Exactness matters: somebody reads their entry off these."""
        auth_client, trade_id = trade_with_candles

        quarters = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "M15"}
        ).json()["candles"]
        hours = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "H1"}
        ).json()["candles"]

        first = hours[0]
        inside = [c for c in quarters if c["time"][:13] == first["time"][:13]]
        assert first["open"] == inside[0]["open"]
        assert first["close"] == inside[-1]["close"]
        assert first["high"] == max(c["high"] for c in inside)
        assert first["low"] == min(c["low"] for c in inside)

    def test_the_collected_timeframe_is_preferred_over_folding(self, trade_with_candles):
        auth_client, trade_id = trade_with_candles

        body = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "M15"}
        ).json()

        assert body["source"] == "local"

    def test_a_shorter_timeframe_is_not_invented(self, trade_with_candles):
        """M1 cannot be recovered from M15, so it is refused rather than faked."""
        auth_client, trade_id = trade_with_candles

        body = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "M1"}
        ).json()

        assert body["candles"] == []
        assert body["source"] == "none"

    def test_it_says_which_timeframes_can_be_drawn(self, trade_with_candles):
        """So the chart offers buttons that work, rather than empty ones."""
        auth_client, trade_id = trade_with_candles

        body = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "M15"}
        ).json()

        assert body["available"] == ["M15", "M30", "H1", "H4", "D1", "W1"]
        assert "M1" not in body["available"]

    def test_a_longer_timeframe_asks_for_a_longer_window(self, trade_with_candles):
        """Otherwise zooming out shows the same two hours as two candles."""
        auth_client, trade_id = trade_with_candles

        daily = auth_client.get(
            "/api/mt5/candles", params={"trade_id": trade_id, "timeframe": "D1"}
        ).json()

        assert daily["candles"], "the window has to widen with the timeframe"
