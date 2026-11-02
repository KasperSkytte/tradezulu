"""What the provisioner decides, tested without a MetaTrader in sight.

This code runs on someone's own server, where a mistake shows up as a terminal
that quietly does nothing rather than as a failing build -- which is how a
missing import once shipped. The parts worth testing are the decisions: when a
running terminal counts as working, when to restart it, when to give up on it,
and what belongs to whom. None of those need Wine, so none of them are left
untested here.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tz_provision as tz  # noqa: E402

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def bottles(tmp_path, monkeypatch):
    """Point every path at a temporary tree, so nothing real is touched."""
    monkeypatch.setattr(tz, "BOTTLES", tmp_path)
    monkeypatch.setattr(tz, "STATE_DIR", tmp_path / ".tz-state")
    monkeypatch.setattr(tz, "BUILDS", tmp_path / ".tz-state/builds")
    (tmp_path / "bottles").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Nothing here is waiting for a real MetaTrader to reach a login."""
    monkeypatch.setattr(tz.time, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def screens(monkeypatch):
    """Every account has a screen of its own; none of them is under test here.

    There is no X server in a test container, and bringing one up per account
    is not what any of this is checking.
    """
    monkeypatch.setattr(tz, "ensure_display", lambda *a, **k: True)
    monkeypatch.setattr(tz, "ensure_vnc", lambda *a, **k: None)


# --- is this terminal working? -----------------------------------------------


class TestHealth:
    def test_a_terminal_that_reported_a_moment_ago_is_working(self):
        assert tz.health(NOW - timedelta(seconds=20), NOW - timedelta(hours=3), NOW) == "reporting"

    def test_a_terminal_that_has_just_started_is_given_time(self):
        assert tz.health(None, NOW - timedelta(seconds=30), NOW) == "settling"

    def test_a_terminal_that_never_reported_is_not_working(self):
        """Running is not the same as working, and this is the difference.

        A terminal sitting on a refused login, or with an Expert Advisor that
        cannot reach TradeZulu, is running perfectly and copying nothing.
        """
        assert tz.health(None, NOW - timedelta(minutes=30), NOW) == "never-reported"

    def test_a_terminal_that_went_quiet_is_not_working_either(self):
        assert (
            tz.health(NOW - timedelta(hours=2), NOW - timedelta(hours=3), NOW) == "gone-quiet"
        )

    def test_a_gap_between_polls_is_not_silence(self):
        assert tz.health(NOW - timedelta(minutes=5), NOW - timedelta(days=1), NOW) == "reporting"

    def test_an_unknown_launch_time_does_not_grant_forever(self):
        assert tz.health(None, None, NOW) == "never-reported"


# --- whose prefix is this? ----------------------------------------------------


class TestAccountOf:
    def test_an_account_prefix_names_its_account(self):
        assert tz.account_of(Path("/x/bottles/tz-12")) == 12

    @pytest.mark.parametrize(
        "name", ["tz-template-default", "tz-template-vantage", "MT5", "tz-", "tz-1x"]
    )
    def test_nothing_else_is_an_account(self, name):
        """Templates especially: every account is a copy of one."""
        assert tz.account_of(Path("/x/bottles") / name) is None


class TestState:
    def test_what_is_written_is_what_comes_back(self):
        tz.save_state(3, {"login": "22609000", "restarts": 2})
        assert tz.load_state(3) == {"login": "22609000", "restarts": 2}

    def test_an_account_with_no_state_has_no_state(self):
        assert tz.load_state(99) == {}

    def test_state_survives_its_prefix_being_deleted(self, bottles):
        """The reason it lives out here at all.

        Every retry count used to be kept inside the prefix, so "rebuild it and
        try again" reset the count that decides how many rebuilds to allow --
        which is not a ladder, it is a loop.
        """
        prefix = tz.bottle_for(4)
        prefix.mkdir()
        tz.save_state(4, {"rebuilds": 1})
        tz.discard_prefix(prefix, "testing")
        assert not prefix.exists()
        assert tz.load_state(4)["rebuilds"] == 1


# --- which processes belong to a prefix? --------------------------------------


class TestProcessMatching:
    """The distinction that decides whether a terminal is restarted at all."""

    def _proc(self, argv: list[str], prefix: Path | None) -> tuple[bytes, bytes]:
        command = b"\0".join(arg.encode() for arg in argv)
        environ = b"HOME=/home/x\0" + (f"WINEPREFIX={prefix}\0".encode() if prefix else b"")
        return command, environ

    def test_the_terminal_itself_counts(self, bottles):
        prefix = tz.bottle_for(1)
        command, environ = self._proc(
            [r"C:\Program Files\MetaTrader 5\terminal64.exe", "/portable"], prefix
        )
        assert tz.is_terminal(command, environ, prefix)

    def test_the_launcher_stub_does_not(self, bottles):
        """``start.exe /exec terminal64.exe`` names the terminal but is not it.

        It can outlive a launch that failed, and counting it made an empty
        prefix look occupied -- so the terminal that was stuck stayed stuck,
        because nothing ever decided it was not running.
        """
        prefix = tz.bottle_for(1)
        command, environ = self._proc(["start.exe", "/exec", "terminal64.exe"], prefix)
        assert not tz.is_terminal(command, environ, prefix)

    def test_another_accounts_terminal_does_not(self, bottles):
        command, environ = self._proc(
            [r"C:\Program Files\MetaTrader 5\terminal64.exe"], tz.bottle_for(2)
        )
        assert not tz.is_terminal(command, environ, tz.bottle_for(1))

    def test_one_prefix_is_not_the_prefix_of_another(self, bottles):
        """tz-1 must never match tz-11: that would kill a working account."""
        command, environ = self._proc(
            [r"C:\Program Files\MetaTrader 5\terminal64.exe"], tz.bottle_for(11)
        )
        assert not tz.is_terminal(command, environ, tz.bottle_for(1))


class TestStrayPids:
    def test_our_own_process_is_never_a_stray(self, bottles, monkeypatch):
        """A cleanup that can kill the thing doing the cleaning is not one."""
        prefix = tz.bottle_for(1)
        mine = os.getpid()
        monkeypatch.setattr(
            tz,
            "_procs",
            lambda: [(mine, f'sh\0-c\0export WINEPREFIX="{prefix}"'.encode(), b"")],
        )
        assert tz.stray_pids(prefix) == []

    def test_a_sandbox_wrapper_is_a_stray(self, bottles, monkeypatch):
        """They have no WINEPREFIX in the environment -- only in the command.

        Six of these were left behind on this project's own machine by starts
        that failed days apart. A stale wineserver among them stops the next
        launch dead, so they are what "clear it up and try again" has to mean.
        """
        prefix = tz.bottle_for(1)
        monkeypatch.setattr(
            tz,
            "_procs",
            lambda: [(4242, f'bwrap\0sh\0-c\0export WINEPREFIX="{prefix}"'.encode(), b"")],
        )
        assert tz.stray_pids(prefix) == [4242]

    def test_a_running_terminal_is_not_a_stray(self, bottles, monkeypatch):
        prefix = tz.bottle_for(1)
        monkeypatch.setattr(
            tz,
            "_procs",
            lambda: [(7, b"terminal64.exe\0/portable", f"WINEPREFIX={prefix}\0".encode())],
        )
        assert tz.stray_pids(prefix) == []


# --- what happens to a terminal that will not work ----------------------------


class TestRecycle:
    """Restart, then rebuild, then stop and say so -- and never loop."""

    def setup_method(self):
        self.spec = {"account_id": 5, "login": "22609000", "server": "VantageInternational-Live"}
        self.plan = tz.Plan("http://127.0.0.1:8420/api", "k", [], {})

    def _run(self, tmp, state):
        prefix = tz.bottle_for(5)
        prefix.mkdir(exist_ok=True)
        tz.recycle(self.spec, prefix, state, "it stopped reporting in", self.plan)
        return prefix, tz.load_state(5)

    def test_the_first_answer_is_a_restart(self, bottles, monkeypatch):
        stopped = []
        monkeypatch.setattr(tz, "stop_terminal", lambda prefix, **_: stopped.append(prefix))
        prefix, state = self._run(bottles, {})
        assert stopped == [prefix]
        assert prefix.exists(), "a restart must not delete the install"
        assert state["restarts"] == 1

    def test_restarting_twice_over_is_a_broken_install(self, bottles, monkeypatch):
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: None)
        prefix, state = self._run(bottles, {"restarts": tz.RESTARTS_BEFORE_REBUILD})
        assert not prefix.exists(), "the prefix is rebuilt from the template"
        assert state["rebuilds"] == 1
        assert state["restarts"] == 0, "the ladder starts again on the new install"

    def test_eventually_it_stops_and_asks_for_a_person(self, bottles, monkeypatch, caplog):
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: None)
        prefix, state = self._run(
            bottles,
            {"restarts": tz.RESTARTS_BEFORE_REBUILD, "rebuilds": tz.REBUILDS_BEFORE_GIVING_UP},
        )
        assert state["gave_up"] is True
        assert prefix.exists(), "nothing is deleted once we have stopped trying"
        assert "--reset 22609000" in caplog.text, "it has to say what to do next"

    def test_a_terminal_that_starts_reporting_is_forgiven(self, bottles, monkeypatch):
        """Otherwise one bad week eventually spends every rebuild it had."""
        prefix = tz.bottle_for(5)
        prefix.mkdir()
        tz.save_state(5, {"login": "22609000", "restarts": 2, "rebuilds": 1})
        spec = dict(self.spec, last_seen=NOW.isoformat())
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        tz.supervise(spec, self.plan, prefix, tz.load_state(5))
        assert "restarts" not in tz.load_state(5)
        assert "rebuilds" not in tz.load_state(5)


