"""Phase 4 — the verification queue. BUILD_PLAN section 5.7.

    "Verification queue (nothing auto-publishes)
     States: candidate -> verified | rejected | sensitive
     'sensitive' covers fragile ecology, restricted areas (e.g. parts of the
     Chittagong Hill Tracts needing permits) and private or home businesses.
     Sensitive items stay in the government register but never appear on the
     tourist side. Every decision records who, when and why."

This is the module the government side of the product rests on, so the design
is deliberately conservative in four ways:

NOTHING AUTO-PUBLISHES
    A scored candidate is only ever `candidate`. No gem score, however high,
    moves an item to `verified` — only a recorded human decision does. The gem
    score decides what a district officer is *shown first*, never what the
    public sees.

SENSITIVE IS NOT A SOFT REJECT
    A `sensitive` item stays in the government register with its full evidence
    and is excluded from anything tourist-facing. Fragile ecology and permit
    areas are the cases the plan names; publishing one is the harm this whole
    queue exists to prevent, and it is irreversible once a crowd arrives.
    `publishable()` is the single place that decision is enforced.

EVERY DECISION IS APPENDED, NEVER OVERWRITTEN
    Decisions live in an append-only log: who, when, which state, and why. The
    current state of an item is the latest entry for it. An officer changing
    their mind leaves both entries, because a register that quietly rewrites
    its own history cannot be audited — and an audit trail is the thing a
    government buyer asks about first.

A REASON IS REQUIRED
    A decision with no stated reason is refused. "Rejected" with no reason is
    unreviewable by the next person, and `sensitive` with no reason gives a
    district officer nothing to act on.

Run:
    .venv/bin/python scripts/verification_queue.py --list
    .venv/bin/python scripts/verification_queue.py --decide E0007 \
        --state sensitive --by unaiza --reason "permit area in the CHT"
    .venv/bin/python scripts/verification_queue.py --export-register
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import (  # noqa: E402
    PUBLISHABLE_STATES,
    VERIFICATION_HELP,
    VERIFICATION_STATES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_SCORES = DATA_DIR / "phase4_gem_scores.csv"
IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_GAZETTEER = DATA_DIR / "phase4_gazetteer.csv"
IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"

DECISION_LOG = DATA_DIR / "phase4_verification_log.csv"
OUT_QUEUE = DATA_DIR / "phase4_verification_queue.csv"
OUT_REGISTER = DATA_DIR / "phase4_district_register.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_verification_report.md"

DEFAULT_STATE = "candidate"

LOG_COLUMNS = ["decided_at_utc", "entity_id", "state", "decided_by", "reason"]


class DecisionRefused(ValueError):
    """A decision that would not be auditable, so it is not recorded."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publishable(state: str) -> bool:
    """Whether an item may appear on the tourist side.

    The single enforcement point for section 5.7. `sensitive` and `rejected`
    are both excluded, and so is `candidate` — an unreviewed item has not been
    cleared by anyone, and defaulting it to visible is how a fragile site ends
    up on a public map.
    """
    return state in PUBLISHABLE_STATES


def read_log() -> pd.DataFrame:
    if not DECISION_LOG.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    try:
        frame = pd.read_csv(DECISION_LOG)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=LOG_COLUMNS)
    for column in LOG_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[LOG_COLUMNS]


def current_states(log: pd.DataFrame) -> dict[str, dict]:
    """The latest decision per entity. Earlier entries are kept in the log."""
    states: dict[str, dict] = {}
    if log.empty:
        return states
    ordered = log.sort_values("decided_at_utc", kind="stable")
    for _, row in ordered.iterrows():
        states[str(row["entity_id"])] = {
            "state": str(row["state"]),
            "decided_by": row["decided_by"],
            "decided_at_utc": row["decided_at_utc"],
            "reason": row["reason"],
        }
    return states


def record_decision(entity_id: str, state: str, decided_by: str, reason: str,
                    known_ids: set[str] | None = None) -> dict:
    """Append one decision. Refuses anything that would not be auditable."""
    state = (state or "").strip().lower()
    if state not in VERIFICATION_STATES:
        raise DecisionRefused(
            f"state must be one of {VERIFICATION_STATES}, got {state!r}")
    if state == DEFAULT_STATE:
        raise DecisionRefused(
            "`candidate` is the state an item starts in, not a decision to record")
    if not (decided_by or "").strip():
        raise DecisionRefused(
            "--by is required: a decision with no author cannot be audited")
    if not (reason or "").strip():
        raise DecisionRefused(
            "--reason is required: `rejected` with no reason is unreviewable by the "
            "next person, and `sensitive` with no reason tells a district officer "
            "nothing about what to protect")
    if known_ids is not None and entity_id not in known_ids:
        raise DecisionRefused(
            f"no entity {entity_id!r}; run --list to see the queue")

    entry = {
        "decided_at_utc": utc_now(),
        "entity_id": entity_id,
        "state": state,
        "decided_by": decided_by.strip(),
        "reason": reason.strip(),
    }
    DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
    is_new = not DECISION_LOG.exists()
    with DECISION_LOG.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(entry)
    return entry


