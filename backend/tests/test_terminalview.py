"""Where the web interface connects to watch a terminal."""

from app.services.terminalview import viewer_target


def test_no_screen_until_the_orchestrator_says_where_it_is():
    assert viewer_target({}) is None
    assert viewer_target(None) is None
    # Half an address is no address.
    assert viewer_target({"vnc_port": 5900}) is None
    assert viewer_target({"vnc_host": "tradezulu-terminal-3"}) is None


def test_a_terminal_is_reached_by_its_container_name():
    state = {"vnc_port": 5900, "vnc_host": "tradezulu-terminal-3"}
    assert viewer_target(state) == ("tradezulu-terminal-3", 5900)