class _FrozenClock:
    def __init__(self, now):
        self._now = now

    def now(self, tz=None):  # noqa: A002 - matching datetime's own signature
        return self._now

    def fromisoformat(self, value):
        return datetime.fromisoformat(value)


class TestSupervise:
    def setup_method(self):
        self.plan = tz.Plan("http://127.0.0.1:8420/api", "k", [], {})

    def test_silence_is_not_judged_before_we_have_been_listening(
        self, bottles, monkeypatch
    ):
        """The site being down must not restart every terminal at once.

        Nothing can record a poll while the server is unreachable, so on the
        first cycle after it comes back every terminal looks like it has gone
        quiet. Acting on that turns a minute of downtime into an outage.
        """
        prefix = tz.bottle_for(6)
        prefix.mkdir()
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        spec = {
            "account_id": 6,
            "login": "1",
            "server": "s",
            "last_seen": (NOW - timedelta(hours=1)).isoformat(),
        }
        tz.supervise(spec, self.plan, prefix, {"launched": (NOW - timedelta(days=1)).isoformat()},
                     settled=False)
        assert tz.load_state(6).get("restarts") is None

    def test_a_terminal_that_never_reported_gets_its_permission_granted(
        self, bottles, monkeypatch
    ):
        prefix = tz.bottle_for(7)
        prefix.mkdir()
        tried = []
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        monkeypatch.setattr(tz, "allow_webrequest", lambda login, url, display="": tried.append(login))
        spec = {"account_id": 7, "login": "9", "server": "s"}
        state = {"launched": (NOW - timedelta(hours=1)).isoformat()}
        tz.supervise(spec, self.plan, prefix, state)
        assert tried == ["9"]
        assert tz.load_state(7)["webrequest_attempts"] == 1

    def test_the_permission_is_not_retried_for_ever(self, bottles, monkeypatch):
        """It used to be tried once and then never again, which is worse.

        The retry lived in the branch that only ran in the cycle a terminal was
        started, so the count could not reach two. Now it climbs, and then the
        prefix itself is suspected.
        """
        prefix = tz.bottle_for(8)
        prefix.mkdir()
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        monkeypatch.setattr(tz, "allow_webrequest", lambda *a: pytest.fail("gave up too late"))
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: None)
        spec = {"account_id": 8, "login": "9", "server": "s"}
        state = {
            "launched": (NOW - timedelta(hours=1)).isoformat(),
            "webrequest_attempts": tz.WEBREQUEST_ATTEMPTS,
        }
        tz.supervise(spec, self.plan, prefix, state)
        assert tz.load_state(8)["restarts"] == 1

    def test_a_refused_login_is_not_retried(self, bottles, monkeypatch):
        """None of the rungs types a different password.

        The ladder assumes the install is at fault. When the broker has said
        no, climbing it spends four cycles and twenty minutes to arrive at
        "start failed", which sends whoever reads it to look at the one thing
        that is working.
        """
        prefix = _with_terminal(tz.bottle_for(9))
        _write_log(prefix, "0\t09:15:58.857\tNetwork\t'9': login failed")
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        monkeypatch.setattr(tz, "allow_webrequest", lambda *a, **k: pytest.fail("retried a refusal"))
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: pytest.fail("restarted a refusal"))
        spec = {"account_id": 9, "login": "9", "server": "s"}
        tz.supervise(spec, self.plan, prefix, {"launched": (NOW - timedelta(hours=1)).isoformat()})
        state = tz.load_state(9)
        assert "login failed" in state["login_refused"]
        assert "restarts" not in state

    def test_a_terminal_that_is_merely_silent_is_still_retried(self, bottles, monkeypatch):
        """A log with no verdict in it must not read as a refusal."""
        prefix = _with_terminal(tz.bottle_for(10))
        _write_log(prefix, "0\t09:15:58.857\tTerminal\tMetaTrader 5 build 4620 started")
        tried = []
        monkeypatch.setattr(tz, "datetime", _FrozenClock(NOW))
        monkeypatch.setattr(tz, "allow_webrequest", lambda login, url, display="": tried.append(login))
        spec = {"account_id": 10, "login": "9", "server": "s"}
        tz.supervise(spec, self.plan, prefix, {"launched": (NOW - timedelta(hours=1)).isoformat()})
        assert tried == ["9"]
        assert "login_refused" not in tz.load_state(10)


