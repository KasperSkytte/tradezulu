"""Upgrading from a mode that no longer exists."""

from app.models import Setting
from app.services.appsettings import (
    SETTINGS_KEY,
    get_app_settings,
    save_app_settings,
)


class TestRetiredSyncModes:
    def test_bridge_becomes_ea(self, db):
        """An install still set to 'bridge' must not land on a dead mode.

        The containerised terminal it referred to is gone. Left alone, the
        setting would name a mode nothing implements, and the UI would show
        sync as simply broken rather than moved.
        """
        save_app_settings(db, {"mt5": {"sync_mode": "bridge"}})
        assert get_app_settings(db)["mt5"]["sync_mode"] == "ea"

    def test_a_deliberate_choice_is_left_alone(self, db):
        save_app_settings(db, {"mt5": {"sync_mode": "off"}})
        assert get_app_settings(db)["mt5"]["sync_mode"] == "off"


class TestTimesWidenedFromTheChart:
    """The setting was introduced governing the replay chart alone.

    Widening it to every time in the journal renamed it, and a rename is a
    silent way to throw away a choice: the old key stops being read, the new
    one falls back to its default, and someone who had deliberately put the
    journal on their own timezone quietly gets the broker's back.

    The old name is written straight to the row rather than saved through the
    API, because that is the only way it can exist: saving prunes keys the
    schema no longer has, so a value under the old name is by definition one
    that was written before the upgrade.
    """

    @staticmethod
    def _as_stored(db, general: dict) -> None:
        db.add(Setting(key=SETTINGS_KEY, value={"general": general}))
        db.flush()

    def test_a_choice_made_under_the_old_name_is_kept(self, db):
        self._as_stored(db, {"chart_times": "local"})
        assert get_app_settings(db)["general"]["times"] == "local"

    def test_the_broker_was_the_old_default_and_stays_it(self, db):
        self._as_stored(db, {"chart_times": "broker"})
        assert get_app_settings(db)["general"]["times"] == "broker"

    def test_the_new_name_wins_once_it_is_set(self, db):
        self._as_stored(db, {"chart_times": "local", "times": "broker"})
        assert get_app_settings(db)["general"]["times"] == "broker"

    def test_an_install_that_never_saw_the_old_name_gets_the_default(self, db):
        assert get_app_settings(db)["general"]["times"] == "broker"
