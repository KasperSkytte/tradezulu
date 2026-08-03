#!/usr/bin/env bash
# Look at the terminals TradeZulu is running.
#
# They live on a virtual display so they never appear on anyone's screen, which
# is right until something goes wrong and you need to see what MetaTrader is
# actually showing -- a login that failed, a dialog waiting for an answer, or an
# Expert Advisor that never attached.
#
#   ./tz-view.sh list             # which terminals are up, and their windows
#   ./tz-view.sh shot             # a PNG of the whole display
#   ./tz-view.sh shot 22609000    # just that account's window
#   ./tz-view.sh watch            # a live view over VNC, with the SSH command
#
# The display is :77 unless TZ_DISPLAY says otherwise, matching the
# provisioner. Nothing here changes anything -- it only reads the screen -- so
# it is safe to run against terminals that are trading.
#
set -euo pipefail

DISPLAY_ID="${TZ_DISPLAY:-:77}"
PORT="${TZ_VNC_PORT:-5977}"
OUT_DIR="${TZ_SHOT_DIR:-${TMPDIR:-/tmp}}"

# USER is not set under systemd, cron or docker exec, and this runs under all
# three. It is only ever used to spell out a command to copy and paste.
WHO="${USER:-$(id -un)}"
HOSTNAME_FQDN="$(hostname -f 2>/dev/null || hostname)"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is not installed. ${2:-apt install $1}"
}

# Everything below reads the display, so fail early and clearly if there is not
# one -- "no windows found" would otherwise look like "no terminals running".
check_display() {
  need xdotool
  if [ "${DISPLAY_ID#:}" != "${DISPLAY_ID}" ] \
     && [ ! -e "/tmp/.X11-unix/X${DISPLAY_ID#:}" ]; then
    die "no display at ${DISPLAY_ID}. Is the provisioner running? (systemctl status tradezulu-agent)"
  fi
  DISPLAY="${DISPLAY_ID}" xdotool getdisplaygeometry >/dev/null 2>&1 \
    || die "cannot read ${DISPLAY_ID}. If it belongs to another user, run this as them."
}

# MetaTrader puts the account number and server in the title bar, which is the
# only thing tying a window to an account -- Wine reports every terminal under
# the same executable path, so the process list cannot say which is which.
windows() {
  DISPLAY="${DISPLAY_ID}" xdotool search --name '.' 2>/dev/null || true
}

# Wine gives every process an input-method window or two of its own. They are
# invisible, they are not terminals, and listing them made a display with one
# account on it look like a display with eight things on it.
is_noise() {
  case "$1" in
    ''|'openbox'|'Desktop'|'Default IME'|'Input'|'MSCTFIME UI'|'winex11'*) return 0 ;;
    *) return 1 ;;
  esac
}

# The terminal itself, not the stub that starts it. Wine launches MetaTrader
# through `start.exe /exec terminal64.exe`, which names the terminal in its own
# command line and can outlive a launch that failed.
is_terminal_pid() {
  local argv0
  argv0="$(tr '\0' '\n' < "/proc/$1/cmdline" 2>/dev/null | head -1)"
  case "${argv0##*[\\/]}" in
    terminal64.exe|Terminal64.exe) return 0 ;;
    *) return 1 ;;
  esac
}

