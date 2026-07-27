"""Small maintenance commands, run inside the container.

The one that matters is ``set-password``. The admin user is created from
``TZ_ADMIN_USER`` / ``TZ_ADMIN_PASSWORD`` on the first start and never again,
which is the right behaviour — the password can be changed in the app, and a
restart must not quietly undo that. The cost is that editing those variables
later looks like it should work and does nothing, so there has to be an
obvious way to set the credentials from outside.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from .db import SessionLocal
from .models import User
from .security import hash_password


def set_password(username: str | None, password: str, rename_from: str | None = None) -> int:
    """Set a user's password, creating the user when it does not exist."""
    if len(password) < 8:
        print("The password must be at least 8 characters.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        users = list(db.scalars(select(User).order_by(User.id)))

        if rename_from:
            user = db.scalar(
                select(User).where(func.lower(User.username) == rename_from.lower())
            )
            if user is None:
                print(f"No user named {rename_from!r}.", file=sys.stderr)
                _print_users(users)
                return 1
        elif username:
            user = db.scalar(
                select(User).where(func.lower(User.username) == username.lower())
            )
        elif len(users) == 1:
            # The overwhelmingly common case: one user, and the point is to get
            # back into it. Naming it should not be required.
            user = users[0]
        else:
            print("Several users exist; say which one with --username.", file=sys.stderr)
            _print_users(users)
            return 1

        if user is None:
            user = User(username=username or "admin", password_hash="")
            db.add(user)
            action = "Created"
        else:
            action = "Updated"

        if username:
            user.username = username
        user.password_hash = hash_password(password)
        # Existing sessions must not survive a password reset.
        user.token_version = (user.token_version or 1) + 1
        db.commit()

        print(f"{action} user {user.username!r}. Existing sessions were signed out.")
        return 0


def list_users() -> int:
    with SessionLocal() as db:
        _print_users(list(db.scalars(select(User).order_by(User.id))))
    return 0


def _print_users(users: list[User]) -> None:
    if not users:
        print("No users exist yet.")
        return
    print("Users in this database:")
    for user in users:
        print(f"  {user.username}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradezulu", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    password = sub.add_parser(
        "set-password",
        help="set a user's password, or create the user",
    )
    password.add_argument("--username", help="the username to set or create")
    password.add_argument(
        "--rename-from",
        help="rename an existing user to --username instead of creating a new one",
    )
    password.add_argument("--password", required=True, help="the new password")

    sub.add_parser("list-users", help="show which users exist")

    args = parser.parse_args(argv)

    if args.command == "set-password":
        return set_password(args.username, args.password, args.rename_from)
    if args.command == "list-users":
        return list_users()
    return 1


if __name__ == "__main__":  # pragma: no cover - invoked through the entrypoint
    raise SystemExit(main())
