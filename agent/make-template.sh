#!/usr/bin/env bash
# Build a template prefix with one broker's MetaTrader installed.
#
# Every account TradeZulu provisions is a copy of one of these. Installing
# MetaTrader takes minutes and can fail halfway; copying a prefix that is known
# good takes seconds and cannot half-work. So the install happens once, here,
# and never again on a running system.
#
# A template is deliberately not logged in to anything. It carries the broker's
# terminal and server list and no credentials, so it is safe to copy for any
# number of accounts.
#
#   ./make-template.sh            # the generic MetaQuotes terminal
#   ./make-template.sh vantage    # Vantage Markets
#
set -euo pipefail

BROKER="${1:-default}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTTLES="${HOME}/.var/app/com.usebottles.bottles/data/bottles"
PREFIX="${BOTTLES}/bottles/tz-template-${BROKER}"
DISPLAY_NUM="${TZ_DISPLAY:-:77}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

INSTALLER="$(python3 - "$HERE/brokers.json" "$BROKER" <<'PY'
import json, sys
brokers = json.load(open(sys.argv[1]))
entry = brokers.get(sys.argv[2])
if not isinstance(entry, dict):
    known = [k for k, v in brokers.items() if isinstance(v, dict)]
    sys.exit("unknown broker {!r}; known: {}".format(sys.argv[2], ", ".join(known)))
print(entry["installer"])
PY
)" || die "$INSTALLER"

say "broker    : ${BROKER}"
say "installer : ${INSTALLER}"
say "prefix    : ${PREFIX}"

if [ -e "${PREFIX}/.tz-template-ready" ]; then
  say "already built; delete the prefix to rebuild"
  exit 0
fi

RUNNER="$(ls -d "${BOTTLES}"/runners/soda-* 2>/dev/null | tail -1 || true)"
[ -n "${RUNNER}" ] || die "no Soda runner under ${BOTTLES}/runners -- run install.sh first"

# MetaTrader will not install without a screen, but it must not be given the
# operator's: a template build should never throw windows in front of whoever
# is using the machine.
#
# A display of the form host:N belongs to someone else -- another machine, or a
# container -- so it is used as given and never started here. Only a plain :N
# is ours to bring up, and its socket says whether it is already running
# without needing any X client installed to ask.
case "${DISPLAY_NUM}" in
  :*)
    if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
      command -v Xvfb >/dev/null 2>&1 || die \
        "no display at ${DISPLAY_NUM} and Xvfb is not installed (apt install xvfb)"
      say "starting virtual display ${DISPLAY_NUM}"
      Xvfb "${DISPLAY_NUM}" -ac -screen 0 1400x1000x24 >/dev/null 2>&1 &
      sleep 3
      command -v openbox >/dev/null 2>&1 && DISPLAY="${DISPLAY_NUM}" openbox >/dev/null 2>&1 &
      sleep 2
    fi
    ;;
  *) say "using the display at ${DISPLAY_NUM}" ;;
esac

mkdir -p "${PREFIX}/drive_c"
SETUP="${PREFIX}/drive_c/setup.exe"

say "downloading installer"
curl -fL --retry 3 --max-time 900 -o "${SETUP}" "${INSTALLER}"

say "installing (this takes a few minutes)"
flatpak run --command=sh com.usebottles.bottles -c "
  export WINEPREFIX='${PREFIX}' WINEDEBUG=-all DISPLAY=${DISPLAY_NUM}
  export WINEDLLOVERRIDES='mscoree,mshtml='
  unset PYTHONPATH PYTHONHOME
  # /auto is MetaTrader's unattended install. Without it the installer waits
  # on a wizard nobody is there to click through.
  '${RUNNER}/bin/wine' '${SETUP}' /auto >/dev/null 2>&1 &
  # The installer launches the terminal when it finishes, so waiting for
  # terminal64.exe to exist is the signal that the install completed. Polling
  # for the file beats a fixed timeout: a slow machine just takes longer
  # rather than producing a half-installed prefix.
  for i in \$(seq 1 90); do
    if find '${PREFIX}/drive_c' -name terminal64.exe -print -quit 2>/dev/null | grep -q .; then
      break
    fi
    sleep 10
  done
  sleep 20
" || true

TERMINAL="$(find "${PREFIX}/drive_c" -name terminal64.exe -print -quit 2>/dev/null || true)"
[ -n "${TERMINAL}" ] || die "installer did not produce terminal64.exe -- see ${PREFIX}"

say "installed: ${TERMINAL#${PREFIX}/}"

# The installer starts the terminal; a template must not have one running or
# the copy would capture its lock files and half-written config.
#
# Wine reports every terminal under the same Windows path, so the command line
# cannot say which prefix a process belongs to and matching on it would kill
# terminals that are trading. The environment can: WINEPREFIX is per process.
kill_terminals() {
  local signal="$1" pid found=""
  for pid in $(pgrep -x terminal64.exe 2>/dev/null; pgrep -f 'terminal64\.exe' 2>/dev/null); do
    [ -r "/proc/${pid}/environ" ] || continue
    if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${PREFIX}"; then
      kill "${signal}" "${pid}" 2>/dev/null && found="yes"
    fi
  done
  [ -n "${found}" ]
}
kill_terminals -TERM && sleep 5 || true
kill_terminals -KILL || true

rm -f "${SETUP}"
touch "${PREFIX}/.tz-template-ready"
say "template ready: $(du -sh "${PREFIX}" | cut -f1)"
say ""
say "One thing remains, and it has to be done once per template:"
say "allow algorithmic trading and add TradeZulu to the WebRequest list."
say "MetaTrader keeps both encrypted in its own config, so they can only be"
say "set through its dialog -- but a clone inherits them, so doing it here"
say "means no account ever needs it:"
say ""
say "  ./agent/set-permissions.sh ${BROKER}"
