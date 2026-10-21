"""Moderate and ingest visitor-submitted reviews.

Visitors send reviews through the website's "Share a review" tab. Each one is
saved as a small file in its own folder, apart from the real dataset:

    data/visitor_uploads/pending/    waiting for you
    data/visitor_uploads/approved/   you said yes; not yet in the dataset
    data/visitor_uploads/rejected/   you said no
    data/visitor_uploads/ingested/   already in the dataset

Nothing a visitor sends reaches the dataset until you approve it here AND run
--ingest. A name and a reason are required for every decision, the same rule the
hidden-gem verification queue uses.

    .venv/bin/python scripts/process_submissions.py --list
    .venv/bin/python scripts/process_submissions.py --show V20261006T101500-ab12cd
    .venv/bin/python scripts/process_submissions.py --approve V2026...-ab12cd --by Yakin --reason "genuine, mentions a local ghat"
    .venv/bin/python scripts/process_submissions.py --reject  V2026...-ab12cd --by Yakin --reason "advertising"
    .venv/bin/python scripts/process_submissions.py --ingest

A review for a place that is not in the dataset yet needs its division when you
approve it (--division Sylhet), because the planner and the district register
group places by division. The ingest step adds the place to place_geography.csv.

--ingest copies the approved reviews into the dataset (through add_reviews.py, so
duplicates are skipped) and then runs the same chain every new batch goes through:

    clean -> language label -> find mentions -> merge name variants
          -> check against maps -> gem score -> verification queue -> rebuild database

Topic modelling (BERTopic) and the paid preference step are NOT run here: they need
torch and API quota. The new reviews show up in listings, ratings, search and the
Discoveries tab straight away, and join recommendations at the next full refresh.

If a step fails, the approved files stay where they are and --ingest can simply be
run again; already-added reviews are skipped.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend import submissions  # noqa: E402



def data_dir() -> Path:
    """Read each time, so a test or a running server can point it somewhere else."""
    return Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))


SCRIPTS = REPO_ROOT / "scripts"
STALE_LOCK_SECONDS = 3 * 3600
NEW_PLACE_CATEGORY = "Tourist attraction"


def short(text: str, width: int = 70) -> str:
    return textwrap.shorten(" ".join(str(text).split()), width=width, placeholder="…")


# --- listing ----------------------------------------------------------------


def show_list(status: str) -> None:
    rows = submissions.list_submissions(None if status == "all" else status)
    if not rows:
        print(f"no {status} submissions")
        return
    print(f"{len(rows)} {status} submission(s):\n")
    for r in rows:
        new = "  [NEW PLACE: " + str(r["district"]) + "]" if r["is_new_place"] else ""
        print(f"{r['id']}  {r['status']:<9} {r['rating']}★  {r['place_name']}{new}")
        print(f"    {short(r['review_text'])}")


def show_one(submission_id: str) -> int:
    try:
        record, _ = submissions.find(submission_id)
    except KeyError:
        print(f"error: no submission {submission_id!r}")
        return 1
    print(f"{record['id']}  ({record['status']})  sent {record['submitted_at_utc']}")
    print(f"place:  {record['place_name']}" + (f"   NEW PLACE in {record['district']}" if record["is_new_place"] else ""))
    print(f"rating: {record['rating']}/5\n")
    print(record["review_text"])
    for d in record["decisions"]:
        print(f"\n{d['at_utc']}  {d['state']} by {d['by']}: {d['reason']}")
    return 0


# --- deciding ----------------------------------------------------------------


def decide(args: argparse.Namespace, state: str) -> int:
    submission_id = args.approve or args.reject
    geography = {"division": args.division, "district": args.district, "city": args.city}
    try:
        record = submissions.decide(submission_id, state, args.by or "", args.reason or "", geography)
    except KeyError:
        print(f"error: no submission {submission_id!r}")
        return 1
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"{record['id']} -> {state} by {args.by}")
    if state == "approved":
        print("  Run --ingest when you have approved everything you want added.")
    return 0


# --- ingesting ---------------------------------------------------------------


def batch_name() -> str:
    base = "visitor_" + datetime.now(timezone.utc).strftime("%Y%m%d")
    name, n = base, 1
    while (data_dir() / f"real_reviews_{name}.csv").exists():
        n += 1
        name = f"{base}_{n}"
    return name


def place_lookup() -> dict[str, dict]:
    """City and category already on file for each existing place."""
    path = data_dir() / "processed_reviews.csv"
    if not path.exists():
        return {}
    corpus = pd.read_csv(path, usecols=lambda c: c in {"place_name", "city", "category"})
    return {
        str(name): {"city": g["city"].dropna().iloc[0] if "city" in g and g["city"].notna().any() else "",
                    "category": g["category"].dropna().iloc[0] if "category" in g and g["category"].notna().any() else ""}
        for name, g in corpus.groupby("place_name")
    }


def add_new_places(approved: list[dict]) -> list[str]:
    """Append a place_geography.csv row for each new place. Returns what was added."""
    path = data_dir() / "place_geography.csv"
    geo = pd.read_csv(path) if path.exists() else pd.DataFrame(
        columns=["place_name", "city", "district", "division", "place_kind", "notes"])
    have = set(geo["place_name"].astype(str).str.lower())
    rows, added = [], []
    for r in approved:
        if not r["is_new_place"] or r["place_name"].lower() in have:
            continue
        g = r["geography"] or {}
        rows.append({
            "place_name": r["place_name"], "city": g.get("city") or r["district"],
            "district": g.get("district") or r["district"], "division": g["division"],
            "place_kind": "attraction", "notes": "added from a visitor submission",
        })
        have.add(r["place_name"].lower())
        added.append(r["place_name"])
    if rows:
        pd.concat([geo, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)
    return added


def _noop(*_args, **_kwargs) -> None:
    return None


def run_step(label: str, command: list[str], report=print, on_step=_noop) -> tuple[bool, str]:
    """Run one pipeline script. Returns (succeeded, tail of its output when it failed)."""
    on_step(label, "running", None)
    report(f"  … {label}")
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, env=os.environ.copy())
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()[-1500:]
        report(f"  ✗ {label} failed (exit {result.returncode})")
        report(textwrap.indent(detail, "      "))
        on_step(label, "failed", detail)
        return False, detail
    report(f"  ✓ {label}")
    on_step(label, "ok", None)
    return True, ""


def _lock_path() -> Path:
    return submissions.upload_dir() / ".ingest.lock"


def acquire_lock() -> bool:
    """Only one ingest at a time, whether it was started here or from the admin panel."""
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK_SECONDS:
            path.unlink()  # a crashed run left it behind
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as handle:
        handle.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    return True


def release_lock() -> None:
    _lock_path().unlink(missing_ok=True)


def run_ingest(offline: bool = False, skip_funnel: bool = False, dry_run: bool = False,
               report=print, on_step=_noop) -> dict:
    """Add every approved review to the dataset and run the pipeline on it.

    Used by the command line (`--ingest`) and by the admin panel, so there is one
    copy of the logic. `report(line)` receives progress text; `on_step(label, status,
    detail)` is told when each step starts, finishes or fails.

    Returns {"ok", "error", "batch", "approved", "added", "dropped", "new_places"}.
    """
    outcome = {"ok": False, "error": None, "batch": None, "approved": 0, "added": 0,
               "dropped": [], "new_places": []}
    approved = submissions.list_submissions("approved")
    outcome["approved"] = len(approved)
    if not approved:
        report("nothing approved to ingest")
        outcome.update(ok=True, error=None)
        return outcome
    for r in approved:
        if r["is_new_place"] and not (r.get("geography") or {}).get("division"):
            outcome["error"] = f"{r['id']} is for a new place but has no division; approve it again with a division"
            report(f"error: {outcome['error']}")
            return outcome

    batch = batch_name()
    outcome["batch"] = batch
    report(f"Ingesting {len(approved)} approved review(s) as batch {batch}")

    if dry_run:
        for r in approved:
            report(f"  would add: {r['place_name']}{' (new place)' if r['is_new_place'] else ''} — {short(r['review_text'], 50)}")
        report("--dry-run: nothing written")
        outcome["ok"] = True
        return outcome

    if not acquire_lock():
        outcome["error"] = "another ingest is already running"
        report(f"error: {outcome['error']}")
        return outcome
    try:
        return _ingest_locked(approved, batch, outcome, offline, skip_funnel, report, on_step)
    finally:
        release_lock()


def _ingest_locked(approved, batch, outcome, offline, skip_funnel, report, on_step) -> dict:
    lookup = place_lookup()
    new_places = add_new_places(approved)
    outcome["new_places"] = new_places
    if new_places:
        report(f"  added {len(new_places)} new place(s) to place_geography.csv: {', '.join(new_places)}")

    rows = []
    for r in approved:
        known = lookup.get(r["place_name"], {})
        g = r.get("geography") or {}
        rows.append({
            "review_id": r["id"],
            "place_name": r["place_name"],
            "city": known.get("city") or g.get("city") or "",
            "category": known.get("category") or (NEW_PLACE_CATEGORY if r["is_new_place"] else ""),
            "stars": r["rating"],
            # `text` with an empty `textTranslated`: add_reviews reads that as "this is
            # exactly what the reviewer wrote", so Bangla stays Bangla.
            "text": r["review_text"],
            "textTranslated": "",
            "publishedAtDate": r["submitted_at_utc"],
        })
    work = submissions.upload_dir() / ".work"
    work.mkdir(parents=True, exist_ok=True)
    staging = work / f"{batch}.csv"
    pd.DataFrame(rows).to_csv(staging, index=False)

    py = sys.executable
    steps: list[tuple[str, list[str]]] = [
        ("add to the dataset", [py, str(SCRIPTS / "add_reviews.py"), str(staging), "--source", "visitor",
                                "--source-type", "visitor", "--name", batch, "--no-preprocess"]),
        ("clean the text (phase 2)", [py, str(SCRIPTS / "run_phase2_preprocessing.py")]),
    ]
    if not skip_funnel:
        gazetteer = [py, str(SCRIPTS / "build_gazetteer.py")] + (["--offline"] if offline else [])
        steps += [
            ("label the language", [py, str(SCRIPTS / "run_phase3_language_pipeline.py")]),
            ("find mentions of other places", [py, str(SCRIPTS / "extract_mentions.py"), "--extractor", "gazetteer"]),
            ("merge spelling variants", [py, str(SCRIPTS / "resolve_entities.py")]),
            ("check against the maps (gazetteer)", gazetteer),
            ("score hidden-gem candidates", [py, str(SCRIPTS / "score_gems.py")]),
            ("update the verification queue", [py, str(SCRIPTS / "verification_queue.py"), "--export-register"]),
            ("rebuild the database", [py, str(SCRIPTS / "build_phase8_database.py")]),
        ]

    for label, command in steps:
        on_step(label, "waiting", None)
    for label, command in steps:
        ok, detail = run_step(label, command, report, on_step)
        if not ok:
            outcome["error"] = f"{label} failed: {detail.splitlines()[-1] if detail else 'see log'}"
            report("\nStopped. The approved files were left where they are — fix the problem and run it again.")
            return outcome

    corpus_ids = set(pd.read_csv(data_dir() / "processed_reviews.csv", usecols=["review_id"])["review_id"].astype(str))
    dropped = []
    for r in approved:
        if r["id"] in corpus_ids:
            submissions.mark_ingested(r["id"], batch)
        else:
            submissions.mark_ingested(r["id"], batch, note="not added: duplicate of an existing review or removed by cleaning")
            dropped.append(r["id"])
    staging.unlink(missing_ok=True)

    outcome.update(ok=True, added=len(approved) - len(dropped), dropped=dropped)
    report(f"\nDone: {outcome['added']} review(s) added to the dataset in batch {batch}.")
    if dropped:
        report(f"  {len(dropped)} were not added (already in the dataset, or too short after cleaning): {', '.join(dropped)}")
    report("  They count in listings, ratings, search and the Discoveries tab now.")
    report("  They get topics and preference evidence at the next full refresh (Phase 3 + Phase 4).")
    return outcome


def ingest(args: argparse.Namespace) -> int:
    """Command-line wrapper around run_ingest."""
    outcome = run_ingest(offline=args.offline, skip_funnel=args.skip_funnel, dry_run=args.dry_run)
    if outcome["ok"] and not args.dry_run and outcome["added"]:
        print("  Restart the server (python -m backend.main) to serve the rebuilt database.")
    return 0 if outcome["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="show submissions (default: pending)")
    parser.add_argument("--status", default="pending", choices=["pending", "approved", "rejected", "ingested", "all"])
    parser.add_argument("--show", metavar="ID", help="show one submission in full")
    parser.add_argument("--approve", metavar="ID")
    parser.add_argument("--reject", metavar="ID")
    parser.add_argument("--by", help="who is deciding")
    parser.add_argument("--reason", help="why (required)")
    parser.add_argument("--division", help="for a NEW place: its division")
    parser.add_argument("--district", help="for a NEW place: its district (default: what the visitor wrote)")
    parser.add_argument("--city", help="for a NEW place: its city/town (default: the district)")
    parser.add_argument("--ingest", action="store_true", help="add approved reviews to the dataset and run the pipeline")
    parser.add_argument("--skip-funnel", action="store_true", help="with --ingest: add and clean only, skip the rest")
    parser.add_argument("--offline", action="store_true", help="with --ingest: skip live map lookups")
    parser.add_argument("--dry-run", action="store_true", help="with --ingest: show what would happen")
    args = parser.parse_args()

    if args.show:
        return show_one(args.show)
    if args.approve:
        return decide(args, "approved")
    if args.reject:
        return decide(args, "rejected")
    if args.ingest:
        return ingest(args)
    show_list(args.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
