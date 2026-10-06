"""Verification queue tests — BUILD_PLAN section 5.7.

This is the module with the worst failure mode in the project. Publishing a
fragile site, a permit-only area or someone's home business to a tourist
audience is not a bug that can be fixed after the fact — a crowd cannot be
un-sent. So the tests are weighted heavily towards the things that must never
happen:

  1. nothing is publishable without a recorded human decision, whatever it
     scores — `candidate` is not visible, and a 0.99 gem score does not make it
     visible;
  2. `sensitive` is never publishable, and is not a soft rejection: it stays in
     the district register with its evidence;
  3. `rejected` never reaches the register;
  4. a decision with no author or no reason is refused, because an unauditable
     decision is worse than an undecided item;
  5. the log is append-only — a changed mind leaves both entries, so the
     history cannot be quietly rewritten.

Everything runs on a throwaway data directory; no real decision is recorded.

Run:
    .venv/bin/python scripts/test_verification_queue.py
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import verification_queue as vq  # noqa: E402
from gem_schema import PUBLISHABLE_STATES, VERIFICATION_STATES  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []

COPY = ("phase4_gem_scores.csv", "phase4_entities.csv", "phase4_gazetteer.csv",
        "phase4_mentions.csv", "phase4_entity_variants.csv",
        "processed_reviews.csv", "place_geography.csv")


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def fresh_module(tmp: Path):
    """verification_queue bound to a throwaway data directory."""
    data = tmp / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in COPY:
        shutil.copy(REPO_ROOT / "data" / name, data / name)
    os.environ["TOURISTINBD_DATA_DIR"] = str(data)
    importlib.reload(vq)
    return vq, data


def test_publishable_rule() -> None:
    print("the publishable rule (the single enforcement point)")
    check("verified is publishable", vq.publishable("verified"))
    # The three that must not be.
    check("sensitive is NOT publishable", not vq.publishable("sensitive"))
    check("rejected is NOT publishable", not vq.publishable("rejected"))
    check("candidate is NOT publishable", not vq.publishable("candidate"),
          "an unreviewed item defaulting to visible is how a fragile site gets published")
    check("an unknown state is NOT publishable", not vq.publishable("whatever"))
    check("only one state is publishable at all",
          [s for s in VERIFICATION_STATES if vq.publishable(s)] == ["verified"],
          str(PUBLISHABLE_STATES))


def test_refusals() -> None:
    print("\nrefusals: an unauditable decision is not recorded")
    tmp = Path(tempfile.mkdtemp(prefix="vq_refuse_"))
    try:
        module, data = fresh_module(tmp)
        for kwargs, why in [
            (dict(entity_id="E1", state="verified", decided_by="", reason="r"), "no author"),
            (dict(entity_id="E1", state="verified", decided_by="x", reason=""), "no reason"),
            (dict(entity_id="E1", state="verified", decided_by="x", reason="   "), "blank reason"),
            (dict(entity_id="E1", state="banana", decided_by="x", reason="r"), "bad state"),
            (dict(entity_id="E1", state="candidate", decided_by="x", reason="r"),
             "`candidate` is a starting state, not a decision"),
        ]:
            try:
                module.record_decision(**kwargs)
                check(f"refused: {why}", False, "it was recorded")
            except module.DecisionRefused:
                check(f"refused: {why}", True)

        check("nothing was written to the log",
              not (data / "phase4_verification_log.csv").exists(),
              "a refused decision left a log entry")

        try:
            module.record_decision("NOT_AN_ENTITY", "verified", "x", "r", known_ids={"E1"})
            check("refused: unknown entity", False, "it was recorded")
        except module.DecisionRefused:
            check("refused: unknown entity", True)
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_nothing_auto_publishes() -> None:
    print("\nnothing auto-publishes")
    tmp = Path(tempfile.mkdtemp(prefix="vq_auto_"))
    try:
        module, _ = fresh_module(tmp)
        queue, _ = module.build_queue()
        check("the queue is non-empty", len(queue) > 0, str(len(queue)))
        check("every item starts as candidate",
              set(queue["state"]) == {"candidate"}, str(set(queue["state"])))
        check("nothing is publishable before any decision",
              int(queue["publishable"].sum()) == 0, str(int(queue["publishable"].sum())))
        # The important one: the highest-scoring candidate is still not visible.
        top = queue.iloc[0]
        check("even the top-scoring candidate is not publishable",
              not bool(top["publishable"]),
              f"{top['canonical_name']} at {top['gem_score']}")
        check("no decision metadata is invented",
              queue["decided_by"].isna().all() and queue["reason"].isna().all())
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_states_end_to_end() -> None:
    print("\nthe three decisions, end to end")
    tmp = Path(tempfile.mkdtemp(prefix="vq_e2e_"))
    try:
        module, data = fresh_module(tmp)
        queue, _ = module.build_queue()
        ids = queue["entity_id"].tolist()
        known = set(ids)

        module.record_decision(ids[0], "verified", "officer", "checked two reviews", known)
        module.record_decision(ids[1], "sensitive", "officer", "permit area", known)
        module.record_decision(ids[2], "rejected", "officer", "duplicate listing", known)
        queue, notes = module.build_queue()
        module.write_outputs(queue, notes)

        by_id = queue.set_index("entity_id")
        check("the verified item is publishable", bool(by_id.loc[ids[0], "publishable"]))
        check("the sensitive item is not publishable", not bool(by_id.loc[ids[1], "publishable"]))
        check("the rejected item is not publishable", not bool(by_id.loc[ids[2], "publishable"]))
        check("the reason is carried on the row",
              by_id.loc[ids[1], "reason"] == "permit area", str(by_id.loc[ids[1], "reason"]))
        check("the decider is carried on the row",
              by_id.loc[ids[1], "decided_by"] == "officer")
        check("the timestamp is recorded", bool(by_id.loc[ids[1], "decided_at_utc"]))

        register = pd.read_csv(data / "phase4_district_register.csv")
        in_register = set(register["entity_id"].astype(str))
        # Section 5.7: sensitive items stay in the government register.
        check("the sensitive item IS in the district register", ids[1] in in_register,
              "sensitive is not a soft reject; the officer still needs to see it")
        check("the sensitive item carries its evidence into the register",
              bool(register.set_index("entity_id").loc[ids[1], "n_evidence"] >= 0))
        check("the rejected item is NOT in the register", ids[2] not in in_register)
        check("the verified item is in the register", ids[0] in in_register)
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_append_only_log() -> None:
    print("\nthe log is append-only")
    tmp = Path(tempfile.mkdtemp(prefix="vq_log_"))
    try:
        module, data = fresh_module(tmp)
        queue, _ = module.build_queue()
        entity = queue["entity_id"].iloc[0]
        known = set(queue["entity_id"])

        module.record_decision(entity, "sensitive", "officer", "fragile ecology", known)
        module.record_decision(entity, "verified", "supervisor", "reassessed", known)

        log = pd.read_csv(data / "phase4_verification_log.csv")
        check("both decisions are in the log", len(log) == 2, str(len(log)))
        check("the earlier decision is not overwritten",
              "sensitive" in set(log["state"]) and "verified" in set(log["state"]),
              str(set(log["state"])))
        check("both authors survive",
              set(log["decided_by"]) == {"officer", "supervisor"}, str(set(log["decided_by"])))
        check("both reasons survive",
              "fragile ecology" in set(log["reason"]), str(set(log["reason"])))

        # The current state is the latest entry, not the first or a merge.
        states = module.current_states(log)
        check("the current state is the latest decision",
              states[entity]["state"] == "verified", str(states[entity]))
        check("and it carries the latest author",
              states[entity]["decided_by"] == "supervisor", str(states[entity]))

        queue, _ = module.build_queue()
        row = queue.set_index("entity_id").loc[entity]
        check("the queue reflects the latest state", row["state"] == "verified")
        check("and the item is now publishable", bool(row["publishable"]))
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_queue_ordering_and_evidence() -> None:
    print("\nordering and evidence")
    tmp = Path(tempfile.mkdtemp(prefix="vq_order_"))
    try:
        module, _ = fresh_module(tmp)
        queue, _ = module.build_queue()
        check("rows carry evidence counts", (queue["n_evidence"] > 0).any(),
              "no row has any evidence")
        check("rows carry an example sentence",
              queue["example_evidence"].astype(str).str.len().max() > 0)
        check("rows name where the evidence was found",
              queue["example_found_in"].astype(str).str.len().max() > 0)
        check("rows carry divisions for the register",
              "divisions" in queue.columns)
        check("undecided items sort first",
              bool(queue.iloc[0]["state"] == "candidate"),
              "an officer should see what still needs deciding")
        check("visibility is carried through from the gazetteer",
              set(queue["visibility"]) <= {"V0", "V1", "V2", "V3", "unknown"},
              str(set(queue["visibility"])))
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    print("Verification queue tests (BUILD_PLAN 5.7)\n")
    test_publishable_rule()
    test_refusals()
    test_nothing_auto_publishes()
    test_states_end_to_end()
    test_append_only_log()
    test_queue_ordering_and_evidence()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All verification queue tests passed.")


if __name__ == "__main__":
    main()
