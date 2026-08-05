"""Building the timeframes nobody collected out of the one that was.

A terminal uploads a single timeframe -- there is no point sending six, since
five of them are arithmetic on the sixth. Everything above the collected one
is derived here: three M5 bars are an M15 bar, twelve are an H1, and so on.

Nothing is derived downwards. M1 cannot be recovered from M5 and no amount of
interpolation would make it true, so a timeframe below the one collected is
simply not offered rather than invented.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Every timeframe the journal knows, and how long one bar of it lasts.
#: Ordered, because "the largest stored timeframe that divides this one" is a
#: question about order as much as about arithmetic.
TIMEFRAMES: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
}


@dataclass(frozen=True)
class Bar:
    """One candle, in the shape the API returns."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def seconds(timeframe: str) -> int:
    return TIMEFRAMES.get(timeframe.upper(), 900)


def source_for(timeframe: str, stored: Sequence[str]) -> str | None:
    """Which stored timeframe to build ``timeframe`` from, if any.

    The largest one that divides it exactly. Exactness is the whole point: two
    M5 bars do not make an M15 bar, and a "roughly right" candle on a chart
    somebody is reading their entry off is worse than no candle.
    """
    target = seconds(timeframe)
    candidates = [
        name
        for name in stored
        if name.upper() in TIMEFRAMES
        and seconds(name) <= target
        and target % seconds(name) == 0
    ]
    if not candidates:
        return None
    return max(candidates, key=seconds)


def available(stored: Sequence[str]) -> list[str]:
    """Every timeframe that can be drawn, given what has been collected."""
    return [name for name in TIMEFRAMES if source_for(name, stored) is not None]


def aggregate(bars: Sequence[Bar], timeframe: str) -> list[Bar]:
    """Fold bars up into a longer timeframe.

    Buckets are aligned to the epoch, so an H4 bar starts at 00:00, 04:00, 08:00
    UTC and a D1 bar at midnight UTC -- the same boundaries MetaTrader uses on a
    server set to UTC. A broker whose day rolls at 22:00 will disagree with the
    daily candle by two hours; that is a property of the broker's clock rather
    than of this arithmetic, and it is why the timeframe actually collected is
    preferred over a derived one wherever both exist.

    An incomplete final bucket is kept. It is what the price is doing now, and
    dropping it would leave the chart ending an hour before the trade did.
    """
    span = seconds(timeframe)
    out: list[Bar] = []
    bucket_start: datetime | None = None
    working: list[Bar] = []

    for bar in sorted(bars, key=lambda item: item.time):
        start = _floor(bar.time, span)
        if bucket_start is None or start != bucket_start:
            if working:
                out.append(_fold(working, bucket_start))
            bucket_start, working = start, []
        working.append(bar)

    if working:
        out.append(_fold(working, bucket_start))
    return out


def _floor(when: datetime, span: int) -> datetime:
    stamp = int(when.timestamp())
    return datetime.fromtimestamp(stamp - stamp % span, tz=when.tzinfo)


def _fold(bars: list[Bar], start: datetime | None) -> Bar:
    return Bar(
        time=start or bars[0].time,
        open=bars[0].open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=bars[-1].close,
        volume=sum(bar.volume for bar in bars),
    )


#: A day either side, if nothing says otherwise.
DEFAULT_DAYS = 1.0


def window_padding(days_before: float, days_after: float) -> tuple[timedelta, timedelta]:
    """How far either side of a trade to read, as real time.

    Days rather than a bar count, so the window means the same thing at every
    timeframe: switching from M5 to H4 changes how finely the same stretch is
    drawn, not how much of it there is. A bar count did the opposite -- 144
    bars was twelve hours at M5 and most of a month at H4 -- which made the
    setting impossible to reason about and asked for history nothing had
    collected.
    """
    return (
        timedelta(days=max(0.0, days_before or DEFAULT_DAYS)),
        timedelta(days=max(0.0, days_after or DEFAULT_DAYS)),
    )


def bars_in(days: float, timeframe: str) -> int:
    """How many bars of ``timeframe`` fit in ``days``.

    What the terminal has to be asked for, and what the settings page shows so
    a number of days is not an abstract quantity.
    """
    return max(1, round(days * 86_400 / seconds(timeframe)))
