#!/usr/bin/env bash
# Move a TradeZulu install from terminals on the host to terminals in
# containers.
#
# Earlier versions ran MetaTrader on the host: Bottles and its Soda Wine build,
# one Wine prefix per account (tz-<id>, from tz-template-<broker>), virtual
# displays from :77 up, and the tradezulu-agent service driving it all. This
# removes that, so the orchestrator can take over. Run it once, then
# ./install.sh.
#
# Your journal is not touched: not the database, not .env, not the site's
# container. Nothing about the accounts is lost either -- their credentials are
# in the journal, and the new terminal containers log in from there. What goes
# is only what the host terminals kept for themselves.
#
#   sudo ./migrate-from-host.sh --dry-run        # print what would happen
#   sudo ./migrate-from-host.sh                  # remove the host terminals
#   sudo ./migrate-from-host.sh --purge-wine     # ...and Bottles/Soda, if no
#                                                #    other bottle uses them
#   sudo ./migrate-from-host.sh --purge-packages # ...and xvfb, xdotool, x11vnc,
#                                                #    openbox, x11-utils
#
# Which account owned the terminals is read from the service file; pass
# --user <name> if that file is already gone.
#
# Only bottles named tz-<id> and tz-template-* are ever removed. Any other
# MetaTrader install in Bottles is yours and is left alone.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="/etc/systemd/system/tradezulu-agent.service"
RUN_USER=""
RUN_HOME=""
PURGE_WINE=0
PURGE_PACKAGES=0
DRY_RUN=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-wine)     PURGE_WINE=1; shift ;;
    --purge-packages) PURGE_PACKAGES=1; shift ;;
    --user)           RUN_USER="$2"; shift 2 ;;
    --dry-run|-n)     DRY_RUN=1; shift ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    -h|--help)        sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say()  { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }
# What was done, said only when it was: a dry run has already said "would run".
did()  { [ "${DRY_RUN}" -eq 1 ] || say "$@"; }
run()  {
  if [ "${DRY_RUN}" -eq 1 ]; then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

if [ "$(id -u)" -ne 0 ] && [ "${DRY_RUN}" -eq 0 ]; then
  die "run this with sudo: it removes a system service and another user's files"
fi

# Whose home the terminals are in. The service file records what install.sh
# used; prefer it over guessing, because looking in the wrong home finds
# nothing and reports success.
if [ -z "${RUN_USER}" ] && [ -r "${SERVICE}" ]; then
  RUN_USER="$(sed -n 's/^User=//p' "${SERVICE}" | head -1)"
  RUN_HOME="$(sed -n 's/^Environment=HOME=//p' "${SERVICE}" | head -1)"
fi
if [ -z "${RUN_USER}" ]; then
  RUN_USER="${SUDO_USER:-$(id -un)}"
fi
if [ -z "${RUN_HOME}" ]; then
  RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
  [ -d "${HERE}/.home" ] && RUN_HOME="${HERE}/.home"
fi
BOTTLES="${RUN_HOME}/.var/app/com.usebottles.bottles/data/bottles"
SODA_DIR="$(find "${BOTTLES}/runners" -maxdepth 1 -name 'soda-*' -type d 2>/dev/null | sort | tail -1)"

# Only ever these two shapes: a plain tz* glob would match a bottle someone
# happened to name "tzsomething".
mapfile -t TZ_PREFIXES < <(
  find "${BOTTLES}/bottles" -maxdepth 1 -mindepth 1 -type d \
    \( -name 'tz-template-*' -o -regex '.*/tz-[0-9]+' \) 2>/dev/null | sort
)
mapfile -t OTHER_PREFIXES < <(
  find "${BOTTLES}/bottles" -maxdepth 1 -mindepth 1 -type d 2>/dev/null \
    | grep -vE '/tz-(template-.*|[0-9]+)$' | sort || true
)

step "What this will do"
say "terminals owned by                      ${RUN_USER} (${RUN_HOME})"
say "remove the tradezulu-agent service      $([ -e "${SERVICE}" ] && echo yes || echo '(not installed)')"
say "stop and delete the host terminals      ${#TZ_PREFIXES[@]} prefix(es)"
for p in "${TZ_PREFIXES[@]}"; do [ -n "${p}" ] && say "    - $(basename "${p}")"; done
say "remove Bottles and Soda                 $([ "${PURGE_WINE}" -eq 1 ] && echo yes || echo 'no (kept)')"
say "remove xvfb, xdotool, x11vnc, ...       $([ "${PURGE_PACKAGES}" -eq 1 ] && echo yes || echo 'no (kept)')"
say "your journal, .env and the site         kept, untouched"
if [ "${#OTHER_PREFIXES[@]}" -gt 0 ] && [ -n "${OTHER_PREFIXES[0]:-}" ]; then
  say ""
  say "left alone (not TradeZulu's):"
  for p in "${OTHER_PREFIXES[@]}"; do say "    - $(basename "${p}")"; done
fi

if [ "${DRY_RUN}" -eq 0 ] && [ "${ASSUME_YES}" -eq 0 ]; then
  echo
  printf 'Continue? [y/N] '
  read -r reply
  case "${reply}" in [yY]*) ;; *) echo "aborted"; exit 1 ;; esac
