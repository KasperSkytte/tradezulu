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

The APIs that do exist are not for you. MetaQuotes licenses server-side access
— the Manager and Web APIs — to the *brokers* who run an MT5 server, as part of
running one, at prices set for a business. Nobody sells a trader an API to
their own account, at any price. What every trader is given instead is the
terminal, and inside it MQL5, which can make an HTTP request.

So "just use my account details" means *something* has to run a terminal.
TradeZulu runs one for you, out of sight: a container per account, with a real
MetaTrader in it under Wine, and an Expert Advisor inside that reports every
deal back over plain HTTP.

### Yes, this is a hack

It is worth being plain about it. Attaching an account means starting a real
MetaTrader on a virtual display nobody looks at, letting it log itself in, and
driving its Options dialog by clicking, because the WebRequest allowlist the
Expert Advisor depends on is kept encrypted in the terminal's own config and
there is no other way in.

That is GUI automation against a program that never agreed to be automated,
and it can break: a MetaTrader update could move the dialog, a broker's build
could name things differently. What makes it liveable is that none of it is
trusted:

- The dialog is *measured* every time rather than clicked at from memory, so a
  window that opens somewhere else is still found.
- Nothing counts as done because a click appeared to work. The permission
  counts as granted only when that account's Expert Advisor actually reaches
  the server. Until then it retries, and then it stops and says what to check.
- You can look at exactly what any terminal is showing, at any time, from the
  Accounts page — and, when looking is not enough, take the mouse and use it.

The alternative was asking every user to install MetaTrader themselves, attach
an Expert Advisor to a chart, and paste a URL and a token into its inputs. That
is not a hack, and it is a great deal worse.

---

## Account details

**Accounts → Master account credentials**:

| Field | Example |
|---|---|
| Trade server | `ICMarketsSC-Live12` |
| Account number | `5000123` |
| Investor password | the read-only one your broker issued |

Save, and within a minute or so a terminal exists for that account — logged in,
with TradeZulu's Expert Advisor attached and reporting back. There is nothing
else to do. Slaves are added on the same page, and get a terminal each the same
way.

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

It is never in a container's environment either, so `docker inspect` does not
show it. A terminal container is started knowing only its account's id and the
ingest token; it fetches its own login from the site when it starts, writes it
into MetaTrader's start-up file, and rewrites that file without it as soon as
MetaTrader has logged in. From then on MetaTrader keeps its own encrypted copy
on the terminal's volume.

The start-up file is used because the command line cannot be: current
MetaTrader builds ignore `/login:` and `/password:` entirely and sit on the
new-account wizard instead, which looks exactly like a rejected password.

---

## How it is put together

```
                         ┌──────────────── Docker network "tradezulu" ───────────────┐
  browser ── nginx ──▶ tradezulu (site, API, SQLite)                                 │
                         │   ▲  ▲                                                     │
                         │   │  └── Expert Advisor polls over HTTP ──┐                │
                         │   │                                       │                │
                         │   └── plan / status ── orchestrator ──▶ tradezulu-terminal-1 (vantage-6295-wine11.0)
                         │                         (Docker socket)  tradezulu-terminal-2 (vantage-6295-wine11.0)
                         └── screen relay (VNC) ──────────────────▶ tradezulu-terminal-3 (falcon-6296-wine11.0)
```

### One image per broker and MetaTrader build

`terminal/build.sh <broker>` builds an image from [`brokers.json`](../brokers.json)
and tags it with what is in it:

```
tradezulu-terminal:vantage-6295-wine11.0     the broker, its MetaTrader build, the Wine it runs on
tradezulu-terminal:vantage                   the newest build of that broker, for convenience
```

The broker's own installer runs at build time and the Expert Advisor is
compiled there, with that image's own MetaEditor. So:

- a terminal that starts has nothing left to download or compile, and starts in
  seconds;
- the compiled `.ex5` always matches the terminal — MetaTrader refuses bytecode
  from a newer MetaEditor than itself, and brokers do not all ship the same
  build at once;
- an installer, or a MetaEditor, that refuses the Wine it was given fails the
  build with a message saying so, instead of leaving a terminal on a dialog
  nobody is watching.

Broker-specific installers matter: the generic MetaQuotes terminal cannot
resolve a name like `VantageMarkets-Live` at all and offers to open a new
account instead. Brokers with no entry of their own use `default`.

The images are not published anywhere: each carries a broker's MetaTrader, so
each install builds its own.

### Which image an account gets

The orchestrator picks the broker from the account's **server name**, not its
broker name: the server name always arrives correct because it comes from the
broker, while a demo account may report its broker as something as unhelpful as
"Demo Broker". Each broker's `matches` in `brokers.json` are what it looks for.

