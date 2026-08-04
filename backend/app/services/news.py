"""The economic calendar, from ForexFactory's own feed.

ForexFactory cannot be embedded. The site sits behind a Cloudflare challenge
and answers with ``X-Frame-Options: SAMEORIGIN``, so an iframe of it shows a
403 page and nothing else -- there is no widget to point at.

What it does publish is the week's calendar as JSON, on its own media host.
That is fetched here rather than in the browser, for three reasons: the feed
sends no CORS header, so a page cannot read it directly; it is rate limited
hard enough that a second request within a minute is answered with 429; and
fetching it once for everyone means the calendar keeps working while the
limit is in force.

Only the current week exists. ``ff_calendar_nextweek.json`` and its lastweek
counterpart are 404, so there is nothing to page through and the calendar
shows the week it is in.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

#: How long a fetched week is good for. The calendar itself changes rarely --
#: forecasts firm up, actuals land -- and the feed's rate limit is the binding
#: constraint rather than freshness.
TTL_SECONDS = 900.0

#: How long to keep serving a copy after the feed stops answering. A day-old
#: calendar is worth far more than an empty panel: the releases are still on
#: the days they were on, and only the actuals go stale.
STALE_SECONDS = 24 * 3600.0

#: How long to leave a feed alone after it refuses us. Shorter than the normal
#: interval, because a page with no calendar on it should recover quickly --
#: but not absent, or every page view would retry a rate limit and extend it.
RETRY_SECONDS = 60.0

#: ForexFactory's own impact names, strongest first. "Red folder" is High.
IMPACTS = ("High", "Medium", "Low", "Holiday")


@dataclass
class Event:
    """One release, as the calendar shows it."""

    title: str
    currency: str
    when: datetime
    impact: str
    forecast: str = ""
    previous: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "currency": self.currency,
            "time": self.when.isoformat(),
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
        }


@dataclass
class Cache:
    events: list[Event] = field(default_factory=list)
    fetched_at: float = 0.0
    fetched_wall: datetime | None = None
    error: str | None = None


_cache = Cache()


def _parse(payload: Any) -> list[Event]:
    events: list[Event] = []
    for row in payload if isinstance(payload, list) else []:
        try:
            when = datetime.fromisoformat(str(row["date"]))
        except (KeyError, TypeError, ValueError):
            continue
        events.append(
            Event(
                title=str(row.get("title") or "").strip(),
                # The feed calls it "country" and puts a currency in it.
                currency=str(row.get("country") or "").strip().upper(),
                when=when,
                impact=str(row.get("impact") or "").strip().title(),
                forecast=str(row.get("forecast") or "").strip(),
                previous=str(row.get("previous") or "").strip(),
            )
        )
    events.sort(key=lambda event: event.when)
    return events


def load(force: bool = False) -> Cache:
    """This week's calendar, from cache unless it is old enough to refetch.

    A failed fetch never clears what is already held. The feed answers 429 to
    anything eager, and throwing away a good week's calendar because of a rate
    limit would turn a working page into an empty one for the next quarter of
    an hour.
    """
    now = time.monotonic()
    # A failed fetch counts as a fetch. It used to count only when something
    # was already held, so the first failure left nothing cached and every
    # page view went straight back to a feed that had just refused us.
    interval = TTL_SECONDS if _cache.events and not _cache.error else RETRY_SECONDS
    if not force and _cache.fetched_at and now - _cache.fetched_at < interval:
        return _cache

    try:
        response = httpx.get(
            FEED_URL,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "TradeZulu/1 (self-hosted trading journal)"},
        )
        response.raise_for_status()
        events = _parse(response.json())
        if not events:
            raise ValueError("the feed returned no events")
    except Exception as error:  # noqa: BLE001 - a calendar must not break a page
        _cache.error = f"{type(error).__name__}: {error}"
        _cache.fetched_at = now  # do not hammer a feed that is refusing us
        log.warning("news: could not refresh the ForexFactory calendar: %s", _cache.error)
        return _cache

    _cache.events = events
    _cache.fetched_at = now
    _cache.fetched_wall = datetime.now().astimezone()
    _cache.error = None
    return _cache


def select(
    events: list[Event], currencies: list[str], impacts: list[str]
) -> list[Event]:
    """Filter to what was asked for.

    Events marked "All" -- OPEC meetings, G20, bank holidays across a region --
    belong to no currency and matter to whoever is trading that session, so
    they pass any currency filter. They still have to pass the impact one.
    """
    wanted = {code.strip().upper() for code in currencies if code.strip()}
    levels = {level.strip().title() for level in impacts if level.strip()}
    return [
        event
        for event in events
        if (not levels or event.impact in levels)
        and (not wanted or event.currency in wanted or event.currency == "ALL")
    ]


def calendar(currencies: list[str], impacts: list[str]) -> dict[str, Any]:
    """The filtered calendar, plus enough about the fetch to explain itself."""
    cache = load()
    age = time.monotonic() - cache.fetched_at if cache.fetched_at else None
    return {
        "source": "forexfactory",
        "events": [event.as_dict() for event in select(cache.events, currencies, impacts)],
        "updated_at": cache.fetched_wall.isoformat() if cache.fetched_wall else None,
        # True when the feed refused the last refresh and this is what was held
        # from before. The page says so rather than implying it is live.
        "stale": bool(cache.error and cache.events),
        "error": cache.error if not cache.events else None,
        "unreachable": bool(cache.error),
        "expired": bool(age is not None and cache.events and age > STALE_SECONDS),
    }
