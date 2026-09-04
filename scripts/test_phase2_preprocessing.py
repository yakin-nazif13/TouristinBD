"""Phase 2 — tests for preprocessing and for adding new review batches.

The important guarantee here is **reproducibility**: re-running Phase 2 over the
current batches must reproduce the committed `data/processed_reviews.csv`
exactly, because every later phase is keyed on the `review_id`s in that file. If
cleaning drifts, topic assignments and preference mappings silently detach from
their reviews.

The rest of the suite exercises the ingestion path on throwaway copies of the
data directory (via `TOURISTINBD_DATA_DIR`), so the real corpus is never touched.

Run:
    .venv/bin/python scripts/test_phase2_preprocessing.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import run_phase2_preprocessing as phase2  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def run_script(script: str, *args: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
def test_clean_text() -> None:
    print("\nphase 2 — text cleaning")
    cases = [
        ("Good | Liked: clean rooms", "Good. clean rooms", "Booking labels become sentences"),
        (
            "Nice | Liked: bed | Disliked: noise",
            "Nice. bed. noise",
            "both Booking labels are handled",
        ),
        ("Liked: no leading pipe", "no leading pipe", "a leading label is stripped, not converted"),
        ("line one\nline two", "line one line two", "newlines collapse to a space"),
        ("spaced   out\t\ttext", "spaced out text", "runs of whitespace collapse"),
        ("  padded  ", "padded", "surrounding whitespace is trimmed"),
        ("caf&eacute; &amp; bar", "café & bar", "HTML entities are unescaped"),
        ("", "", "empty text stays empty"),
    ]
    for raw, expected, name in cases:
        check(name, phase2.clean_text(raw) == expected, f"{phase2.clean_text(raw)!r}")

    check("non-string input returns empty", phase2.clean_text(None) == "", "not empty")
    check("numeric input returns empty", phase2.clean_text(3.5) == "", "not empty")
    check(
        "emoji and Bengali script survive cleaning",
        phase2.clean_text("গিজার কাজ করে না 😔") == "গিজার কাজ করে না 😔",
        "content was stripped",
    )
    sample = "Good. | Liked: Breakfast is good.\nThe location is nice. | Disliked: Noise."
    once = phase2.clean_text(sample)
    check("cleaning is idempotent", phase2.clean_text(once) == once, f"{once!r}")


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
def test_detect_language() -> None:
    print("\nphase 2 — language detection")
    check(
        "pure Bengali is bn",
        phase2.detect_language("গিজার কাজ করে না বেসিনে পানি আসে না") == "bn",
        phase2.detect_language("গিজার কাজ করে না বেসিনে পানি আসে না"),
    )
    check(
        "Bengali mixed with Latin is bn-en-mixed",
        phase2.detect_language("সুন্দর জায়গা but the road is rough") == "bn-en-mixed",
        phase2.detect_language("সুন্দর জায়গা but the road is rough"),
    )
    check(
        "short Latin text defaults to English rather than a wrong guess",
        phase2.detect_language("Exceptional. Beautyful") == "en",
        phase2.detect_language("Exceptional. Beautyful"),
    )
    dutch = (
        "Aparte, maar unieke, locatie! De behulpzaamheid van het personeel is goed. "
        "Het is een bijzondere locatie: je moet door een winkel naar binnen en dan met "
        "de lift naar boven, waar de receptie zich bevindt."
    )
    check("real non-English prose is still detected", phase2.detect_language(dutch) == "nl",
          phase2.detect_language(dutch))
    english = (
        "The longest beach in the world. You can enjoy your seafood on the beach with live "
        "cooking. Some things can be improved. Hotels are good and reasonably priced."
    )
    check("long English prose is detected as English", phase2.detect_language(english) == "en",
          phase2.detect_language(english))
    check(
        "the short-text threshold is configurable",
        phase2.detect_language("Exceptional. Beautyful", short_text_max=0) != "en",
        "threshold had no effect",
    )


# ---------------------------------------------------------------------------
# Reproducing the committed corpus
# ---------------------------------------------------------------------------
def test_reproduces_committed_output() -> None:
    print("\nphase 2 — reproduces data/processed_reviews.csv exactly")
    committed = pd.read_csv(DATA_DIR / "processed_reviews.csv")
    batches = phase2.find_batches(DATA_DIR, None)
    check("both raw batches are discovered", len(batches) >= 2, str([p.name for p in batches]))

    notes: list[str] = []
    raw = phase2.load_batches(batches, notes)
    out, stats = phase2.preprocess(raw, notes)

    check("row count matches", len(out) == len(committed), f"{len(out)} vs {len(committed)}")
    check(
        "column order matches",
        list(out.columns) == list(committed.columns),
        str(list(out.columns)),
    )
    check(
        "review ids match, in order",
        out["review_id"].tolist() == committed["review_id"].tolist(),
        "ids or ordering differ — later phases would detach from their reviews",
    )
    for column in ("review_text_clean", "detected_language", "source", "place_name"):
        same = out[column].fillna("").tolist() == committed[column].fillna("").tolist()
        check(f"{column} matches the committed file", same, "differs")
    try:
        pd.testing.assert_frame_equal(out, committed, check_dtype=False)
        identical = True
        detail = ""
    except AssertionError as exc:
        identical = False
        detail = str(exc).splitlines()[0]
    check("the whole frame is identical", identical, detail)

    check(
        "the documented drops happened",
        stats["dropped_too_short"] == 1 and stats["dropped_duplicate_text"] == 1,
        str(stats),
    )
    check(
        "the language mix is the documented one",
        stats["by_language"] == {"en": 530, "bn-en-mixed": 5, "bn": 2, "nl": 1},
        str(stats["by_language"]),
    )


def test_drop_rules() -> None:
    print("\nphase 2 — drop rules")
    frame = pd.DataFrame(
        [
            {"review_id": "a", "place_name": "P", "source": "s", "review_text": "Bad. No"},
            {"review_id": "b", "place_name": "P", "source": "s", "review_text": "A perfectly fine review here"},
            {"review_id": "c", "place_name": "Q", "source": "s", "review_text": "A perfectly fine review here"},
            {"review_id": "d", "place_name": "R", "source": "s", "review_text": "Another distinct review body"},
            {"review_id": "d", "place_name": "R", "source": "s", "review_text": "Duplicate id, different text"},
        ]
    )
    notes: list[str] = []
    out, stats = phase2.preprocess(frame, notes)
    kept = out["review_id"].tolist()
    check("too-short reviews are dropped", "a" not in kept, str(kept))
    check("duplicate text is dropped across places", kept.count("b") + kept.count("c") == 1, str(kept))
    check("the first copy of duplicated text is kept", "b" in kept and "c" not in kept, str(kept))
    check("a repeated review_id is dropped", stats["dropped_duplicate_id"] == 1, str(stats))
    check("distinct reviews survive", "d" in kept, str(kept))
    check(
        "missing optional columns are written empty, not dropped",
        set(out.columns) == set(phase2.OUTPUT_COLUMNS) and out["traveler_type"].isna().all(),
        str(list(out.columns)),
    )


# ---------------------------------------------------------------------------
# The script end to end, on a throwaway data directory
# ---------------------------------------------------------------------------
def test_script_run(tmp: Path) -> None:
    print("\nphase 2 — the script on a copy of the data directory")
    data = tmp / "phase2run"
    data.mkdir()
    for name in ("real_reviews_batch1.csv", "real_reviews_booking_batch1.csv",
                 "reviews_with_topics.csv", "place_geography.csv"):
        shutil.copy2(DATA_DIR / name, data / name)

    result = run_script("run_phase2_preprocessing.py", data_dir=data)
    check("the script exits cleanly", result.returncode == 0, result.stderr[-300:])
    produced = data / "processed_reviews.csv"
    check("it writes processed_reviews.csv", produced.exists(), "missing")
    if produced.exists():
        check(
            "the file it writes is byte-for-byte the committed one",
            produced.read_bytes() == (DATA_DIR / "processed_reviews.csv").read_bytes(),
            "content differs",
        )
    check("it writes a report", (data / "phase2_report.md").exists(), "missing")
    report = json.loads((data / "phase2_report.json").read_text())
    check("the report records both inputs", len(report["inputs"]) == 2, str(report["inputs"]))
    check("the report records the row counts", report["rows_out"] == 538, str(report["rows_out"]))
    check(
        "no warning fires when every review is already clustered",
        not report["warnings"],
        str(report["warnings"]),
    )

    # A dry run must not touch anything.
    stamp = produced.stat().st_mtime_ns
    result = run_script("run_phase2_preprocessing.py", "--dry-run", data_dir=data)
    check("--dry-run exits cleanly", result.returncode == 0, result.stderr[-300:])
    check("--dry-run writes nothing", produced.stat().st_mtime_ns == stamp, "file was rewritten")

    # A manual language correction should win over the detector.
    first_id = pd.read_csv(produced, usecols=["review_id"])["review_id"].iloc[0]
    pd.DataFrame([{"review_id": first_id, "detected_language": "bn"}]).to_csv(
        data / "language_overrides.csv", index=False
    )
    run_script("run_phase2_preprocessing.py", data_dir=data)
    corrected = pd.read_csv(produced).set_index("review_id").loc[first_id, "detected_language"]
    check("a manual language override is applied", corrected == "bn", str(corrected))
    (data / "language_overrides.csv").unlink()

    result = run_script("run_phase2_preprocessing.py", "no_such_batch.csv", data_dir=data)
    check("a missing named input fails loudly", result.returncode != 0, "exited 0")


def test_add_reviews(tmp: Path) -> None:
    print("\nadd_reviews — importing a new batch")
    data = tmp / "ingest"
    data.mkdir()
    for name in ("real_reviews_batch1.csv", "real_reviews_booking_batch1.csv",
                 "reviews_with_topics.csv", "place_geography.csv"):
        shutil.copy2(DATA_DIR / name, data / name)

    # An export in Apify's column names, rated out of 10, with no review_id.
    export = tmp / "export.csv"
    pd.DataFrame(
        [
            {"title": "Nilgiri Hills", "categoryName": "Tourist attraction", "city": "Bandarban",
             "stars": 9.0, "totalScore": 8.6,
             "text": "Clouds below your feet at sunrise, and the drive up is spectacular.",
             "publishedAtDate": "2026-07-01T08:00:00Z", "language": "en", "url": "https://e.g/1"},
            {"title": "Nilgiri Hills", "categoryName": "Tourist attraction", "city": "Bandarban",
             "stars": 4.0, "totalScore": 8.6, "text": "Bad",
             "publishedAtDate": "2026-07-02T08:00:00Z", "language": "en", "url": "https://e.g/2"},
        ]
    ).to_csv(export, index=False)

    result = run_script("add_reviews.py", str(export), "--source", "google_maps",
                        "--name", "batch2", "--rating-scale", "10", "--dry-run", data_dir=data)
    check("--dry-run exits cleanly", result.returncode == 0, result.stderr[-300:])
    check(
        "--dry-run writes no batch file",
        not (data / "real_reviews_batch2.csv").exists(),
        "a file was written",
    )

    result = run_script("add_reviews.py", str(export), "--source", "google_maps",
                        "--name", "batch2", "--rating-scale", "10", data_dir=data)
    check("the import exits cleanly", result.returncode == 0, result.stderr[-400:])
    batch = data / "real_reviews_batch2.csv"
    check("the batch file is written", batch.exists(), "missing")
    if not batch.exists():
        return
    added = pd.read_csv(batch)

    check("Apify column names are mapped", "place_name" in added.columns, str(list(added.columns)))
    check("the source column is set", set(added["source"]) == {"google_maps"}, str(set(added["source"])))
    check("review ids are generated", added["review_id"].notna().all(), "missing ids")
    check(
        "generated ids look like the existing ones",
        added["review_id"].astype(str).str.fullmatch(r"[0-9a-f]{16}").all(),
        str(added["review_id"].tolist()),
    )
    check(
        "ratings are converted to the 1-5 scale",
        added["review_rating"].max() <= 5 and added["review_rating"].iloc[0] == 4.5,
        str(added["review_rating"].tolist()),
    )
    check("unrecognised columns are dropped", "url" not in added.columns, str(list(added.columns)))

    # Phase 2 ran as part of the import and picked the batch up.
    processed = pd.read_csv(data / "processed_reviews.csv")
    check(
        "the new place reaches processed_reviews.csv",
        "Nilgiri Hills" in set(processed["place_name"]),
        "place missing",
    )
    check(
        "the too-short row is still dropped downstream",
        len(processed) == 539,
        f"{len(processed)} rows",
    )
    report = json.loads((data / "phase2_report.json").read_text())
    check(
        "the report warns that new reviews have no topic yet",
        any("no topic assignment" in w for w in report["warnings"]),
        str(report["warnings"]),
    )

    # Re-importing the same export must be a no-op, not a doubling.
    result = run_script("add_reviews.py", str(export), "--source", "google_maps",
                        "--name", "batch3", "--rating-scale", "10", data_dir=data)
    check("re-importing exits cleanly", result.returncode == 0, result.stderr[-300:])
    check(
        "re-importing the same export adds nothing",
        "nothing new to add" in result.stdout and not (data / "real_reviews_batch3.csv").exists(),
        result.stdout[-300:],
    )

    result = run_script("add_reviews.py", str(export), "--name", "batch4", data_dir=data)
    check(
        "an export with no source is rejected with an explanation",
        result.returncode != 0 and "--source" in result.stdout,
        result.stdout[-200:],
    )
    # A different export carrying genuinely new rows, but a name already taken.
    other = tmp / "export2.csv"
    pd.DataFrame(
        [
            {"title": "Nilgiri Hills", "categoryName": "Tourist attraction", "city": "Bandarban",
             "stars": 8.0, "totalScore": 8.6,
             "text": "Cold at night up on the ridge, so bring a jacket with you.",
             "publishedAtDate": "2026-07-05T08:00:00Z", "language": "en", "url": "https://e.g/3"},
        ]
    ).to_csv(other, index=False)
    result = run_script("add_reviews.py", str(other), "--source", "google_maps",
                        "--name", "batch2", data_dir=data)
    check(
        "an existing batch name is refused rather than overwritten",
        result.returncode != 0 and "already exists" in result.stdout,
        result.stdout[-200:],
    )
    result = run_script("add_reviews.py", str(tmp / "nope.csv"), "--source", "x", data_dir=data)
    check("a missing input file is reported", result.returncode != 0, "exited 0")

    check(
        "the real data directory was never touched",
        (DATA_DIR / "processed_reviews.csv").exists()
        and not (DATA_DIR / "real_reviews_batch2.csv").exists(),
        "the test leaked into data/",
    )


def main() -> None:
    print("Phase 2 — preprocessing & ingestion tests")
    try:
        import langdetect  # noqa: F401
    except ImportError:
        print("\nlangdetect is not installed — install it with:")
        print("  .venv/bin/pip install langdetect")
        sys.exit(1)

    test_clean_text()
    test_detect_language()
    test_reproduces_committed_output()
    test_drop_rules()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        test_script_run(tmp)
        test_add_reviews(tmp)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 2 preprocessing/ingestion tests passed.")


if __name__ == "__main__":
    main()
