"""Watching a MetaTrader terminal from the web interface.

Every terminal runs in a container of its own, on a virtual screen nobody has
a monitor for, with a VNC server on that screen. This is the plumbing that puts
the same picture on a page.

Two rules shape it:

* **One screen per account.** Each terminal container has exactly one display
  and one VNC server, so a viewer is attached to exactly one account. Nothing
  here has to filter windows, and no bug in it can show somebody another
  account's open positions, because the pixels are not on that screen in the
  first place.

* **Reachable from the site and from nowhere else.** The VNC server listens
  inside the terminal's container, which is on TradeZulu's own Docker network
  and publishes no ports. The site reaches it by the container's name; nothing
  outside that network can.
"""

from __future__ import annotations


def viewer_target(terminal_state: dict | None) -> tuple[str, int] | None:
    """Where to connect for this account's screen, if it has one yet.

    Both halves come from the orchestrator rather than from arithmetic here:
    it is what started the container and knows what it is called, and an
    address worked out independently in two places is one that eventually
    disagrees.
    """
    state = terminal_state or {}
    port = state.get("vnc_port")
    host = str(state.get("vnc_host") or "")
    if not port or not host:
        return None
    return host, int(port)
