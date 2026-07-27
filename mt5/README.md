# TradeZuluSync

An Expert Advisor that feeds your TradeZulu journal.

**You probably do not need this.** TradeZulu's default is to sync with just a
trade server, an account number and an investor password — see
[`../docs/metatrader.md`](../docs/metatrader.md). Use this instead when you
would rather no password were stored anywhere, and you already keep a terminal
running.

It reads deal history and, optionally, candles, and POSTs them to your journal.
It never places, modifies or closes an order — there is no trading code in it at
all.

## Install

1. MetaTrader 5 → **File → Open Data Folder**, then copy `TradeZuluSync.mq5`
   into `MQL5\Experts\`.
2. Open it in MetaEditor and press **F7** to compile.
3. **Tools → Options → Expert Advisors** → tick *Allow WebRequest for listed
   URL* and add your journal's origin, e.g. `https://journal.example.com`
   (scheme, host and port only — no path).
4. Drag **TradeZuluSync** onto any chart and fill in `ServerUrl` and `ApiKey`.
5. Make sure **Algo Trading** is on.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `ServerUrl` | — | Journal API base, ending in `/api` |
| `ApiKey` | — | Your `TZ_INGEST_TOKEN` |
| `RequestTimeoutMs` | 15000 | WebRequest timeout |
| `SyncIntervalSeconds` | 60 | How often to check for new deals |
| `FirstSyncHistoryDays` | 730 | How far back the first sync reaches |
| `DealsPerRequest` | 300 | Deals per HTTP request |
| `SyncOnTrade` | true | Also sync the moment a deal is added |
| `UploadCandles` | true | Send candles so trades can be replayed offline |
| `CandleTimeframe` | M15 | Which timeframe to upload |
| `CandlesBefore` / `CandlesAfter` | 150 / 80 | Bars around the trade |
| `Verbose` | true | Log every request to the Experts tab |

## Why leave it running

MetaTrader stores the stop loss on the *order*. A stop attached after entry —
dragged onto the chart, or trailed — never reaches the deal history, so a
journal reading history alone cannot know what you risked.

While it runs, the EA snapshots each position's stop and target the first time
it sees them, keeps them in `MQL5\Files\TradeZulu_stops_<login>.csv` so they
survive restarts, and attaches them to the entry deal when the position closes.
That is what makes the R multiples real.

## Full guide

See [`../docs/metatrader.md`](../docs/metatrader.md), including troubleshooting
and the two alternative import routes.
