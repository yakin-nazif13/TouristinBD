"""Set up who may use the admin panel.

The owners share ONE password, and each signs in with their own email address.
The panel is switched off until a password is set and at least one owner email is
added. The email is what the panel records next to every approval or rejection.

    .venv/bin/python scripts/manage_admins.py set-password            # the shared password
    .venv/bin/python scripts/manage_admins.py add-owner someone@example.com
    .venv/bin/python scripts/manage_admins.py list
    .venv/bin/python scripts/manage_admins.py remove-owner someone@example.com

The password is typed at a hidden prompt (never on the command line, where it would
end up in your shell history) and must be at least 10 characters. Only a salted scrypt
hash is saved, in data/admin_users.json, which git ignores. Never commit that file.

Only registered emails can sign in, so knowing the password is not enough. Changing the
password signs everyone out; removing an owner signs that owner out. No restart needed.

Because the password is shared, an email proves nothing by itself: anyone who knows the
password and a registered email can sign in as that owner. Tell owners to keep the
password private, and change it whenever someone leaves.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend import admin_auth  # noqa: E402


def ask_password() -> str | None:
    first = getpass.getpass(f"New shared password (at least {admin_auth.MIN_PASSWORD} characters): ")
    if getpass.getpass("Type it again: ") != first:
        print("error: the two passwords did not match")
        return None
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("set-password")
    sub.add_parser("add-owner").add_argument("email")
    sub.add_parser("remove-owner").add_argument("email")
    sub.add_parser("list")
    args = parser.parse_args()

    try:
        if args.command == "list":
            owners = admin_auth.list_owners()
            print("shared password:", "set" if admin_auth.has_password() else "NOT SET")
            if not owners:
                print("owners: none yet — the admin panel is off. Add one:  manage_admins.py add-owner EMAIL")
            for owner in owners:
                print(f"owner: {owner['email']}   (added {owner['added_utc']})")
            print("admin panel:", "ON" if admin_auth.enabled() else "OFF")
        elif args.command == "set-password":
            password = ask_password()
            if password is None:
                return 1
            admin_auth.set_shared_password(password)
            print("shared password saved. Everyone has been signed out.")
        elif args.command == "add-owner":
            print(f"added {admin_auth.add_owner(args.email)}")
            if not admin_auth.has_password():
                print("No shared password yet — run:  manage_admins.py set-password")
        else:
            admin_auth.remove_owner(args.email)
            print(f"removed {args.email}")
    except admin_auth.AuthError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
