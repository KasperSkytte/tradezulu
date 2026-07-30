# The bridge, and why it does not work here

The `mt5-bridge` container runs MetaTrader 5 under Wine so TradeZulu can read
an account from nothing but a server, a login and a password. The container
builds, the terminal runs, and the HTTP API serves — but the Python API cannot
reach the terminal, so nothing is ever read from it.

This is the record of what was tried, so nobody repeats it.

## The symptom

```python
mt5.initialize(r"C:\Program Files\MetaTrader 5\terminal64.exe")
# False, (-10005, 'IPC timeout')      -- with a full Python install
# False, (-10001, 'IPC send failed')  -- with the embeddable Python
```

The `MetaTrader5` package does not talk to the broker. It talks to
`terminal64.exe` on the same machine over a **Windows named pipe**, which
lives entirely inside Wine and never touches the network. `initialize()` is
the call that attaches to that pipe, and it is what fails.

The terminal itself is healthy while this happens. Its own log shows:

```
Terminal   MetaTrader 5 x64 build 6063 started
MCP        started on 127.0.0.1:22346
Compiler   full recompilation has been finished: 131 file(s) compiled
LiveUpdate 'mt5onnx64' downloaded and updated (68441 kb)
```

It starts, compiles, reaches the internet and listens on its control port.
Only the pipe the Python package wants never appears.

## What has been eliminated

Each of these was tested directly, not reasoned about.

| Suspect | Result |
|---|---|
| Docker networking | Ruled out. A Windows process under Wine connects to `127.0.0.1:22346`. |
| Host networking mode | Ruled out. `--network host` changes nothing. |
| seccomp / AppArmor | Ruled out. `seccomp=unconfined`, `apparmor=unconfined`, `SYS_PTRACE`. |
| The terminal being unhealthy | Ruled out. See its log above. |
| The first-run compile window | Ruled out. It blocks the API 2–3 minutes; probes now wait 5. |
| Reported Windows version | Ruled out. Set to `win10`, as MetaTrader expects. |
| Two competing terminals | Fixed. `initialize(path=...)` starts its own with `/portable`, so the entrypoint no longer starts one. |
| Wine version | Ruled out. 8, 10 and 11 all fail (differently — see below). |
| Python version | Ruled out. 3.9.13 and 3.11.9. |
| Embeddable vs full Python | Improved but insufficient. Full install moves the error from `IPC send failed` to `IPC timeout`. |
| `MetaTrader5` package version | Ruled out. Current `5.0.5735` and pinned `5.0.36`. |
| Broker build | Ruled out. Generic MetaQuotes and Vantage's own branded terminal. |
| Desktop session | Ruled out. Bare Xvfb, `wine explorer /desktop=`, and a full KasmVNC desktop. |

## The reference implementations fail here too

`github.com/gmag11/MetaTrader5-Docker` was built and run **verbatim** on this
host. It fails in two ways, both already fixed in this repository:

* it hangs for ever at `[3/7] Installing MetaTrader 5` — the same
  `mt5setup.exe /auto` stall that Wine 11 has and Wine 10 does not, which is
  why the Wine version here is pinned to 10, and
* it installs numpy unpinned, so `import MetaTrader5` dies with
  `numpy.core.multiarray failed to import` — numpy 2 calls
  `ucrtbase.dll.crealf`, which Wine does not implement.

Given a working terminal and numpy pinned, its own environment — Python 3.9.13,
`MetaTrader5==5.0.36`, a KasmVNC desktop — still returns `IPC timeout`.

So the fault is not this image.

## Round two: what the terminal actually does

Running it as a **non-root user** is required and was missed for a long time.
As root the journal stops at `MCP started` and the terminal never touches the
network. As an ordinary user it goes further and discovers MQL5 Cloud servers,
which is real network activity:

```
Tester  MQL5 Cloud Server "MQL5 Cloud Europe 3: 10 gbit" found
Startup successfully initialized from start config ".../login.ini"
```

Three more requirements found by comparing against
`bahadirumutiscimen/silicon-metatrader5`:

