"""Visitor review uploads — the storage side.

A review typed into the website's "Share a review" form is saved as one small
JSON file in its own folder, completely apart from the real dataset:

    data/visitor_uploads/
        pending/     just received, nobody has looked at it
        approved/    a person said yes; waiting for `process_submissions.py --ingest`
        rejected/    a person said no (kept, with the reason, for the record)
        ingested/    already added to the dataset

Nothing a visitor sends touches `data/real_reviews_*.csv` or the database until
a person approves it and runs the ingest step.

What is stored: the place, the rating, the text and the time. Never a name, an
email or an IP address — BUILD_PLAN section 10 keeps reviewer identity out of
the project, and the rate limiter below lives in memory for the same reason.

Only the standard library is used, so this runs anywhere the API does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATES = ("pending", "approved", "rejected", "ingested")
DIVISIONS = ["Barishal", "Chattogram", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"]

MIN_TEXT, MAX_TEXT = 30, 3000
MIN_PLACE, MAX_PLACE = 3, 120
MIN_DISTRICT, MAX_DISTRICT = 2, 60
MAX_LINKS = 1
DEFAULT_MAX_PENDING = 500


class SubmissionError(ValueError):
    """The visitor's input cannot be accepted. The message is safe to show them."""


class DuplicateSubmission(SubmissionError):
    """The same text has already been sent."""


class InboxFull(RuntimeError):
    """Too many reviews are waiting; stop accepting until someone clears them."""


# --- where files live ------------------------------------------------------


def upload_dir() -> Path:
    """Read each time so a test or deployment can redirect it with an env var."""
    override = os.environ.get("TOURISTINBD_UPLOADS_DIR")
    if override:
        return Path(override)
    data = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
    return data / "visitor_uploads"


def folder(state: str) -> Path:
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    path = upload_dir() / state
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- cleaning and validation ----------------------------------------------

_TAG = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LINK = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


def clean_text(text: object) -> str:
    """Strip markup and control characters; leave the words exactly as typed.

    Bangla, Banglish and English are all kept untouched. Only things that could
    break a page or a CSV are removed.
    """
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _TAG.sub(" ", value)
    value = _CONTROL.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def text_fingerprint(text: str) -> str:
    """Same review pasted twice (any spacing or case) gives the same fingerprint."""
    squashed = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(squashed.encode("utf-8")).hexdigest()


def validate(
    place_name: object,
    is_new_place: bool,
    district: object,
    rating: object,
    review_text: object,
    known_places: dict[str, str],
) -> dict:
    """Return a cleaned submission, or raise SubmissionError with a plain message.

    `known_places` maps lower-cased place name -> its proper name, taken from the
    database, so a visitor can only attach a review to a place that exists unless
    they say it is a new one.
    """
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        raise SubmissionError("Please choose a rating from 1 to 5 stars.") from None
    if not 1 <= stars <= 5:
        raise SubmissionError("Please choose a rating from 1 to 5 stars.")

    text = clean_text(review_text)
    if len(text) < MIN_TEXT:
        raise SubmissionError(f"Please write a little more — at least {MIN_TEXT} characters.")
    if len(text) > MAX_TEXT:
        raise SubmissionError(f"That is too long — please keep it under {MAX_TEXT} characters.")
    if len(_LINK.findall(text)) > MAX_LINKS:
        raise SubmissionError("Please remove the links from your review.")
    if len(set(text.replace(" ", ""))) < 6:
        raise SubmissionError("That does not look like a real review.")

    name = clean_text(place_name)
    proper = known_places.get(name.lower())
    if proper:
        return {"place_name": proper, "is_new_place": False, "district": None,
                "rating": stars, "review_text": text}

    if not is_new_place:
        raise SubmissionError(
            "We do not know that place. Choose one from the list, or tick \"a place not listed\"."
        )
    if not MIN_PLACE <= len(name) <= MAX_PLACE:
        raise SubmissionError(f"Please give the place name ({MIN_PLACE}-{MAX_PLACE} characters).")
    area = clean_text(district)
    if not MIN_DISTRICT <= len(area) <= MAX_DISTRICT:
        raise SubmissionError("Please tell us which district the place is in.")
    return {"place_name": name, "is_new_place": True, "district": area,
            "rating": stars, "review_text": text}


# --- saving and loading ---------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def all_files() -> list[Path]:
    return [p for state in STATES for p in sorted(folder(state).glob("V*.json"))]


def known_fingerprints() -> set[str]:
    found = set()
    for path in all_files():
        try:
            found.add(json.loads(path.read_text(encoding="utf-8"))["text_hash"])
        except (OSError, ValueError, KeyError):
            continue
    return found


