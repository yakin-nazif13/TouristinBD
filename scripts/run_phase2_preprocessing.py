"""
Phase 2 — merge, clean and language-tag the raw review batches.

This is the step that turns whatever you scraped into
`data/processed_reviews.csv`, the file every later phase reads. It is
deliberately *rediscovering* its inputs rather than naming them: every
`data/real_reviews_*.csv` is picked up, so adding a new batch is a matter of
dropping a file in (or letting `scripts/add_reviews.py` do it for you) and
re-running this script.

What it does, in order:
1. **Merge** every batch into one table, in filename order. Columns that only
   some sources have (traveler_type, nights_stayed, …) are kept and left empty
   for the sources that lack them; unknown extra columns are dropped.
2. **Clean** the text: HTML entities unescaped, Booking.com's
   "Liked:/Disliked:" labels turned into sentences, newlines and runs of
   whitespace collapsed.
3. **Drop** reviews too short to carry meaning (< 10 characters after
   cleaning) and exact duplicates of an earlier review's cleaned text.
4. **Detect the language** for real, rather than trusting the platform tag —
   which is unreliable: many Booking rows tagged `en` are Bengali script, and
   81 rows carry Booking's placeholder tag `xu`. When a batch carries the
   reviewer's own words (`review_text_original`, written by add_reviews.py),
   the language is detected on *those*, not on Google's translation — so
   `detected_language` means "the language the reviewer wrote in".
5. **Carry the original text through** as `review_text_original` (cleaned the
   same way) plus `original_language`. These two columns are only written when
   at least one batch has them, so corpora collected before the fix reproduce
   byte for byte.

Re-running this on the current batches reproduces the committed
`data/processed_reviews.csv` byte for byte, which is what
`scripts/test_phase2_preprocessing.py` asserts.

Run:
    .venv/bin/python scripts/run_phase2_preprocessing.py
    .venv/bin/python scripts/run_phase2_preprocessing.py --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

BATCH_GLOB = "real_reviews_*.csv"
OUT_CSV = DATA_DIR / "processed_reviews.csv"
OUT_REPORT_MD = DATA_DIR / "phase2_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase2_report.json"
# Optional hand corrections for rows the detector gets wrong; see
# `_apply_overrides`. Not required to exist.
OVERRIDES_CSV = DATA_DIR / "language_overrides.csv"
GEOGRAPHY_CSV = DATA_DIR / "place_geography.csv"

# A review shorter than this after cleaning ("Bad. No") carries no signal for
# topic modelling and only adds noise to the corpus.
MIN_CLEAN_LENGTH = 10

# langdetect is trained on running prose and misfires badly on short strings —
# it reads "Exceptional. Beautyful" as Romanian and "Very poor. Dirty property"
# as Afrikaans. Below this length, Latin-script text is taken as English, which
# is right for this corpus (Google/Booking listings that face international
# visitors skew heavily English). Raising it trades false non-English labels for
# missed real ones; 50 is where the current corpus stops producing false hits.
SHORT_TEXT_MAX = 50

BENGALI_RE = re.compile(r"[ঀ-৿]")
LATIN_RE = re.compile(r"[A-Za-z]")
# Booking.com packs its structured fields into one string:
#   "Good | Liked: clean rooms | Disliked: noisy street"
BOOKING_LABEL_RE = re.compile(r"\s*\|\s*(?:Liked|Disliked):\s*")
BOOKING_LEADING_LABEL_RE = re.compile(r"^\s*(?:Liked|Disliked):\s*")

# Written in this order, matching the schema every later phase expects.
OUTPUT_COLUMNS = [
    "review_id",
    "source",
    "place_name",
    "city",
    "category",
    "review_rating",
    "place_avg_rating",
    "review_text_clean",
    "review_date",
    "detected_language",
    "platform_language_tag",
    "traveler_type",
    "user_location",
    "nights_stayed",
    "reviewer_num_reviews",
    "reviewer_is_local_guide",
    "review_likes",
    "source_url",
]

# Written after OUTPUT_COLUMNS, and only when some batch provides them.
OPTIONAL_OUTPUT_COLUMNS = ["review_text_original", "original_language"]

# Raw column -> output column, for the two that get renamed.
RENAMES = {"review_text": "review_text_clean", "review_language": "platform_language_tag"}

REQUIRED_RAW_COLUMNS = {"review_id", "place_name", "review_text", "source"}


def clean_text(value: object) -> str:
    """Normalize one review body. Deterministic and idempotent."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(value)
    text = BOOKING_LEADING_LABEL_RE.sub("", text)
    text = BOOKING_LABEL_RE.sub(". ", text)
    return re.sub(r"\s+", " ", text).strip()


