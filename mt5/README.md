# TradeZuluCopier

One Expert Advisor doing both halves of the job:

- **Copying** — reports the account's open positions, is told what to do about
  them, and carries it out. Every decision is the server's; this only executes.
- **The journal** — sends closed deals as they happen, with the stop the broker
  recorded, which is what every R figure is calculated from.

## You do not need to install this

`install.sh` creates a MetaTrader terminal per account and puts this in it,
compiled, with the server URL and token already filled in. Adding an account in
the web interface is the whole procedure — see
[`../docs/metatrader.md`](../docs/metatrader.md).

What follows is only for running it in a terminal of your own: on a Windows
machine, say, or one you would rather manage yourself.

## By hand

1. MetaTrader 5 → **File → Open Data Folder**, then copy `TradeZuluCopier.mq5`
   into `MQL5\Experts\`.
2. Open it in MetaEditor and press **F7** to compile.
3. **Tools → Options → Expert Advisors**:
   - tick **Allow algorithmic trading**
   - untick every **Disable algorithmic trading when…** option. The first of
     them switches trading off the moment the terminal logs in, which looks
     exactly like the EA silently doing nothing.
   - tick **Allow WebRequest for listed URL** and add your journal's origin,
     e.g. `https://journal.example.com` — scheme, host and port only, no path.
4. Drag **TradeZuluCopier** onto any chart and fill in `ServerUrl` and `ApiKey`.

The chart's symbol and timeframe do not matter; it is not reading the chart.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `ServerUrl` | — | TradeZulu's API base, ending in `/api` |
| `ApiKey` | — | Your `TZ_INGEST_TOKEN`. Without it the EA refuses to start |
| `RequestTimeoutMs` | 15000 | WebRequest timeout |
| `PollSeconds` | 2 | How often to report in; the server can ask for slower |
| `Slippage` | 20 | Maximum deviation, in points |
| `MagicNumber` | 0 | Stamped on copied orders; 0 leaves it unset |
| `SendHistory` | true | Send closed deals to the journal |
| `HistorySeconds` | 60 | How often to look for new ones |
| `FirstSyncDays` | 730 | How far back the first pass reaches |
| `DealsPerRequest` | 200 | Deals per HTTP request |
| `UploadCandles` | true | Send bars around each trade, so charts have something to draw |
| `CandleTimeframe` | M5 | The one timeframe collected; longer ones are built from it |
| `CandlesBefore` / `CandlesAfter` | 288 | Bars either side of the trade — a full day at M5 |
| `CandleBackfillDays` | 60 | How far back to fetch charts for trades already journalled |
| `Verbose` | true | Log every command to the Experts tab |

Only one timeframe is sent, because the rest are arithmetic on it: the server
folds M15, M30, H1, H4 and D1 out of the M5 bars as they are asked for. Nothing
is folded downwards — M1 cannot be recovered from M5 — so the collected
timeframe is the shortest chart anyone will see, and the journal offers only
the timeframes it can actually draw rather than buttons that come up empty.

Deals are sent from a cursor the server hands out, so a restart re-sends
nothing and a terminal that was off for a week catches up by itself. They are
keyed by ticket, so a duplicate changes nothing.

## Why leave it running

MetaTrader records the stop loss on the *order*. A stop attached after entry —
trailed, or dragged onto the chart — never reaches the deal history, so a
journal reading history alone cannot know what the trade risked.

While it runs, the EA remembers the first stop it sees on each open position
and attaches that to the entry deal when the position closes. The *first*, not
the latest: a stop trailed into profit is no longer what the trade risked, and
using it would flatter every R figure it touched.

That memory does not currently survive a restart — a position opened with no
stop, given one later, and closed after the terminal restarted will still have
no R. Stops set with the order are unaffected, as they are read back from the
order itself.

## Read-only accounts

An investor password is enough to journal an account, and means the EA cannot
place an order on it even by mistake. Copying *to* an account needs that
account's real password, which is why slave accounts stay in dry-run until you
arm them.
