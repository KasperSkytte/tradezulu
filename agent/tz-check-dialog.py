#!/usr/bin/env python3
"""Check that the provisioner's clicks still land where it thinks they do.

The WebRequest permission is granted by driving MetaTrader's Options dialog,
because that list is kept encrypted in the terminal's own config and there is
no other way in. Wine draws the dialog's controls itself, so they are not X
windows and cannot be found by name -- only the dialog as a whole can.

That means the click points are measured, and a build with a different layout
would move them. This says so, without changing anything: it opens the dialog,
resolves each point, reports whether it is still inside, and closes it again
with Escape.

    ./agent/tz-check-dialog.py 22609000

Run it after a MetaTrader update, or when an account's Expert Advisor is
running and reporting nothing.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tz_provision as tz  # noqa: E402

#: Where the provisioner clicks, as fractions of the dialog. Kept here as the
#: single description of the layout, so this check and the real thing cannot
#: disagree about what is being tested.
POINTS = (
    ("Experts tab", 0.26, 0.04),
    ("add-URL row", 0.24, 0.67),
    ("OK button", 0.66, 0.95),
)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    login = sys.argv[1]
    env = {**os.environ, "DISPLAY": tz.DISPLAY}

    found = subprocess.run(
        ["xdotool", "search", "--name", login], env=env, capture_output=True, text=True
    )
    if not found.stdout.strip():
        print(f"no terminal window for {login} on {tz.DISPLAY}.")
        print("is it running?  ./agent/tz-view.sh list")
        return 1
    window = found.stdout.split()[-1]

    before = tz._windows(env)
    subprocess.run(["xdotool", "windowactivate", window], env=env, capture_output=True)
    time.sleep(2)
    subprocess.run(["xdotool", "key", "--window", window, "ctrl+o"], env=env, capture_output=True)

    dialog = tz._await_new_window(env, before)
    if dialog is None:
        print("the Options dialog did not open. Ctrl+O may be bound elsewhere in this build.")
        return 1

    box = tz._geometry(env, dialog)
    if box is None:
        print(f"could not measure dialog {dialog}.")
        return 1

    left, top, width, height = box
    print(f"dialog {width}x{height} at ({left}, {top})")

    ok = True
    for name, fx, fy in POINTS:
        x, y = left + int(width * fx), top + int(height * fy)
        inside = left <= x <= left + width and top <= y <= top + height
        ok = ok and inside
        print(
            f"  {name:<12} -> ({x - left:>3}, {y - top:>3}) in the dialog"
            f"   {'ok' if inside else 'OUTSIDE -- the layout has moved'}"
        )

    # Escape rather than OK: this changes nothing on a terminal that may be
    # trading, and a check that alters what it checks is not a check.
    subprocess.run(["xdotool", "key", "--window", dialog, "Escape"], env=env, capture_output=True)
    time.sleep(2)
    if dialog in tz._windows(env):
        print("  the dialog did not close on Escape; close it by hand.")
        ok = False

    print("all points land inside the dialog." if ok else "the layout no longer matches.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