_detect = None


def _detector():
    """Load langdetect once, with a fixed seed.

    langdetect is probabilistic: without seeding, the same review can get
    different labels on different runs, which would make Phase 2 unreproducible.
    Seeding here rather than in `main()` means importing this module — as the
    tests and any future script do — is seeded too.
    """
    global _detect
    if _detect is None:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        _detect = detect
    return _detect


def detect_language(text: str, short_text_max: int = SHORT_TEXT_MAX) -> str:
    """Language of one cleaned review: `bn`, `bn-en-mixed`, or an ISO code.

    Bengali script is matched directly rather than left to langdetect, because
    the code-mixed rows ("গিজার কাজ করে না" alongside English) are exactly the
    multilingual signal the project cares about and a single label would hide.
    """
    if BENGALI_RE.search(text):
        return "bn-en-mixed" if LATIN_RE.search(text) else "bn"
    if len(text) < short_text_max and LATIN_RE.search(text):
        return "en"
    try:
        return _detector()(text)
    except ImportError:
        return "en" if LATIN_RE.search(text) else "unknown"
    except Exception:
        # langdetect raises on text with no detectable features (emoji only).
        return "unknown"


def find_batches(data_dir: Path, explicit: list[str] | None) -> list[Path]:
    if explicit:
        paths = [Path(p) if Path(p).is_absolute() else (data_dir / p) for p in explicit]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise SystemExit(f"input file(s) not found: {', '.join(missing)}")
        return paths
    # Sorted so the merge order — and therefore which copy of a duplicated
    # review is kept — is stable across machines and runs.
    return sorted(data_dir.glob(BATCH_GLOB))


