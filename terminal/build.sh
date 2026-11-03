#!/usr/bin/env bash
# Build a broker's terminal image and tag it with what is in it.
#
#   terminal/build.sh vantage            # build (or reuse the cached install)
#   terminal/build.sh vantage --refresh  # run the installer again for the
#                                          broker's current MetaTrader build
#   terminal/build.sh all                # every broker in brokers.json
#
# Tags:
#   tradezulu-terminal:<broker>-<mt5 build>-wine<wine version>   e.g.
#   tradezulu-terminal:vantage-6295-wine11.0
#   tradezulu-terminal:<broker>                                  the newest
#
# The orchestrator picks, per broker, the image with the highest MetaTrader
# build, so building a newer one is how terminals are upgraded: they move to it
# at the next weekly restart, or at once when restarted from the web interface.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"
REPO="${TZ_TERMINAL_REPO:-tradezulu-terminal}"
BROKERS="${ROOT}/brokers.json"

refresh=0
targets=()
for arg in "$@"; do
  case "${arg}" in
    --refresh) refresh="$(date +%s)" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) targets+=("${arg}") ;;
  esac
done
[ "${#targets[@]}" -gt 0 ] || { sed -n '2,18p' "$0"; exit 2; }
if [ "${targets[0]}" = "all" ]; then
  mapfile -t targets < <(python3 -c 'import json,sys; print("\n".join(k for k,v in json.load(open(sys.argv[1])).items() if isinstance(v,dict)))' "${BROKERS}")
fi

field() {  # field <broker> <python expression over entry e>
  python3 - "${BROKERS}" "$1" "$2" <<'PY'
import json, sys
brokers = json.load(open(sys.argv[1]))
e = brokers.get(sys.argv[2])
if not isinstance(e, dict):
    sys.exit("unknown broker %r" % sys.argv[2])
e.setdefault("installer", brokers["default"]["installer"])
e.setdefault("wine", brokers["default"]["wine"])
print(eval(sys.argv[3], {"e": e}))
PY
}

for broker in "${targets[@]}"; do
  installer="$(field "${broker}" 'e["installer"]')"
  wine_branch="$(field "${broker}" 'e["wine"]["branch"]')"
  wine_version="$(field "${broker}" 'e["wine"]["version"]')"
  wine_short="${wine_version%%~*}"
  wine_short="${wine_short%.0.0}"            # 11.0.0.0 -> 11.0
  scratch="${REPO}:build-${broker}"

  args=(-f "${HERE}/Dockerfile"
        --build-arg "BROKER=${broker}" --build-arg "INSTALLER=${installer}"
        --build-arg "WINE_BRANCH=${wine_branch}" --build-arg "WINE_VERSION=${wine_version}"
        --build-arg "WINE_LABEL=${wine_short}" --build-arg "REFRESH=${refresh}")

  echo "== ${broker}: wine ${wine_branch} ${wine_short}"
  docker build "${args[@]}" -t "${scratch}" "${ROOT}"
  build="$(docker run --rm --entrypoint cat "${scratch}" /opt/tz/mt5-build)"
  tag="${REPO}:${broker}-${build}-wine${wine_short}"

  # Same build again with the build number as a label: every layer but the
  # label's is cached, so this takes a second.
  docker build "${args[@]}" --build-arg "MT5_BUILD=${build}" -t "${tag}" -t "${REPO}:${broker}" "${ROOT}" >/dev/null
  docker rmi "${scratch}" >/dev/null
  echo "== ${broker}: ${tag}"
done

# Superseded layers from earlier builds of the same tags.
docker image prune -f >/dev/null
