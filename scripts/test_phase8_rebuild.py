"""Phase 8 (part 3) — forward-compatibility tests for the database build.

The point of the project is that later phases can add data without breaking
earlier ones. These tests copy `data/` into a temp directory, mutate it the way
real growth would, and assert the build still produces a working database.

Scenarios covered:
  1. New reviews for a brand-new place that is not in place_geography.csv.
  2. Reviews that Phase 3 has not clustered yet (missing from reviews_with_topics).
  3. A brand-new preference id appearing in the taxonomy.
  4. Only Phase 2 output present — every Phase 3-7 artifact missing.
  5. An extra column added upstream (schema drift).
  6. A stale place_geography.csv row for a place with no reviews.

Each scenario also boots the API against the rebuilt DB and checks it answers.

Run:
    .venv/bin/python scripts/test_phase8_rebuild.py
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_phase8_database.py"

# Expected sizes come from the committed corpus, so these tests keep passing as it grows.
_corpus = pd.read_csv(DATA_DIR / "processed_reviews.csv")
N_REVIEWS = len(_corpus)
N_PLACES = _corpus["place_name"].nunique()

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def fresh_data_dir(tmp: Path) -> Path:
    """A copy of data/ holding only the CSV/JSON inputs the build reads."""
    out = tmp / "data"
    out.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.csv", "*.json"):
        for src in DATA_DIR.glob(pattern):
            shutil.copy2(src, out / src.name)
    # Never carry an existing DB into a scenario.
    (out / "touristinbd.db").unlink(missing_ok=True)
    return out


def run_build(data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


def api_client(data_dir: Path):
    """Boot the API against `data_dir` by re-importing the modules that read it."""
    os.environ["TOURISTINBD_DATA_DIR"] = str(data_dir)
    for mod in [m for m in list(sys.modules) if m.startswith("backend")]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient

    main = importlib.import_module("backend.main")
    return TestClient(main.app)


def scenario_new_place(tmp: Path) -> None:
    """A new venue arrives that place_geography.csv has never heard of."""
    data = fresh_data_dir(tmp / "new_place")
    reviews = pd.read_csv(data / "processed_reviews.csv")
    new = reviews.head(3).copy()
    new["review_id"] = ["NEW_PLACE_1", "NEW_PLACE_2", "NEW_PLACE_3"]
    new["place_name"] = "Bichanakandi Stone Quarry"
    new["city"] = "Gowainghat"
    new["category"] = "Tourist attraction"
    new["source"] = "google_maps"
    pd.concat([reviews, new], ignore_index=True).to_csv(
        data / "processed_reviews.csv", index=False
    )
    # Phase 3 has not been re-run, so the new rows have no topic assignment.
    result = run_build(data)
    check("new place: build succeeds", result.returncode == 0, result.stderr[-400:])
    if result.returncode != 0:
        return

    check(
        "new place: build warns it is missing from place_geography.csv",
        "Bichanakandi" in result.stdout,
        result.stdout[-400:],
    )
    check(
        "new place: build warns the new reviews are unclustered",
        "not in reviews_with_topics" in result.stdout,
        result.stdout[-400:],
    )

    client = api_client(data)
    code = client.get("/health").json()
    check("new place: API healthy", code["status"] == "ok", str(code))
    overview = client.get("/api/overview").json()
    check(
        "new place: overview counts the new reviews",
        overview["total_reviews"] == len(reviews) + 3,
        str(overview["total_reviews"]),
    )
    check(
        "new place: new place appears in /api/places",
        overview["total_places"] == 28,
        str(overview["total_places"]),
    )
    detail = client.get("/api/places/Bichanakandi Stone Quarry")
    check("new place: detail endpoint resolves it", detail.status_code == 200, str(detail.status_code))
    body = detail.json()
    check(
        "new place: city falls back to the review CSV value",
        body["place"]["city"] == "Gowainghat",
        str(body["place"]["city"]),
    )
    check(
        "new place: unmapped district is NULL, not a crash",
        body["place"]["district"] is None,
        str(body["place"]["district"]),
    )
    unclustered = client.get("/api/reviews", params={"place": "Bichanakandi"}).json()
    check(
        "new place: its unclustered reviews are still queryable",
        unclustered["total"] == 3 and all(r["topic_id"] is None for r in unclustered["items"]),
        str(unclustered["total"]),
    )


def scenario_new_preference(tmp: Path) -> None:
    """A new preference id enters the taxonomy (e.g. a Culinary dimension)."""
    data = fresh_data_dir(tmp / "new_pref")
    prefs = pd.read_csv(data / "preference_classification.csv")
    prefs.loc[len(prefs)] = {
        "preference_id": "P11",
        "category": "Culinary",
        "subcategory": "Local Food",
        "preference": "Street food and local cuisine",
        "description": "Travelers seeking regional Bangladeshi dishes.",
        "preference_type": "mainstream",
    }
    prefs.to_csv(data / "preference_classification.csv", index=False)

    result = run_build(data)
    check("new preference: build succeeds", result.returncode == 0, result.stderr[-400:])
    if result.returncode != 0:
        return

    client = api_client(data)
    listed = client.get("/api/preferences").json()
    check(
        "new preference: appears with zero evidence",
        any(p["preference_id"] == "P11" and p["review_count"] == 0 for p in listed),
        str([p["preference_id"] for p in listed]),
    )
    tree = client.get("/api/taxonomy").json()
    check(
        "new preference: new Culinary category shows in the taxonomy tree",
        any(c["category"] == "Culinary" for c in tree),
        str([c["category"] for c in tree]),
    )
    rec = client.get("/api/recommend", params={"preferences": "P11"})
    check(
        "new preference: recommend accepts it and returns no evidence",
        rec.status_code == 200 and rec.json() == [],
        str(rec.status_code),
    )


def scenario_phase2_only(tmp: Path) -> None:
    """Only Phase 2 output exists — every later artifact is missing."""
    data = tmp / "phase2_only" / "data"
    data.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA_DIR / "processed_reviews.csv", data / "processed_reviews.csv")
    shutil.copy2(DATA_DIR / "place_geography.csv", data / "place_geography.csv")

    result = run_build(data)
    check("phase2-only: build succeeds", result.returncode == 0, result.stderr[-500:])
    if result.returncode != 0:
        return

    client = api_client(data)
    health = client.get("/health").json()
    check("phase2-only: API healthy", health["status"] == "ok", str(health))
    overview = client.get("/api/overview").json()
    check(
        "phase2-only: reviews still load",
        overview["total_reviews"] == N_REVIEWS and overview["total_preferences"] == 0,
        str(overview),
    )
    for path in ("/api/topics", "/api/preferences", "/api/analytics/city-preferences"):
        r = client.get(path)
        check(
            f"phase2-only: {path} returns an empty list, not an error",
            r.status_code == 200 and r.json() == [],
            f"{r.status_code} {str(r.json())[:120]}",
        )
    r = client.get("/api/research/statistical-tests").json()
    check(
        "phase2-only: statistical-tests reports unavailable cleanly",
        r["available"] is False,
        str(r),
    )
    r = client.get("/api/research/sensitivity").json()
    check(
        "phase2-only: sensitivity returns null recommendation, not an error",
        r["recommended_min_corpus_size"] is None,
        str(r),
    )
    r = client.get("/api/places", params={"limit": 5})
    check("phase2-only: places still work", r.status_code == 200 and r.json()["total"] == N_PLACES, str(r.status_code))


def scenario_schema_drift(tmp: Path) -> None:
    """Upstream adds a column and a stale geography row exists."""
    data = fresh_data_dir(tmp / "drift")
    reviews = pd.read_csv(data / "processed_reviews.csv")
    reviews["sentiment_score"] = 0.5  # a column Phase 8 knows nothing about
    reviews.to_csv(data / "processed_reviews.csv", index=False)

    geo = pd.read_csv(data / "place_geography.csv")
    geo.loc[len(geo)] = {
        "place_name": "Somewhere Not Yet Scraped",
        "city": "Rangpur",
        "district": "Rangpur",
        "division": "Rangpur",
        "place_kind": "attraction",
        "notes": "planned for a later batch",
    }
    geo.to_csv(data / "place_geography.csv", index=False)

    result = run_build(data)
    check("schema drift: build succeeds", result.returncode == 0, result.stderr[-400:])
    if result.returncode != 0:
        return
    check(
        "schema drift: stale geography row is reported and ignored",
        "no reviews yet" in result.stdout,
        result.stdout[-400:],
    )

    client = api_client(data)
    r = client.get("/api/places", params={"limit": 500}).json()
    check(
        "schema drift: unknown extra column does not create a phantom place",
        r["total"] == N_PLACES,
        str(r["total"]),
    )
    r = client.get("/api/overview").json()
    check("schema drift: overview intact", r["total_reviews"] == N_REVIEWS, str(r["total_reviews"]))


def scenario_phase3_language(tmp: Path) -> None:
    """Phase 3's language artifact: present, absent, and carrying junk ids.

    It arrived after the database schema existed, so the question is whether
    the build treats it as optional in the same way as every other Phase 3-7
    artifact, and whether a stale copy (ids from a corpus that has since been
    re-run) is dropped rather than written as orphan rows.
    """
    import sqlite3

    data = fresh_data_dir(tmp / "p3_language")
    labels = data / "phase3_language_labels.csv"
    if not labels.exists():
        check("phase3 language: artifact exists to test", False, f"{labels} not copied")
        return

    result = run_build(data)
    check("phase3 language: build succeeds", result.returncode == 0, result.stderr[-400:])
    conn = sqlite3.connect(data / "touristinbd.db")
    try:
        rows = conn.execute("SELECT COUNT(*) FROM review_language").fetchone()[0]
        check("phase3 language: every review is labelled", rows == N_REVIEWS, str(rows))
        mix = conn.execute("SELECT COUNT(*) FROM v_language_mix").fetchall()
        check("phase3 language: v_language_mix answers", len(mix) > 0, str(mix))
        # A rule-based label must keep a NULL confidence rather than a stand-in.
        nulls = conn.execute(
            "SELECT COUNT(*) FROM review_language "
            "WHERE language_method IN ('script','short-text') AND language_confidence IS NOT NULL"
        ).fetchone()[0]
        check("phase3 language: rule-based rows carry no fabricated confidence",
              nulls == 0, str(nulls))
        orphans = conn.execute(
            "SELECT COUNT(*) FROM review_language l "
            "LEFT JOIN reviews r ON r.review_id = l.review_id WHERE r.review_id IS NULL"
        ).fetchone()[0]
        check("phase3 language: no orphan rows", orphans == 0, str(orphans))
    finally:
        conn.close()

    # A stale artifact naming ids that no longer exist must be dropped, with a note.
    stale = pd.read_csv(labels)
    stale["review_id"] = ["gone_" + str(i) for i in range(len(stale))]
    stale.to_csv(labels, index=False)
    result = run_build(data)
    check("phase3 language: a stale artifact does not fail the build",
          result.returncode == 0, result.stderr[-400:])
    check("phase3 language: dropped rows are reported",
          "not in the corpus" in result.stdout, result.stdout[-500:])
    conn = sqlite3.connect(data / "touristinbd.db")
    try:
        rows = conn.execute("SELECT COUNT(*) FROM review_language").fetchone()[0]
        check("phase3 language: stale rows are not written", rows == 0, str(rows))
    finally:
        conn.close()

    # Absent entirely: the table must exist and be empty, and the API must work.
    labels.unlink()
    result = run_build(data)
    check("phase3 language: build succeeds without the artifact",
          result.returncode == 0, result.stderr[-400:])
    conn = sqlite3.connect(data / "touristinbd.db")
    try:
        rows = conn.execute("SELECT COUNT(*) FROM review_language").fetchone()[0]
        check("phase3 language: the table is empty, not missing", rows == 0, str(rows))
    finally:
        conn.close()
    client = api_client(data)
    r = client.get("/api/overview")
    check("phase3 language: the API still answers without it", r.status_code == 200, str(r.status_code))


def scenario_missing_db(tmp: Path) -> None:
    """The API must degrade honestly when the database has not been built."""
    data = tmp / "no_db" / "data"
    data.mkdir(parents=True, exist_ok=True)
    client = api_client(data)
    health = client.get("/health").json()
    check(
        "missing db: /health reports degraded with a build hint",
        health["status"] == "degraded" and "build_phase8_database" in (health["detail"] or ""),
        str(health),
    )
    r = client.get("/api/overview")
    check("missing db: data endpoint returns 503", r.status_code == 503, str(r.status_code))


def main() -> None:
    print("Phase 8 — rebuild / forward-compatibility tests\n")
    original = os.environ.get("TOURISTINBD_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="touristinbd-phase8-") as tmpdir:
            tmp = Path(tmpdir)
            print("scenario: new place not in place_geography.csv")
            scenario_new_place(tmp)
            print("\nscenario: new preference id in the taxonomy")
            scenario_new_preference(tmp)
            print("\nscenario: Phase 2 output only, later phases missing")
            scenario_phase2_only(tmp)
            print("\nscenario: upstream schema drift + stale geography row")
            scenario_schema_drift(tmp)
            print("\nscenario: Phase 3 language artifact present, stale and absent")
            scenario_phase3_language(tmp)
            print("\nscenario: database not built yet")
            scenario_missing_db(tmp)
    finally:
        if original is None:
            os.environ.pop("TOURISTINBD_DATA_DIR", None)
        else:
            os.environ["TOURISTINBD_DATA_DIR"] = original

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All Phase 8 rebuild tests passed.")


if __name__ == "__main__":
    main()