def load_batches(paths: list[Path], notes: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        df = pd.read_csv(path)
        missing = REQUIRED_RAW_COLUMNS - set(df.columns)
        if missing:
            raise SystemExit(
                f"{path.name} is missing required column(s): {', '.join(sorted(missing))}.\n"
                f"Every batch needs at least {sorted(REQUIRED_RAW_COLUMNS)}."
            )
        notes.append(f"loaded {len(df)} row(s) from {path.name}")
        frames.append(df)
    if not frames:
        raise SystemExit(
            f"no review batches found in {paths[0].parent if paths else DATA_DIR}.\n"
            f"Expected file(s) matching {BATCH_GLOB} — see scripts/add_reviews.py."
        )
    return pd.concat(frames, ignore_index=True)


def _apply_overrides(df: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """Let a human correct detected languages without editing this script.

    `data/language_overrides.csv` needs a `review_id` and a
    `detected_language` column. Rows whose id is not in the corpus are
    reported, not silently ignored — a typo'd id should be visible.
    """
    if not OVERRIDES_CSV.exists():
        return df
    overrides = pd.read_csv(OVERRIDES_CSV)
    if not {"review_id", "detected_language"} <= set(overrides.columns):
        notes.append(f"{OVERRIDES_CSV.name} lacks review_id/detected_language; ignored")
        return df
    mapping = dict(zip(overrides["review_id"], overrides["detected_language"]))
    known = df["review_id"].isin(mapping)
    unknown = sorted(set(mapping) - set(df["review_id"]))
    if unknown:
        notes.append(f"{len(unknown)} override id(s) match no review: {', '.join(map(str, unknown[:5]))}")
    if known.any():
        df.loc[known, "detected_language"] = df.loc[known, "review_id"].map(mapping)
        notes.append(f"applied {int(known.sum())} manual language override(s)")
    return df


def preprocess(
    raw: pd.DataFrame, notes: list[str], short_text_max: int = SHORT_TEXT_MAX
) -> tuple[pd.DataFrame, dict]:
    total_in = len(raw)
    df = raw.rename(columns=RENAMES).copy()

    duplicate_ids = int(df["review_id"].duplicated().sum())
    if duplicate_ids:
        df = df.drop_duplicates(subset=["review_id"], keep="first")
        notes.append(f"dropped {duplicate_ids} row(s) sharing a review_id with an earlier row")

    df["review_text_clean"] = df["review_text_clean"].map(clean_text)

    too_short = df["review_text_clean"].str.len() < MIN_CLEAN_LENGTH
    if too_short.any():
        for text in df.loc[too_short, "review_text_clean"].head(5):
            notes.append(f"dropped as too short (< {MIN_CLEAN_LENGTH} chars): {text!r}")
        df = df[~too_short]

    duplicate_text = df["review_text_clean"].duplicated(keep="first")
    if duplicate_text.any():
        for text in df.loc[duplicate_text, "review_text_clean"].head(5):
            notes.append(f"dropped as an exact duplicate of an earlier review: {text!r}")
        df = df[~duplicate_text]

    has_original = "review_text_original" in df.columns
    if has_original:
        original = df["review_text_original"].map(clean_text)
        df["review_text_original"] = original.where(original != "", pd.NA)
        language_basis = df["review_text_original"].fillna(df["review_text_clean"])
    else:
        language_basis = df["review_text_clean"]

    df["detected_language"] = language_basis.map(lambda t: detect_language(t, short_text_max))
    df = _apply_overrides(df, notes)

    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
            notes.append(f"column {column} absent from every batch; written empty")
    extra = [c for c in OPTIONAL_OUTPUT_COLUMNS if c in df.columns]
    out = df[OUTPUT_COLUMNS + extra].reset_index(drop=True)

    stats = {
        "rows_in": total_in,
        "rows_out": len(out),
        "dropped_duplicate_id": duplicate_ids,
        "dropped_too_short": int(too_short.sum()),
        "dropped_duplicate_text": int(duplicate_text.sum()),
        "by_source": {str(k): int(v) for k, v in out["source"].value_counts().items()},
        "by_language": {str(k): int(v) for k, v in out["detected_language"].value_counts().items()},
        "places": int(out["place_name"].nunique()),
    }
    if has_original:
        with_original = out["review_text_original"].notna()
        stats["with_original_text"] = int(with_original.sum())
        stats["translated_by_platform"] = int(
            (with_original & (out["review_text_original"] != out["review_text_clean"])).sum()
        )
    return out, stats


def check_downstream(out: pd.DataFrame, notes: list[str]) -> list[str]:
    """Warn about what a new batch invalidates, instead of leaving it silent."""
    warnings: list[str] = []

    topics_path = DATA_DIR / "reviews_with_topics.csv"
    if topics_path.exists():
        known = set(pd.read_csv(topics_path, usecols=["review_id"])["review_id"])
        unclustered = sorted(set(out["review_id"]) - known)
        if unclustered:
            warnings.append(
                f"{len(unclustered)} review(s) have no topic assignment yet. They will load "
                "with topic_id NULL — counted in ratings and totals, but contributing no "
                "preference evidence to recommendations or itineraries. Re-run Phase 3 "
                "(and then Phase 4) to cluster them."
            )

    if GEOGRAPHY_CSV.exists():
        geo = pd.read_csv(GEOGRAPHY_CSV)
        missing_geo = sorted(
            set(out.loc[out["city"].isna() | (out["city"].astype(str).str.strip() == ""), "place_name"])
            - set(geo["place_name"])
        )
        if missing_geo:
            warnings.append(
                f"{len(missing_geo)} place(s) have no city in the batch and no row in "
                f"{GEOGRAPHY_CSV.name}: {', '.join(missing_geo[:5])}. Add them there or their "
                "city/district/division will be empty everywhere in the app."
            )

    if out["review_rating"].max() is not pd.NA and pd.to_numeric(
        out["review_rating"], errors="coerce"
    ).max() > 5:
        warnings.append(
            "Some review_rating values exceed 5 — Booking.com's 1-10 scale was probably not "
            "converted. Re-import that batch with `add_reviews.py --rating-scale 10`."
        )
    return warnings


def write_report(paths: list[Path], stats: dict, notes: list[str], warnings: list[str]) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": [p.name for p in paths],
        "output": OUT_CSV.name,
        "min_clean_length": MIN_CLEAN_LENGTH,
        "short_text_max": SHORT_TEXT_MAX,
        **stats,
        "notes": notes,
        "warnings": warnings,
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Phase 2 — preprocessing report",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        f"- Inputs: {', '.join(payload['inputs'])}",
        f"- Output: `data/{OUT_CSV.name}` — **{stats['rows_out']} reviews** "
        f"across {stats['places']} places (from {stats['rows_in']} raw rows)",
        f"- Dropped: {stats['dropped_too_short']} too short, "
        f"{stats['dropped_duplicate_text']} duplicate text, "
        f"{stats['dropped_duplicate_id']} duplicate id",
        f"- By source: {stats['by_source']}",
        f"- By detected language: {stats['by_language']}",
    ]
    if "with_original_text" in stats:
        lines.append(
            f"- Original-language text kept for {stats['with_original_text']} reviews; "
            f"{stats['translated_by_platform']} of them were machine-translated by the platform"
        )
    lines.append("")
    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]
    lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    OUT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help=f"batch CSVs (default: every data/{BATCH_GLOB})")
    parser.add_argument("--dry-run", action="store_true", help="report without writing any file")
    parser.add_argument(
        "--short-text-max",
        type=int,
        default=SHORT_TEXT_MAX,
        help=f"below this length, Latin-script text is taken as English (default {SHORT_TEXT_MAX})",
    )
    args = parser.parse_args()

    print("Phase 2 — preprocessing raw review batches")
    notes: list[str] = []
    paths = find_batches(DATA_DIR, args.inputs)
    print(f"  inputs: {', '.join(p.name for p in paths)}")

    try:
        _detector()
    except ImportError:
        notes.append(
            "langdetect not installed — Latin-script text defaulted to English. "
            "Install it (`pip install langdetect`) for real detection."
        )
        print("  WARNING: langdetect not installed; detection degraded to script matching")

    raw = load_batches(paths, notes)
    out, stats = preprocess(raw, notes, args.short_text_max)
    warnings = check_downstream(out, notes)

    print(f"  {stats['rows_in']} raw rows -> {stats['rows_out']} clean reviews")
    print(f"    dropped: {stats['dropped_too_short']} too short, "
          f"{stats['dropped_duplicate_text']} duplicate text, "
          f"{stats['dropped_duplicate_id']} duplicate id")
    print(f"    sources:   {stats['by_source']}")
    print(f"    languages: {stats['by_language']}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
    else:
        out.to_csv(OUT_CSV, index=False)
        write_report(paths, stats, notes, warnings)
        print(f"  wrote data/{OUT_CSV.name} and data/{OUT_REPORT_MD.name}")

    if warnings:
        print("\n  WARNINGS")
        for w in warnings:
            print(f"    - {w}")
    print(
        "\n  Next: re-run Phase 3 (topics) -> Phase 4 (preferences) -> "
        "scripts/build_phase8_database.py"
    )


if __name__ == "__main__":
    sys.exit(main())
