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


class TestTheChartWindowInDays:
    """The window around a trade was a bar count and is now days.

    A bar count meant a different length of time at every timeframe -- 144 bars
    was twelve hours at M5 and most of a month at H4 -- so there is no faithful
    conversion from the old setting. It is dropped rather than mistranslated,
    and the defaults describe the same window the terminal was already
    collecting: a day either side.
    """

    def test_the_defaults_are_a_day_either_side(self, db):
        charts = get_app_settings(db)["charts"]
        assert charts["history_days_before"] == 1.0
        assert charts["history_days_after"] == 1.0

    def test_the_old_bar_counts_decide_nothing(self, db):
        """They sit in the document until the next save prunes them.

        Nothing reads them any more, so the window is the new default rather
        than a bar count reinterpreted as days -- which would have turned 144
        into a 144-day window on the first upgrade.
        """
        db.add(Setting(key=SETTINGS_KEY, value={"charts": {"candles_before": 144}}))
        db.flush()

        charts = get_app_settings(db)["charts"]

        assert charts["history_days_before"] == 1.0

    def test_they_are_gone_once_anything_is_saved(self, db):
        db.add(Setting(key=SETTINGS_KEY, value={"charts": {"candles_before": 144}}))
        db.flush()

        save_app_settings(db, {"charts": {"history_days_before": 2}})

        assert "candles_before" not in get_app_settings(db)["charts"]

    def test_a_chosen_window_is_kept(self, db):
        save_app_settings(db, {"charts": {"history_days_before": 5, "zoom_hours": 4}})
        charts = get_app_settings(db)["charts"]
        assert charts["history_days_before"] == 5
        assert charts["zoom_hours"] == 4


class TestTheRetiredChartProvider:
    """One of the two stored-candle charts was removed.

    "local" drew the same bars with a different library and did strictly less
    with them -- price lines across the whole chart instead of the position,
    fills snapped to the nearest bar, no drawing tools. Anyone whose setting
    still names it, or names "studio" from before the survivor was renamed
    after the library it uses, must land on the chart that replaced it rather
    than on a provider nothing implements.
    """

    def test_the_default_is_klinecharts(self, db):
        assert get_app_settings(db)["charts"]["provider"] == "klinecharts"

    def test_the_old_replay_chart_maps_across(self, db):
        db.add(Setting(key=SETTINGS_KEY, value={"charts": {"provider": "local"}}))
        db.flush()
        assert get_app_settings(db)["charts"]["provider"] == "klinecharts"

    def test_so_does_its_old_name(self, db):
        db.add(Setting(key=SETTINGS_KEY, value={"charts": {"provider": "studio"}}))
        db.flush()
        assert get_app_settings(db)["charts"]["provider"] == "klinecharts"

    def test_tradingview_is_left_alone(self, db):
        save_app_settings(db, {"charts": {"provider": "tradingview"}})
        assert get_app_settings(db)["charts"]["provider"] == "tradingview"