# --- what the terminal's own log says about logging in ------------------------


def _with_terminal(prefix: Path) -> Path:
    """A prefix with a MetaTrader in it, where ``terminal_dir`` will find one."""
    (prefix / "drive_c" / "Program Files" / "MT5").mkdir(parents=True, exist_ok=True)
    (prefix / "drive_c" / "Program Files" / "MT5" / "terminal64.exe").touch()
    return prefix


def _write_log(prefix: Path, *lines: str, name: str = "20260802.log") -> Path:
    """Write a terminal log as MetaTrader writes one: UTF-16, CRLF, in logs/."""
    logs = prefix / "drive_c" / "Program Files" / "MT5" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / name
    path.write_bytes("\r\n".join(lines).encode("utf-16"))
    return path


class TestLoginEvidence:
    """Whether MetaTrader ever got a session, read from its own log.

    Nothing else can tell. A terminal with no session has no account for an
    Expert Advisor to run against, so the one component that reports to
    TradeZulu is the one that cannot say the login was refused -- and an
    account with no session reports an equity of zero, which read as
    funded-and-flat.
    """

    def test_an_authorized_account_is_authorized(self, tmp_path):
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(
            prefix,
            "KK\t0\t09:15:58.857\tNetwork\t'22609000': authorized on "
            "VantageMarkets-Live through Access Point 1",
        )
        verdict, evidence = tz.login_evidence(tz.terminal_dir(prefix), "22609000")
        assert verdict == "authorized"
        assert "authorized on VantageMarkets-Live" in evidence

    @pytest.mark.parametrize(
        "line",
        [
            "0\t09:15:58.857\tNetwork\t'176249607': login failed",
            "0\t09:15:58.857\tNetwork\t'176249607': authorization failed",
            "0\t09:15:58.857\tNetwork\t'176249607': invalid account",
            "0\t09:15:58.857\tNetwork\t'176249607': invalid password",
            "0\t09:15:58.857\tNetwork\t'176249607': account disabled",
            "0\t09:15:58.857\tNetwork\t'176249607': access denied",
        ],
    )
    def test_every_way_a_broker_says_no(self, tmp_path, line):
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(prefix, line)
        verdict, evidence = tz.login_evidence(tz.terminal_dir(prefix), "176249607")
        assert verdict == "refused"
        assert "\t" not in evidence, "the message is read by people, not by columns"

    def test_the_forum_login_is_not_the_trade_login(self, tmp_path):
        """This line appears in a perfectly healthy terminal.

        It is the MQL5 community account, it has nothing to do with trading,
        and matching the words alone would halt every terminal on the machine.
        What keeps it out is that it names no account.
        """
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(prefix, "JO\t2\t05:17:45.314\tMQL5.community\tauthorization failed")
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000")[0] == "silent"

    def test_another_accounts_refusal_is_not_ours(self, tmp_path):
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(prefix, "0\t09:15:58.857\tNetwork\t'999': login failed")
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000")[0] == "silent"

    def test_the_last_word_wins(self, tmp_path):
        """A password changed at the broker leaves both lines in the log."""
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(
            prefix,
            "0\t08:00:00.000\tNetwork\t'22609000': authorized on Live through Access Point 1",
            "0\t09:00:00.000\tNetwork\t'22609000': invalid password",
        )
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000")[0] == "refused"

    def test_a_refusal_yesterday_does_not_outrank_a_login_today(self, tmp_path):
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(prefix, "0\t09:00:00.000\tNetwork\t'22609000': invalid password",
                   name="20260801.log")
        _write_log(prefix, "0\t09:00:00.000\tNetwork\t'22609000': authorized on Live",
                   name="20260802.log")
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000")[0] == "authorized"

    def test_the_compilers_log_is_not_the_terminals(self, tmp_path):
        """metaeditor.log sorts after every date, so it would be read instead."""
        prefix = _with_terminal(tmp_path / "tz-1")
        _write_log(prefix, "0\t09:00:00.000\tNetwork\t'22609000': invalid password")
        _write_log(prefix, "irrelevant", name="metaeditor.log")
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000")[0] == "refused"

    def test_a_terminal_with_no_log_says_nothing(self, tmp_path):
        prefix = _with_terminal(tmp_path / "tz-1")
        assert tz.login_evidence(tz.terminal_dir(prefix), "22609000") == ("silent", "")

    def test_no_terminal_at_all_says_nothing(self):
        assert tz.login_evidence(None, "22609000") == ("silent", "")


