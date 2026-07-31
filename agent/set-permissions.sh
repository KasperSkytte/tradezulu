#!/usr/bin/env bash
# Grant a template terminal the two permissions its Expert Advisor needs.
#
# MetaTrader keeps both of these encrypted inside its own configuration, so
# there is no file to write and no switch to pass -- the dialog is the only
# way in. This drives it.
#
# Doing it on the *template* is what makes it a one-off. Every account is a
# copy of the template, and a copy is byte for byte the same installation, so
# the settings come with it. Nobody adding an account ever sees this.
#
# Both permissions matter, and neither fails loudly:
#
#   Allow algorithmic trading   -- without it the expert never runs.
#   Allow WebRequest for URL    -- without it every report is refused, which
#                                  looks exactly like the server being down.
#
#   ./set-permissions.sh vantage
#
set -euo pipefail

BROKER="${1:-default}"
URL="${2:-http://127.0.0.1:8420}"
BOTTLES="${HOME}/.var/app/com.usebottles.bottles/data/bottles"
PREFIX="${BOTTLES}/bottles/tz-template-${BROKER}"

# This runs on its own display rather than the one the account terminals use.
# Every MetaTrader window is called some variation of "MetaTrader", and asking
# X which one belongs to which process does not reliably work through Wine --
# so on a shared display, picking the right window is a guess. It guessed
# wrong once here and configured a live account's terminal instead of the
# template, reporting success either way. A display with exactly one terminal
# on it cannot be ambiguous.
DISPLAY_NUM="${TZ_DISPLAY:-}"
OWN_DISPLAY=0

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ -e "${PREFIX}/.tz-template-ready" ] || die \
  "no template for '${BROKER}' -- run make-template.sh ${BROKER} first"

# These are checkboxes, and this ticks them blindly because it cannot read
# their state. Running twice would therefore turn them back off, quietly
# undoing the thing the script exists to do.
if [ -e "${PREFIX}/.tz-permissions-set" ] && [ "${FORCE:-0}" != "1" ]; then
  say "permissions were already set for '${BROKER}'; nothing to do"
  say "(FORCE=1 to run it again -- only useful if you have reset the template)"
  exit 0
fi

command -v xdotool  >/dev/null 2>&1 || die "xdotool is not installed (apt install xdotool)"
command -v xwininfo >/dev/null 2>&1 || die "xwininfo is not installed (apt install x11-utils)"

RUNNER="$(find "${BOTTLES}/runners" -maxdepth 1 -name 'soda-*' | sort | tail -1)"
[ -n "${RUNNER}" ] || die "no Soda runner under ${BOTTLES}/runners"
TERMINAL="$(find "${PREFIX}/drive_c" -name terminal64.exe -print -quit)"
TERMINAL_DIR="$(dirname "${TERMINAL}")"

# The same trick the provisioner uses: WINEPREFIX in a process's environment is
# the only reliable way to tell one account's terminal from another's, because
# Wine reports them all under the same Windows path.
terminal_pids() {
  local pid
  for pid in $(pgrep -f 'terminal64\.exe' 2>/dev/null); do
    [ -r "/proc/${pid}/environ" ] || continue
    if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${PREFIX}"; then
      printf '%s\n' "${pid}"
    fi
  done
}

if [ -z "${DISPLAY_NUM}" ]; then
  command -v Xvfb >/dev/null 2>&1 || die "Xvfb is not installed (apt install xvfb)"
  for n in 91 92 93 94 95; do
    [ -e "/tmp/.X11-unix/X${n}" ] && continue
    DISPLAY_NUM=":${n}"; break
  done
  [ -n "${DISPLAY_NUM}" ] || die "could not find a free display"
  say "using a private display ${DISPLAY_NUM}"
  Xvfb "${DISPLAY_NUM}" -ac -screen 0 1400x1000x24 >/dev/null 2>&1 &
  XVFB_PID=$!
  OWN_DISPLAY=1
  sleep 3
  command -v openbox >/dev/null 2>&1 && DISPLAY="${DISPLAY_NUM}" openbox >/dev/null 2>&1 &
  sleep 2
  cleanup() {
    [ "${OWN_DISPLAY}" -eq 1 ] && kill "${XVFB_PID}" 2>/dev/null || true
  }
  trap cleanup EXIT
else
  say "using the display at ${DISPLAY_NUM} (given)"
fi

say "starting the template terminal"
flatpak run --command=sh com.usebottles.bottles -c "
  export WINEPREFIX='${PREFIX}' WINEDEBUG=-all DISPLAY=${DISPLAY_NUM}
  unset PYTHONPATH PYTHONHOME
  cd '${TERMINAL_DIR}'
  exec '${RUNNER}/bin/wine' terminal64.exe /portable
" >/dev/null 2>&1 &

export DISPLAY="${DISPLAY_NUM}"

# Windows have to be found by geometry rather than by name. MetaTrader's
# dialogs carry no title that X can see -- the new-account wizard that blocks
# everything is nameless -- so anything searching by name simply does not find
# them and concludes the screen is clear. What is reliable is the list of
# viewable children of the root window and how big each one is.
viewable_windows() {
  local id info w h x y
  for id in $(xwininfo -root -children 2>/dev/null | awk '/^     0x/ {print $1}'); do
    info="$(xwininfo -id "${id}" 2>/dev/null)" || continue
    echo "${info}" | grep -q IsViewable || continue
    w="$(echo "${info}" | awk '/Width:/ {print $2}')"
    h="$(echo "${info}" | awk '/Height:/ {print $2}')"
    x="$(echo "${info}" | awk '/Absolute upper-left X:/ {print $4}')"
    y="$(echo "${info}" | awk '/Absolute upper-left Y:/ {print $4}')"
    # Ignore the one-pixel helper windows Wine litters the display with.
    [ "${w:-0}" -gt 200 ] && [ "${h:-0}" -gt 150 ] || continue
    printf '%s %s %s %s %s\n' "$((id))" "${w}" "${h}" "${x}" "${y}"
  done
}