* **a window manager.** On bare Xvfb the terminal creates *no windows at all*.
  With openbox it builds its real main window. 0 windows to 40.
* **vcrun2019** via winetricks. The package hunts for `VCRUNTIME140_1.dll`.
* **an `[Expert]` section** in a startup ini with `AllowAlgoTrading=1` and
  `EnableAlgoTrading=1`, plus `/config:` to apply it.

With every one of those in place the terminal is genuinely healthy: build 6069
branded for the broker, config accepted, credentials written to `accounts.dat`,
one clean instance.

And `mt5.initialize()` still returns `IPC timeout`, on both a 64-bit package
(5.0.5735) and the 32-bit `5.0.36` the reference pins.

## The specific thing that is wrong

The terminal never opens a Python API endpoint, and never dials a broker:

```
listening TCP ports in the container:  22346      # MCP only
established outbound connections:      0
```

`22346` is the terminal's own control port, not the API. So there is nothing
for the package to connect to — which is exactly what an IPC timeout is. The
journal ends at `MCP started` every time, with no authorisation line, even
though the credentials were accepted and saved.

That reframes the problem: it is not that the API cannot be reached, it is that
the terminal never starts serving it.

## mt5linux, tested end to end

`mt5linux` is the package most often recommended for this, so it was set up
exactly as documented: `MetaTrader5`, `rpyc` and `mt5linux` installed into the
Wine Python, the server started inside Wine, and the client run from Linux.

```
server started on [0.0.0.0]:18812        # inside Wine
client connected to the wine-side server  # from Linux
INIT False (-10005, 'IPC timeout')
```

It works perfectly as a transport — the Linux client reaches the Wine-side
Python and calls into it. But `mt5linux` is an RPyC wrapper around the same
`MetaTrader5.initialize()`, so it inherits the same failure exactly. Tested
both bare and with an explicit terminal path plus credentials.

This is worth being clear about: mt5linux solves *calling MT5 from Linux
Python*, which the bridge here already solved. It does not solve the terminal
declining to serve its API, which is the actual fault.

## The terminal never authorises, which is upstream of everything

A clean container, fresh prefix, generic build, window manager, `-ac` on the X
server, Windows 10 mode, the account supplied by startup ini:

```
Startup   successfully initialized from start config "...\acct.ini"
Terminal  MetaTrader 5 x64 build 6070 started
MCP       started on 127.0.0.1:22346
Tester    MQL5 Cloud Server "MQL5 Cloud Europe 3: 10 gbit" found
LiveUpdate 'mt5onnx64' downloaded and updated (68441 kb)
```

The terminal has real internet — it pulled a 68MB update and discovered the
MQL5 cloud fleet. It reads the account config without error. And then:

```
established outbound connections:  0
authorisation lines in the journal: none
windows created:                    0
```

It never dials the broker. Copying the broker's `servers.dat` into the generic
install does not change it, and the broker's own branded build — which does
carry the server list — never initialises far enough to create a window at all,
as root or as an ordinary user.

So the ordering is: no broker connection, therefore no API to serve, therefore
an IPC timeout. The IPC error was always a symptom.

This also rules out the Expert Advisor as a way around it. An EA runs *inside*
the terminal, so it inherits the same missing connection; it would load and
have nothing to report.

## What the working projects actually do

Three were examined:

| Project | Approach | Result here |
|---|---|---|
| `gmag11/MetaTrader5-Docker` | Wine + KasmVNC + mt5linux | built verbatim; fails identically |
| `SmartLever/Docker_mt5` | Wine + Xdummy + a **ZMQ Expert Advisor** | uses an EA, not the Python API |
| `im-mahdi-74/Dockerized-MetaTrader5...` | **`mcr.microsoft.com/windows/servercore`** | not Wine at all |

The last one is the tell. The project built specifically to expose MetaTrader 5
to Python from a container does it in a **Windows container**, where the Python
API works natively. It does not attempt Wine.

## The GUI works, and my instrument was broken

`xwininfo` was never installed in the test container. Every "0 windows" reading
taken there was the shell reporting an empty result for a command that did not
exist, and conclusions were drawn from it. With `x11-utils` installed the same
container reports:

