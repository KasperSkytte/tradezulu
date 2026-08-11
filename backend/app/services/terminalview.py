"""Watching a MetaTrader terminal from the web interface.

The terminals run on the host, on virtual displays nobody has a screen for,
and looking at one used to mean an SSH tunnel, a VNC viewer and knowing which
of several stacked windows belonged to which account. This is the plumbing
that puts the same picture on a page instead.

Two rules shape it:

* **One display per account.** The provisioner gives every terminal a screen
  of its own and one VNC server on it, so a viewer is attached to exactly one
  account. Nothing here has to filter windows, and no bug in it can show
  somebody another account's open positions, because the pixels are not on
  that screen in the first place.

* **Reachable from the site and from nowhere else.** The site runs in a
  container and the terminals do not, so the VNC servers bind to the host end
  of the container's own bridge -- an address that exists for exactly this
  crossing. Not localhost, which the container cannot reach, and not 0.0.0.0,
  which would put a logged-in trading terminal on the office network.
"""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: Where the kernel lists this container's routes.
ROUTES = Path("/proc/net/route")


def bridge_address() -> str:
    """The host address this container reaches its default gateway on.

    Read from the routing table rather than guessed: Compose puts each project
    on its own bridge, so the address is 172.17.0.1 on one machine, 172.18.0.1
    on another, and hard-coding either is a viewer that works on one install
    and not the next.

    Empty when there is no gateway to find -- the site running outside a
    container, on the same host as the terminals -- and the provisioner then
    serves them on loopback, which is the right answer for that arrangement.
    """
    try:
        lines = ROUTES.read_text().splitlines()[1:]
    except OSError:
        return ""

    for line in lines:
        fields = line.split()
        # iface, destination, gateway, flags... Destination 0 is the default
        # route, and its gateway is the host end of the bridge.
        if len(fields) < 3 or fields[1] != "00000000":
            continue
        try:
            packed = int(fields[2], 16).to_bytes(4, "little")
            return str(ipaddress.IPv4Address(packed))
        except (ValueError, ipaddress.AddressValueError):
            continue
    return ""


def viewer_target(terminal_state: dict | None) -> tuple[str, int] | None:
    """Where to connect for this account's screen, if it has one yet.

    The port comes from the provisioner rather than from arithmetic here. It
    is the one that reported starting the server, it knows which display it
    put the terminal on, and a port worked out independently in two places is
    a port that eventually disagrees.
    """
    state = terminal_state or {}
    port = state.get("vnc_port")
    if not port:
        return None
    host = bridge_address() or "127.0.0.1"
    return host, int(port)
