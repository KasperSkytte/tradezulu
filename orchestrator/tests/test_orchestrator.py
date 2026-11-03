"""The orchestrator's decisions, without a Docker daemon.

Run from the repository root:  python3 -m pytest orchestrator/tests
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def orch(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ_INGEST_TOKEN", "t")
    monkeypatch.setenv("TZ_BROKERS", str(ROOT / "brokers.json"))
    monkeypatch.setenv("TZ_STATE", str(tmp_path / "state.json"))
    sys.path.insert(0, str(ROOT / "orchestrator"))
    try:
        module = importlib.import_module("orchestrator")
        yield importlib.reload(module)
    finally:
        sys.path.remove(str(ROOT / "orchestrator"))


def test_the_server_name_picks_the_broker(orch):
    assert orch.broker_for("VantageMarkets-Live 8") == "vantage"
    assert orch.broker_for("FalconMarkets-Server") == "falcon"
    assert orch.broker_for("Dukascopy-demo-mt5-1") == "dukascopy"
    assert orch.broker_for("MetaQuotes-Demo") == "default"


def image(broker, build, created, tag, ident):
    return {"Id": ident, "Created": created, "RepoTags": [tag],
            "Labels": {"tz.role": "terminal", "tz.broker": broker, "tz.mt5.build": str(build)}}


def test_the_newest_build_wins_then_the_newest_image(orch, monkeypatch):
    listing = [
        image("vantage", 6230, 300, "tradezulu-terminal:vantage-6230-wine11.0", "a"),
        image("vantage", 6295, 100, "tradezulu-terminal:vantage-6295-wine11.0", "b"),
        image("vantage", 6295, 200, "tradezulu-terminal:vantage-6295-wine11.21", "c"),
        image("falcon", 6296, 100, "tradezulu-terminal:falcon-6296-wine11.0", "d"),
    ]
    monkeypatch.setattr(orch, "docker", lambda *a, **k: listing)
    best = orch.images()
    assert best["vantage"]["id"] == "c"
    assert best["vantage"]["ref"] == "tradezulu-terminal:vantage-6295-wine11.21"
    assert best["falcon"]["build"] == 6296
    assert "dukascopy" not in best


def test_the_alias_tag_is_not_used_as_the_reference(orch, monkeypatch):
    # tradezulu-terminal:vantage moves with every build; the container records
    # the tag that says what is in it.
    entry = image("vantage", 6295, 1, "tradezulu-terminal:vantage", "x")
    entry["RepoTags"] = ["tradezulu-terminal:vantage", "tradezulu-terminal:vantage-6295-wine11.0"]
    monkeypatch.setattr(orch, "docker", lambda *a, **k: [entry])
    assert orch.images()["vantage"]["ref"] == "tradezulu-terminal:vantage-6295-wine11.0"


def test_an_untagged_image_is_never_chosen(orch, monkeypatch):
    # Rolling back is untagging the newer image. Docker still lists it while a
    # terminal runs on it, so it has to be skipped or the rollback never takes.
    newer = image("vantage", 6296, 200, "tradezulu-terminal:vantage-6296-wine11.0", "new")
    newer["RepoTags"] = []
    older = image("vantage", 6295, 100, "tradezulu-terminal:vantage-6295-wine11.0", "old")
    monkeypatch.setattr(orch, "docker", lambda *a, **k: [newer, older])
    assert orch.images()["vantage"]["id"] == "old"


def test_a_changed_password_changes_the_credentials_label(orch):
    a = {"login": "1", "server": "S", "password": "p"}
    assert orch.credentials_hash(a) == orch.credentials_hash(dict(a))
    assert orch.credentials_hash(a) != orch.credentials_hash({**a, "password": "q"})
    assert "p" not in orch.credentials_hash(a)


def test_maintenance_runs_once_in_its_window(orch, monkeypatch):
    from datetime import datetime as real

    class Sunday(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 11, 8, 3, 30)  # a Sunday, 03:30

    monkeypatch.setattr(orch, "datetime", Sunday)
    plan = {"maintenance": {"weekday": 6, "hour": 3}}
    assert orch.maintenance_due(plan, {})
    assert not orch.maintenance_due(plan, {"maintenance": "2026-11-08"})
    assert not orch.maintenance_due({"maintenance": {"weekday": 6, "hour": 4}}, {})
