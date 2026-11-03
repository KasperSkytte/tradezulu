#!/bin/sh
# Compile the Expert Advisor with this image's own MetaEditor. Build time only.
#
# MetaTrader refuses an .ex5 built by a newer MetaEditor than itself, so it is
# built here, against exactly the terminal it will run in, and the build fails
# if it does not come out.
set -eu

T=/opt/tz/mt5
mkdir -p "${T}/MQL5/Experts"
cp /opt/tz/ea/TradeZuluCopier.mq5 "${T}/MQL5/Experts/"
rm -f "${T}/MQL5/Experts/TradeZuluCopier.ex5"

Xvfb :1 -ac -screen 0 1400x1000x24 >/dev/null 2>&1 &
sleep 2
cd "${T}"
wine MetaEditor64.exe '/compile:MQL5\Experts\TradeZuluCopier.mq5' '/log:MQL5\Experts\compile.log' >/dev/null 2>&1 &

for _ in $(seq 1 120); do
  [ -s "${T}/MQL5/Experts/TradeZuluCopier.ex5" ] && break
  sleep 1
done
sleep 2
wineserver -k || true

if [ ! -s "${T}/MQL5/Experts/TradeZuluCopier.ex5" ]; then
  echo "error: MetaEditor did not produce TradeZuluCopier.ex5" >&2
  [ -f "${T}/MQL5/Experts/compile.log" ] && iconv -f utf-16le -t utf-8 "${T}/MQL5/Experts/compile.log" >&2 || true
  exit 1
fi
cp "${T}/MQL5/Experts/TradeZuluCopier.ex5" /opt/tz/ea/
rm -rf "${T}/logs" "${T}/MQL5/Logs"
echo "compiled TradeZuluCopier.ex5"