```
46 windows
"MetaTrader 5 - Netting - EURUSD,H1"
"Login"                                  <- a login dialog, open and waiting
```

The terminal had a complete working GUI the whole time and was **sitting at a
login prompt**. It can be driven with `xdotool`: activating the dialog and
typing fills Login, Password and Server correctly, and submitting it loads the
account — the title bar becomes `22609000 - vantagemarkets-live - Netting`.

So a headless MT5 needs, in addition to everything above:

* `x11-utils` and `xdotool`, to see and drive the GUI at all, and
* the login dialog answered, because a startup ini alone leaves it open.

## And still no broker connection

With the account loaded and the GUI live:

```
status bar:            0 / 0 Kb        <- no traffic
chart data:            August 2024     <- cached, not live
TCP sockets:           1 (127.0.0.1:22346, the MCP listener)
journal, networking:   nothing at all
```

Submitting the login produces no error dialog, no journal line, and no socket.
The terminal simply never attempts to reach the broker. `mt5.initialize()`
continues to time out, which is consistent: there is no connected terminal to
serve an API.

That is the wall. Everything upstream of the broker connection now works.

## winhttp / wininet: no

Native `winhttp.dll` (1.7MB) and `wininet.dll` (2.5MB) installed via winetricks
and overridden to `native,builtin`. No change. Consistent with the winsock
trace, which shows MetaTrader using raw sockets for the broker link rather than
either of those.

## MetaQuotes publish an official Linux recipe, and it contradicts several assumptions

The terminal says so itself, in its own journal under Wine 9:

```
unstable and unsupported Wine 9.0, please upgrade to Wine 10.0 or later
please uninstall and download from https://www.metatrader5.com/en/download
```

So a *newer* Wine is wanted, not an older one. The official installer,
`https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh`,
does four things this repository was not doing:

| MetaQuotes | What was here |
|---|---|
| `winehq-**staging**` | stable only |
| `winecfg -v=**win11**` | win10 |
| installs the **WebView2 runtime** | never installed |
| `WINEPREFIX=~/.mt5` | `/wine` |

Wine Mono and Gecko are described as "required for platform operation" — this
repository explicitly disabled both via `WINEDLLOVERRIDES="mscoree,mshtml="`.

Following that recipe exactly on Debian bookworm with `winehq-staging`
(11.10) gets further and then stops: the prefix builds to 892MB with a working
`system32\kernel32.dll`, but `syswow64\kernel32.dll` is never created, so every
32-bit executable — including MetaTrader's own installer — fails with

```
wine: could not load kernel32.dll, status c0000135
```

This is not a missing dependency. The 32-bit loader runs
(`/opt/wine-staging/lib/wine/i386-unix/wine --version` reports 11.10), every
i386 library resolves, and both `wine-staging-i386` and its 1104 i386-windows
DLLs are installed. The prefix simply never grows its WoW64 half, on a fresh
build as well as a repaired one.

## Where that leaves it

Every known configuration fails identically on this host:

```
kernel 5.15.0-186-generic, Docker 29.6.2
```

The remaining variable is the host itself — most likely Wine's named-pipe or
shared-memory implementation against this kernel. Testing that means a
different machine, which is the next step if this route is worth continuing.

## What works instead, today

* **The Expert Advisor.** `TradeZuluSync` pushes deals straight from a terminal
  you already run, needs no bridge, and is covered in
  [metatrader.md](metatrader.md). This is the working path for the journal.
* **File import.** Also in that document.

## What this blocks

The copier. Placing an order needs a terminal the application can drive, so
until the API can reach one, slave accounts cannot trade. Everything above that
line is built and tested against a simulated broker: sizing, risk gates,
account guards, prop-firm rules, symbol resolution, the copy loop, and the
worker-per-account pool. The engine is covered by 128 tests; only the terminal
underneath it is missing.

If this host cannot be made to work, the shape that would: run the terminals on
a Windows machine or VM, and have the bridge talk to them over the network
rather than through Wine.
