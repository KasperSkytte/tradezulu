"""Holding a slave's request open until there is something to tell it.

MetaTrader cannot be pushed to. An Expert Advisor has ``WebRequest`` and
nothing else: outbound, one call at a time, and no way for anything to reach
*in*. So the only way for the server to speak first is to be asked a question
it does not answer yet -- the slave opens one request, the server keeps it, and
replies the instant the master reports a change.

That is push in everything but name. There is no interval to tune and no
repeated asking: one held connection per armed slave, and a copy goes out
within a network round trip of the fill that caused it.

Nothing here is durable and nothing needs to be. A waiter that is lost because
the process restarted is a request the terminal reopens immediately, and the
first thing the server does with a reopened request is plan from the current
state -- which is the same answer it would have been woken with.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

#: account id -> the terminals currently waiting on it.
_waiters: dict[int, set[asyncio.Event]] = {}


def wake(account_ids: list[int]) -> int:
    """Tell these accounts' waiting terminals that something has changed.

    Called from the master's own heartbeat, which is itself event-driven, so
    the chain from a fill on the master to a command leaving for a slave has no
    timer in it anywhere.
    """
    woken = 0
    for account_id in account_ids:
        for event in _waiters.get(account_id, ()):
            if not event.is_set():
                event.set()
                woken += 1
    return woken


async def wait_for_work(account_id: int, timeout: float) -> bool:
    """Hold this terminal's request until there is work, or until it is time to
    let it reconnect. True if it was woken, False if it timed out.

    The timeout is not a poll interval in disguise: nothing is planned on it
    and no work waits for it. It exists because a connection held open for ever
    is a connection nobody notices has died -- an idle proxy, a dropped route,
    a laptop that closed. Coming back every half minute proves the path still
    works.
    """
    event = asyncio.Event()
    _waiters.setdefault(account_id, set()).add(event)
    try:
        await asyncio.wait_for(event.wait(), timeout)
        return True
    except (TimeoutError, asyncio.TimeoutError):
        return False
    finally:
        waiting = _waiters.get(account_id)
        if waiting is not None:
            waiting.discard(event)
            if not waiting:
                _waiters.pop(account_id, None)


def waiting_count(account_id: int | None = None) -> int:
    """How many terminals are being held. For tests and for the health page."""
    if account_id is not None:
        return len(_waiters.get(account_id, ()))
    return sum(len(events) for events in _waiters.values())
