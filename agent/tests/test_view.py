"""What tz-view.sh picks, tested without an X server in sight.

The script's one hard problem is saying which window it means. Every terminal
is stacked in the same place on the display, and X11 hands out the pixels that
are on the screen rather than the window's own -- so for a while, asking for
one account and asking for the other produced the same picture, of whichever
terminal happened to be on top. Nothing about that needs a real display to
test: xdotool answers the questions, and a stub can answer them just as well.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

VIEW = Path(__file__).resolve().parents[1] / "tz-view.sh"

# What the stubbed display holds: two terminals logged into two accounts, one
# message box belonging to the first, and the input-method windows Wine opens
# for every process. The dialog comes first, so a script that takes the first
# title it matches takes the wrong one.
WINDOWS = {
    "100": "Default IME",
    "200": "Order -- 22609000",
    "300": "22609000 - Vantage International: Demo Account",
    "400": "25736691 - Vantage International: Demo Account",
}

XDOTOOL = """\
#!/bin/sh
# A display that answers back, without being one.
log="$STUB_LOG"
case "$1" in
  getdisplaygeometry) echo "1400 1000" ;;
  search)             printf '%s\\n' {ids} ;;
  getwindowname)      case "$2" in {names} esac ;;
  windowraise)        echo "raise $2" >> "$log" ;;
  *)                  echo "$*" >> "$log" ;;
esac
"""

IMPORT = """\
#!/bin/sh
# import -window <id> <file>
echo "import $2" >> "$STUB_LOG"
: > "$3"
"""

X11VNC = """\
#!/bin/sh
echo "x11vnc $*" >> "$STUB_LOG"
"""


@pytest.fixture
def run(tmp_path):
    """Run the script against a stubbed display, and read back what it did."""
    stub = tmp_path / "bin"
    stub.mkdir()
    names = " ".join(f'{i}) echo "{n}" ;;' for i, n in WINDOWS.items())
    write = {
        "xdotool": XDOTOOL.format(ids=" ".join(WINDOWS), names=names),
        "import": IMPORT,
        "x11vnc": X11VNC,
    }
    for name, body in write.items():
        path = stub / name
        path.write_text(textwrap.dedent(body))
        path.chmod(0o755)

    log = tmp_path / "log"
    log.touch()

    def go(*args: str) -> tuple[subprocess.CompletedProcess, list[str]]:
        env = {
            **os.environ,
            "PATH": f"{stub}:{os.environ['PATH']}",
            "STUB_LOG": str(log),
            # Not a :N display, so the script does not look for its socket.
            "TZ_DISPLAY": "127.0.0.1:77",
            "TZ_SHOT_DIR": str(tmp_path),
            "TZ_RAISE_WAIT": "0",
        }
        done = subprocess.run(
            ["bash", str(VIEW), *args], env=env, capture_output=True, text=True
        )
        return done, log.read_text().split("\n")[:-1]

    return go


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
class TestPicking:
    def test_each_account_gets_its_own_window(self, run):
        first, _ = run("shot", "22609000")
        second, _ = run("shot", "25736691")
        assert "window 300:" in first.stdout
        assert "window 400:" in second.stdout

    def test_the_window_is_raised_before_it_is_photographed(self, run):
        """The bug itself: an overlapped window photographs as what is above
        it, so the picture has to be taken of a window that is on top."""
        _, log = run("shot", "22609000")
        assert log == ["raise 300", "import 300"]

    def test_the_terminal_wins_over_its_dialogs(self, run):
        """Both windows have the login in the title, and the message box is
        found first; the terminal is the one worth looking at."""
        done, _ = run("shot", "22609000")
        assert "Vantage International" in done.stdout
        assert "Order --" not in done.stdout

    def test_the_whole_display_disturbs_nothing(self, run):
        done, log = run("shot")
        assert log == ["import root"]
        assert done.returncode == 0

    def test_an_account_with_no_window_is_an_error(self, run):
        done, log = run("shot", "99999999")
        assert done.returncode == 1
        assert "no window matching" in done.stderr
        assert log == []

    def test_front_raises_and_says_which(self, run):
        done, log = run("front", "25736691")
        assert log == ["raise 400"]
        assert "25736691 - Vantage" in done.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
class TestWatch:
    def test_a_viewer_cannot_touch_anything_by_default(self, run):
        _, log = run("watch")
        assert "-viewonly" in log[-1]

    def test_control_hands_over_the_mouse(self, run):
        done, log = run("watch", "--control")
        assert "-viewonly" not in log[-1]
        assert "mouse and keyboard are live" in done.stdout

    def test_watch_can_start_on_a_chosen_terminal(self, run):
        _, log = run("watch", "--control", "22609000")
        assert log[0] == "raise 300"

    def test_it_stays_behind_the_ssh_tunnel(self, run):
        for args in (["watch"], ["watch", "--control"]):
            _, log = run(*args)
            assert "-localhost" in log[-1]