def build_queue() -> tuple[pd.DataFrame, list[str]]:
    """The queue: every scored candidate with its current state and evidence."""
    notes: list[str] = []
    if not IN_SCORES.exists():
        raise FileNotFoundError(
            f"{IN_SCORES.name} missing; run scripts/score_gems.py first")

    scores = pd.read_csv(IN_SCORES)
    gazetteer = pd.read_csv(IN_GAZETTEER) if IN_GAZETTEER.exists() else pd.DataFrame()
    mentions = pd.read_csv(IN_MENTIONS) if IN_MENTIONS.exists() else pd.DataFrame()
    variants = pd.read_csv(IN_VARIANTS) if IN_VARIANTS.exists() else pd.DataFrame()
    corpus = pd.read_csv(IN_CORPUS) if IN_CORPUS.exists() else pd.DataFrame()
    geography = pd.read_csv(IN_GEOGRAPHY) if IN_GEOGRAPHY.exists() else pd.DataFrame()

    states = current_states(read_log())

    # Evidence per entity: the sentences, and which division they came from.
    evidence: dict[str, list[dict]] = {}
    if not mentions.empty and not variants.empty:
        surface_to_entity = dict(zip(variants["surface"].astype(str),
                                     variants["entity_id"].astype(str)))
        mentions = mentions.copy()
        mentions["entity_id"] = mentions["surface"].astype(str).map(surface_to_entity)
        review_place = (dict(zip(corpus["review_id"].astype(str),
                                 corpus["place_name"].astype(str)))
                        if not corpus.empty else {})
        division_of = (dict(zip(geography["place_name"].astype(str),
                                geography["division"].astype(str)))
                       if not geography.empty else {})
        for _, mention in mentions.iterrows():
            entity_id = mention.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            host = review_place.get(str(mention["review_id"]), "")
            evidence.setdefault(entity_id, []).append({
                "sentence": str(mention.get("sentence") or ""),
                "found_in_place": host,
                "division": division_of.get(host, ""),
                "review_id": str(mention["review_id"]),
            })

    visibility_of = (dict(zip(gazetteer["name"].astype(str), gazetteer["visibility"].astype(str)))
                     if not gazetteer.empty else {})

    rows = []
    for _, candidate in scores.iterrows():
        entity_id = str(candidate["entity_id"])
        decision = states.get(entity_id)
        state = decision["state"] if decision else DEFAULT_STATE
        items = evidence.get(entity_id, [])
        divisions = sorted({i["division"] for i in items if i["division"]})
        rows.append({
            "entity_id": entity_id,
            "canonical_name": candidate["canonical_name"],
            "entity_type": candidate["entity_type"],
            "gem_score": candidate.get("gem_score"),
            "visibility": visibility_of.get(str(candidate["canonical_name"]), "unknown"),
            "n_reviews": candidate.get("n_reviews"),
            "n_mentions": candidate.get("n_mentions"),
            "state": state,
            "publishable": publishable(state),
            "decided_by": decision["decided_by"] if decision else None,
            "decided_at_utc": decision["decided_at_utc"] if decision else None,
            "reason": decision["reason"] if decision else None,
            "divisions": "|".join(divisions),
            "n_evidence": len(items),
            # One representative sentence, so a queue row is actionable without
            # a second query. The full evidence stays in phase4_mentions.csv.
            "example_evidence": items[0]["sentence"][:200] if items else "",
            "example_found_in": items[0]["found_in_place"] if items else "",
        })

    queue = pd.DataFrame(rows)
    if not queue.empty:
        # Undecided first, then by score: an officer should see what still
        # needs a decision before what has already had one.
        queue["_undecided"] = queue["state"] == DEFAULT_STATE
        queue = queue.sort_values(["_undecided", "gem_score"], ascending=[False, False])
        queue = queue.drop(columns="_undecided")

    if not evidence:
        notes.append("no mentions available, so queue rows carry no evidence")
    return queue, notes


