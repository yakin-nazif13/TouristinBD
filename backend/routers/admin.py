"""Admin panel API — for the website's owners only.

Every route except `login` needs a valid owner token (`Authorization: Bearer ...`).
The owner's email always comes from the token, never from the request body, so a
decision is recorded under the address that is really signed in. Owners share one
password and each signs in with their own email (see backend/admin_auth.py).

What an owner can do: read pending reviews, approve (a new place also needs a
division) or reject with a reason, and add approved reviews to the dataset. The
last one runs the pipeline in a background thread and reports progress; only one
run can be active at a time.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend import admin_auth, submissions

REPO_ROOT = Path(__file__).resolve().parents[2]

# Packages the pipeline steps need. A slim public deployment may not have them.
PIPELINE_PACKAGES = ("rapidfuzz", "sklearn", "vaderSentiment", "langdetect")


def no_store(response: Response) -> None:
    """Admin responses hold private text; tell browsers and proxies not to keep them."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(no_store)])


def _token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def require_admin(request: Request) -> str:
    """The logged-in owner's name, or a 401."""
    name = admin_auth.sessions.get(_token_of(request))
    if not name:
        raise HTTPException(status_code=401, detail="Please sign in.", headers={"WWW-Authenticate": "Bearer"})
    return name


# --- sign in / out ----------------------------------------------------------


class LoginIn(BaseModel):
    email: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=300)


@router.post("/login")
def login(payload: LoginIn, request: Request) -> dict:
    if not admin_auth.enabled():
        raise HTTPException(
            status_code=503,
            detail="The admin panel is switched off because no owner password and email have been set up yet. "
                   "On the server run: python scripts/manage_admins.py set-password  and  "
                   "python scripts/manage_admins.py add-owner EMAIL",
        )
    client = request.client.host if request.client else "unknown"
    name_key = payload.email.strip().lower()
    if admin_auth.client_guard.blocked(client) or admin_auth.name_guard.blocked(name_key):
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Please wait 15 minutes and try again.")

    name = admin_auth.verify(payload.email, payload.password)
    if not name:
        admin_auth.client_guard.fail(client)
        admin_auth.name_guard.fail(name_key)
        # Same message for "not an owner's email" and "wrong password".
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    admin_auth.name_guard.clear(name_key)
    token, expires = admin_auth.sessions.create(name)
    return {
        "token": token,
        "email": name,
        "expires_at_utc": datetime.fromtimestamp(expires, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "divisions": submissions.DIVISIONS,
    }


@router.post("/logout")
def logout(request: Request, _: str = Depends(require_admin)) -> dict:
    admin_auth.sessions.revoke(_token_of(request))
    return {"ok": True}


@router.get("/me")
def me(name: str = Depends(require_admin)) -> dict:
    return {"email": name, "divisions": submissions.DIVISIONS}


# --- reviews ------------------------------------------------------------------


def _public_record(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "text_hash"}


@router.get("/summary")
def summary(_: str = Depends(require_admin)) -> dict:
    counts = {state: len(list(submissions.folder(state).glob("V*.json"))) for state in submissions.STATES}
    return {"counts": counts, "ingest": _job_snapshot()}


@router.get("/submissions")
def list_reviews(status: str = "pending", _: str = Depends(require_admin)) -> dict:
    if status != "all" and status not in submissions.STATES:
        raise HTTPException(status_code=422, detail=f"status must be one of: all, {', '.join(submissions.STATES)}")
    rows = submissions.list_submissions(None if status == "all" else status)
    return {"status": status, "total": len(rows), "items": [_public_record(r) for r in rows]}


@router.get("/submissions/{submission_id}")
def get_review(submission_id: str, _: str = Depends(require_admin)) -> dict:
    try:
        record, _path = submissions.find(submission_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such review.") from None
    return _public_record(record)


class ApproveIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
    division: str | None = Field(None, max_length=40)
    district: str | None = Field(None, max_length=80)
    city: str | None = Field(None, max_length=80)


class RejectIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


def _decide(submission_id: str, state: str, by: str, reason: str, geography: dict | None = None) -> dict:
    try:
        record = submissions.decide(submission_id, state, by, reason, geography)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such review.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _public_record(record)


@router.post("/submissions/{submission_id}/approve")
def approve(submission_id: str, payload: ApproveIn, name: str = Depends(require_admin)) -> dict:
    geography = {"division": payload.division, "district": payload.district, "city": payload.city}
    return _decide(submission_id, "approved", name, payload.reason, geography)


@router.post("/submissions/{submission_id}/reject")
def reject(submission_id: str, payload: RejectIn, name: str = Depends(require_admin)) -> dict:
    return _decide(submission_id, "rejected", name, payload.reason)


# --- add approved reviews to the dataset ---------------------------------------

_job_lock = threading.Lock()
_job: dict = {"state": "idle"}


def _job_snapshot() -> dict:
    with _job_lock:
        snap = dict(_job)
        snap["steps"] = [dict(s) for s in _job.get("steps", [])]
        snap["log"] = list(_job.get("log", []))[-60:]
        return snap


def _scripts_module():
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("process_submissions")


class IngestIn(BaseModel):
    offline: bool = False       # skip live OpenStreetMap / Wikidata lookups
    skip_funnel: bool = False   # only add + clean; skip the later pipeline steps


def _run_job(by: str, offline: bool, skip_funnel: bool) -> None:
    def report(line: str) -> None:
        with _job_lock:
            _job.setdefault("log", []).append(str(line))
            del _job["log"][:-200]

    def on_step(label: str, status: str, detail: str | None) -> None:
        with _job_lock:
            steps = _job.setdefault("steps", [])
            step = next((s for s in steps if s["label"] == label), None)
            if step is None:
                step = {"label": label, "status": status}
                steps.append(step)
            step["status"] = status
            if detail:
                step["detail"] = detail[-600:]

    try:
        outcome = _scripts_module().run_ingest(offline=offline, skip_funnel=skip_funnel,
                                               report=report, on_step=on_step)
        final = "done" if outcome["ok"] else "failed"
        with _job_lock:
            _job.update(state=final, result=outcome, error=outcome.get("error"),
                        finished_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except Exception as exc:  # the thread must always finish with a visible result
        with _job_lock:
            _job.update(state="failed", error=f"{type(exc).__name__}: {exc}",
                        finished_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@router.post("/ingest", status_code=202)
def start_ingest(payload: IngestIn, name: str = Depends(require_admin)) -> dict:
    if not submissions.list_submissions("approved"):
        raise HTTPException(status_code=400, detail="There are no approved reviews waiting to be added.")
    if not payload.skip_funnel:
        missing = [m for m in PIPELINE_PACKAGES if importlib.util.find_spec(m) is None]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="This server is missing packages the pipeline needs "
                       f"({', '.join(missing)}). Install requirements.txt, or tick \"only add and clean\".",
            )
    with _job_lock:
        if _job.get("state") == "running":
            raise HTTPException(status_code=409, detail="An ingest is already running.")
        _job.clear()
        _job.update(state="running", by=name, offline=payload.offline, skip_funnel=payload.skip_funnel,
                    started_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), steps=[], log=[])
    threading.Thread(target=_run_job, args=(name, payload.offline, payload.skip_funnel), daemon=True).start()
    return _job_snapshot()


@router.get("/ingest/status")
def ingest_status(_: str = Depends(require_admin)) -> dict:
    return _job_snapshot()
