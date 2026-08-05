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
        monkeypatch.setattr(tz, "allow_webrequest", lambda login, url: tried.append(login))
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