def write_outputs(queue: pd.DataFrame, notes: list[str]) -> None:
    OUT_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(OUT_QUEUE, index=False)

    # The district register is the government-facing view: everything except
    # rejected items, INCLUDING sensitive ones, which is exactly what section
    # 5.7 specifies. The tourist side reads `publishable` instead.
    register = queue[queue["state"] != "rejected"].copy()
    register.to_csv(OUT_REGISTER, index=False)

    counts = queue["state"].value_counts().to_dict() if not queue.empty else {}
    n_publishable = int(queue["publishable"].sum()) if not queue.empty else 0

    lines = [
        "# Phase 4 — Verification queue",
        "",
        "Nothing auto-publishes (BUILD_PLAN 5.7). A high gem score decides what a",
        "district officer sees first; only a recorded human decision makes anything",
        "visible to the public.",
        "",
        f"- Candidates in the queue: **{len(queue)}**",
        f"- Publishable to the tourist side: **{n_publishable}**",
        f"- In the district register (everything but rejected): "
        f"**{len(queue[queue['state'] != 'rejected']) if not queue.empty else 0}**",
        "",
        "## States",
        "",
        "| state | meaning | count | tourist-visible |",
        "| --- | --- | --- | --- |",
    ]
    for state in VERIFICATION_STATES:
        lines.append(
            f"| {state} | {VERIFICATION_HELP[state]} | {counts.get(state, 0)} | "
            f"{'yes' if publishable(state) else 'no'} |"
        )
    lines += [
        "",
        "`sensitive` is not a soft rejection. The item stays in the district register",
        "with its evidence and never reaches the tourist side — fragile ecology,",
        "permit areas such as parts of the Chittagong Hill Tracts, and private or",
        "home businesses. Publishing one of those is the harm this queue exists to",
        "prevent, and a crowd cannot be un-sent.",
        "",
        "## Audit trail",
        "",
        f"Decisions are appended to `{DECISION_LOG.name}`, never overwritten: who,",
        "when, which state and why. An item's current state is its latest entry, and",
        "a changed mind leaves both, because a register that rewrites its own history",
        "cannot be audited.",
        "",
    ]
    if not queue.empty:
        undecided = queue[queue["state"] == DEFAULT_STATE]
        if not undecided.empty:
            lines += [
                "## Awaiting a decision",
                "",
                "| entity | score | visibility | reviews | divisions |",
                "| --- | --- | --- | --- | --- |",
            ]
            for _, row in undecided.head(20).iterrows():
                score = "—" if pd.isna(row["gem_score"]) else f"{row['gem_score']:.2f}"
                lines.append(
                    f"| {row['canonical_name']} | {score} | {row['visibility']} | "
                    f"{row['n_reviews']} | {row['divisions'] or '—'} |"
                )
            lines.append("")
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="show the queue")
    parser.add_argument("--decide", metavar="ENTITY_ID", help="record a decision")
    parser.add_argument("--state", choices=[s for s in VERIFICATION_STATES if s != DEFAULT_STATE])
    parser.add_argument("--by", help="who is deciding")
    parser.add_argument("--reason", help="why")
    parser.add_argument("--export-register", action="store_true",
                        help="write the queue and district register files")
    parser.add_argument("--history", metavar="ENTITY_ID", help="every decision for an entity")
    args = parser.parse_args()

    try:
        queue, notes = build_queue()
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1

    if args.history:
        log = read_log()
        own = log[log["entity_id"].astype(str) == args.history]
        if own.empty:
            print(f"no decisions recorded for {args.history}")
            return 0
        print(f"Decision history for {args.history} (oldest first):")
        for _, row in own.sort_values("decided_at_utc").iterrows():
            print(f"  {row['decided_at_utc']}  {row['state']:<9} by {row['decided_by']}")
            print(f"      {row['reason']}")
        return 0

    if args.decide:
        try:
            entry = record_decision(
                args.decide, args.state or "", args.by or "", args.reason or "",
                known_ids=set(queue["entity_id"].astype(str)) if not queue.empty else None,
            )
        except DecisionRefused as exc:
            print(f"refused: {exc}")
            return 1
        print(f"recorded: {entry['entity_id']} -> {entry['state']} by {entry['decided_by']}")
        print(f"  reason: {entry['reason']}")
        print(f"  tourist-visible: {publishable(entry['state'])}")
        queue, notes = build_queue()

    if args.list or args.decide or not any((args.decide, args.export_register, args.history)):
        print(f"Verification queue — {len(queue)} candidate(s)")
        if not queue.empty:
            counts = queue["state"].value_counts().to_dict()
            print(f"  states: {counts}")
            print(f"  publishable to tourists: {int(queue['publishable'].sum())}")
            print()
            for _, row in queue.head(20).iterrows():
                score = "    —" if pd.isna(row["gem_score"]) else f"{row['gem_score']:.3f}"
                flag = "PUBLIC" if row["publishable"] else "      "
                print(f"  {score}  {row['visibility']:<7} {row['state']:<9} {flag} "
                      f"{row['canonical_name']}")

    if args.export_register or args.decide:
        write_outputs(queue, notes)
        print(f"\n  wrote {OUT_QUEUE.name}, {OUT_REGISTER.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
