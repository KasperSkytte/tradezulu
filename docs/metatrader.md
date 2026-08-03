# Getting your trades into TradeZulu

Two routes, and for almost everyone the first is the only one worth reading.
Both can be used on the same journal — deals are keyed by their MetaTrader
ticket, so nothing is imported twice.

| Route | What you provide | Anything to install? |
|---|---|---|
| [Account details](#account-details) | server, account number, investor password | no |
| [File import](#file-import) | an HTML report or CSV | no |

---

## Why a terminal has to exist somewhere

MetaTrader 5's client-server protocol is proprietary and undocumented. There is
no public API that takes a server name, a login and a password and hands back
your trade history — the only software that can speak to a broker's MT5 server
is MetaTrader itself.

So "just use my account details" means *something* has to run a terminal.
TradeZulu runs one for you, out of sight, on the same machine as the site. It
is a normal MetaTrader install rather than a container, which is deliberate and
is the subject of the [last section](#why-not-a-container).

---

## Account details

**Settings → MetaTrader 5**:

| Field | Example |
|---|---|
| Trade server | `ICMarketsSC-Live12` |
| Account number | `5000123` |
| Investor password | the read-only one your broker issued |

Save, and within a minute or so a terminal exists for that account — logged in,
with TradeZulu's Expert Advisor attached and reporting back. There is nothing
else to do.

### Use the investor password

Every broker issues two passwords. The **investor** password is read-only: it
can see the account and nothing else. Use it for the master account and
TradeZulu cannot place an order on it even by mistake.

Copying *to* an account needs that account's real password, which is why slaves
are created disabled and in dry-run, and why arming one is a separate,
deliberate step.

### How the password is kept

Encrypted in the database, never returned to the browser, and kept out of the
settings document the UI reads wholesale.

It leaves the server exactly once: the provisioner writes it into the terminal's
startup file, MetaTrader reads it at launch, and the file is rewritten without
it as soon as the terminal has connected. From then on MetaTrader keeps its own
encrypted copy and TradeZulu's is gone.

This is also why the command line is not used for it. Current MetaTrader builds
ignore `/login:` and `/password:` entirely and sit on the new-account wizard
instead, which looks exactly like a rejected password.

### What gets set up

Per broker, once:

- A **template** — one MetaTrader install, built by `agent/make-template.sh`.
  Broker-specific builds matter: the generic MetaQuotes terminal cannot resolve
  a name like `VantageMarkets-Live` at all and offers to open a new account
  instead.
- Its **permissions**, by `agent/set-permissions.sh` — algorithmic trading on,
  every "disable algorithmic trading when…" off, and TradeZulu on the WebRequest
  allowlist. MetaTrader keeps that allowlist encrypted in its own config, so it
  can only be set through the dialog. Doing it on the template means it happens
  once rather than per account.

Per account, automatically:

- The template is copied. A copy is the same installation byte for byte, so it
  inherits those permissions and no dialog is ever driven again.
- The Expert Advisor is installed, with the callback URL and token written into
  its preset. Both come from the server the provisioner is already authenticated
  to, which is why nobody is ever asked for them — and why the URL is this
  server's internal address, so putting a domain in front of the site later
  changes nothing about how its terminals reach it.

  It is compiled once, not once per account. The compiled `.ex5` is kept under
  `.tz-state/builds` and copied to every terminal that wants the same one.
  Broker branding does not affect this — a branded terminal is the same
  MetaQuotes engine with a different logo — but the terminal's *build* does:
  MetaTrader refuses bytecode produced by a newer MetaEditor than itself, and
  brokers do not all ship the same build at once. So the cache is keyed by the
  source and the build, and a terminal that has updated past its expert simply
  builds a new one.
- The terminal starts, logs in, and reports.

Which template an account gets is decided by its **server name**, not its broker
name: the server name always arrives correct because it comes from the broker,
while a demo account may report its broker as something as unhelpful as "Demo
Broker". Brokers live in [`agent/brokers.json`](../agent/brokers.json) — adding
one is a name and an installer URL.

### Weekly restart

Terminals are restarted every Sunday at 3am, and templates refreshed at the same
time.

MetaTrader downloads updates while it runs and then asks to restart to install
them. Left alone, that question sits on screen indefinitely and a terminal
waiting on it is not copying anything — so the failure would arrive on whatever
day a broker happened to ship a build. Restarting on a schedule applies updates
during the quietest hour of the week, with no dialog, because a terminal that is
already stopped installs them on the way up.

Change it with `--maintenance-day` (Monday=0) and `--maintenance-hour`, or run
one immediately:

```bash
python3 agent/tz_provision.py --maintenance-now --once
```

### When a terminal will not work

Nothing here needs a person, and none of it involves uninstalling anything.

"Running" is the weakest possible statement about a MetaTrader terminal. It can
be running while sitting on a login the broker refused, or on an update dialog,
or with an Expert Advisor whose WebRequest permission never took — all of which
look identical from outside and none of which copy a trade. So the provisioner
does not ask whether a terminal is running. It asks when that account's expert
last reached TradeZulu, and works down a ladder when the answer is "never" or
"not lately":

| | |
|---|---|
| under 5 minutes since it started | left alone; it is still logging in |
| never reported | grant the WebRequest permission, up to 3 times |
| still nothing, or it went quiet for 10 minutes | restart the terminal, twice |
| still nothing | delete the prefix and rebuild it from the template, twice |
| still nothing | stop, and log what to check by hand |

Each rung is tried only because the one before it did not help. The counts are
kept in `~/.var/app/.../data/bottles/.tz-state/<account>.json`, outside the
prefix — which matters, because a count kept inside the thing being rebuilt
cannot survive the rebuild, and a ladder that resets itself is a loop.

Silence is only acted on when the provisioner has been reaching TradeZulu
continuously. Nothing can record a poll while the site is restarting, so after
any outage every terminal looks like it has gone quiet at once, and restarting
them all on that evidence would turn a minute of downtime into an outage.

### Clearing one up by hand

```bash
python3 agent/tz_provision.py --reset 22609000    # this account's terminal
python3 agent/tz_provision.py --reset all         # every terminal
```

This stops the terminal, clears whatever is left holding its prefix, and
deletes the prefix. Nothing in TradeZulu is touched — no account, no trade, no
password — so the next provisioning cycle finds an account with no terminal and
builds a fresh one, a minute or two later. It takes account numbers, and it is
the whole of "clear it up and start over": `uninstall.sh --all` is not the tool
for a terminal that is stuck, and never was.

Forgetting an account in the web interface does the same thing on its own. Its
MetaTrader install is removed on the next cycle, because the account is no
longer one the server lists.

### Troubleshooting

```bash
sudo journalctl -u tradezulu-agent -f   # what the provisioner is doing
```

The `sudo` is not optional. It is a system service running as its own
account, and `journalctl` without privileges quietly shows you your own
journal instead of saying it cannot see that unit — so it looks like the
service is producing nothing.

The Expert Advisor writes to the terminal's own log, under `MQL5/logs/` in that
account's prefix
(`~/.var/app/com.usebottles.bottles/data/bottles/bottles/tz-<account id>/`). It
says plainly when something is wrong: an empty token, a URL that is not on the
allowlist, algorithmic trading switched off.

Those logs are UTF-16, so `grep` finds nothing in them until they are converted:

```bash
iconv -f UTF-16LE -t UTF-8 <logfile> | tail
```

---

## A note on stop losses

R multiples come from the stop the broker recorded. A trade closed manually with
no stop on it has no risk to measure, so it has no R — the journal shows the
money and leaves R blank rather than inventing a denominator.

If you move a stop to breakeven and are taken out there, that counts as a
breakeven rather than a win, and stays out of the win rate in both directions.

---

## File import

**Accounts → Manual import**. In MetaTrader: **Toolbox → History**, right-click →
**Report** → save as HTML or XLSX, then drop the file in. Plain CSV works too, as
long as it has open and close times and prices.

It sits with the accounts because that is what it is: the other way an
account's trades get here. The account number in the file decides which account
they land under, and one that is not here yet is added — as an ordinary journal
account, never as the master.

Imports are matched on the deal ticket, so importing the same statement twice
changes nothing.

## Rebuilding after the fact

Changing the risk defaults or the breakeven rule does not rewrite history by
itself. **Settings → Rebuild** re-folds every stored deal into trades using the
current rules. Notes, tags and ratings are keyed to the trade and survive it.

---

## Why not a container

TradeZulu is containerised. MetaTrader is not, and that is not an oversight.

The original design ran a headless MetaTrader in its own container and drove it
with MetaQuotes' Python package. The terminal starts and loads an account, and
`mt5.initialize()` returns an IPC timeout — the terminal accepts the connection
and never answers.

Eliminated one at a time, all failing identically: Docker networking, host
networking, seccomp and AppArmor, the clock, CA certificates, port reachability,
WineHQ 8 through 11 including staging, Python 3.9 and 3.11, 32- and 64-bit,
several versions of the Python package, generic and broker-branded terminals,
root and non-root, four display configurations, `winhttp`/`wininet`, `mt5linux`,
and two published reference projects built verbatim.

Under Wine-TkG "Soda" 9.0 the error changes to `-6 Authorization failed` — the
terminal *answering*. That is the build the provisioner uses, and it is why
Bottles is installed as a runtime rather than as an application: Soda is built
against that flatpak's libraries and does not work outside it.

So the terminal runs where it demonstrably works, and reaches TradeZulu over
plain HTTP from an Expert Advisor inside it. That is better than the original
plan regardless of Wine: the terminal talks outwards, so there is no inbound
port and no credentials in flight at request time, and a terminal on someone
else's laptop works exactly like one sitting beside the server.

The bridge container has been removed. If it is ever worth retrying, the code is
in the git history (`git log --diff-filter=D -- mt5-bridge/`) and the list above
is what not to try first.

## The WebRequest permission

An Expert Advisor may only reach a URL that is on the terminal's allowlist, and
that list is kept encrypted in MetaTrader's own config -- there is no file to
write. The only way in is the Options dialog, so the provisioner drives it.

Wine draws the dialog's controls itself, so they are not X windows and cannot
be found by name; only the dialog as a whole can. The clicks are therefore
measured, but they are measured **against the dialog**, which is located by
being the window that appeared and then read for its real geometry. Screen
coordinates were the previous approach and were wrong the moment the dialog
opened anywhere else -- on one live terminal the "OK" click landed on *Cancel*,
discarding the change, and the run reported success.

Nothing reports success on the strength of a click now. The permission counts
as granted only when that account's Expert Advisor actually reaches the server,
which the provisioner sees in the plan it already fetches. Until then it
retries, and after a few attempts it says plainly what to do by hand.

To check the layout after a MetaTrader update, or when a terminal is running
and sending nothing:

```bash
./agent/tz-check-dialog.py 22609000
```

It opens the dialog, reports whether each click still lands inside it, and
closes it with Escape — it changes nothing, so it is safe on a terminal that is
trading.

## Looking at a terminal

The terminals draw on a virtual display (`:77` by default), which is right
until something goes wrong: a login that failed, a dialog waiting for an answer,
an Expert Advisor that never attached. All of those are visible on screen and
invisible in the logs.

`agent/tz-view.sh` reads that display. It only reads it, so it is safe to run
against terminals that are trading.

```bash
./agent/tz-view.sh list             # which terminals are up, and their windows
./agent/tz-view.sh shot             # a PNG of the whole display
./agent/tz-view.sh shot 22609000    # just that account's window
./agent/tz-view.sh watch            # a live view over VNC
```

`list` is usually enough — MetaTrader puts the account number and server in the
window title, so a terminal that is logged in says so, and one still sitting at
a login prompt says that too:

```
display :77 (1400x1000)

  2097164      22609000 - VantageMarkets-Live: Read Only
  4194316      25862011 - VantageMarkets-Demo: Demo Account

terminals running, by prefix:
  pid 1805395  tz-1
  pid 1802281  tz-2
```

`shot` needs ImageMagick and `watch` needs x11vnc; neither is installed by
`install.sh`, because neither is needed to run anything — the script names the
package when you reach for it. `watch` binds to loopback only and serves
view-only, so it is reachable through an SSH tunnel and not from the network:
the display holds logged-in trading terminals, and x11vnc's own authentication
is not worth relying on. It prints the `ssh -L` command to paste.
