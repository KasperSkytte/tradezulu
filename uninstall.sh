#!/usr/bin/env bash
# Undo what install.sh did.
#
# By default this removes the software and leaves your trades alone: the
# journal's Docker volume, and the .env that can decrypt the MetaTrader
# passwords stored in it. Data is only deleted if you ask for it.
#
#   ./uninstall.sh                 # remove the stack and terminals, keep the journal
#   ./uninstall.sh --dry-run       # print what would happen, change nothing
#   ./uninstall.sh --purge-images  # also remove the terminal images
#   ./uninstall.sh --purge-data    # also delete the journal and its secrets
#   ./uninstall.sh --all           # all of the above
#
# The terminals' own volumes always go with them. They hold nothing that is
# not in the journal already: a reinstall logs every account in again from the
# credentials stored there.
#
# Only containers and volumes labelled as this stack's are touched. Anything
# else on this machine, Docker or otherwise, is left alone.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURGE_DATA=0
PURGE_IMAGES=0
DRY_RUN=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-data)   PURGE_DATA=1; shift ;;
    --purge-images) PURGE_IMAGES=1; shift ;;
    --all)          PURGE_DATA=1; PURGE_IMAGES=1; shift ;;
    --dry-run|-n)   DRY_RUN=1; shift ;;
    --yes|-y)       ASSUME_YES=1; shift ;;
    -h|--help)      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say()  { printf '    %s\n' "$*"; }
run()  {
  if [ "${DRY_RUN}" -eq 1 ]; then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

command -v docker >/dev/null 2>&1 || { echo "docker is not installed; nothing to do"; exit 0; }
DOCKER=(docker)
if ! docker info >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  DOCKER=(sudo docker)
fi
COMPOSE=("${DOCKER[@]}" compose --project-directory "${HERE}" -f "${HERE}/docker-compose.yml")

# The stack's label value, as the orchestrator was given it.
STACK="tradezulu"
if [ -f "${HERE}/.env" ]; then
  STACK="$(sed -n 's/^TZ_STACK=//p' "${HERE}/.env" | tail -1)"
  STACK="${STACK:-tradezulu}"
fi
PROJECT="$(basename "${HERE}")"
if [ -f "${HERE}/.env" ]; then
  PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "${HERE}/.env" | tail -1)"
  PROJECT="${PROJECT:-$(basename "${HERE}")}"
fi
TERMINALS="label=tz.role=terminal"
mapfile -t CONTAINERS < <("${DOCKER[@]}" ps -a --filter "${TERMINALS}" --filter "label=tz.stack=${STACK}" --format '{{.Names}}' 2>/dev/null)
mapfile -t VOLUMES < <("${DOCKER[@]}" volume ls --filter "${TERMINALS}" --filter "label=tz.stack=${STACK}" --format '{{.Name}}' 2>/dev/null)
mapfile -t IMAGES < <("${DOCKER[@]}" images --filter "${TERMINALS}" --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -v '<none>' || true)

step "What this will do"
say "stop the orchestrator and the site      containers, network, app images"
say "remove terminal containers and data     ${#CONTAINERS[@]} container(s), ${#VOLUMES[@]} volume(s)"
for c in "${CONTAINERS[@]}"; do [ -n "${c}" ] && say "    - ${c}"; done
say "remove terminal images                  $([ "${PURGE_IMAGES}" -eq 1 ] && echo "yes, ${#IMAGES[@]}" || echo 'no (kept)')"
say "delete the journal and .env             $([ "${PURGE_DATA}" -eq 1 ] && echo 'YES -- your trade history' || echo 'no (kept)')"

if [ "${DRY_RUN}" -eq 0 ] && [ "${ASSUME_YES}" -eq 0 ]; then
  echo
  if [ "${PURGE_DATA}" -eq 1 ]; then
    printf 'This deletes your trade history and cannot be undone. Type DELETE to confirm: '
    read -r reply
    [ "${reply}" = "DELETE" ] || { echo "aborted"; exit 1; }
  else
    printf 'Continue? [y/N] '
    read -r reply
    case "${reply}" in [yY]*) ;; *) echo "aborted"; exit 1 ;; esac
  fi
fi

step "Stopping the orchestrator"
# First, or it starts every terminal removed below straight back up.
run "${COMPOSE[@]}" stop orchestrator || true

step "Removing terminals"
for c in "${CONTAINERS[@]}"; do
  [ -n "${c}" ] || continue
  if [ "${DRY_RUN}" -eq 1 ]; then
    say "would stop and remove ${c}"
    continue
  fi
  # A minute to close MetaTrader cleanly; it is being removed, but a terminal
  # killed mid-write is a terminal whose last log says nothing useful.
  "${DOCKER[@]}" stop -t 60 "${c}" >/dev/null || true
  "${DOCKER[@]}" rm -f "${c}" >/dev/null || true
  say "removed ${c}"
done
for v in "${VOLUMES[@]}"; do
  [ -n "${v}" ] || continue
  if [ "${DRY_RUN}" -eq 1 ]; then
    say "would remove volume ${v}"
  elif "${DOCKER[@]}" volume rm "${v}" >/dev/null; then
    say "removed volume ${v}"
  fi
done

step "Removing the stack"
if [ "${PURGE_DATA}" -eq 1 ]; then
  run "${COMPOSE[@]}" down --volumes --rmi all --remove-orphans || true
else
  run "${COMPOSE[@]}" down --rmi all --remove-orphans || true
fi

if [ "${PURGE_IMAGES}" -eq 1 ]; then
  step "Removing terminal images"
  for i in "${IMAGES[@]}"; do
    [ -n "${i}" ] || continue
    if [ "${DRY_RUN}" -eq 1 ]; then
      say "would remove ${i}"
    elif "${DOCKER[@]}" rmi "${i}" >/dev/null; then
      say "removed ${i}"
    fi
  done
  [ "${DRY_RUN}" -eq 1 ] || "${DOCKER[@]}" image prune -f >/dev/null
fi

if [ "${PURGE_DATA}" -eq 1 ]; then
  step "Removing the journal's secrets"
  # .env holds TZ_SECRET_KEY, without which the stored MetaTrader passwords in
  # a surviving database cannot be decrypted. It goes with the data, never
  # separately.
  run rm -f "${HERE}/.env"
  run rm -rf "${HERE}/data"
fi

step "Done"
if [ "${DRY_RUN}" -eq 1 ]; then
  say "This was a dry run. Nothing changed."
elif [ "${PURGE_DATA}" -eq 1 ]; then
  say "TradeZulu and its data are gone."
else
  say "TradeZulu is uninstalled. Your journal is still here:"
  say "  ${HERE}/.env         the key that decrypts it"
  say "  docker volume       ${PROJECT}_tradezulu-data"
  say "Run ./install.sh to bring it back; your accounts reconnect by themselves."
fi
