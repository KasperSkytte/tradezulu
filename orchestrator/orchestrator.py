"""Run one MetaTrader terminal container per TradeZulu account.

Every pass it asks TradeZulu which terminals should exist, compares that with
the terminal containers it owns, and makes them agree:

* an account with credentials gets a container, on the newest image built for
  its broker (the image with the highest MetaTrader build, see
  terminal/build.sh), and a volume for that account's MetaTrader data;
* changed credentials, or an account deleted and added again, get a fresh
  container -- the second also a fresh volume, because whatever was wrong with
  the old install is what re-adding is meant to get rid of;
* a newer image for the broker is moved to at the weekly restart, or when the
  terminal is restarted from the web interface -- never mid-week by itself;
* an account that was forgotten loses its container and its volume.

What each terminal is doing is read from the status file its supervisor keeps
on its volume and passed back to TradeZulu, together with where its screen is.

This is the only part of TradeZulu that talks to Docker, and talking to Docker
is root on the host. It is kept small for that reason, uses nothing but the
standard library, and only ever touches containers and volumes carrying its own
stack's label.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import logging
import os
import socket
import tarfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

log = logging.getLogger("orchestrator")

API = os.environ.get("TZ_URL", "http://app.tradezulu.internal:8420/api").rstrip("/")
TOKEN = os.environ["TZ_INGEST_TOKEN"]
NETWORK = os.environ.get("TZ_NETWORK", "tradezulu")
STACK = os.environ.get("TZ_STACK", "tradezulu")
PREFIX = os.environ.get("TZ_TERMINAL_PREFIX", f"{STACK}-terminal")
INTERVAL = int(os.environ.get("TZ_INTERVAL", "15"))
BROKERS = json.loads(Path(os.environ.get("TZ_BROKERS", "/app/brokers.json")).read_text())
STATE = Path(os.environ.get("TZ_STATE", "/state/orchestrator.json"))
#: Seconds MetaTrader gets to close itself on stop. It writes its settings on
#: the way out, so this is not a formality.
STOP_GRACE = 60


# --- Docker, over its socket ------------------------------------------------

class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class DockerError(RuntimeError):
    pass


def docker(method: str, path: str, body: dict | None = None, query: dict | None = None,
           timeout: float = STOP_GRACE + 30, raw: bool = False):
    if query:
        path += "?" + urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in query.items()})
    conn = _UnixConnection("/var/run/docker.sock", timeout)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json"} if payload else {})
        response = conn.getresponse()
        data = response.read()
    finally:
        conn.close()
    if response.status >= 400:
        raise DockerError(f"{method} {path}: {response.status} {data[:300]!r}")
    if raw:
        return data
    return json.loads(data) if data else None


def mine() -> dict[str, str]:
    return {"tz.stack": STACK, "tz.role": "terminal"}


def label_filter(**extra: str) -> dict:
    labels = {**mine(), **extra}
    return {"label": [f"{k}={v}" for k, v in labels.items()]}


# --- TradeZulu ----------------------------------------------------------------

def tz(method: str, path: str, body: dict | None = None) -> dict | None:
    request = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
    return json.loads(data) if data else None


# --- choosing an image --------------------------------------------------------

def broker_for(server: str) -> str:
    """Which broker's terminal a server belongs to. The server name decides:
    it comes from the broker, so it is always right, where the broker field is
    whatever the Expert Advisor last said the company was called."""
    lowered = server.lower()
    for key, entry in BROKERS.items():
        if isinstance(entry, dict) and any(m in lowered for m in entry.get("matches", [])):
            return key
    return "default"


def images() -> dict[str, dict]:
    """The newest terminal image per broker: highest MetaTrader build, then
    the most recently built."""
    best: dict[str, dict] = {}
    for image in docker("GET", "/images/json", query={"filters": {"label": ["tz.role=terminal"]}}):
        labels = image.get("Labels") or {}
        broker = labels.get("tz.broker")
        if not broker:
            continue
        try:
            build = int(labels.get("tz.mt5.build") or 0)
        except ValueError:
            build = 0
        # Only an image tagged with what is in it counts. An untagged one is
        # either superseded (rebuilt under the same tag) or was untagged on
        # purpose to roll back, and Docker keeps listing it for as long as a
        # container still runs on it.
        tags = [t for t in image.get("RepoTags") or [] if t.count("-") >= 2 and ":build-" not in t]
        if not tags:
            continue
        ref = tags[0]
        key = (build, image.get("Created", 0))
        if broker not in best or key > best[broker]["key"]:
            best[broker] = {"key": key, "ref": ref, "id": image["Id"], "build": build}
    return best


# --- containers ---------------------------------------------------------------

def name_for(account_id: int) -> str:
    return f"{PREFIX}-{account_id}"


def volume_for(account_id: int) -> str:
    return f"{PREFIX}-{account_id}-data"


def credentials_hash(entry: dict) -> str:
    text = f"{entry['login']}\0{entry['server']}\0{entry['password']}"
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def remove(container: dict, with_volume: bool) -> None:
    account = container["Labels"].get("tz.account")
    log.info("removing %s%s", container["Names"][0].lstrip("/"), " and its data" if with_volume else "")
    if container["State"] == "running":
        docker("POST", f"/containers/{container['Id']}/stop", query={"t": STOP_GRACE})
    docker("DELETE", f"/containers/{container['Id']}", query={"force": "true"})
    if with_volume and account:
        try:
            docker("DELETE", f"/volumes/{volume_for(int(account))}")
        except DockerError as error:
            log.warning("could not remove the volume of account %s: %s", account, error)


def create(entry: dict, image: dict) -> None:
    account_id = int(entry["account_id"])
    labels = {
        **mine(),
        "tz.account": str(account_id),
        "tz.incarnation": entry.get("created_at") or "",
        "tz.credentials": credentials_hash(entry),
        "tz.image": image["ref"],
        # The id as well as the tag: rebuilding a broker's image for a new
        # Expert Advisor keeps the tag (same MetaTrader build) but not the id.
        "tz.image.id": image["id"],
        "tz.broker": broker_for(entry["server"]),
    }
    volume = volume_for(account_id)
    try:
        docker("GET", f"/volumes/{volume}")
    except DockerError:
        docker("POST", "/volumes/create", {"Name": volume, "Labels": {**mine(), "tz.account": str(account_id)}})
    body = {
        "Image": image["ref"],
        "Hostname": name_for(account_id),
        "Labels": labels,
        # No password here: the terminal fetches its own login from TradeZulu
        # with the token below, which its Expert Advisor needs anyway.
        "Env": [f"TZ_ACCOUNT_ID={account_id}", f"TZ_URL={API}", f"TZ_TOKEN={TOKEN}"],
        "StopTimeout": STOP_GRACE,
        "HostConfig": {
            "Init": False,  # the image runs tini itself
            "Tmpfs": {"/tmp": "exec"},
            "Mounts": [{"Type": "volume", "Source": volume, "Target": "/data"}],
            "NetworkMode": NETWORK,
            # Restarting is decided here, not by Docker: a terminal that was
            # refused by the broker or by MetaTrader should stay put, with its
            # screen up, until somebody changes something.
            "RestartPolicy": {"Name": "no"},
            "ShmSize": 256 * 1024 * 1024,
        },
    }
    name = name_for(account_id)
    log.info("creating %s for %s on %s (%s)", name, entry["login"], entry["server"], image["ref"])
    created = docker("POST", "/containers/create", body, query={"name": name})
    docker("POST", f"/containers/{created['Id']}/start")


def read_status(container: dict) -> dict:
    try:
        data = docker("GET", f"/containers/{container['Id']}/archive",
                      query={"path": "/data/status.json"}, raw=True, timeout=15)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.extractfile(archive.getmembers()[0])
            return json.loads(member.read()) if member else {}
    except (DockerError, tarfile.TarError, ValueError, IndexError, OSError):
        return {}


# --- the pass -----------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def maintenance_due(plan: dict, state: dict) -> bool:
    window = plan.get("maintenance") or {}
    now = datetime.now()
    if now.weekday() != int(window.get("weekday", 6)) or now.hour < int(window.get("hour", 3)):
        return False
    return state.get("maintenance") != now.date().isoformat()


def reconcile(state: dict) -> None:
    plan = tz("GET", "/agent/terminals") or {}
    wanted = {int(t["account_id"]): t for t in plan.get("terminals", [])}
    known = {int(a) for a in plan.get("known_accounts", [])}
    best = images()
    containers = {
        int(c["Labels"]["tz.account"]): c
        for c in docker("GET", "/containers/json", query={"all": "true", "filters": label_filter()})
        if c["Labels"].get("tz.account", "").isdigit()
    }
    weekly = maintenance_due(plan, state)
    restarts = state.setdefault("restart_tokens", {})
    reports = []

    for account_id, container in list(containers.items()):
        if account_id not in wanted:
            # Forgotten: the data goes too. Merely without a password: keep the
            # data, since the saved login and history are still that account's.
            remove(container, with_volume=account_id not in known)
            containers.pop(account_id)

    for account_id, entry in wanted.items():
        broker = broker_for(entry["server"])
        image = best.get(broker)
        container = containers.get(account_id)
        report = {"account_id": account_id, "display": "", "vnc_port": None, "vnc_host": ""}

        if image is None:
            reports.append({**report, "phase": "failed",
                            "message": f"There is no terminal image for {broker} yet. Build one "
                                       f"with terminal/build.sh {broker}."})
            continue

        token = entry.get("restart_token") or ""
        restart_asked = bool(token) and restarts.get(str(account_id)) != token
        if container is not None:
            labels = container["Labels"]
            if labels.get("tz.incarnation", "") != (entry.get("created_at") or ""):
                remove(container, with_volume=True)
                container = None
            elif labels.get("tz.credentials") != credentials_hash(entry):
                remove(container, with_volume=False)
                container = None
            elif labels.get("tz.image.id") != image["id"] and (weekly or restart_asked):
                log.info("moving account %s to %s", account_id, image["ref"])
                remove(container, with_volume=False)
                container = None

        try:
            if container is None:
                create(entry, image)
            elif restart_asked or weekly:
                log.info("restarting %s", name_for(account_id))
                docker("POST", f"/containers/{container['Id']}/restart", query={"t": STOP_GRACE})
            elif container["State"] != "running":
                status = read_status(container)
                if not status.get("fatal"):
                    log.info("starting %s again", name_for(account_id))
                    docker("POST", f"/containers/{container['Id']}/start")
        except DockerError as error:
            log.error("account %s: %s", account_id, error)
            reports.append({**report, "phase": "failed", "message": str(error)[:400]})
            continue
        if restart_asked:
            restarts[str(account_id)] = token

        found = docker("GET", "/containers/json",
                       query={"all": "true", "filters": label_filter(**{"tz.account": str(account_id)})})
        status = read_status(found[0]) if found else {}
        running = bool(found) and found[0]["State"] == "running"
        reports.append({
            **report,
            "phase": (status.get("phase") or "starting") if running or status.get("fatal") else "starting",
            "message": (status.get("message") or "")[:400],
            "attempts": int(status.get("attempts") or 0),
            "display": f"{name_for(account_id)}:0",
            "vnc_port": 5900 if running else None,
            "vnc_host": name_for(account_id) if running else "",
        })

    if weekly:
        state["maintenance"] = datetime.now().date().isoformat()
        log.info("weekly restart done")
    tz("POST", "/agent/terminals/state", {"terminals": reports})


def main() -> None:
    logging.basicConfig(level=os.environ.get("TZ_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)-7s %(message)s")
    log.info("orchestrating %s terminals on network %s, reporting to %s", STACK, NETWORK, API)
    state = load_state()
    while True:
        try:
            reconcile(state)
            save_state(state)
        except Exception:  # noqa: BLE001 - one bad pass must not end the loop
            log.exception("pass failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
