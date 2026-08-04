"""The ForexFactory calendar: fetching it once, and surviving it refusing.

ForexFactory cannot be embedded -- Cloudflare challenge, and
X-Frame-Options: SAMEORIGIN -- so the server reads their published feed
instead. That feed rate-limits hard, which is what most of this is about.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services import news

WEEK = [
    {
        "title": "ISM Manufacturing PMI",
        "country": "USD",
        "date": "2026-08-03T10:00:00-04:00",
        "impact": "High",
        "forecast": "54.0",
        "previous": "53.3",
    },
    {
        "title": "Retail Sales m/m",
        "country": "GBP",
        "date": "2026-08-04T02:00:00-04:00",
        "impact": "High",
        "forecast": "",
        "previous": "0.4%",
    },
    {
        "title": "Crude Oil Inventories",
        "country": "USD",
        "date": "2026-08-05T10:30:00-04:00",
        "impact": "Medium",
        "forecast": "",
        "previous": "-1.2M",
    },
    {
        "title": "OPEC-JMMC Meetings",
        "country": "All",
        "date": "2026-08-02T05:15:00-04:00",
        "impact": "High",
        "forecast": "",
        "previous": "",
    },
]


@pytest.fixture(autouse=True)
def clean_cache():
    news._cache = news.Cache()
    yield
    news._cache = news.Cache()


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestParsing:
    def test_a_release_keeps_its_own_time(self, monkeypatch):
        """The feed is New York time with an offset on it, not UTC."""
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))

        events = news.load().events

        assert len(events) == 4
        first = next(e for e in events if e.title == "ISM Manufacturing PMI")
        assert first.when == datetime.fromisoformat("2026-08-03T10:00:00-04:00")
        assert first.currency == "USD"
        assert first.forecast == "54.0"

    def test_events_come_back_in_order(self, monkeypatch):
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))
        times = [event.when for event in news.load().events]
        assert times == sorted(times)


class TestFiltering:
    def test_red_folder_dollars_is_the_point(self, monkeypatch):
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))

        titles = [e.title for e in news.select(news.load().events, ["USD"], ["High"])]

        assert "ISM Manufacturing PMI" in titles
        assert "Retail Sales m/m" not in titles, "that is sterling"
        assert "Crude Oil Inventories" not in titles, "that is an orange folder"

    def test_events_belonging_to_no_currency_still_show(self, monkeypatch):
        """OPEC meetings and the like are marked "All" and move everything."""
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))

        titles = [e.title for e in news.select(news.load().events, ["USD"], ["High"])]

        assert "OPEC-JMMC Meetings" in titles

    def test_no_filter_is_everything(self, monkeypatch):
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))
        assert len(news.select(news.load().events, [], [])) == 4


class TestFetching:
    def test_the_feed_is_read_once_and_reused(self, monkeypatch):
        """It answers 429 to anything eager, so a page view cannot cost a fetch."""
        calls = []

        def once(*args, **kwargs):
            calls.append(1)
            return _Response(WEEK)

        monkeypatch.setattr(news.httpx, "get", once)

        news.load()
        news.load()
        news.load()

        assert len(calls) == 1

    def test_a_refusal_keeps_the_week_it_already_had(self, monkeypatch):
        """A rate limit must not turn a working calendar into an empty one."""
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))
        news.load()

        def refused(*args, **kwargs):
            return _Response(None, status=429)

        monkeypatch.setattr(news.httpx, "get", refused)
        news._cache.fetched_at = 0.0  # old enough to want refreshing
        result = news.calendar(["USD"], ["High"])

        assert result["events"], "the last good copy is still there"
        assert result["stale"] is True
        assert result["error"] is None

    def test_a_refusal_with_nothing_held_says_so(self, monkeypatch):
        monkeypatch.setattr(
            news.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("no route"))
        )

        result = news.calendar(["USD"], ["High"])

        assert result["events"] == []
        assert "no route" in result["error"]

    def test_a_failed_fetch_is_not_retried_immediately(self, monkeypatch):
        """Hammering a feed that is refusing us is how the ban gets longer."""
        calls = []

        def refused(*args, **kwargs):
            calls.append(1)
            return _Response(None, status=429)

        monkeypatch.setattr(news.httpx, "get", refused)
        news.calendar(["USD"], ["High"])
        news.calendar(["USD"], ["High"])

        assert len(calls) == 1

    def test_an_empty_feed_is_a_failure_not_an_answer(self, monkeypatch):
        """200 with nothing in it is what a blocked request looks like."""
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))
        news.load()
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response([]))
        news._cache.fetched_at = 0.0  # let it try again

        result = news.calendar(["USD"], ["High"])

        assert result["events"], "the good copy survives"
        assert result["stale"] is True


class TestEndpoint:
    def test_it_defaults_to_what_was_saved(self, auth_client, monkeypatch):
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))
        auth_client.put(
            "/api/settings", json={"news": {"currencies": ["GBP"], "impacts": ["High"]}}
        )

        body = auth_client.get("/api/news/calendar").json()

        titles = [event["title"] for event in body["events"]]
        assert "Retail Sales m/m" in titles
        assert "ISM Manufacturing PMI" not in titles

    def test_the_query_can_override_it(self, auth_client, monkeypatch):
        monkeypatch.setattr(news.httpx, "get", lambda *a, **k: _Response(WEEK))

        body = auth_client.get(
            "/api/news/calendar", params={"currencies": "USD", "impacts": "High,Medium"}
        ).json()

        titles = [event["title"] for event in body["events"]]
        assert "Crude Oil Inventories" in titles

    def test_it_needs_a_session(self, client):
        assert client.get("/api/news/calendar").status_code == 401
