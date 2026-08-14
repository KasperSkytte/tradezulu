"""Reading ForexFactory's news stories out of the page they are rendered on.

There is no feed for these -- the stories arrive as JSON inside a ``data-items``
attribute -- so this suite pins the shape that is relied on. If ForexFactory
changes it, these fail here rather than the panel quietly emptying itself in
front of somebody deciding whether to trade.
"""

from __future__ import annotations

import html as htmllib
import json
from datetime import timezone

import pytest

from app.services import stories as ff


def page(*items: dict) -> str:
    """A page carrying these stories the way ForexFactory carries them."""
    payload = json.dumps([{"story": item} for item in items])
    return (
        "<section class='content news'>"
        f"<hot-stories-component data-items=\"{htmllib.escape(payload, quote=True)}\">"
        "</hot-stories-component></section>"
    )


def story(**overrides) -> dict:
    body = {
        "id": 1413351,
        "dateline": 1786686309,
        "url": "/news/1413351-boj-could-raise-rates-in-september",
        "title": "BOJ could raise rates in September, sources say",
        "preview": " <span class=\"flexposts__storylabel\">table</span> Some text ",
        "source": "@FirstSquawk",
        "impact": "high",
        "comments": 14,
        "calendar_linked": False,
    }
    body.update(overrides)
    return body


class TestReadingAStory:
    def test_the_fields_the_panel_needs(self):
        (parsed,) = ff._stories_from(page(story()))

        assert parsed.id == 1413351
        assert parsed.title == "BOJ could raise rates in September, sources say"
        assert parsed.source == "@FirstSquawk"
        assert parsed.impact == "High"
        assert parsed.comments == 14

    def test_the_url_is_made_absolute(self):
        """The page carries a path; a link in another site needs the host."""
        (parsed,) = ff._stories_from(page(story()))
        assert parsed.url == (
            "https://www.forexfactory.com/news/1413351-boj-could-raise-rates-in-september"
        )

    def test_the_timestamp_is_utc(self):
        """A unix dateline, so nothing about the reader's clock comes into it."""
        (parsed,) = ff._stories_from(page(story(dateline=1786686309)))
        assert parsed.when.tzinfo is timezone.utc
        assert parsed.when.isoformat() == "2026-08-14T05:45:09+00:00"

    def test_preview_markup_does_not_reach_the_page(self):
        (parsed,) = ff._stories_from(page(story()))
        assert "<span" not in parsed.preview
        assert "table Some text" in parsed.preview

    def test_an_unrated_story_keeps_no_rating(self):
        """Most of the wire is unrated; that is not the same as low impact."""
        (parsed,) = ff._stories_from(page(story(impact="")))
        assert parsed.impact == ""

    def test_a_story_tied_to_a_release_says_so(self):
        (parsed,) = ff._stories_from(page(story(calendar_linked=True)))
        assert parsed.scheduled is True


class TestReadingThePage:
    def test_newest_first(self):
        html = page(
            story(id=1, dateline=1786600000),
            story(id=2, dateline=1786686309),
        )
        assert [s.id for s in ff._stories_from(html)] == [2, 1]

    def test_a_story_in_two_lists_is_read_once(self):
        """The page repeats stories across its components; the panel must not."""
        html = page(story(), story()) + page(story())
        assert len(ff._stories_from(html)) == 1

    def test_a_story_missing_its_timestamp_is_skipped_not_fatal(self):
        html = page(story(id=1, dateline="not a time"), story(id=2))
        assert [s.id for s in ff._stories_from(html)] == [2]

    def test_a_page_with_nothing_on_it_reads_as_nothing(self):
        """Which is what makes the fetch treat it as a failure and keep the
        last good copy, rather than replacing it with an empty list."""
        assert ff._stories_from("<html><body>Just a moment...</body></html>") == []


class TestFiltering:
    @pytest.fixture()
    def three(self):
        return ff._stories_from(
            page(
                story(id=1, impact="high", dateline=1786686309),
                story(id=2, impact="low", dateline=1786686308),
                story(id=3, impact="", dateline=1786686307),
            )
        )

    def test_by_rating(self, three):
        assert [s.id for s in ff.select(three, ["High"])] == [1]

    def test_several_ratings(self, three):
        assert [s.id for s in ff.select(three, ["High", "Low"])] == [1, 2]

    def test_no_filter_means_everything_including_the_unrated(self, three):
        """Two thirds of the wire carries no rating, so "everything" has to
        mean everything -- otherwise the default filter shows almost nothing."""
        assert [s.id for s in ff.select(three, [])] == [1, 2, 3]

    def test_asking_for_a_rating_leaves_out_the_unrated(self, three):
        """Otherwise "red folder only" would return the whole page with the red
        ones somewhere in it."""
        assert 3 not in [s.id for s in ff.select(three, ["High", "Medium", "Low"])]

    def test_the_limit_is_honoured(self, three):
        assert len(ff.select(three, [], limit=2)) == 2