# --- clearing up accounts that are gone ---------------------------------------


class TestReap:
    def _plan(self, known):
        return tz.Plan("u", "k", [], {}, known_accounts=known)

    def test_a_forgotten_accounts_terminal_is_removed(self, bottles, monkeypatch):
        """What "Forget account" could not do on its own.

        The rows went and the MetaTrader install stayed: running, logged in,
        polling an account the server no longer had, and holding the prefix
        name the next account added would be given.
        """
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: None)
        monkeypatch.setattr(tz, "clear_strays", lambda *a, **k: 0)
        kept, gone = tz.bottle_for(1), tz.bottle_for(2)
        kept.mkdir()
        gone.mkdir()
        tz.save_state(2, {"login": "22609000"})

        tz.reap(self._plan({1}))

        assert kept.exists()
        assert not gone.exists()
        assert tz.load_state(2) == {}

    def test_templates_are_never_touched(self, bottles, monkeypatch):
        monkeypatch.setattr(tz, "stop_terminal", lambda *a, **k: None)
        template = bottles / "bottles/tz-template-vantage"
        template.mkdir()
        tz.reap(self._plan(set()))
        assert template.exists(), "every account is a copy of this"

    def test_a_server_that_does_not_say_gets_nothing_removed(self, bottles):
        """"Not in the plan" is also what an account with no password looks like."""
        prefix = tz.bottle_for(3)
        prefix.mkdir()
        tz.reap(self._plan(None))
        assert prefix.exists()


class TestOneTerminalPerAccount:
    """Two terminals on one account is the failure that costs money."""

    def _plan(self, *logins):
        return tz.Plan(
            "u",
            "k",
            [
                {"account_id": index + 1, "login": login, "server": "S",
                 "password": "p", "enabled": True}
                for index, login in enumerate(logins)
            ],
            {},
        )

    def test_the_same_login_twice_gets_one_terminal(self, bottles, monkeypatch, caplog):
        """It happened: an imported statement created a second master row.

        Both rows are the same broker account, so both terminals log into it
        and both run the Expert Advisor -- and every copied order is placed
        twice.
        """
        started = []
        monkeypatch.setattr(tz, "ensure_terminal", lambda spec, *a, **k: started.append(spec["account_id"]))
        monkeypatch.setattr(tz, "reap", lambda plan: None)

        tz.reconcile(self._plan("22609000", "22609000"), Path("/template"), Path("/expert"))

        assert started == [1]
        assert "both 22609000" in caplog.text

    def test_different_accounts_each_get_one(self, bottles, monkeypatch):
        started = []
        monkeypatch.setattr(tz, "ensure_terminal", lambda spec, *a, **k: started.append(spec["account_id"]))
        monkeypatch.setattr(tz, "reap", lambda plan: None)

        tz.reconcile(self._plan("111", "222"), Path("/template"), Path("/expert"))

        assert started == [1, 2]

    def test_a_launch_in_flight_is_not_launched_again(self, bottles, monkeypatch):
        """There is no terminal process yet while MetaTrader is starting.

        The sandbox is up and the terminal is not, which is indistinguishable
        from "nothing is running" unless the launch is remembered -- and the
        next cycle would start a second one.
        """
        prefix = tz.bottle_for(1)
        prefix.mkdir()
        (prefix / "drive_c").mkdir()
        (prefix / "drive_c/terminal64.exe").write_bytes(b"")
        monkeypatch.setattr(tz, "is_running", lambda bottle: False)
        monkeypatch.setattr(tz, "stray_pids", lambda bottle: [4242])
        monkeypatch.setattr(tz, "launch", lambda *a: pytest.fail("started a second terminal"))
        monkeypatch.setattr(tz, "install_expert", lambda *a: None)

        tz.save_state(1, {"login": "9", "launched": _minutes_ago(1)})
        tz.ensure_terminal(
            {"account_id": 1, "login": "9", "server": "S", "password": "p"},
            tz.Plan("u", "k", [], {}),
            Path("/template"),
            Path("/expert"),
        )

    def test_a_launch_that_never_arrived_is_cleared_and_retried(self, bottles, monkeypatch):
        prefix = tz.bottle_for(1)
        prefix.mkdir()
        (prefix / "drive_c").mkdir()
        (prefix / "drive_c/terminal64.exe").write_bytes(b"")
        cleared, launched = [], []
        monkeypatch.setattr(tz, "is_running", lambda bottle: False)
        monkeypatch.setattr(tz, "stray_pids", lambda bottle: [4242])
        monkeypatch.setattr(tz, "clear_strays", lambda bottle, **k: cleared.append(bottle))
        monkeypatch.setattr(tz, "install_expert", lambda *a: None)
        monkeypatch.setattr(tz, "launch", lambda *a: launched.append(a))
        monkeypatch.setattr(tz, "write_startup", lambda *a, **k: None)
        monkeypatch.setattr(tz.time, "sleep", lambda seconds: None)

        tz.save_state(1, {"login": "9", "launched": _minutes_ago(30)})
        tz.ensure_terminal(
            {"account_id": 1, "login": "9", "server": "S", "password": "p"},
            tz.Plan("u", "k", [], {}),
            Path("/template"),
            Path("/expert"),
        )

        assert cleared, "the stuck launch has to be cleared before another is started"
        assert launched