Of that broker's images it uses the one with the highest MetaTrader build, and
the newest of those. Only images tagged `<broker>-<build>-wine<version>` count,
which is what makes rolling back a matter of untagging one (see
[deployment.md](deployment.md#terminal-images)).

### What the orchestrator does

Every 15 seconds it reads the same plan the site has always published — which
accounts should have a terminal — and makes the containers agree:

| Situation | What happens |
|---|---|
| an account with credentials and no container | create one, with a volume for its data, and start it |
| the password, login or server changed | replace the container; the volume is kept |
| the account was deleted and added again | replace the container *and* the volume, so whatever was wrong goes too |
| a newer image exists for the broker | move to it at the weekly restart, or when Restart is pressed — never mid-week on its own |
| Restart pressed on the Accounts page | restart the container (and move it, as above) |
| the container stopped | start it again, unless its supervisor gave up for a reason a restart will not fix |
| the account was forgotten | remove the container and its volume |
| the account still exists but has no password | remove the container, keep the volume |

It only ever touches containers and volumes labelled with its own stack, and it
writes each terminal's status back to the site, which is what the Accounts page
shows.

### What a terminal container does

Its supervisor (`terminal/supervisor.py`) starts a virtual screen and a VNC
server on it, puts the account's data on the volume, writes the Expert
Advisor's preset (the site's address on the Docker network, and the token) and
the start-up file, and starts MetaTrader. Then it watches:

| | |
|---|---|
| logged in, nothing reported after 20 s | grant the WebRequest permission, up to 3 times a minute apart |
| still nothing | phase *failed*: "logged in, but the Expert Advisor never reached TradeZulu" |
| the broker refused the login | phase *failed*, with the broker's reason; it keeps the screen up and keeps watching, so a corrected password is picked up |
| MetaTrader's anti-debugger check refused this Wine | phase *failed*, permanently: the image needs another Wine version |
| an update is downloaded and wants a restart | restart MetaTrader so it installs on the way up |
| MetaTrader exited | start it again, backing off |
| reporting, then silent for 90 s | phase *quiet* |

"Running" is the weakest possible statement about a MetaTrader terminal. It can
be running while sitting on a refused login, or on an update dialog, or with an
Expert Advisor whose WebRequest permission never took — all of which look
identical from outside and none of which copy a trade. So the supervisor never
asks whether MetaTrader is running. It asks the site when that account's Expert
Advisor last reached it.

On `docker stop` MetaTrader is closed the way a person would close it, with a
minute to finish, so it writes what it keeps on the way out.

### Weekly restart

Terminals are restarted every Sunday at 3am by default — change it on the
**Accounts** page, in the server's local time.

MetaTrader downloads updates while it runs and then asks to restart to install
them. The supervisor answers that itself now, but a scheduled restart is still
when terminals move to a newer image, and the quietest hour of the week is the
right time for both. The window is checked rather than scheduled, so a machine
that was off on Sunday restarts its terminals when it comes back.

---

## Adding a broker, or a new MetaTrader build

A broker is an entry in [`brokers.json`](../brokers.json): a label, its
installer, the Wine to build on, the server names it matches, and the servers
to offer in the account form. Then:

```bash
terminal/build.sh <broker>
```

A broker that ships a new MetaTrader build needs nothing but a rebuild — the
installer always fetches the current one:

```bash
terminal/build.sh vantage --refresh   # tradezulu-terminal:vantage-<new build>-wine11.0
```

Running terminals move to it at the next weekly restart, or when restarted from
the Accounts page.

### Picking a Wine version

MetaTrader has an anti-debugger check, and some Wine builds trip it. When they
do, the program shows a small box — *"A debugger has been found running in your
system. Please, unload it from memory and restart your program."* — and waits
for ever. Which builds trip it depends on the MetaTrader build *and* on the
installer:

| | Soda 9.0 | WineHQ 10.0 | WineHQ 11.0 | WineHQ 11.21 |
|---|---|---|---|---|
| broker terminals, build ≤ 6230 | ✅ | | | |
| broker terminals, build 6295–6296 | ❌ | ❌ | ✅ | ✅ |
| the generic MetaQuotes installer | | | ❌ | ✅ |

That is why the Wine version is set per broker, in `brokers.json`, and is part
of the image's tag. `build.sh` notices the box during the install and fails
saying so; a terminal that meets it at run time reports *failed* with the same
explanation. Either way the fix is another `wine` for that broker and a rebuild.

---

## When a terminal will not work

Nothing here needs uninstalling anything. Look first:

- **The Accounts page** says what the terminal's supervisor last reported, and
  **Inspect** shows its screen — a refused login, a dialog, a missing Expert
  Advisor are all visible there and nowhere else.
- **Its log:**

  ```bash
  docker logs -f tradezulu-terminal-3      # what its supervisor did, and when
  docker compose logs -f orchestrator      # why it was (or was not) started
  ```

- **MetaTrader's own logs**, which are on the terminal's volume. They are
  UTF-16, so `grep` finds nothing in them until they are converted:

  ```bash
  docker exec tradezulu-terminal-3 sh -c \
    'iconv -f UTF-16LE -t UTF-8 /data/logs/$(date +%Y%m%d).log | tail -40'
  ```

  The Expert Advisor's own messages (an empty token, a URL not on the
  allowlist, algorithmic trading switched off) are on the **Experts** tab of
  the terminal's screen; MetaTrader writes them to disk only now and then.

