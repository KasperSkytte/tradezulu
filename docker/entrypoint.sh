#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${TZ_DATA_DIR:-/data}"
PORT="${PORT:-8420}"
WORKERS="${TZ_WORKERS:-1}"
APP_USER="tradezulu"

# A fresh named volume inherits the image's ownership, but a bind mount from
# the host does not. Fix it while we are still root, then drop privileges.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "${DATA_DIR}"
  chown -R "${APP_USER}:${APP_USER}" "${DATA_DIR}" 2>/dev/null || true

  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u "${APP_USER}" -- "$0" "$@"
  elif command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid="${APP_USER}" --regid="${APP_USER}" --init-groups -- "$0" "$@"
  elif command -v su >/dev/null 2>&1; then
    exec su -s /bin/bash "${APP_USER}" -c "$(printf '%q ' "$0" "$@")"
  else
    echo "entrypoint: no way to drop privileges found; continuing as root." >&2
  fi
fi

case "${1:-serve}" in
  serve)
    # SQLite plus a single-user journal: one worker is the right shape, and it
    # keeps the in-process login throttle meaningful.
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${PORT}" \
      --workers "${WORKERS}" \
      --proxy-headers \
      --forwarded-allow-ips '*' \
      --no-server-header
    ;;
  demo)
    export TZ_DEMO=1
    exec "$0" serve
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
