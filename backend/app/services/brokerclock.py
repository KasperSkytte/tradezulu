"""What time the broker thinks it is.

MetaTrader has one clock and it is the broker's. Deal times, candle times,
position times -- all of them are that server's wall clock, written without an
offset, so 09:37 in the history of a Cyprus broker and 09:37 in the history of
an Australian one are stored identically and are two hours apart in reality.

Nothing in a MetaTrader payload says which. The terminal has to be asked, and
what it answers is compared against real UTC here rather than against the
terminal's own idea of GMT: the terminal runs in a container whose timezone is
nobody's decision in particular, and getting this wrong would move every time
in the journal.

Knowing the offset is what makes it possible to show a trade at the time the
trader took it rather than at the time the broker filed it. Until a terminal
has reported one, times stay as the broker wrote them -- which is what
MetaTrader itself shows, and is never silently wrong by an hour.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Offsets brokers actually use are whole quarter-hours, so rounding to one
#: absorbs the second or two a request spends in flight without ever landing on
#: an offset no broker has.
STEP_MINUTES = 15

#: Beyond this, it is not an offset. A terminal that has not synchronised yet
#: reports 1970, and no broker is half a day from UTC.
MAX_MINUTES = 12 * 60


def offset_minutes(server_time: Any, *, now: datetime | None = None) -> int | None:
    """How far the broker's clock runs from UTC, from the clock it just sent.

    ``None`` when the terminal sent nothing usable, which leaves whatever was
    already known in place rather than replacing it with a guess.
    """
    broker_now = _as_naive_utc(server_time)
    if broker_now is None:
        return None

    reference = now or datetime.now(timezone.utc)
    reference = reference.replace(tzinfo=None) if reference.tzinfo else reference

    drift = (broker_now - reference).total_seconds() / 60
    if abs(drift) > MAX_MINUTES:
        return None
    return int(round(drift / STEP_MINUTES) * STEP_MINUTES)


def _as_naive_utc(value: Any) -> datetime | None:
    """The terminal's timestamp as a plain datetime, or None if it is not one.

    ``TimeCurrent()`` arrives as a Unix epoch, but the same field is accepted
    as a string from anything hand-rolled against the ingest endpoint.
    """
    if isinstance(value, datetime):
        pass
    elif isinstance(value, bool):
        return None
    elif isinstance(value, (int, float)):
        try:
            value = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
