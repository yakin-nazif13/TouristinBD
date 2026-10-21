"""Owner login for the admin panel.

The public site has no logins. This module adds one for the people who own the
site, so that approving a visitor's review cannot be done by the visitor.

How it works
    * The owners share ONE password. It is stored only as a salted scrypt hash.
    * Each owner signs in with their own email address plus that password. Only
      emails on the owners' list may sign in, so knowing the password is not
      enough. The email is what is recorded next to every approval or rejection.
    * Logging in gives a random token that lasts a few hours. The admin page
      sends it in an `Authorization: Bearer ...` header. No cookies are used, so
      another website cannot make a visitor's browser act as an owner.
    * Tokens live in memory only, so restarting the server logs everyone out.
    * With no password or no owner emails, the admin panel is switched off.

A shared password means the email is a label, not proof: anyone who knows the
password and a registered email can sign in as that owner. That is the trade-off
of one shared password; per-owner passwords would remove it.

Only the standard library is used.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MIN_PASSWORD = 10
MAX_PASSWORD = 200
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s.]{2,}$")
SESSION_SECONDS = 8 * 3600
LOGIN_FAILURE_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60

# scrypt cost. 2**14 is the usual interactive setting (about 16 MB, tens of ms).
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class AuthError(ValueError):
    """Bad input to an account operation. The message is safe to show."""


# --- the accounts file ------------------------------------------------------
#
#   {"shared_password": {"salt": ..., "hash": ..., "params": ..., "created_utc": ...},
#    "owners": {"someone@example.com": {"email": ..., "added_utc": ...}}}


def users_file() -> Path:
    override = os.environ.get("TOURISTINBD_ADMIN_USERS_FILE")
    if override:
        return Path(override)
    data = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
    return data / "admin_users.json"


def _hash(password: str, salt: bytes, params: dict | None = None) -> bytes:
    p = params or _SCRYPT
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=p["n"], r=p["r"], p=p["p"],
                          dklen=p["dklen"], maxmem=128 * 1024 * 1024)


def _load() -> dict:
    path = users_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = users_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)  # only the owner of the file may read it
    except OSError:
        pass
    temp.replace(path)


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.match(value):
        raise AuthError("Please enter a valid email address.")
    return value


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"The password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AuthError(f"The password must be at most {MAX_PASSWORD} characters.")


def set_shared_password(password: str) -> None:
    """Set (or change) the one password every owner uses. Signs everyone out."""
    _check_password(password)
    salt = secrets.token_bytes(16)
    data = _load()
    data["shared_password"] = {
        "salt": salt.hex(),
        "hash": _hash(password, salt).hex(),
        "params": dict(_SCRYPT),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    data.setdefault("owners", {})
    _save(data)
    sessions.clear()


def add_owner(email: str) -> str:
    """Allow this email to sign in. Returns the normalised address."""
    address = normalize_email(email)
    data = _load()
    owners = data.setdefault("owners", {})
    if address in owners:
        raise AuthError(f"{address} is already an owner.")
    owners[address] = {"email": address, "added_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save(data)
    return address


def remove_owner(email: str) -> None:
    address = normalize_email(email)
    data = _load()
    if address not in data.get("owners", {}):
        raise AuthError(f"{address} is not an owner.")
    del data["owners"][address]
    _save(data)
    sessions.revoke_user(address)


def list_owners() -> list[dict]:
    return [{"email": o["email"], "added_utc": o.get("added_utc", "")} for o in _load().get("owners", {}).values()]


def has_password() -> bool:
    return bool(_load().get("shared_password"))


def enabled() -> bool:
    """The panel is on only when a shared password and at least one owner email exist."""
    data = _load()
    return bool(data.get("shared_password")) and bool(data.get("owners"))


# A fixed throw-away record, so an unregistered email costs the same time as a
# wrong password. Otherwise response time would reveal which emails are owners.
_DUMMY_SALT = bytes(16)
_DUMMY_HASH = _hash("not-a-real-password", _DUMMY_SALT)


def verify(email: str, password: str) -> str | None:
    """The owner's email when the email is registered and the password is right, else None."""
    password = (password or "")[:MAX_PASSWORD]
    data = _load()
    try:
        address = normalize_email(email)
    except AuthError:
        address = None
    shared = data.get("shared_password")
    if not address or address not in data.get("owners", {}) or not shared:
        hmac.compare_digest(_hash(password, _DUMMY_SALT), _DUMMY_HASH)
        return None
    try:
        expected = bytes.fromhex(shared["hash"])
        candidate = _hash(password, bytes.fromhex(shared["salt"]), shared.get("params"))
    except (KeyError, ValueError):
        return None
    return address if hmac.compare_digest(candidate, expected) else None


# --- sessions ---------------------------------------------------------------


class Sessions:
    """Logged-in owners, in memory. A token maps to a name and an expiry time."""

    def __init__(self, lifetime: int = SESSION_SECONDS, clock=time.time) -> None:
        self.lifetime = lifetime
        self.clock = clock
        self._by_hash: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> str:
        # Only a hash of the token is kept, so it cannot be read back out of memory.
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, name: str) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        expires = self.clock() + self.lifetime
        with self._lock:
            self._by_hash[self._digest(token)] = (name, expires)
            self._purge()
        return token, expires

    def get(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            entry = self._by_hash.get(self._digest(token))
            if not entry:
                return None
            name, expires = entry
            if expires <= self.clock():
                self._by_hash.pop(self._digest(token), None)
                return None
            return name

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._by_hash.pop(self._digest(token), None)

    def revoke_user(self, name: str) -> None:
        with self._lock:
            for key in [k for k, (n, _) in self._by_hash.items() if n.strip().lower() == name.strip().lower()]:
                del self._by_hash[key]

    def clear(self) -> None:
        with self._lock:
            self._by_hash.clear()

    def _purge(self) -> None:
        now = self.clock()
        for key in [k for k, (_, exp) in self._by_hash.items() if exp <= now]:
            del self._by_hash[key]


class LoginGuard:
    """Locks a key out after too many failed logins within a window.

    Used twice: per client address (stops one machine trying many names) and per
    account name (stops many machines trying one account). Failures are counted,
    not attempts, so a real owner is not locked out by logging in normally.
    """

    def __init__(self, limit: int = LOGIN_FAILURE_LIMIT, window: int = LOGIN_WINDOW_SECONDS, clock=time.time) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = self.clock()
        return [t for t in self._fails.get(key, []) if now - t < self.window]

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key] = self._recent(key) + [self.clock()]
            if len(self._fails) > 5000:
                self._fails = {k: v for k, v in self._fails.items() if self._recent(k)}

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


sessions = Sessions()
client_guard = LoginGuard(limit=LOGIN_FAILURE_LIMIT * 2)
name_guard = LoginGuard()
