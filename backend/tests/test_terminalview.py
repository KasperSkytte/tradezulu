"""Where the web interface connects to watch a terminal."""

from app.services import terminalview
from app.services.terminalview import viewer_target


def test_no_port_means_nothing_to_watch():
    assert viewer_target({}) is None
    assert viewer_target(None) is None
    assert viewer_target({"vnc_host": "tradezulu-terminal-3"}) is None


def test_a_terminal_container_is_reached_by_its_own_name(monkeypatch):
    # The bridge is where the host provisioner served screens. A terminal in a
    # container names itself, and that has to win over the bridge.
    monkeypatch.setattr(terminalview, "bridge_address", lambda: "172.18.0.1")
    state = {"vnc_port": 5900, "vnc_host": "tradezulu-terminal-3"}
    assert viewer_target(state) == ("tradezulu-terminal-3", 5900)


def test_a_host_terminal_is_on_the_far_end_of_the_bridge(monkeypatch):
    monkeypatch.setattr(terminalview, "bridge_address", lambda: "172.18.0.1")
    assert viewer_target({"vnc_port": 5979}) == ("172.18.0.1", 5979)
    assert viewer_target({"vnc_port": 5979, "vnc_host": ""}) == ("172.18.0.1", 5979)


def test_outside_a_container_it_is_loopback(monkeypatch):
    monkeypatch.setattr(terminalview, "bridge_address", lambda: "")
    assert viewer_target({"vnc_port": 5979}) == ("127.0.0.1", 5979)