def _minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class TestResolveTargets:
    """What someone typed, turned into prefixes on disk."""

    def test_an_account_number_is_what_a_person_knows(self, bottles):
        tz.bottle_for(5).mkdir()
        tz.save_state(5, {"login": "22609000"})
        assert tz.resolve_targets(["22609000"], "http://nowhere", "") == {5}

    def test_the_row_id_works_too(self, bottles):
        tz.bottle_for(5).mkdir()
        assert tz.resolve_targets(["5"], "http://nowhere", "") == {5}

    def test_all_means_every_terminal_but_no_template(self, bottles):
        tz.bottle_for(1).mkdir()
        tz.bottle_for(2).mkdir()
        (bottles / "bottles/tz-template-default").mkdir()
        assert tz.resolve_targets(["all"], "http://nowhere", "") == {1, 2}

    def test_a_name_nobody_has_matches_nothing(self, bottles, caplog):
        assert tz.resolve_targets(["nonsense"], "http://nowhere", "") == set()
        assert "nonsense" in caplog.text

    def test_resetting_says_so_rather_than_pretending(self, bottles):
        assert tz.reset(["nonsense"], "http://nowhere", "") == 1


class TestPlan:
    def test_an_older_server_is_understood(self):
        assert tz.Plan("u", "k", [], {}).known_accounts is None


# --- reusing a compiled expert ------------------------------------------------


class TestBuildKey:
    def _terminal(self, tmp_path, source: bytes, exe_size: int) -> tuple[Path, Path]:
        terminal = tmp_path / "terminal"
        terminal.mkdir(parents=True, exist_ok=True)
        (terminal / "terminal64.exe").write_bytes(b"x" * exe_size)
        mq5 = terminal / "TradeZuluCopier.mq5"
        mq5.write_bytes(source)
        return terminal, mq5

    def test_the_same_source_and_build_share_a_binary(self, tmp_path):
        first, mq5 = self._terminal(tmp_path / "a", b"source", 1000)
        second, other = self._terminal(tmp_path / "b", b"source", 1000)
        assert tz.build_key(mq5, first) == tz.build_key(other, second)

    def test_a_changed_source_does_not(self, tmp_path):
        first, mq5 = self._terminal(tmp_path / "a", b"source", 1000)
        second, other = self._terminal(tmp_path / "b", b"source v2", 1000)
        assert tz.build_key(mq5, first) != tz.build_key(other, second)

    def test_a_different_terminal_build_does_not(self, tmp_path):
        """MetaTrader refuses bytecode from a newer MetaEditor than itself."""
        first, mq5 = self._terminal(tmp_path / "a", b"source", 1000)
        second, other = self._terminal(tmp_path / "b", b"source", 2000)
        assert tz.build_key(mq5, first) != tz.build_key(other, second)

    def test_a_built_expert_is_used_instead_of_building_again(self, tmp_path, monkeypatch):
        terminal, mq5 = self._terminal(tmp_path / "a", b"source", 1000)
        tz.BUILDS.mkdir(parents=True)
        (tz.BUILDS / f"TradeZuluCopier-{tz.build_key(mq5, terminal)}.ex5").write_bytes(b"built")
        monkeypatch.setattr(tz, "compile_expert", lambda *a: pytest.fail("compiled again"))

        tz.provide_binary(terminal, mq5)

        assert mq5.with_suffix(".ex5").read_bytes() == b"built"

    def test_the_first_build_is_kept_for_the_next_terminal(self, tmp_path, monkeypatch):
        terminal, mq5 = self._terminal(tmp_path / "a", b"source", 1000)
        monkeypatch.setattr(
            tz, "compile_expert", lambda t, m: m.with_suffix(".ex5").write_bytes(b"fresh")
        )

        tz.provide_binary(terminal, mq5)

        assert (tz.BUILDS / f"TradeZuluCopier-{tz.build_key(mq5, terminal)}.ex5").exists()


