# Getting your trades into TradeZulu

Three routes. They can all be used on the same journal — deals are keyed by
their MetaTrader ticket, so nothing is ever imported twice.

| Route | What you provide | Anything to install? | Recommended |
|---|---|---|---|
| [Account details](#1-account-details-recommended) | server, account number, investor password | no | ✅ |
| [Expert Advisor](#2-expert-advisor) | nothing stored | an EA in a terminal you keep running | if you would rather not store a password |
| [File import](#3-file-import) | an HTML report or CSV | no | for one-off history |

---

## Why a terminal has to exist somewhere

MetaTrader 5's client-server protocol is proprietary and undocumented. There is
no public API that takes a server name, a login and a password and hands back
your trade history — the only software that can speak to a broker's MT5 server
is MetaTrader itself, and the official Python package works by talking to a
running terminal over local IPC.

So "just use my account details" means: *something* has to run a terminal.
TradeZulu's answer is to run one for you, headless, in the `mt5-bridge`
container, so you never have to see it or keep your own PC on. That is the
whole purpose of that container.

---

## 1. Account details (recommended)

### Start the terminal container

```bash
docker compose --profile bridge up -d
docker compose logs -f mt5-bridge
```

The first boot downloads Wine's prefix, a Windows Python and the MetaTrader
installer into the `mt5-wine` volume — 5 to 15 minutes and a couple of GB.
Watch the log until it says `starting the bridge on port 8080`. Every later
start takes seconds, because the volume keeps all of it.

### Enter your account

**Settings → MetaTrader 5**, with *Account details* selected:

| Field | Where to find it |
|---|---|
| **Trade server** | In MetaTrader, *File → Open an Account* lists it, or look at the bottom-right status bar. It must match exactly, e.g. `ICMarketsSC-Live12`, `Pepperstone-Demo`. |
| **Account number** | Your login, e.g. `5000123`. |
| **Investor password** | The read-only password your broker issued alongside the master one. |

**Save account**, then **Test connection**. On success it tells you the broker,
the account and the balance it can see, and whether the login is read-only.

Then press **Sync** in the header. The first sync pulls the whole history
window (two years by default, adjustable), and from then on the journal
refreshes itself whenever you open it.

### Use the investor password

Every broker issues two passwords: the master one, which can trade, and the
investor one, which can only look. TradeZulu only ever reads, but with the
investor password that stops being a promise and becomes a property of the
account — the terminal is physically unable to place an order.

If you enter a master password anyway, the *Test connection* result says so,
because you should know.

### How the password is kept

- Encrypted with AES-GCM before it touches the database, under a key derived
  from `TZ_SECRET_KEY`.
- Never returned by any API. The form shows only whether one is stored; the
  settings endpoint does not include it at all.
- Sent only to the bridge container, over the internal compose network, when
  logging the terminal in.
- Change `TZ_SECRET_KEY` and the stored password becomes unreadable on purpose.
  TradeZulu notices and asks you to enter it again rather than silently
  carrying on.

If you would rather no password existed anywhere, use the Expert Advisor below.

### Troubleshooting

| What you see | What it means |
|---|---|
| *"The bridge container is not answering"* | It is not running, or still on its first boot. `docker compose --profile bridge up -d` then `docker compose logs -f mt5-bridge`. |
| *"Invalid account (-6)"* | Wrong number, wrong password, or a server name that does not match exactly. The server string is case- and punctuation-sensitive. |
| *"The terminal did not answer in time (-8)"* | It is still starting. Wait a minute and press *Test connection* again. |
| `no terminal to run` in the logs | Your broker ships a custom MetaTrader build the generic installer will not fetch. Set `MT5_SETUP_URL` in `.env` to their installer and recreate the container. |
| Connects, but no trades appear | The history window may predate your trades. Raise *History to pull on a full sync*, then Sync again. |
| A broker dialog seems to be blocking login | Set `MT5_ENABLE_VNC=1`, publish port 5900 on `mt5-bridge`, and connect with a VNC viewer to answer it once. |

### What it costs to run

Roughly 1.5–2 GB of RAM and a couple of GB of disk while running, and almost no
CPU between syncs. On the 12-thread Xeon this is nothing, but it is worth a
`deploy.resources.limits` block if the VM is tight — see
[deployment.md](deployment.md).

---

## 2. Expert Advisor

The alternative when you would rather not store a password anywhere. Your
broker credentials never leave MetaTrader; the terminal calls TradeZulu with an
API key instead. The cost is that a terminal has to be running on a machine of
yours.

1. In MetaTrader: **File → Open Data Folder**, copy `mt5/TradeZuluSync.mq5`
   into `MQL5\Experts\`.
2. Open it in MetaEditor and compile with **F7**.
3. **Tools → Options → Expert Advisors** → tick *Allow WebRequest for listed
   URL* and add your journal's origin (scheme, host and port; no path):

   ```text
   https://journal.example.com
   ```

4. Drag **TradeZuluSync** onto any chart. Set `ServerUrl` to
   `https://journal.example.com/api` and `ApiKey` to your `TZ_INGEST_TOKEN`.
5. Make sure **Algo Trading** is enabled. The chart shows a status block.

Switch *Settings → MetaTrader 5* to **Expert Advisor** so the UI stops looking
for the bridge.

### A note on stop losses, for both routes

R multiples are only as good as the stop, and MetaTrader stores the stop on the
*order*. A stop attached after entry — dragged onto the chart, or trailed —
never reaches the deal history at all.

- **The Expert Advisor** solves this: it snapshots each position's stop the
  first time it sees it and keeps it in `MQL5\Files\`, so the real risk is
  recorded even when the order carried none. This is the one genuine advantage
  it has over account-details sync.
- **Account-details sync** sees only what the broker recorded. Where no stop
  exists, TradeZulu falls back to the rule in *Settings → Risk*, and you can
  type the real stop into any trade to recompute its R.

If you always set your stop on the entry order, the two are equivalent.

---

## 3. File import

For history from before you set anything up.

**From MetaTrader:** *Toolbox → History* → right-click → **Report** → save as
**HTML**. Then *Settings → MetaTrader 5 → Import a file* and drop it in.
TradeZulu reads the report's *Positions* table, which is already trade-level.

**From a CSV:** any file with at least a symbol, an open time and a price.
Column names are matched loosely, so all of these work:

```text
Symbol, Type, Volume, Open Time, Open Price, Close Time, Close Price, S/L, T/P, Profit, Commission
instrument; side; lots; opentime; entry; exittime; exit; pnl
symbol,type,open time,price,profit,tags,notes
```

`tags` may be comma- or pipe-separated and creates tags that do not exist yet.

Imported trades carry no contract specifications, so TradeZulu recovers the
value-per-point from the realised result and the price distance travelled —
which means R multiples still work on imported history.

Re-importing the same file updates the existing trades rather than duplicating
them, and never overwrites notes, tags, ratings or manual stop overrides.

---

## Rebuilding after the fact

*Settings → MetaTrader 5 → Maintenance* has two safe buttons:

- **Rebuild trades from stored deals** re-groups the raw deals into trades.
- **Recompute all statistics** re-derives risk, R and outcomes using the
  current settings.

Neither touches anything you typed: notes, tags, ratings, manual stops, targets
and risk overrides all survive.