fi

step "Stopping the host provisioner"
if [ -e "${SERVICE}" ]; then
  # First, or it starts every terminal stopped below straight back up.
  run systemctl disable --now tradezulu-agent.service || true
  run rm -f "${SERVICE}"
  run systemctl daemon-reload
  did "removed"
else
  say "not installed"
fi

step "Stopping the host terminals"
# Everything attached to a prefix, not only terminal64.exe: each launch is a
# chain of flatpak sandboxes around a shell, plus a wineserver. The terminal
# and wineserver carry WINEPREFIX in their environment; the sandbox wrappers
# have it on their command line instead. Both are matched, quoted exactly so
# that tz-1 never catches tz-11.
prefix_pids() {
  local prefix="$1" entry pid
  for entry in /proc/[0-9]*; do
    pid="${entry#/proc/}"
    [ -r "/proc/${pid}/environ" ] || continue
    if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${prefix}"; then
      echo "${pid}"
    elif tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null | grep -qF "WINEPREFIX=\"${prefix}\""; then
      echo "${pid}"
    fi
  done
}
signal_prefixes() {
  local sig="$1" p pid found
  for p in "${TZ_PREFIXES[@]}"; do
    [ -n "${p}" ] || continue
    found=0
    for pid in $(prefix_pids "${p}"); do
      found=$((found + 1))
      run kill "-${sig}" "${pid}" 2>/dev/null || true
    done
    if [ "${found}" -gt 0 ]; then
      say "${sig} to ${found} process(es) in $(basename "${p}")"
    fi
  done
  return 0
}
signal_prefixes TERM
[ "${DRY_RUN}" -eq 0 ] && sleep 5
signal_prefixes KILL

# The displays the terminals drew on and the VNC servers on them: :77 upwards,
# anchored so a desktop session on :0 or somebody else's :1 is never matched.
for n in $(seq 77 99); do
  if pgrep -f "x11vnc -display :${n}\b" >/dev/null 2>&1; then
    run pkill -f "x11vnc -display :${n}\b" || true
  fi
  if pgrep -f "Xvfb :${n}\b" >/dev/null 2>&1; then
    run pkill -f "Xvfb :${n}\b" || true
  fi
done

step "Removing the host terminals"
for p in "${TZ_PREFIXES[@]}"; do
  [ -n "${p}" ] || continue
  run rm -rf "${p}"
  did "removed $(basename "${p}")"
done
# What the provisioner remembered about each terminal; meaningless without them.
run rm -rf "${BOTTLES}/.tz-state" "${BOTTLES}/.tz-last-maintenance"

if [ "${PURGE_WINE}" -eq 1 ]; then
  step "Removing Bottles and Soda"
  if [ "${#OTHER_PREFIXES[@]}" -gt 0 ] && [ -n "${OTHER_PREFIXES[0]:-}" ]; then
    say "NOT removing: ${#OTHER_PREFIXES[@]} other bottle(s) still use it. Delete them first if you mean it."
  else
    if [ -n "${SODA_DIR}" ]; then
      run rm -rf "${SODA_DIR}"
      did "removed $(basename "${SODA_DIR}")"
    fi
    if command -v flatpak >/dev/null 2>&1 && flatpak info com.usebottles.bottles >/dev/null 2>&1; then
      run flatpak uninstall -y --noninteractive --delete-data com.usebottles.bottles || true
      did "removed the Bottles runtime"
    fi
    run rm -rf "${RUN_HOME}/.var/app/com.usebottles.bottles"
  fi
fi

if [ "${PURGE_PACKAGES}" -eq 1 ]; then
  step "Removing the host terminals' packages"
  # flatpak and curl stay: too likely to be something else's.
  run apt-get remove -y -qq xvfb xdotool x11-utils openbox x11vnc || true
fi

step "Done"
if [ "${DRY_RUN}" -eq 1 ]; then
  say "This was a dry run. Nothing changed."
else
  say "The host terminals are gone. Now build the brokers you use and start the"
  say "containerised stack; every account reconnects by itself:"
  say ""
  say "  ./install.sh --brokers vantage,falcon"
fi