class TestACompileThatHangs:
    """A slow compile must not become a broken account.

    MetaEditor can sit on something nobody is there to answer. The timeout
    used to come out of here as an exception, through install_expert and
    ensure_terminal, so the account was abandoned for the cycle -- no terminal
    started, nothing logged in -- and the next cycle spent the same five
    minutes reaching the same place. Starting the terminal is what would have
    fixed it, because a terminal compiles the sources it finds, and starting
    the terminal was the step being skipped.
    """

    def _terminal(self, tmp_path) -> tuple[Path, Path]:
        terminal = tmp_path / "bottle" / "drive_c" / "MT5"
        terminal.mkdir(parents=True)
        (terminal / "terminal64.exe").write_bytes(b"x" * 1000)
        (terminal / "MetaEditor64.exe").write_bytes(b"editor")
        mq5 = terminal / "TradeZuluCopier.mq5"
        mq5.write_bytes(b"source")
        return terminal, mq5

    def _hang(self, monkeypatch):
        def timeout(*args, **kwargs):
            raise tz.subprocess.TimeoutExpired(cmd="metaeditor", timeout=tz.COMPILE_TIMEOUT)

        monkeypatch.setattr(tz.subprocess, "run", timeout)
        monkeypatch.setattr(tz, "_runner", lambda: "/wine")

    def test_it_is_reported_rather_than_raised(self, tmp_path, monkeypatch, caplog):
        terminal, mq5 = self._terminal(tmp_path)
        self._hang(monkeypatch)
        monkeypatch.setattr(tz, "_kill_editors", lambda bottle: 0)

        tz.compile_expert(terminal, mq5)  # must not raise

        assert "did not finish" in caplog.text
        assert not mq5.with_suffix(".ex5").exists()

    def test_the_hung_editor_is_killed(self, tmp_path, monkeypatch):
        """Or every cycle adds another one, each holding the prefix open.

        subprocess kills the shell it started, not the Wine process that shell
        started.
        """
        terminal, mq5 = self._terminal(tmp_path)
        self._hang(monkeypatch)
        killed = []
        monkeypatch.setattr(tz, "_kill_editors", lambda bottle: killed.append(bottle) or 1)

        tz.compile_expert(terminal, mq5)

        assert killed == [tmp_path / "bottle"], "the prefix, not the terminal directory"

    def test_what_wine_said_is_kept(self, tmp_path, monkeypatch):
        """The launch used to go to /dev/null, so a MetaEditor that refused to
        start and one that sat on a dialog were the same five-minute silence."""
        terminal, mq5 = self._terminal(tmp_path)
        seen = {}
        monkeypatch.setattr(tz, "_runner", lambda: "/wine")
        monkeypatch.setattr(
            tz.subprocess, "run",
            lambda argv, **kw: seen.update(script=argv[-1]),
        )

        tz.compile_expert(terminal, mq5)

        assert "/dev/null" not in seen["script"]
        assert str(tz.BUILDS) in seen["script"]


class TestTerminalStatus:
    """What the journal is told a terminal is doing.

    The provisioner has always known the difference between installing,
    starting, retrying and having given up -- it acts on it every cycle -- and
    never said so anywhere the user could see. All of it reads as "no terminal
    yet" until this leaves the machine.
    """

    @staticmethod
    def _status(tmp_path, spec=None, state=None, exists=True):
        bottle = tmp_path / "tz-1"
        if exists:
            (bottle / "drive_c" / "Program Files" / "MT5").mkdir(parents=True)
            (bottle / "drive_c" / "Program Files" / "MT5" / "terminal64.exe").touch()
        return tz.terminal_status(
            {"account_id": 1, "login": "5000", **(spec or {})},
            bottle,
            state or {},
            datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        )

    def test_a_terminal_that_is_reporting_is_running(self, tmp_path):
        status = self._status(
            tmp_path, spec={"last_seen": "2026-08-05T11:59:50+00:00"}
        )
        assert status["phase"] == "running"

    def test_no_metatrader_yet_is_installing(self, tmp_path):
        """The first start of an account builds a whole Wine prefix."""
        status = self._status(tmp_path, exists=False)
        assert status["phase"] == "installing"
        assert "few minutes" in status["message"]

    def test_freshly_launched_is_starting(self, tmp_path):
        status = self._status(
            tmp_path, state={"launched": "2026-08-05T11:59:30+00:00"}
        )
        assert status["phase"] == "starting"

    def test_being_retried_says_how_many_times(self, tmp_path):
        status = self._status(
            tmp_path,
            state={"launched": "2026-08-05T10:00:00+00:00", "restarts": 2},
        )
        assert status["phase"] == "retrying"
        assert status["attempts"] == 2

    def test_given_up_is_a_failure_with_something_to_do(self, tmp_path):
        status = self._status(tmp_path, state={"gave_up": True, "restarts": 2, "rebuilds": 2})
        assert status["phase"] == "failed"
        assert "Forget" in status["message"]
        assert status["attempts"] == 4

    def test_a_refused_login_says_so_and_quotes_the_broker(self, tmp_path):
        status = self._status(tmp_path, state={"login_refused": "'9': invalid password"})
        assert status["phase"] == "rejected"
        assert "invalid password" in status["message"], "say what MetaTrader said"

    def test_a_refused_login_outranks_having_given_up(self, tmp_path):
        """Both are true at once, and only one of them says what to fix.

        "Start failed" sends whoever reads it to look at the install, which is
        the one part of a refused login that is working.
        """
        status = self._status(
            tmp_path, state={"gave_up": True, "login_refused": "'9': invalid account"}
        )
        assert status["phase"] == "rejected"

    def test_one_that_worked_and_stopped_is_quiet(self, tmp_path):
        status = self._status(
            tmp_path,
            spec={"last_seen": "2026-08-05T09:00:00+00:00"},
            state={"launched": "2026-08-05T08:00:00+00:00"},
        )
        assert status["phase"] == "quiet"

    def test_running_beats_a_stale_failure(self, tmp_path):
        """Only gave_up outranks it: anything reporting in is working."""
        status = self._status(
            tmp_path,
            spec={"last_seen": "2026-08-05T11:59:50+00:00"},
            state={"restarts": 2, "rebuilds": 1},
        )
        assert status["phase"] == "running"
        assert status["attempts"] == 0


