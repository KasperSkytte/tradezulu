"""The maintenance commands, which are the way back in after a lockout."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.cli import main
from app.models import User
from app.security import hash_password, verify_password


@pytest.fixture()
def one_user(db):
    db.query(User).delete()
    db.add(User(username="kasper", password_hash=hash_password("original-password")))
    db.commit()
    return db


def reload_user(db, username: str) -> User | None:
    db.expire_all()
    return db.scalar(select(User).where(User.username == username))


class TestSetPassword:
    def test_sets_the_password_of_the_only_user_without_naming_it(self, one_user):
        assert main(["set-password", "--password", "a-new-password"]) == 0

        user = reload_user(one_user, "kasper")
        assert verify_password("a-new-password", user.password_hash)

    def test_names_a_user_explicitly(self, one_user):
        assert main(["set-password", "--username", "kasper", "--password", "another-one"]) == 0
        assert verify_password("another-one", reload_user(one_user, "kasper").password_hash)

    def test_matching_a_username_ignores_case(self, one_user):
        assert main(["set-password", "--username", "KASPER", "--password", "case-test-pw"]) == 0
        # The name is applied as given, and no second user appears.
        assert reload_user(one_user, "KASPER") is not None
        assert one_user.query(User).count() == 1

    def test_creates_the_user_when_the_name_is_unknown(self, one_user):
        assert main(["set-password", "--username", "newcomer", "--password", "brand-new-pw"]) == 0

        user = reload_user(one_user, "newcomer")
        assert user is not None
        assert verify_password("brand-new-pw", user.password_hash)

    def test_renames_an_existing_user(self, one_user):
        """The lockout case: the env var says one name, the database another."""
        code = main(
            [
                "set-password",
                "--username", "kapper",
                "--rename-from", "kasper",
                "--password", "renamed-password",
            ]
        )
        assert code == 0

        assert reload_user(one_user, "kasper") is None
        user = reload_user(one_user, "kapper")
        assert user is not None
        assert verify_password("renamed-password", user.password_hash)
        # Still one user: a rename must not leave the old one behind.
        assert one_user.query(User).count() == 1

    def test_renaming_from_an_unknown_user_fails_without_changing_anything(self, one_user):
        code = main(
            [
                "set-password",
                "--username", "kapper",
                "--rename-from", "nobody",
                "--password", "should-not-apply",
            ]
        )
        assert code == 1
        assert reload_user(one_user, "kasper") is not None
        assert reload_user(one_user, "kapper") is None

    def test_a_short_password_is_refused(self, one_user):
        assert main(["set-password", "--password", "short"]) == 2
        # And the old one still works.
        assert verify_password("original-password", reload_user(one_user, "kasper").password_hash)

    def test_existing_sessions_are_invalidated(self, one_user):
        before = reload_user(one_user, "kasper").token_version

        main(["set-password", "--password", "a-fresh-password"])

        assert reload_user(one_user, "kasper").token_version > before

    def test_ambiguous_without_a_username_when_several_users_exist(self, one_user):
        one_user.add(User(username="second", password_hash=hash_password("second-password")))
        one_user.commit()

        assert main(["set-password", "--password", "which-user-though"]) == 1
        # Neither was touched.
        assert verify_password("original-password", reload_user(one_user, "kasper").password_hash)


class TestListUsers:
    def test_lists_them(self, one_user, capsys):
        assert main(["list-users"]) == 0
        assert "kasper" in capsys.readouterr().out


class TestLoginAfterReset:
    def test_the_new_password_actually_logs_in(self, client, one_user):
        main(["set-password", "--username", "kapper", "--rename-from", "kasper",
              "--password", "works-in-the-app"])

        response = client.post(
            "/api/auth/login",
            json={"username": "kapper", "password": "works-in-the-app"},
        )
        assert response.status_code == 200

    def test_the_old_password_stops_working(self, client, one_user):
        main(["set-password", "--password", "replaced-password"])

        response = client.post(
            "/api/auth/login",
            json={"username": "kasper", "password": "original-password"},
        )
        assert response.status_code == 401
