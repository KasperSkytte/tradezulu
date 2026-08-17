"""ForexFactory's news stories -- the headlines, beside the calendar.

The calendar answers "what is scheduled"; this answers "what has happened".
ForexFactory carries stories from hundreds of sources with an impact rating on
each, which is the part nobody else does: a wire feed gives you headlines, and
this gives you the ones ForexFactory's own readers treat as market-moving.

There is no published feed for it. The calendar has one because ForexFactory
mirrors that to a media host for the MetaTrader crowd; the news page does not,
and the site itself sits behind a challenge that answers anything without a
full browser header set with a 403. It does answer a request that looks like
a browser, and the page it returns carries every story as JSON inside a
``data-items`` attribute -- component props, not markup -- so what is parsed
here is structured data rather than scraped HTML. That matters for how it
breaks: a redesign moves the page around without touching these fields, and a
change to the fields themselves is a parse that returns nothing rather than
one that returns something wrong.

Fetched here rather than in the browser for the same reasons as the calendar:
no CORS header, one fetch serving everyone, and a cache that keeps the panel
populated when the site declines to answer.
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

STORIES_URL = "https://www.forexfactory.com/news"

#: Headers matter here in a way they do not for the calendar feed. A bare
#: user-agent is answered with the Cloudflare challenge page; the full set a
#: browser sends is answered with the news. This is not a disguise -- the
#: request is honest about being a program in every other way -- it is the
#: minimum the site accepts.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

#: Stories arrive continuously, unlike a calendar that changes a few times a
#: day -- but not so fast that a page view should cost a fetch.
TTL_SECONDS = 300.0
STALE_SECONDS = 6 * 3600.0
RETRY_SECONDS = 60.0

#: ForexFactory's own ratings. A story with no rating is not unimportant --
#: most of the wire is unrated -- so it is kept as "" and filtered separately.
IMPACTS = ("High", "Medium", "Low")

_ITEMS = re.compile(r'data-items="([^"]+)"')


@dataclass
class Story:
    """One headline, as ForexFactory files it."""

    id: int
    title: str
    url: str
    source: str
    when: datetime
    impact: str = ""
    preview: str = ""
    comments: int = 0
    #: True when ForexFactory ties this story to a calendar release, which is
    #: what makes a headline about a number one of *the* numbers.
    scheduled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "time": self.when.isoformat(),
            "impact": self.impact,
            "preview": self.preview,
            "comments": self.comments,
            "scheduled": self.scheduled,
        }


@dataclass
class Cache:
    stories: list[Story] = field(default_factory=list)
    fetched_at: float = 0.0
    fetched_wall: datetime | None = None
    error: str | None = None


_cache = Cache()

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: Any) -> str:
    """Story text as text. Previews carry a little markup of their own.

    Whitespace is collapsed as well as stripped: removing a tag leaves the
    spaces that were on either side of it, and two of them in the middle of a
    headline show up as a gap on the page.
    """
    return re.sub(r"\s+", " ", htmllib.unescape(_TAGS.sub(" ", str(text or "")))).strip()


def _stories_from(page: str) -> list[Story]:
    """Every story object the page carries, wherever it carries it.

    The page has several lists -- the hot stories, the stream, each sidebar --
    and they overlap. Walking whatever is in ``data-items`` and keeping the
    objects that look like a story means none of that has to be known here,
    and a list moving between components does not need a change.
    """
    seen: dict[int, Story] = {}
    for match in _ITEMS.finditer(page):
        try:
            payload = json.loads(htmllib.unescape(match.group(1)))
        except (ValueError, TypeError):
            continue

        stack: list[Any] = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            if not ("dateline" in node and "title" in node):
                stack.extend(node.values())
                continue

            try:
                story_id = int(node["id"])
                when = datetime.fromtimestamp(int(node["dateline"]), tz=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue

            url = str(node.get("url") or "")
            story = Story(
                id=story_id,
                title=_clean(node.get("title")),
                url=f"https://www.forexfactory.com{url}" if url.startswith("/") else url,
                source=str(node.get("source") or "").strip(),
                when=when,
                impact=str(node.get("impact") or "").strip().title(),
                preview=_clean(node.get("preview"))[:400],
                comments=int(node.get("comments") or 0),
                scheduled=bool(node.get("calendar_linked")),
            )
            seen[story_id] = _merge(seen.get(story_id), story)

    return sorted(seen.values(), key=lambda story: story.when, reverse=True)


def _merge(prior: Story | None, found: Story) -> Story:
    """One story from the several copies of it the page carries.

    The same story appears in more than one of these lists, and the copies do
    not agree about when it happened: the one in the stream is stamped with a
    later time than the one in the hot list -- half an hour later, in the case
    that turned this up -- and taking whichever came last put a time on screen
    that ForexFactory itself does not show.

    The earliest stamp is the one it was published at, which is what the source
    page displays and the only one that means anything to a reader. The rest of
    the fields are filled from whichever copy has them: the later copies tend
    to carry an empty preview and a placeholder picture.
    """
    if prior is None:
        return found
    return Story(
        id=found.id,
        title=prior.title or found.title,
        url=prior.url or found.url,
        source=prior.source or found.source,
        when=min(prior.when, found.when),
        impact=prior.impact or found.impact,
        preview=prior.preview or found.preview,
        # Comment counts only grow, so the larger is the fresher reading.
        comments=max(prior.comments, found.comments),
        scheduled=prior.scheduled or found.scheduled,
    )


def load(force: bool = False) -> Cache:
    """The latest stories, from cache unless it is time to look again.

    A failed fetch never clears what is held, and counts as a fetch: a site
    that has just refused us must not be asked again by the next page view.
    """
    now = time.monotonic()
    interval = TTL_SECONDS if _cache.stories and not _cache.error else RETRY_SECONDS
    if not force and _cache.fetched_at and now - _cache.fetched_at < interval:
        return _cache

    try:
        response = httpx.get(
            STORIES_URL, timeout=20.0, follow_redirects=True, headers=BROWSER_HEADERS
        )
        response.raise_for_status()
        stories = _stories_from(response.text)
        if not stories:
            raise ValueError("the page carried no stories")
    except Exception as error:  # noqa: BLE001 - news must not break a page
        _cache.error = f"{type(error).__name__}: {error}"
        _cache.fetched_at = now
        log.warning("news: could not refresh ForexFactory stories: %s", _cache.error)
        return _cache

    _cache.stories = stories
    _cache.fetched_at = now
    _cache.fetched_wall = datetime.now().astimezone()
    _cache.error = None
    return _cache


def select(stories: list[Story], impacts: list[str], limit: int = 40) -> list[Story]:
    """Filter to the ratings asked for.

    An empty filter means everything, as it does on the calendar. Unrated
    stories are the bulk of the wire and belong to no level, so they appear
    only when nothing is being filtered for -- otherwise asking for "high"
    would return the whole page with the high ones somewhere in it.
    """
    levels = {level.strip().title() for level in impacts if level.strip()}
    if not levels:
        return stories[:limit]
    return [story for story in stories if story.impact in levels][:limit]


def stories(impacts: list[str], limit: int = 40) -> dict[str, Any]:
    """The filtered stories, plus enough about the fetch to explain itself."""
    cache = load()
    age = time.monotonic() - cache.fetched_at if cache.fetched_at else None
    return {
        "source": "forexfactory",
        "stories": [story.as_dict() for story in select(cache.stories, impacts, limit)],
        "updated_at": cache.fetched_wall.isoformat() if cache.fetched_wall else None,
        # True when the last refresh failed and this is what was held from
        # before, so the page can say so rather than implying it is live.
        "stale": bool(cache.error and cache.stories),
        "error": cache.error if not cache.stories else None,
        "age_seconds": int(age) if age is not None else None,
        "outdated": bool(age is not None and age > STALE_SECONDS),
    }