class TestOneScreenPerAccount:
    """Every terminal draws on a display of its own.

    One screen for all of them was fine while nobody could look at it. The
    moment a terminal can be watched from the web interface it is a privacy
    boundary: whoever may see account 3 must not be shown account 4's open
    positions because the two windows are stacked in the same place.
    """

    def test_each_account_gets_its_own(self, monkeypatch):
        monkeypatch.setattr(tz, "DISPLAY", ":77")
        assert tz.display_for(1) == ":78"
        assert tz.display_for(2) == ":79"

    def test_the_port_follows_the_display(self, monkeypatch):
        monkeypatch.setattr(tz, "DISPLAY", ":77")
        assert tz.vnc_port_for(tz.display_for(1)) == 5978
        assert tz.vnc_port_for(tz.display_for(2)) == 5979

    def test_a_display_somewhere_else_cannot_be_multiplied(self, monkeypatch):
        """``host:N`` is another machine's screen, and there is no second one."""
        monkeypatch.setattr(tz, "DISPLAY", "127.0.0.1:77")
        assert tz.display_for(1) == "127.0.0.1:77"
        assert tz.vnc_port_for(tz.display_for(1)) is None


class TestRestartingOneTerminal:
    """Asked for in the web interface, carried out here.

    Only stopping is done: the reconcile that recovers a terminal which died
    on its own starts it again, so there is no second way to start one.
    """

    def _spec(self, token=""):
        return {
            "account_id": 1, "login": "9", "server": "S", "password": "p",
            "enabled": True, "restart_token": token,
        }

    def _prefix(self):
        prefix = tz.bottle_for(1)
        prefix.mkdir(parents=True)
        (prefix / "drive_c").mkdir()
        (prefix / "drive_c/terminal64.exe").write_bytes(b"")
        return prefix

    def test_a_new_token_stops_the_terminal(self, monkeypatch):
        self._prefix()
        stopped = []
        monkeypatch.setattr(tz, "is_running", lambda bottle: True)
        monkeypatch.setattr(tz, "stop_terminal", lambda bottle: stopped.append(bottle))
        tz.save_state(1, {"login": "9", "display": tz.display_for(1)})

        tz.ensure_terminal(self._spec("2026-08-11T09:00:00"), tz.Plan("u", "k", [], {}),
                           Path("/template"), Path("/expert"))

        assert len(stopped) == 1
        assert tz.load_state(1)["restart_token"] == "2026-08-11T09:00:00"

    def test_the_same_token_twice_restarts_once(self, monkeypatch):
        """Remembered rather than acknowledged, so a plan re-read is harmless."""
        self._prefix()
        stopped = []
        monkeypatch.setattr(tz, "is_running", lambda bottle: True)
        monkeypatch.setattr(tz, "stop_terminal", lambda bottle: stopped.append(bottle))
        monkeypatch.setattr(tz, "supervise", lambda *a, **k: None)
        tz.save_state(1, {"login": "9", "display": tz.display_for(1)})

        for _ in range(2):
            tz.ensure_terminal(self._spec("2026-08-11T09:00:00"), tz.Plan("u", "k", [], {}),
                               Path("/template"), Path("/expert"))

        assert len(stopped) == 1

    def test_no_token_stops_nothing(self, monkeypatch):
        self._prefix()
        monkeypatch.setattr(tz, "is_running", lambda bottle: True)
        monkeypatch.setattr(tz, "stop_terminal", lambda bottle: pytest.fail("stopped"))
        monkeypatch.setattr(tz, "supervise", lambda *a, **k: None)
        tz.save_state(1, {"login": "9", "display": tz.display_for(1)})

        tz.ensure_terminal(self._spec(), tz.Plan("u", "k", [], {}),
                           Path("/template"), Path("/expert"))


class TestUpgradingFromOneSharedScreen:
    """Terminals started before per-account displays are on the wrong one.

    Nothing about such a terminal is unhealthy, so supervision leaves it alone
    for ever -- and Inspect on the accounts page would show whatever else is
    stacked on the shared screen, which is the one thing per-account displays
    exist to prevent.
    """

    def _prefix(self):
        prefix = tz.bottle_for(1)
        prefix.mkdir(parents=True)
        (prefix / "drive_c").mkdir()
        (prefix / "drive_c/terminal64.exe").write_bytes(b"")
        return prefix

    def _run(self, monkeypatch, state):
        self._prefix()
        stopped = []
        monkeypatch.setattr(tz, "DISPLAY", ":77")
        monkeypatch.setattr(tz, "is_running", lambda bottle: True)
        monkeypatch.setattr(tz, "stop_terminal", lambda bottle: stopped.append(bottle))
        monkeypatch.setattr(tz, "supervise", lambda *a, **k: stopped.append("supervised"))
        tz.save_state(1, state)
        tz.ensure_terminal(
            {"account_id": 1, "login": "9", "server": "S", "password": "p", "enabled": True},
            tz.Plan("u", "k", [], {}), Path("/template"), Path("/expert"),
        )
        return stopped

    def test_a_terminal_from_before_is_stopped_once(self, monkeypatch):
        """No display recorded means it was started on the shared one."""
        assert self._run(monkeypatch, {"login": "9"}) == [tz.bottle_for(1)]

    def test_one_already_on_its_own_screen_is_left_alone(self, monkeypatch):
        assert self._run(monkeypatch, {"login": "9", "display": ":78"}) == ["supervised"]

    def test_the_screen_it_started_on_is_remembered(self, monkeypatch, tmp_path):
        """Or the next upgrade cannot tell what needs moving."""
        monkeypatch.setattr(tz, "DISPLAY", ":77")
        monkeypatch.setattr(tz, "is_running", lambda bottle: False)
        monkeypatch.setattr(tz, "stray_pids", lambda bottle: [])
        monkeypatch.setattr(tz, "clear_strays", lambda bottle: None)
        monkeypatch.setattr(tz, "install_expert", lambda *a: None)
        monkeypatch.setattr(tz, "launch", lambda *a, **k: None)
        monkeypatch.setattr(tz, "terminal_dir", lambda bottle: bottle / "drive_c")
        self._prefix()
        tz.save_state(1, {"login": "9"})

        tz.ensure_terminal(
            {"account_id": 1, "login": "9", "server": "S", "password": "p", "enabled": True},
            tz.Plan("u", "k", [], {}), Path("/template"), Path("/expert"),
        )

        assert tz.load_state(1)["display"] == ":78"