def max_pending() -> int:
    try:
        return int(os.environ.get("TOURISTINBD_MAX_PENDING", DEFAULT_MAX_PENDING))
    except ValueError:
        return DEFAULT_MAX_PENDING


def save_pending(clean: dict) -> dict:
    """Write a validated submission into pending/. Refuses repeats and a full inbox."""
    if len(list(folder("pending").glob("V*.json"))) >= max_pending():
        raise InboxFull("The inbox is full. Please try again later.")
    fingerprint = text_fingerprint(clean["review_text"])
    if fingerprint in known_fingerprints():
        raise DuplicateSubmission("It looks like this review has already been sent. Thank you!")

    submitted = _now()
    stamp = submitted.replace("-", "").replace(":", "").rstrip("Z")  # 20261006T101500
    record = {
        "id": f"V{stamp}-{fingerprint[:6]}",
        "submitted_at_utc": submitted,
        "status": "pending",
        **clean,
        "geography": None,
        "text_hash": fingerprint,
        "decisions": [],
    }
    _write_json(folder("pending") / f"{record['id']}.json", record)
    return record


def find(submission_id: str) -> tuple[dict, Path]:
    """Look an ID up in every folder. Raises KeyError when it does not exist."""
    # IDs come from the command line; never let one escape the uploads folder.
    if not re.fullmatch(r"V[0-9T]+-[0-9a-f]{6}", submission_id or ""):
        raise KeyError(submission_id)
    for state in STATES:
        path = folder(state) / f"{submission_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), path
    raise KeyError(submission_id)


def list_submissions(status: str | None = None) -> list[dict]:
    states = [status] if status else list(STATES)
    rows = []
    for state in states:
        for path in sorted(folder(state).glob("V*.json")):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return sorted(rows, key=lambda r: r["submitted_at_utc"])


def decide(submission_id: str, state: str, by: str, reason: str, geography: dict | None = None) -> dict:
    """Approve or reject. A name and a reason are always required.

    The same rule the verification queue uses: a decision nobody can later
    explain is worth nothing. Moving a file between folders *is* the decision,
    and every move is also written into the record's own `decisions` list.
    """
    if state not in ("approved", "rejected"):
        raise ValueError("state must be 'approved' or 'rejected'")
    if not (by or "").strip():
        raise ValueError("a decision needs a name (--by)")
    if not (reason or "").strip():
        raise ValueError("a decision needs a reason (--reason)")

    record, path = find(submission_id)
    if record["status"] == "ingested":
        raise ValueError(f"{submission_id} is already in the dataset and cannot be changed")

    if state == "approved" and record["is_new_place"]:
        division = (geography or {}).get("division")
        if division not in DIVISIONS:
            raise ValueError(
                f"{record['place_name']!r} is a new place: give its division with --division "
                f"(one of: {', '.join(DIVISIONS)})"
            )
        record["geography"] = {
            "division": division,
            "district": (geography or {}).get("district") or record["district"],
            "city": (geography or {}).get("city") or (geography or {}).get("district") or record["district"],
        }

    record["status"] = state
    record["decisions"].append({"state": state, "by": by.strip(), "reason": reason.strip(), "at_utc": _now()})
    target = folder(state) / path.name
    _write_json(target, record)
    if target != path:
        path.unlink()
    return record


def mark_ingested(submission_id: str, batch: str, note: str | None = None) -> dict:
    record, path = find(submission_id)
    if record["status"] != "approved":
        raise ValueError(f"{submission_id} is {record['status']}, not approved")
    record["status"] = "ingested"
    record["ingested_batch"] = batch
    record["ingested_at_utc"] = _now()
    if note:
        record["ingest_note"] = note
    target = folder("ingested") / path.name
    _write_json(target, record)
    path.unlink()
    return record


# --- rate limiting ---------------------------------------------------------


class RateLimiter:
    """At most `limit` submissions per client per `window` seconds, in memory.

    The client key (an IP address) is held only in this process's memory and is
    never written anywhere, so no visitor identifier reaches the disk. A restart
    clears it, which is acceptable for a spam brake and not a security boundary.
    """

    def __init__(self, limit: int = 5, window: float = 3600.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            if len(self._hits) > 5000:  # forget idle clients so memory cannot grow without bound
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _limit_from_env() -> int:
    try:
        return int(os.environ.get("TOURISTINBD_SUBMIT_LIMIT", "5"))
    except ValueError:
        return 5


limiter = RateLimiter(limit=_limit_from_env())
