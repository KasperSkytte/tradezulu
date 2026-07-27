# MetaTrader 5 running headless under Wine, with a small read-only HTTP bridge
# in front of it. This is what lets TradeZulu sync from nothing but a trade
# server, an account number and an investor password.
#
# MetaQuotes does not permit redistributing the terminal, so it is downloaded
# on first boot into the /wine volume and reused from then on.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    WINEPREFIX=/wine \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    # Stop Wine prompting to install Mono and Gecko; MetaTrader needs neither.
    WINEDLLOVERRIDES="mscoree,mshtml=" \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    BRIDGE_PORT=8080

# Debian's own Wine is 8.0, which current MetaTrader builds start on and then
# exit from silently. WineHQ's package is the one that actually runs it.
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg && \
    mkdir -pm755 /etc/apt/keyrings && \
    curl -fsSL -o /etc/apt/keyrings/winehq-archive.key \
        https://dl.winehq.org/wine-builds/winehq.key && \
    curl -fsSL -o /etc/apt/sources.list.d/winehq-bookworm.sources \
        https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources && \
    apt-get update && \
    apt-get install -y --install-recommends winehq-stable && \
    apt-get install -y --no-install-recommends \
        procps \
        unzip \
        x11vnc \
        xauth \
        xvfb \
    && apt-get purge -y gnupg && apt-get install -y --no-install-recommends curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY bridge.py /opt/bridge/bridge.py
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