class TestChartsDoNotPileUp:
    """One EURUSD window per restart, kept for ever by the saved profile.

    The startup file names a symbol and an expert, so every launch opens a new
    chart; MetaTrader saves what was open when it closed and restores it next
    time. Thirty restarts, thirty windows -- and a restored chart keeps its
    expert, which is a second copier on the same account.
    """

    def _terminal(self, charts=("chart01.chr", "chart02.chr")):
        terminal = tz.bottle_for(1) / "drive_c/MT5"
        default = terminal / "Profiles/Charts/Default"
        default.mkdir(parents=True)
        for name in charts:
            (default / name).write_bytes(b"chart")
        return terminal, default

    def test_saved_charts_are_cleared(self):
        terminal, default = self._terminal()
        assert tz.prune_charts(terminal) == 2
        assert list(default.glob("*.chr")) == []

    def test_every_profile_is_cleared_not_just_the_default(self):
        terminal, _ = self._terminal()
        other = terminal / "Profiles/Charts/Market Overview"
        other.mkdir(parents=True)
        (other / "chart01.chr").write_bytes(b"chart")
        assert tz.prune_charts(terminal) == 3

    def test_anything_that_is_not_a_chart_is_left(self):
        """The profile holds more than charts, and the rest is not ours."""
        terminal, default = self._terminal()
        (default / "order.wnd").write_bytes(b"window")
        tz.prune_charts(terminal)
        assert (default / "order.wnd").exists()

    def test_a_terminal_with_no_profile_yet_is_not_an_error(self):
        terminal = tz.bottle_for(1) / "drive_c/MT5"
        terminal.mkdir(parents=True)
        assert tz.prune_charts(terminal) == 0

    def test_launching_clears_them(self, monkeypatch):
        terminal, default = self._terminal()
        monkeypatch.setattr(tz, "_flatpak_spawn", lambda script: None)
        monkeypatch.setattr(tz, "_runner", lambda: Path("/wine"))

        tz.launch(tz.bottle_for(1), terminal, "9", "S", "p", ":78")

        assert list(default.glob("*.chr")) == []


class TestAReusedAccountId:
    """Deleting an account and adding it again must not inherit its prefix.

    SQLite hands out the next rowid as max(rowid) + 1, so the new row takes the
    id the deleted one had -- and a prefix is named after that id. Somebody
    deleting an account normally adds the same one straight back, to get out of
    whatever state it was in, so the id and the login both match and the prefix
    read as its own. The one thing re-adding was meant to clear was the one
    thing that survived it.
    """

    def _spec(self, created_at):
        return {
            "account_id": 5, "login": "176249607",
            "server": "FalconMarkets-Server", "created_at": created_at,
        }

    def test_the_same_login_added_again_gets_a_fresh_prefix(self, bottles, monkeypatch):
        prefix = tz.bottle_for(5)
        prefix.mkdir()
        tz.save_state(5, {"login": "176249607", "created_at": "2026-11-02T15:00:00+00:00"})
        discarded = []
        monkeypatch.setattr(tz, "discard_prefix", lambda b, why: discarded.append(why))

        tz.ensure_terminal(
            self._spec("2026-11-02T15:25:00+00:00"),
            tz.Plan("u", "k", [], {}), prefix.parent / "template", Path("x"),
        )

        assert discarded and "added again" in discarded[0]

    def test_the_same_incarnation_keeps_its_prefix(self, bottles, monkeypatch):
        """Or every cycle would rebuild a terminal that is working."""
        prefix = tz.bottle_for(5)
        prefix.mkdir()
        born = "2026-11-02T15:00:00+00:00"
        tz.save_state(5, {"login": "176249607", "created_at": born})
        monkeypatch.setattr(tz, "discard_prefix", lambda *a: pytest.fail("rebuilt a good prefix"))

        tz.ensure_terminal(
            self._spec(born), tz.Plan("u", "k", [], {}), prefix.parent / "template", Path("x")
        )

    def test_a_prefix_built_before_this_adopts_its_account(self, bottles, monkeypatch):
        """No recorded birthday is not evidence of the wrong one."""
        prefix = tz.bottle_for(5)
        prefix.mkdir()
        tz.save_state(5, {"login": "176249607"})
        monkeypatch.setattr(tz, "discard_prefix", lambda *a: pytest.fail("threw away a good prefix"))

        tz.ensure_terminal(
            self._spec("2026-11-02T15:25:00+00:00"),
            tz.Plan("u", "k", [], {}), prefix.parent / "template", Path("x"),
        )

        assert tz.load_state(5)["created_at"] == "2026-11-02T15:25:00+00:00"
