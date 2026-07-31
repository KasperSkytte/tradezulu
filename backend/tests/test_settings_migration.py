"""Upgrading from a mode that no longer exists."""

from app.services.appsettings import get_app_settings, save_app_settings


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