say "waiting for the terminal"
MAIN=""
for _ in $(seq 1 40); do
  sleep 3
  [ -n "$(terminal_pids)" ] || continue
  # The terminal fills the screen; every dialog is smaller. That is the whole
  # distinction, and it holds regardless of what anything is called.
  MAIN="$(viewable_windows | sort -k2 -rn | head -1 | awk '{print $1}')"
  [ -n "${MAIN}" ] && break
done
[ -n "${MAIN}" ] || die "the terminal never opened a window on ${DISPLAY_NUM}"
say "terminal window ${MAIN}"
sleep 15

# Getting to Options is a race against a terminal that is still waking up. It
# accepts keystrokes well before it will open a menu, and on the way it puts
# up whatever it feels like -- the new-account wizard, a LiveUpdate notice.
# Those are application modal, so nothing opens behind them.
#
# They also cannot be dismissed with Escape, which they ignore, and they never
# take input focus, so a keystroke aimed at "the active window" lands on the
# terminal instead. What does work is clicking their dismissive button, and in
# every one of these dialogs that is the bottom-right one: Cancel on the
# wizard, Later on the update notice.
dismiss_dialogs() {
  local id w h x y closed=0
  while read -r id w h x y; do
    [ "${id}" = "${MAIN}" ] && continue
    say "  dismissing a dialog (${w}x${h})"
    xdotool mousemove $((x + w - 56)) $((y + h - 25)) click 1
    closed=1
    sleep 4
  done <<EOF
$(viewable_windows)
EOF
  return $((1 - closed))
}

say "opening options"
O=""
for attempt in $(seq 1 12); do
  dismiss_dialogs || true

  xdotool windowactivate "${MAIN}" 2>/dev/null || true; sleep 2
  xdotool key ctrl+o; sleep 5

  O="$(xdotool search --name '^Options$' 2>/dev/null | tail -1 || true)"
  [ -n "${O}" ] && break
  say "  not up yet (attempt ${attempt})"
  sleep 5
done
[ -n "${O}" ] || die "the Options dialog never opened"

# The dialog is resizable and remembers whatever size it was last left at, so
# there is no layout to measure against until one is imposed. Pinning it to
# the size a fresh install opens with is what lets the offsets below be fixed
# numbers instead of guesses, and it makes a terminal someone has already
# resized behave the same as a new one.
xdotool windowsize "${O}" 620 389; sleep 2
eval "$(xdotool getwindowgeometry --shell "${O}")"
[ -n "${X:-}" ] || die "could not read the Options dialog geometry"
say "options pinned at ${X},${Y} ${WIDTH}x${HEIGHT}"

# Offsets are from the dialog's own origin, measured at 620x389 and verified
# on both the Vantage and the generic MetaQuotes build.
xdotool mousemove $((X + 161)) $((Y - 4))   click 1; sleep 3   # Experts tab
xdotool mousemove $((X + 38))  $((Y + 40))  click 1; sleep 1   # allow algo trading

# Every "disable algorithmic trading when..." option comes off. The first of
# them is why a freshly provisioned terminal logs in perfectly and then does
# nothing: a template belongs to no account, so the first login *is* an
# account change, and MetaTrader answers it by switching algorithmic trading
# back off -- silently, seconds after everything looked fine. The others are
# the same trap waiting for a profile or chart change later.
#
# They only become clickable once algorithmic trading above is enabled. The
# last two are already off on a fresh install; they are ticked here anyway so
# this does not depend on a default staying what it is today.
xdotool mousemove $((X + 49))  $((Y + 65))  click 1; sleep 1   # not on account change
xdotool mousemove $((X + 49))  $((Y + 90))  click 1; sleep 1   # not on profile change
say "  (chart and Python-API options are off by default; flags are also"
say "   written directly by the provisioner, so this cannot drift)"

xdotool mousemove $((X + 38))  $((Y + 187)) click 1; sleep 1   # allow WebRequest
xdotool mousemove $((X + 160)) $((Y + 216)) click --repeat 2 1; sleep 2
xdotool type --delay 60 "${URL}"; sleep 1
xdotool key Return; sleep 2
xdotool mousemove $((X + 410)) $((Y + 350)) click 1; sleep 3   # OK
say "permissions set"

# MetaTrader writes its configuration when it exits and not before, so closing
# it politely is the entire point of this step. Killing it here would throw
# away exactly what was just set.
say "closing the terminal so it saves"
for pid in $(terminal_pids); do kill -TERM "${pid}" 2>/dev/null || true; done
for _ in $(seq 1 20); do
  [ -z "$(terminal_pids)" ] && break
  sleep 2
done
if [ -n "$(terminal_pids)" ]; then
  say "it did not exit on its own; forcing it (settings may not have saved)"
  for pid in $(terminal_pids); do kill -KILL "${pid}" 2>/dev/null || true; done
fi

touch "${PREFIX}/.tz-permissions-set"
say "done -- every account cloned from this template inherits it"
