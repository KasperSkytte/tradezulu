"""Tags colour themselves.

Two tags the same colour is not cosmetic: the reports page draws habits by
colour, and a chart where "Moved stop" and "Late entry" are the same red is a
chart that cannot be read. Keeping that right by hand, in a colour picker,
while naming a mistake, is the part the software should be doing.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Tag
from app.services.tagcolors import FALLBACK, PALETTE, next_color


class TestChoosingOne:
    def test_the_first_of_the_category_when_nothing_is_taken(self):
        assert next_color([], "mistake") == PALETTE["mistake"][0]

    def test_it_avoids_what_is_already_used(self):
        taken = PALETTE["mistake"][:3]
        assert next_color(taken, "mistake") == PALETTE["mistake"][3]

    def test_a_category_keeps_to_its_own_range(self):
        """An automatic colour that made a mistake look like a setup would be
        worse than making somebody choose."""
        chosen = next_color([], "setup")
        assert chosen in PALETTE["setup"]
        assert chosen not in PALETTE["mistake"]

    def test_an_unknown_category_still_gets_a_colour(self):
        """Categories are user-defined, so most of them have no ramp."""
        assert next_color([], "something-nobody-planned-for") == FALLBACK[0]

    def test_case_and_padding_do_not_hide_a_colour(self):
        taken = [f"  {PALETTE['setup'][0].upper()}  "]
        assert next_color(taken, "setup") == PALETTE["setup"][1]

    def test_colours_used_elsewhere_still_count(self):
        """The comparison is against every tag, not just this category: two
        categories sharing a colour is the same unreadable chart."""
        assert next_color(["#22c55e"], "setup") != "#22c55e"

    def test_a_full_ramp_borrows_rather_than_repeats(self):
        """Twelve tags in one category is a lot of tags, and the thirteenth
        still needs a colour. A slightly off-category colour is a much smaller
        problem than two tags nobody can tell apart -- which is what repeating
        one here did, "fixing" a duplicate by making another."""
        taken = list(PALETTE["mistake"])

        chosen = next_color(taken, "mistake")

        assert chosen not in taken

    def test_only_a_truly_full_palette_repeats(self):
        every = {shade for ramp in PALETTE.values() for shade in ramp} | set(FALLBACK)
        ramp = PALETTE["mistake"]
        # Everything twice over except the first of this category's range.
        taken = list(every) + [c for c in every if c != ramp[0]]

        assert next_color(taken, "mistake") == ramp[0]

    def test_it_is_deterministic(self):
        assert next_color(["#ef4444"], "mistake") == next_color(["#ef4444"], "mistake")


class TestThroughTheApi:
    def test_a_new_tag_needs_no_colour(self, auth_client):
        created = auth_client.post("/api/tags", json={"name": "Chased it", "category": "mistake"})

        assert created.status_code == 201, created.text
        assert created.json()["color"].startswith("#")

    def test_it_differs_from_every_tag_already_there(self, auth_client, db):
        """The seeded tags fill most of a ramp, so this is a real collision test."""
        created = auth_client.post(
            "/api/tags", json={"name": "Chased it", "category": "mistake"}
        ).json()

        others = [
            colour
            for colour, in db.execute(select(Tag.color).where(Tag.id != created["id"]))
        ]
        assert created["color"] not in others

    def test_several_new_tags_all_differ(self, auth_client):
        colours = [
            auth_client.post("/api/tags", json={"name": f"Tag {n}", "category": "mistake"})
            .json()["color"]
            for n in range(4)
        ]
        assert len(set(colours)) == len(colours)

    def test_a_colour_that_was_asked_for_is_honoured(self, auth_client):
        """Automatic is the default, not the only option."""
        created = auth_client.post(
            "/api/tags", json={"name": "Mine", "color": "#123456", "category": "mistake"}
        )
        assert created.json()["color"] == "#123456"

    def test_editing_a_tag_without_a_colour_keeps_the_one_it_has(self, auth_client):
        """The update takes the whole tag, so an omitted colour used to reset
        it to the schema default -- silently recolouring a tag on a rename."""
        created = auth_client.post("/api/tags", json={"name": "Kept", "category": "mistake"}).json()

        renamed = auth_client.patch(
            f"/api/tags/{created['id']}", json={"name": "Renamed", "category": "mistake"}
        ).json()

        assert renamed["color"] == created["color"]


class TestFixingWhatIsAlreadyThere:
    """New tags colouring themselves does nothing for the tags already here."""

    def _colours(self, db):
        return [colour for colour, in db.execute(select(Tag.color))]

    def test_a_repeated_colour_is_given_a_new_one(self, auth_client, db):
        first = db.scalar(select(Tag))
        clash = Tag(name="Clashing", color=first.color, category=first.category)
        db.add(clash)
        db.commit()

        changed = auth_client.post("/api/tags/recolour").json()

        assert [tag["name"] for tag in changed] == ["Clashing"]
        db.expire_all()
        colours = self._colours(db)
        assert len(colours) == len(set(colours))

    def test_tags_that_are_already_unique_are_left_alone(self, auth_client, db):
        """Including a colour somebody chose on purpose, so this is safe to press."""
        before = {tag.id: tag.color for tag in db.scalars(select(Tag))}

        assert auth_client.post("/api/tags/recolour").json() == []

        db.expire_all()
        assert {tag.id: tag.color for tag in db.scalars(select(Tag))} == before

    def test_it_is_worth_pressing_twice(self, auth_client, db):
        first = db.scalar(select(Tag))
        db.add_all(
            [
                Tag(name="Clash one", color=first.color, category=first.category),
                Tag(name="Clash two", color=first.color, category=first.category),
            ]
        )
        db.commit()

        auth_client.post("/api/tags/recolour")

        assert auth_client.post("/api/tags/recolour").json() == []
        db.expire_all()
        colours = self._colours(db)
        assert len(colours) == len(set(colours))