### Starting one over

**Restart** on the Accounts page restarts the container. To start from nothing —
a fresh install from the image, a fresh login — remove the container and its
volume; the orchestrator builds a new one on its next pass:

```bash
docker rm -f tradezulu-terminal-3
docker volume rm tradezulu-terminal-3-data
```

Nothing in TradeZulu is touched — no account, no trade, no password. Forgetting
an account in the web interface does the same on its own.

---

## The WebRequest permission

An Expert Advisor may only reach a URL that is on the terminal's allowlist, and
that list is kept encrypted in MetaTrader's own config — there is no file to
write. The only way in is the Options dialog, so the supervisor drives it:
Ctrl+O, the Experts tab, tick *Allow WebRequest for listed URL* if it is not,
type the site's address into the list, OK.

Wine draws the dialog's controls itself, so they are not X windows and cannot
be found by name; only the dialog as a whole can. So the clicks are measured
**against the dialog**, which is found by being the window that appeared, and
its position is read with `xwininfo`. Not with `xdotool`, which under a
window manager reports positions offset by the window's frame: that put every
click one row low, and once typed TradeZulu's address into the *trade server*
field instead.

With the Wine builds that MetaTrader 6295+ needs, the allowlist is not written
back to MetaTrader's config on exit, so it does not survive a restart. The
supervisor grants it again on every start — about twenty seconds, and verified
the same way as the first time, by the Expert Advisor reaching the site.

The Expert Advisor's first polls fail until then. It resends anything that went
out with a failed poll — the broker's symbol list above all — on the next one,
so nothing is lost but those twenty seconds.

---

## How it got here

The terminals were not always in containers, and the reasons are worth keeping.

**The Python bridge (removed).** The first design ran a headless MetaTrader in
a container and drove it with MetaQuotes' Python package. The terminal started
and loaded an account, and `mt5.initialize()` timed out — the terminal accepted
the IPC connection and never answered. Eliminated one at a time, all failing
identically: Docker networking, host networking, seccomp and AppArmor, the
clock, CA certificates, port reachability, WineHQ 8 through 11 including
staging, Python 3.9 and 3.11, 32- and 64-bit, several versions of the Python
package, generic and broker-branded terminals, root and non-root, four display
configurations, `winhttp`/`wininet`, `mt5linux`, and two published reference
projects built verbatim. That code is in the git history
(`git log --diff-filter=D -- mt5-bridge/`).

**Terminals on the host (replaced).** What did work was turning the direction
round: an Expert Advisor inside the terminal, talking outwards over HTTP. That
needs no inbound port, no credentials in flight at request time, and nothing
from MetaTrader's IPC layer at all. It ran on the host, under Bottles' Soda
9.0 Wine build, driven by a systemd service.

**Containers again (now).** Brokers moving to MetaTrader build 6295–6296 ended
that: under Soda, and under WineHQ 10, those builds stop on the anti-debugger
box before they draw a window. WineHQ 11 passes — and since the Expert Advisor
does not need the IPC layer that defeated the bridge, nothing stood in the way
of putting the terminal back in a container. In one, each broker can have the
Wine its installer accepts, which the host could never offer.

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

## Looking at a terminal

**Accounts → Inspect** shows a terminal's screen in the page, live. The site
relays it from the VNC server inside the terminal's container over the same
signed-in session as everything else; the VNC server publishes no port and is
reachable only on the Docker network.

The keyboard and mouse reach the terminal, so a dialog it is stuck on can be
answered and a chart read. These are the real terminals, logged into real
accounts: a click can place an order, and the supervisor may be typing into the
same screen at the same moment. The viewer says so in red for as long as it is
open.

For a picture without the browser:

```bash
docker exec tradezulu-terminal-3 import -window root /data/screen.png
docker cp tradezulu-terminal-3:/data/screen.png .
```
