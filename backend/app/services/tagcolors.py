"""Picking a colour for a tag, so nobody has to.

A tag's colour is not a decision worth making. It has to be distinct from the
other tags -- two habits the same colour on the reports page is a chart that
lies about which one cost you the money -- and keeping twenty of them distinct
by hand, in a colour picker, at the moment you are trying to name a mistake, is
work the software should be doing.

Grouped by category rather than one long ramp, because the colour already
means something here: the seeded tags put setups in greens and blues, mistakes
in reds and oranges, and behaviour in purples. An automatic colour that ignored
that would make a new mistake look like a setup, which is worse than making
somebody choose.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

#: Each category's ramp, in the order they are handed out. The first entries
#: are the ones the seeded tags already use, so an install that has only those
#: carries on where it left off rather than repeating a colour immediately.
PALETTE: dict[str, tuple[str, ...]] = {
    "setup": (
        "#22c55e", "#84cc16", "#eab308", "#38bdf8", "#60a5fa", "#a78bfa",
        "#f472b6", "#2dd4bf", "#4ade80", "#0ea5e9", "#818cf8", "#c4b5fd",
    ),
    "mistake": (
        "#ef4444", "#f97316", "#dc2626", "#e11d48", "#b91c1c", "#fb923c",
        "#f59e0b", "#ea580c", "#f43f5e", "#fca5a5", "#c2410c", "#facc15",
    ),
    "emotion": (
        "#d946ef", "#c026d3", "#9333ea", "#8b5cf6", "#14b8a6", "#a855f7",
        "#e879f9", "#7c3aed", "#06b6d4", "#f0abfc", "#6366f1", "#5eead4",
    ),
}

#: For a category nobody has defined a ramp for -- including "custom" and any
#: category the user adds themselves. Deliberately spread across the wheel so
#: consecutive tags look nothing like each other.
FALLBACK: tuple[str, ...] = (
    "#7c8cf8", "#f472b6", "#2dd4bf", "#fb923c", "#a78bfa", "#4ade80",
    "#38bdf8", "#f43f5e", "#facc15", "#c084fc", "#22d3ee", "#fda4af",
)


def next_color(taken: Iterable[str], category: str = "custom") -> str:
    """A colour for a new tag in ``category``, given what the others use.

    In order of preference: an unused colour from the category's own range;
    then an unused colour from anywhere, because a tag that looks slightly off
    for its category is a far smaller problem than two tags that cannot be
    told apart; and only when every colour here is spoken for, the least used
    one from the category's range.
    """
    ramp = PALETTE.get(category.strip().lower()) or FALLBACK
    used = Counter(colour.strip().lower() for colour in taken if colour)

    for colour in ramp:
        if not used.get(colour.lower()):
            return colour

    everything = (*FALLBACK, *(shade for other in PALETTE.values() for shade in other))
    for colour in everything:
        if not used.get(colour.lower()):
            return colour

    return min(
        ramp,
        key=lambda colour: (used.get(colour.lower(), 0), ramp.index(colour)),
    )
