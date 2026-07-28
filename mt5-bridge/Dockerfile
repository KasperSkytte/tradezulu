# MetaTrader 5 running headless under Wine, with a small read-only HTTP bridge
# in front of it. This is what lets TradeZulu sync from nothing but a trade
# server, an account number and an investor password.
#
# MetaQuotes does not permit redistributing the terminal, so it is downloaded
# on first boot into the /wine volume and reused from then on.

FROM debian:bookworm-slim

ARG WINE_VERSION=10.0.0.0~bookworm-1

ENV DEBIAN_FRONTEND=noninteractive \
    WINEPREFIX=/wine \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    # Stop Wine prompting to install Mono and Gecko; MetaTrader needs neither.
    WINEDLLOVERRIDES="mscoree,mshtml=" \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    BRIDGE_PORT=8080

# Wine 10.0 specifically, and the pin is load-bearing:
#
#   * Debian's 8.0 installs MetaTrader fine but cannot run it -- terminal64.exe
#     imports bcryptprimitives.dll, which Wine only grew in 9.x, so it dies at
#     load time with status c0000135 and no visible error.
#   * WineHQ's current 11.0 runs the terminal perfectly but its *installer*
#     hangs for ever on a pipe read, having downloaded nothing.
#
# 10.0 is the one version verified to do both. Check both halves before
# moving it: install from scratch, and confirm the terminal stays up.
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    mkdir -pm755 /etc/apt/keyrings && \
    curl -fsSL -o /etc/apt/keyrings/winehq-archive.key \
        https://dl.winehq.org/wine-builds/winehq.key && \
    curl -fsSL -o /etc/apt/sources.list.d/winehq-bookworm.sources \
        https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources && \
    apt-get update && \
    apt-get install -y --install-recommends \
        "winehq-stable=${WINE_VERSION}" \
        "wine-stable=${WINE_VERSION}" \
        "wine-stable-amd64=${WINE_VERSION}" \
        "wine-stable-i386:i386=${WINE_VERSION}" && \
    apt-get install -y --no-install-recommends \
        cabextract \
        procps \
        unzip \
        winbind \
        x11vnc \
        xauth \
        xvfb \
    && apt-get purge -y gnupg && apt-get install -y --no-install-recommends curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# winbind supplies ntlm_auth, which Wine shells out to for NTLM. Without it
# anything behind an authenticating proxy hangs rather than failing, and the
# symptom looks nothing like the cause. cabextract lets Wine unpack the
# cabinets some installers ship.

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY bridge.py pool.py worker.py /opt/bridge/
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME ["/wine"]
# 8080 is the bridge API. 5900 is an optional VNC view of the terminal, only
# started with ENABLE_VNC=1 and useful when a broker wants a dialog answered.
EXPOSE 8080 5900

# First boot downloads Wine's prefix, a Windows Python and MetaTrader, so the
# grace period is generous.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15m --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
