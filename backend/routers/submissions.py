"""Visitor review uploads — the web side.

`POST /api/submissions` takes a review typed into the "Share a review" tab and
parks it in its own folder (see backend/submissions.py). Nothing here writes to
the dataset or the database, and nothing here can approve anything: approving
is a deliberate step done by a person with `scripts/process_submissions.py`,
because the API has no logins and an open "approve" button on a public site
would defeat the point of having an approval step.

What the visitor is told is deliberately small: "received, pending". They never
see other people's pending text.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import db, submissions

router = APIRouter(prefix="/api", tags=["submissions"])


class SubmissionIn(BaseModel):
    place_name: str = Field(..., min_length=1, max_length=300)
    is_new_place: bool = False
    district: str | None = Field(None, max_length=200)
    rating: int = Field(..., ge=1, le=5)
    review_text: str = Field(..., min_length=1, max_length=8000)
    # A field real visitors never see. Bots that fill in every input fill this one.
    website: str | None = Field(None, max_length=500)


class SubmissionReceipt(BaseModel):
    id: str
    status: str
    message: str


RECEIVED = "Thank you! Your review was received and will appear in the dataset once it has been checked."


def _known_places(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["place_name"].lower(): r["place_name"] for r in db.rows(conn, "SELECT place_name FROM places")}


@router.get("/submissions/options")
def submission_options(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Everything the form needs: the places to pick from and the input limits."""
    places = db.rows(
        conn,
        "SELECT place_name, city, district, division FROM places ORDER BY place_name COLLATE NOCASE",
    )
    districts = sorted({p["district"] for p in places if p["district"]})
    return {
        "places": places,
        "districts": districts,
        "limits": {
            "min_text": submissions.MIN_TEXT,
            "max_text": submissions.MAX_TEXT,
            "min_rating": 1,
            "max_rating": 5,
        },
    }


@router.post("/submissions", response_model=SubmissionReceipt, status_code=202)
def submit_review(
    payload: SubmissionIn,
    request: Request,
    conn: sqlite3.Connection = Depends(db.get_conn),
) -> SubmissionReceipt:
    """Receive a visitor's review. It is saved as *pending*; it is not published."""
    client = request.client.host if request.client else "unknown"
    if not submissions.limiter.allow(client):
        raise HTTPException(status_code=429, detail="You have sent several reviews already. Please try again later.")

    if payload.website:
        # A bot. Answer exactly like a success so it learns nothing, and save nothing.
        return SubmissionReceipt(id="V0", status="pending", message=RECEIVED)

    try:
        clean = submissions.validate(
            payload.place_name, payload.is_new_place, payload.district,
            payload.rating, payload.review_text, _known_places(conn),
        )
        record = submissions.save_pending(clean)
    except submissions.DuplicateSubmission as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except submissions.SubmissionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except submissions.InboxFull as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return SubmissionReceipt(id=record["id"], status="pending", message=RECEIVED)
