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
DISPLAY_NUM="${TZ_DISPLAY:-:77}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ -e "${PREFIX}/.tz-template-ready" ] || die \
  "no template for '${BROKER}' -- run make-template.sh ${BROKER} first"
command -v xdotool >/dev/null 2>&1 || die "xdotool is not installed (apt install xdotool)"

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

say "starting the template terminal"
flatpak run --command=sh com.usebottles.bottles -c "
  export WINEPREFIX='${PREFIX}' WINEDEBUG=-all DISPLAY=${DISPLAY_NUM}
  unset PYTHONPATH PYTHONHOME
  cd '${TERMINAL_DIR}'
  exec '${RUNNER}/bin/wine' terminal64.exe /portable
" >/dev/null 2>&1 &

for _ in $(seq 1 40); do
  sleep 3
  W="$(DISPLAY="${DISPLAY_NUM}" xdotool search --name 'MetaTrader\|Terminal' 2>/dev/null | tail -1 || true)"
  [ -n "${W}" ] && break
done
[ -n "${W}" ] || die "the terminal never opened a window on ${DISPLAY_NUM}"
sleep 15

export DISPLAY="${DISPLAY_NUM}"
say "opening options"
xdotool windowactivate "${W}"; sleep 2
xdotool key --window "${W}" ctrl+o; sleep 6

eval "$(xdotool search --name '^Options$' getwindowgeometry --shell 2>/dev/null)"
[ -n "${X:-}" ] || die "the Options dialog did not open"
say "options dialog at ${X},${Y}"

# Everything below is positioned relative to the dialog rather than the screen.
# The dialog is a different size in every broker's build, so absolute
# coordinates work on the terminal they were measured on and nowhere else.
xdotool mousemove $((X + 161)) $((Y - 4))   click 1; sleep 3   # Experts tab
xdotool mousemove $((X + 38))  $((Y + 40))  click 1; sleep 1   # allow algo trading
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
