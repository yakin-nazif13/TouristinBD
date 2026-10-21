"""Admin panel tests.

The panel lets the website's owners approve or reject visitor reviews and add the
approved ones to the dataset. The risk it carries is simple: if a visitor can reach
any of it, the approval step is meaningless. So most of this suite is about who is
let in:

  1. accounts: passwords are stored as hashes, never as text; names and passwords
     are validated; sessions expire and can be revoked; failed logins lock out;
  2. the API: with no accounts the panel is off; every admin route (found by reading
     the OpenAPI schema, so a future route cannot be forgotten) refuses a visitor;
     the approver's name comes from the login, not from the request;
  3. adding approved reviews to the dataset in the background: one run at a time,
     progress is visible, the result lands in the dataset;
  4. the page: no stored credentials, no HTML built from visitor text, every route
     and element it uses exists.

Everything runs on temporary copies of the data. Run:
    .venv/bin/python scripts/test_admin.py
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import test_submissions as ts  # noqa: E402  (shared helpers: copy_data, run_script, fingerprint_dir)

DATA_DIR = REPO_ROOT / "data"
PASSED: list[str] = []
FAILED: list[str] = []
PASSWORD = "correct horse battery"   # a TEST password; the real shared password is never in the repo
OWNER, OWNER2, STRANGER = "yakin@example.com", "unaiza@example.com", "stranger@example.com"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def boot(data_dir: Path, users_file: Path):
    """Start the API on `data_dir` with a fresh copy of every backend module."""
    os.environ["TOURISTINBD_DATA_DIR"] = str(data_dir)
    os.environ["TOURISTINBD_ADMIN_USERS_FILE"] = str(users_file)
    for name in [m for m in sys.modules if m == "backend" or m.startswith("backend.") or m == "process_submissions"]:
        del sys.modules[name]
    from fastapi.testclient import TestClient

    main = importlib.import_module("backend.main")
    return (TestClient(main.app), importlib.import_module("backend.admin_auth"),
            importlib.import_module("backend.submissions"))


# ---------------------------------------------------------------------------
# 1. accounts
# ---------------------------------------------------------------------------
def test_accounts(auth, users_file: Path) -> None:
    print("\nthe shared password, owner emails, sessions and lock-out")
    check("with nothing set up the panel is off", not auth.enabled())

    def refused(fn, *args) -> bool:
        try:
            fn(*args)
            return False
        except auth.AuthError:
            return True

    check("a short password is refused", refused(auth.set_shared_password, "short"))
    for bad in ("not-an-email", "a@b", "@example.com", "two words@example.com", ""):
        check(f"the email {bad!r} is refused", refused(auth.add_owner, bad))

    auth.set_shared_password(PASSWORD)
    check("a password alone does not switch the panel on (no owners yet)", not auth.enabled())
    auth.add_owner(OWNER)
    check("a password plus an owner email switches it on", auth.enabled())
    text = users_file.read_text(encoding="utf-8")
    check("the password is not stored as text", PASSWORD not in text and "horse" not in text, "")
    check("a salted hash is stored instead", '"hash"' in text and '"salt"' in text)
    mode = stat.S_IMODE(users_file.stat().st_mode)
    check("the accounts file is readable by its owner only", mode & 0o077 == 0, oct(mode))
    check("the same email twice is refused (any capitalisation)", refused(auth.add_owner, OWNER.upper()))
    check("emails are stored in lower case", auth.add_owner(OWNER2.upper()) == OWNER2)

    check("a registered email plus the right password signs in", auth.verify(OWNER, PASSWORD) == OWNER)
    check("the email is not case-sensitive", auth.verify(OWNER.upper(), PASSWORD) == OWNER)
    check("the other owner signs in with the same password", auth.verify(OWNER2, PASSWORD) == OWNER2)
    check("a wrong password is refused", auth.verify(OWNER, PASSWORD + "x") is None)
    check("the right password with an UNREGISTERED email is refused", auth.verify(STRANGER, PASSWORD) is None)
    check("an empty password is refused", auth.verify(OWNER, "") is None)
    check("a malformed email is refused, not an error", auth.verify("not an email", PASSWORD) is None)

    token, _ = auth.sessions.create(OWNER)
    auth.set_shared_password("a brand new passphrase")
    check("changing the password signs everyone out", auth.sessions.get(token) is None)
    check("the new password works and the old one does not",
          auth.verify(OWNER, "a brand new passphrase") == OWNER and auth.verify(OWNER, PASSWORD) is None)
    auth.set_shared_password(PASSWORD)

    clock = {"now": 1000.0}
    sessions = auth.Sessions(lifetime=60, clock=lambda: clock["now"])
    token, _ = sessions.create(OWNER)
    check("a token maps to its owner's email", sessions.get(token) == OWNER)
    check("only a hash of the token is kept", token not in sessions._by_hash, "token held in clear")
    check("an unknown token is refused", sessions.get("nonsense") is None and sessions.get(None) is None)
    clock["now"] += 61
    check("a token stops working after its lifetime", sessions.get(token) is None)
    t2, _ = sessions.create(OWNER)
    sessions.revoke(t2)
    check("a revoked token stops working", sessions.get(t2) is None)
    t3, _ = sessions.create(OWNER2)
    sessions.revoke_user(OWNER2.upper())
    check("removing an owner logs them out", sessions.get(t3) is None)

    guard = auth.LoginGuard(limit=3, window=100, clock=lambda: clock["now"])
    for _ in range(3):
        guard.fail("k")
    check("repeated failures lock a key out", guard.blocked("k"))
    check("…but not other keys", not guard.blocked("other"))
    clock["now"] += 101
    check("the lock-out ends after its window", not guard.blocked("k"))
    guard.fail("k")
    guard.clear("k")
    check("a successful login clears the count", not guard.blocked("k") and not guard._fails.get("k"))

    auth.remove_owner(OWNER2)
    check("an owner can be removed", auth.verify(OWNER2, PASSWORD) is None
          and [o["email"] for o in auth.list_owners()] == [OWNER])
    check("removing someone who is not an owner is refused", refused(auth.remove_owner, STRANGER))


def test_manage_command(tmp: Path) -> None:
    print("\nthe manage_admins command")
    env = {**os.environ, "TOURISTINBD_ADMIN_USERS_FILE": str(tmp / "cli_users.json")}
    run = lambda *a: subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "manage_admins.py"), *a],
                                    cwd=REPO_ROOT, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    r = run("list")
    check("list with nothing set up says the panel is off", r.returncode == 0 and "OFF" in r.stdout and "NOT SET" in r.stdout, r.stdout)
    r = run("add-owner", "not-an-email")
    check("a bad email is refused", r.returncode == 1 and "valid email" in r.stdout, r.stdout)
    r = run("add-owner", "Someone@Example.com")
    check("an owner email can be added", r.returncode == 0 and "someone@example.com" in r.stdout, r.stdout)
    r = run("list")
    check("list shows the owner and that no password is set", "someone@example.com" in r.stdout and "NOT SET" in r.stdout, r.stdout)
    r = run("remove-owner", "nobody@example.com")
    check("removing a missing owner fails clearly", r.returncode == 1 and "not an owner" in r.stdout, r.stdout)
    r = run("remove-owner", "someone@example.com")
    check("an owner can be removed", r.returncode == 0, r.stdout)
    help_text = run("--help").stdout + run("set-password", "--help").stdout
    check("there is no way to pass the password on the command line", "--password" not in help_text, help_text)


# ---------------------------------------------------------------------------
# 2. the API
# ---------------------------------------------------------------------------
def test_api(client, auth, subs, data: Path) -> dict:
    print("\nthe admin API")
    real_before = ts.fingerprint_dir(DATA_DIR)
    subs.limiter.limit = 1000
    auth.client_guard.reset()
    auth.name_guard.reset()

    r = client.post("/api/admin/login", json={"email": OWNER, "password": PASSWORD})
    check("with nothing set up, login says the panel is off (503)", r.status_code == 503 and "manage_admins" in r.text,
          f"{r.status_code} {r.text[:150]}")

    auth.set_shared_password(PASSWORD)
    auth.add_owner(OWNER)
    auth.add_owner(OWNER2)
    r1 = client.post("/api/admin/login", json={"email": OWNER, "password": "wrong password!"})
    r2 = client.post("/api/admin/login", json={"email": STRANGER, "password": "wrong password!"})
    r3 = client.post("/api/admin/login", json={"email": STRANGER, "password": PASSWORD})
    check("a wrong password is 401", r1.status_code == 401, str(r1.status_code))
    check("an email that is not an owner's gives the identical answer", r2.status_code == 401 and r1.json() == r2.json(),
          f"{r1.text} / {r2.text}")
    check("the RIGHT password with a non-owner email is still refused, with the same answer",
          r3.status_code == 401 and r3.json() == r1.json(), f"{r3.status_code} {r3.text}")
    check("an empty login is rejected (422)", client.post("/api/admin/login", json={"email": "", "password": ""}).status_code == 422)

    # every admin route, found from the schema, must refuse a visitor
    paths = client.get("/openapi.json").json()["paths"]
    admin_routes = [(m.upper(), p) for p, methods in paths.items() if p.startswith("/api/admin/") for m in methods
                    if p != "/api/admin/login"]
    check("the schema lists the admin routes", len(admin_routes) >= 9, str(admin_routes))
    leaks = []
    for method, path in admin_routes:
        url = path.replace("{submission_id}", "V20261006T101500-ab12cd")
        for headers in ({}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic Zm9vOmJhcg=="}, {"Authorization": "Bearer"}):
            resp = client.request(method, url, headers=headers, json={"reason": "x"} if method == "POST" else None)
            if resp.status_code != 401:
                leaks.append((method, path, headers, resp.status_code))
    check("EVERY admin route answers 401 without a valid token", not leaks, str(leaks[:3]))

    r = client.post("/api/admin/login", json={"email": OWNER.upper(), "password": PASSWORD})
    check("a registered email and the shared password sign in", r.status_code == 200, r.text[:150])
    login = r.json()
    token = login["token"]
    auth_h = {"Authorization": f"Bearer {token}"}
    check("login returns the divisions for the form", "Sylhet" in login["divisions"] and login["email"] == OWNER, str(login))
    check("login responses are not cacheable", "no-store" in r.headers.get("cache-control", ""), str(r.headers))
    me = client.get("/api/admin/me", headers=auth_h)
    check("a valid token is accepted", me.status_code == 200 and me.json()["email"] == OWNER, me.text)
    check("admin responses are not cacheable", "no-store" in me.headers.get("cache-control", ""), str(me.headers))

    pre = client.options("/api/admin/summary", headers={
        "Origin": "https://example.org", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    check("a browser on another site may send the Authorization header",
          pre.status_code == 200 and "authorization" in pre.headers.get("access-control-allow-headers", "").lower(),
          str(pre.headers))

    # lock-out: five wrong guesses stop even the right password for a while
    auth.client_guard.reset()
    auth.name_guard.reset()
    for _ in range(5):
        client.post("/api/admin/login", json={"email": OWNER, "password": "guess guess guess"})
    locked = client.post("/api/admin/login", json={"email": OWNER, "password": PASSWORD})
    check("five failures lock the account out (429)", locked.status_code == 429, str(locked.status_code))
    auth.client_guard.reset()
    auth.name_guard.reset()
    check("a real owner can sign in again once the lock ends",
          client.post("/api/admin/login", json={"email": OWNER, "password": PASSWORD}).status_code == 200)

    # visitors send reviews through the public form
    def visit(**body):
        base = {"place_name": "Lalbagh Fort", "is_new_place": False, "district": None, "rating": 5, "website": ""}
        return client.post("/api/submissions", json={**base, **body})

    ids = {}
    for key, body in {
        "plain": dict(review_text=ts.BANGLA),
        "new": dict(place_name="Chandpai Quiet Channels", is_new_place=True, district="Bagerhat", rating=4,
                    review_text=ts.NEW_PLACE_TEXT),
        "spam": dict(review_text="Buy cheap watches from my shop, best prices anywhere in the country!"),
        "later": dict(review_text="A calm afternoon in the gardens, the guide explained the history very well."),
    }.items():
        resp = visit(**body)
        ids[key] = resp.json()["id"]
        check(f"a visitor review is accepted ({key})", resp.status_code == 202, resp.text[:150])

    summary = client.get("/api/admin/summary", headers=auth_h).json()
    check("the summary counts the pending reviews", summary["counts"]["pending"] == 4, str(summary))
    listing = client.get("/api/admin/submissions", headers=auth_h).json()
    check("the owner can read pending reviews in full", listing["total"] == 4 and
          any(i["review_text"] == ts.BANGLA for i in listing["items"]), str(listing)[:200])
    check("the stored fingerprint is not exposed", all("text_hash" not in i for i in listing["items"]))
    check("an unknown status filter is refused (422)",
          client.get("/api/admin/submissions?status=bogus", headers=auth_h).status_code == 422)
    one = client.get(f"/api/admin/submissions/{ids['plain']}", headers=auth_h)
    check("one review can be opened", one.status_code == 200 and one.json()["id"] == ids["plain"])
    check("an unknown id is 404", client.get("/api/admin/submissions/V20000101T000000-aaaaaa", headers=auth_h).status_code == 404)
    check("a path-traversal id is 404, not a file read",
          client.get("/api/admin/submissions/..%2F..%2Fetc%2Fpasswd", headers=auth_h).status_code in (404, 422))
    check("the public API still cannot list pending reviews",
          client.get("/api/submissions").status_code in (404, 405))

    def approve(sid, **body):
        return client.post(f"/api/admin/submissions/{sid}/approve", headers=auth_h, json=body)

    r = approve(ids["plain"])
    check("approving without a reason is refused (422)", r.status_code == 422, str(r.status_code))
    r = approve(ids["plain"], reason="   ")
    check("a blank reason is refused (422)", r.status_code == 422, r.text[:150])
    r = approve(ids["new"], reason="real place")
    check("approving a new place without a division is refused (422)",
          r.status_code == 422 and "division" in r.text, r.text[:150])
    r = approve(ids["plain"], reason="genuine review", by="Mallory")
    rec = r.json()
    check("approving works", r.status_code == 200 and rec["status"] == "approved", r.text[:150])
    check("the approver's EMAIL is recorded, whatever the request claims",
          rec["decisions"][-1]["by"] == OWNER, str(rec["decisions"]))
    r = approve(ids["new"], reason="real place, on the map", division="Khulna", district="Bagerhat", city="Mongla")
    check("a new place is approved with its location",
          r.status_code == 200 and r.json()["geography"] == {"division": "Khulna", "district": "Bagerhat", "city": "Mongla"},
          r.text[:200])
    other = client.post("/api/admin/login", json={"email": OWNER2, "password": PASSWORD}).json()
    other_h = {"Authorization": f"Bearer {other['token']}"}
    check("a second owner signs in with the same password and their own email", other.get("email") == OWNER2, str(other)[:150])
    r = client.post(f"/api/admin/submissions/{ids['spam']}/reject", headers=other_h, json={"reason": "advertising"})
    check("rejecting works", r.status_code == 200 and r.json()["status"] == "rejected", r.text[:150])
    check("the rejection shows the second owner's own email", r.json()["decisions"][-1]["by"] == OWNER2, str(r.json()["decisions"]))
    seen = client.get(f"/api/admin/submissions/{ids['plain']}", headers=other_h).json()
    check("every owner sees who made each decision", seen["decisions"][-1]["by"] == OWNER, str(seen["decisions"]))
    check("rejecting needs a reason (422)",
          client.post(f"/api/admin/submissions/{ids['later']}/reject", headers=auth_h, json={}).status_code == 422)
    after = client.get("/api/admin/summary", headers=auth_h).json()["counts"]
    check("the counts follow the decisions", (after["pending"], after["approved"], after["rejected"]) == (1, 2, 1), str(after))
    check("nothing reached the dataset yet",
          client.get("/api/overview").json()["total_reviews"] == len(pd.read_csv(data / "processed_reviews.csv")), "")

    out = client.post("/api/admin/logout", headers=auth_h)
    check("signing out works", out.status_code == 200)
    check("a signed-out token no longer works", client.get("/api/admin/me", headers=auth_h).status_code == 401)

    login2 = client.post("/api/admin/login", json={"email": OWNER, "password": PASSWORD}).json()
    h2 = {"Authorization": f"Bearer {login2['token']}"}
    real_clock = auth.sessions.clock
    auth.sessions.clock = lambda: time.time() + auth.SESSION_SECONDS + 5
    check("a token expires after its lifetime", client.get("/api/admin/me", headers=h2).status_code == 401)
    auth.sessions.clock = real_clock
    check("the real data folder was not touched", ts.fingerprint_dir(DATA_DIR) == real_before, "")
    final = client.post("/api/admin/login", json={"email": OWNER, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {final['token']}"}, "ids": ids}


# ---------------------------------------------------------------------------
# 3. adding approved reviews to the dataset
# ---------------------------------------------------------------------------
def wait_for(client, headers, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/admin/ingest/status", headers=headers).json()
        if status["state"] != "running":
            return status
        time.sleep(0.5)
    return {"state": "timeout"}


def test_ingest(client, auth, subs, data: Path, ctx: dict) -> None:
    print("\nadding approved reviews to the dataset from the panel")
    headers, ids = ctx["headers"], ctx["ids"]
    router = importlib.import_module("backend.routers.admin")
    uploads = data / "visitor_uploads"

    r = client.post("/api/admin/ingest", json={})
    check("starting a run needs a login (401)", r.status_code == 401)

    real_find = router.importlib.util.find_spec
    router.importlib.util.find_spec = lambda name, *a, **k: None if name == "rapidfuzz" else real_find(name, *a, **k)
    r = client.post("/api/admin/ingest", headers=headers, json={})
    router.importlib.util.find_spec = real_find
    check("missing pipeline packages give a clear message, not a half-run",
          r.status_code == 400 and "rapidfuzz" in r.text and "only add and clean" in r.text, r.text[:200])
    check("…and nothing was started", client.get("/api/admin/ingest/status", headers=headers).json()["state"] == "idle")

    # another run already holds the lock (e.g. started from the command line)
    lock = uploads / ".ingest.lock"
    lock.write_text("123 test\n")
    started = client.post("/api/admin/ingest", headers=headers, json={"skip_funnel": True, "offline": True})
    final = wait_for(client, headers)
    lock.unlink()
    check("a run that finds the lock held fails cleanly",
          started.status_code == 202 and final["state"] == "failed" and "already running" in (final.get("error") or ""),
          str(final)[:300])
    check("…and leaves the approved reviews where they were",
          len(list((uploads / "approved").glob("V*.json"))) == 2, "")

    stack = all(importlib.util.find_spec(m) for m in ("rapidfuzz", "sklearn", "vaderSentiment"))
    body = {"offline": True, "skip_funnel": not stack}
    if not stack:
        print("  NOTE  pipeline packages missing here: running the panel's ingest without the later steps")
    r = client.post("/api/admin/ingest", headers=headers, json=body)
    check("starting a run answers 202 and is running", r.status_code == 202 and r.json()["state"] == "running", r.text[:200])
    again = client.post("/api/admin/ingest", headers=headers, json=body)
    check("a second run while one is active is refused (409)", again.status_code == 409, f"{again.status_code} {again.text[:120]}")
    status = wait_for(client, headers)
    check("the run finishes successfully", status["state"] == "done", str(status)[:500])
    if status["state"] != "done":
        return
    check("progress was reported step by step",
          status["steps"] and all(s["status"] == "ok" for s in status["steps"]), str(status["steps"]))
    check("the result says what was added", status["result"]["added"] == 2 and status["result"]["new_places"] == ["Chandpai Quiet Channels"],
          str(status["result"]))
    check("approved reviews moved to ingested/", len(list((uploads / "ingested").glob("V*.json"))) == 2
          and not list((uploads / "approved").glob("V*.json")), "")
    check("the lock is released afterwards", not (uploads / ".ingest.lock").exists())

    corpus = pd.read_csv(data / "processed_reviews.csv")
    check("the approved reviews are in the dataset", {ids["plain"], ids["new"]} <= set(corpus["review_id"].astype(str)), "")
    check("the rejected and pending ones are not", not ({ids["spam"], ids["later"]} & set(corpus["review_id"].astype(str))), "")
    summary = client.get("/api/admin/summary", headers=headers).json()["counts"]
    check("the counts show them as added", summary["ingested"] == 2 and summary["approved"] == 0, str(summary))
    r = client.post(f"/api/admin/submissions/{ids['plain']}/reject", headers=headers, json={"reason": "too late"})
    check("a review already in the dataset cannot be changed (422)", r.status_code == 422, str(r.status_code))
    r = client.post("/api/admin/ingest", headers=headers, json=body)
    check("with nothing approved there is nothing to run (400)", r.status_code == 400, r.text[:150])

    if stack:
        names = {p["place_name"]: p for p in client.get("/api/places", params={"limit": 500}).json()["items"]}
        check("the new place is on the site with the division the owner chose",
              names.get("Chandpai Quiet Channels", {}).get("division") == "Khulna", str(names.get("Chandpai Quiet Channels")))
        reviews = client.get("/api/reviews", params={"place": "Lalbagh Fort", "limit": 500}).json()["items"]
        check("the Bangla review is on the site", any(ts.BANGLA in (x.get("review_text_clean") or "") for x in reviews), "")


# ---------------------------------------------------------------------------
# 4. the page
# ---------------------------------------------------------------------------
def test_page(client) -> None:
    print("\nthe admin page")
    html = (REPO_ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    r = client.get("/admin", follow_redirects=False)
    check("/admin redirects to the page", r.status_code in (302, 307) and r.headers.get("location") == "/app/admin.html",
          f"{r.status_code} {r.headers.get('location')}")
    r = client.get("/app/admin.html")
    check("the page is served", r.status_code == 200 and "Owner panel" in r.text, str(r.status_code))
    check("search engines are told to ignore it", 'name="robots" content="noindex' in html)
    public = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'<a [^>]*href="[^"]*admin[^"]*"[^>]*>([^<]*)</a>', public)
    check("the public site has exactly one, discreet link to it (the footer's 'Owner login')",
          links == ["Owner login"] and "api/admin" not in public, str(links))
    check("visitor text is never put through innerHTML", not re.search(r"\.innerHTML\s*[+]?=", html), "innerHTML assignment found")
    check("no external scripts or stylesheets", not re.search(r'(?:src|href)="https?://', html), "")
    check("the token lives in sessionStorage, not localStorage",
          "sessionStorage.setItem(TOKEN_KEY" in html and not re.search(r"localStorage\.setItem\(\s*TOKEN_KEY", html), "")
    check("no password, key or token is written into the page",
          not re.search(r"(password|secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/_\-]{8,}['\"]", html, re.I), "")

    schema = client.get("/openapi.json").json()["paths"]
    used = set(re.findall(r"api\(\s*'(/api/admin/[^'?]+)", html)) | {
        p.split("${")[0].rstrip("/") for p in re.findall(r"api\(\s*`(/api/admin/[^`]+)`", html)}
    used = {u.rstrip("/") for u in used}  # '/api/admin/submissions/' + id + '/approve' is built at run time
    missing = [u for u in sorted(used) if not any(p == u or p.startswith(u + "/") for p in schema)]
    check("every route the page calls exists", used and not missing, f"{missing} of {sorted(used)}")
    ids = set(re.findall(r"getElementById\(\s*'([^']+)'\s*\)", html))
    declared = set(re.findall(r'\bid="([^"]+)"', html))
    check("every element the script touches exists", not (ids - declared), str(sorted(ids - declared)))


def main() -> None:
    print("Admin panel tests\n")
    real_before = ts.fingerprint_dir(DATA_DIR)
    accounts_before = (DATA_DIR / "admin_users.json").read_bytes() if (DATA_DIR / "admin_users.json").exists() else None
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        data = ts.copy_data(tmp / "data")
        build = ts.run_script("build_phase8_database.py", data_dir=data)
        if build.returncode != 0:
            print("could not build the starting database:", build.stderr[-400:])
            sys.exit(1)
        users_file = tmp / "admin_users.json"
        client, auth, subs = boot(data, users_file)
        test_accounts(auth, users_file)
        users_file.unlink()
        test_manage_command(tmp)
        client, auth, subs = boot(data, users_file)
        ctx = test_api(client, auth, subs, data)
        test_ingest(client, auth, subs, data, ctx)
        test_page(client)
    check("the real data folder is exactly as it was", ts.fingerprint_dir(DATA_DIR) == real_before, "")
    accounts_after = (DATA_DIR / "admin_users.json").read_bytes() if (DATA_DIR / "admin_users.json").exists() else None
    check("the real accounts file (if any) was not touched by the tests", accounts_after == accounts_before, "")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All admin panel tests passed.")


if __name__ == "__main__":
    main()