cmd_list() {
  check_display
  say "display ${DISPLAY_ID} ($(DISPLAY="${DISPLAY_ID}" xdotool getdisplaygeometry | tr ' ' 'x'))"
  say ""

  local found=0 id name
  local -a titles=()
  for id in $(windows); do
    name="$(DISPLAY="${DISPLAY_ID}" xdotool getwindowname "$id" 2>/dev/null || true)"
    is_noise "${name}" && continue
    found=1
    # MetaTrader titles its main window "<login> - <server>: ...". Only those
    # say which account a window belongs to; everything else it opens -- the
    # updater, a message box -- is one per terminal and would otherwise look
    # like two terminals on one account.
    case "${name}" in
      [0-9]*\ -\ *) titles+=("${name%% *}") ;;
    esac
    printf '  %-12s %s\n' "$id" "$name"
  done
  [ "${found}" -eq 1 ] || say "  no terminal windows yet."

  # Two windows for one login are two terminals logged into the same account.
  # That is worth shouting about rather than leaving to be counted: both run
  # the Expert Advisor, so both act on every command the copier sends, and an
  # order gets placed twice.
  local dupes
  dupes="$(printf '%s\n' "${titles[@]:-}" | sort | uniq -d)"
  if [ -n "${dupes}" ]; then
    say ""
    say "WARNING: more than one terminal is logged into the same account:"
    printf '  account %s\n' "${dupes}"
    say "  Each of them runs the Expert Advisor, so a copied order is placed twice."
    say "  Clear it up with:  agent/tz_provision.py --reset all"
  fi

  say ""
  say "terminals running, by prefix:"
  local pid prefix any=0 hidden=0
  for pid in $(pgrep -f 'terminal64\.exe' 2>/dev/null || true); do
    is_terminal_pid "${pid}" || continue
    if [ ! -r "/proc/${pid}/environ" ]; then
      hidden=$((hidden + 1))
      continue
    fi
    prefix="$(tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | sed -n 's/^WINEPREFIX=//p')"
    [ -n "${prefix}" ] || continue
    any=1
    printf '  pid %-8s %s\n' "$pid" "$(basename "${prefix}")"
  done

  # Which account a terminal belongs to is only readable from its environment,
  # and only by the user running it. Saying "none" when the answer is really
  # "not yours to read" sent this looking for a problem that was not there.
  if [ "${hidden}" -gt 0 ]; then
    say "  ${hidden} terminal(s) belong to another user and cannot be inspected from here."
    say "  Run this as the user the provisioner runs as:"
    say "    sudo -u \$(sed -n 's/^User=//p' /etc/systemd/system/tradezulu-agent.service) $0 list"
  elif [ "${any}" -eq 0 ]; then
    say "  none."
  fi
}

cmd_shot() {
  check_display
  need import "apt install imagemagick"

  local match="${1:-}" target="root" label="display" id name
  if [ -n "${match}" ]; then
    for id in $(windows); do
      name="$(DISPLAY="${DISPLAY_ID}" xdotool getwindowname "$id" 2>/dev/null || true)"
      case "${name}" in
        *"${match}"*) target="$id"; label="${match}"; break ;;
      esac
    done
    [ "${target}" != "root" ] || die "no window matching '${match}'. Try: $0 list"
  fi

  local file
  file="${OUT_DIR}/tz-${label//[^A-Za-z0-9._-]/_}-$(date +%H%M%S).png"
  DISPLAY="${DISPLAY_ID}" import -window "${target}" "${file}"
  say "wrote ${file}"
  say "copy it back with:  scp ${WHO}@${HOSTNAME_FQDN}:${file} ."
}

cmd_watch() {
  check_display
  need x11vnc "apt install x11vnc"

  say "Serving ${DISPLAY_ID} on localhost:${PORT}."
  say ""
  say "From your own machine, in another shell:"
  say "  ssh -N -L ${PORT}:localhost:${PORT} ${WHO}@${HOSTNAME_FQDN}"
  say "then point a VNC viewer at localhost:${PORT}."
  say ""
  say "Ctrl-C here when you are done."
  say ""
  # -localhost so this is only reachable through the SSH tunnel: the display
  # holds logged-in trading terminals and x11vnc has no authentication worth
  # the name. -viewonly because nothing here should be clicking on them.
  exec x11vnc -display "${DISPLAY_ID}" -localhost -rfbport "${PORT}" \
    -viewonly -shared -forever -nopw -quiet
}

case "${1:-list}" in
  list)         cmd_list ;;
  shot)         shift; cmd_shot "${1:-}" ;;
  watch|vnc)    cmd_watch ;;
  -h|--help)    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)            die "unknown command: $1 (try: list, shot, watch)" ;;
esac
