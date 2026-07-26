# Getting your trades into TradeZulu

There are three routes. They can all be used on the same journal — deals are
keyed by their MetaTrader ticket, so nothing is ever imported twice.

| Route | Effort | Needs the terminal running | Recommended |
|---|---|---|---|
| [Expert Advisor pushes](#1-expert-advisor-recommended) | 5 minutes | yes | ✅ |
| [Server pulls from a bridge](#2-the-bridge-container) | an hour, a few GB | no (the container runs its own) | only if you cannot run the EA |
| [File import](#3-file-import) | one minute, manual | no | for one-off history |

---

## 1. Expert Advisor (recommended)

`mt5/TradeZuluSync.mq5` runs inside your terminal and POSTs deals to TradeZulu.
Your broker password never leaves MetaTrader, and TradeZulu never needs to be
reachable from your trading machine's network — the traffic is outbound only.

### Install

1. In MetaTrader: **File → Open Data Folder**, then copy `TradeZuluSync.mq5`
   into `MQL5\Experts\`.
2. Open it in MetaEditor (double-click) and compile with **F7**. The Errors tab
   should say `0 error(s), 0 warning(s)`.
3. **Tools → Options → Expert Advisors**: tick *Allow WebRequest for listed
   URL* and add the origin of your journal — scheme and host only, no path:

   ```
   https://journal.example.com
   ```

   For a LAN address include the port: `http://192.168.1.10:8420`.
4. In the Navigator, drag **TradeZuluSync** onto any chart (which symbol does
   not matter — it reads the whole account).
5. Set the inputs:

   | Input | Value |
   |---|---|
   | `ServerUrl` | `https://journal.example.com/api` — note the `/api` |
   | `ApiKey` | the `TZ_INGEST_TOKEN` from your `.env` |
   | `SyncIntervalSeconds` | `60` is fine; the EA is nearly free to run |
   | `FirstSyncHistoryDays` | how far back to reach on the first run |
   | `UploadCandles` | leave on so trades can be replayed offline |

6. Make sure **Algo Trading** is enabled in the toolbar. The chart will show a
   status block; the Experts tab logs each sync.

The EA never places, modifies or closes an order. It only reads history.

### What it does about stop losses

R multiples are only as good as the stop. MetaTrader stores the stop on the
*order*, so a stop you attach after entry — dragging it onto the chart, or a
trailing stop — is not in the deal history at all.

The EA therefore snapshots `POSITION_SL` and `POSITION_TP` the first time it
sees a position open, keeps them in `MQL5/Files/TradeZulu_stops_<login>.csv`,
and attaches them to the entry deal when the position closes. Two consequences:

- **Leave the EA running while you trade.** If it is only started afterwards,
  trades whose stop was attached after entry arrive without one.
- Anything still missing falls back to the rule you chose in *Settings → Risk*,
  and you can always type the real stop into the trade itself, which recomputes
  every R figure for it.

### Troubleshooting

| Symptom | Cause |
|---|---|
| `WebRequest is not allowed for …` (error 4014) | The URL is not in the Expert Advisors allow-list. Add scheme + host + port, no path. |
| `HTTP 401` | `ApiKey` does not match `TZ_INGEST_TOKEN`, or the server has none set. |
| Nothing appears, no errors | Algo Trading is off, or the EA is not attached — check for the smiley face on the chart. |
| Trades appear but with no R | No stop was recorded; see above. |
| `HTTP 404` | `ServerUrl` is missing the `/api` suffix. |

---

## 2. The bridge container

Optional, and honestly the heavy option: a headless MetaTrader 5 under Wine with
the official `MetaTrader5` Python package in front of it, so the TradeZulu
server can *pull* history on demand. Use it when the terminal cannot stay
running on your own machine.

```bash
# in .env
MT5_LOGIN=5000123
MT5_PASSWORD=your-investor-password
MT5_SERVER=YourBroker-Live

docker compose --profile bridge up -d
```

Then set *Settings → MetaTrader 5 → Server pulls (bridge)* with the bridge URL
`http://mt5-bridge:8080`. The Sync button now fetches new deals directly.

**Use the investor password**, not your real one. Most brokers issue a
read-only investor password; with it the container is physically incapable of
placing a trade.

Notes and caveats:

- The first boot downloads Wine's prefix, a Windows Python and the MetaTrader
  installer into the `mt5-wine` volume. Expect 10–20 minutes and several GB.
- MetaQuotes does not allow redistributing the terminal, so it is fetched at
  runtime rather than baked into the image.
- Some brokers ship a custom build that the generic installer will not fetch. In
  that case install your broker's terminal into the volume once by hand and
  point `MT5_TERMINAL_PATH` at it.
- This path depends on Wine behaving on your particular host, so treat it as the
  fallback it is. The Expert Advisor is both lighter and more predictable.

The bridge exposes only `GET /health`, `/account`, `/deals` and `/candles`, and
is never published outside the compose network.

---

## 3. File import

For history from before you set anything up, or if you would rather not run an
EA at all.

**From MetaTrader:** *Toolbox → History* tab → right-click → **Report** → save
as **HTML**. Then *Settings → MetaTrader 5 → Import a file* and drop it in.
TradeZulu reads the report's *Positions* table, which is already trade-level.

**From a CSV:** any file with at least a symbol, an open time and a price is
understood. Column names are matched loosely, so these all work:

```
Symbol, Type, Volume, Open Time, Open Price, Close Time, Close Price, S/L, T/P, Profit, Commission
instrument; side; lots; opentime; entry; exittime; exit; pnl
symbol,type,open time,price,profit,tags,notes
```

`tags` may be comma- or pipe-separated and creates tags that do not exist yet.

Imported trades have no per-lot contract data, so TradeZulu recovers the
value-per-point from the realised result and the price distance travelled —
which means R multiples still work on imported history.

Re-importing the same file updates the existing trades instead of duplicating
them, and never overwrites notes, tags, ratings or manual stop overrides.

---

## Rebuilding after the fact

*Settings → MetaTrader 5 → Maintenance* has two safe buttons:

- **Rebuild trades from stored deals** re-groups the raw deals into trades.
  Useful after upgrading TradeZulu.
- **Recompute all statistics** re-derives risk, R and outcomes for every trade
  using the current settings.

Neither touches anything you typed: notes, tags, ratings, manual stops, targets
and risk overrides all survive.
