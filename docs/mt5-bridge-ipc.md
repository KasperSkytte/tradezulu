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
