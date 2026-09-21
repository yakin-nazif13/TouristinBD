"""
Add a new batch of scraped reviews to the corpus.

This is the front door for new data. Point it at a fresh export and it will
normalize the columns, fill in anything the export left out, refuse rows that
are already in the corpus, save the batch as `data/real_reviews_<name>.csv`,
and re-run Phase 2 so `data/processed_reviews.csv` is up to date.

    .venv/bin/python scripts/add_reviews.py ~/Downloads/apify_export.csv \\
        --source google_maps --name batch2

Booking.com exports rate out of 10; convert them on the way in so the corpus
stays on one scale:

    .venv/bin/python scripts/add_reviews.py ~/Downloads/booking.csv \\
        --source booking.com --name booking_batch2 --rating-scale 10

Nothing is overwritten: the batch file is new, the raw export is left alone,
and `--dry-run` shows exactly what would happen first.

**Original-language text is kept.** Google Maps actors return a review twice:
what the reviewer wrote, and Google's translation into the scrape language.
Earlier versions of this script mapped the translation onto `review_text` and
threw the original away, which is why the first corpus reads as 98.5% English.
Now `review_text` stays the (usually English) analysis text and the reviewer's
own words land in `review_text_original`, with `original_language` beside it.
When an export gives no way to tell original from translation, the script says
so instead of guessing.

**Adding reviews is only half the job.** New rows have no topic and therefore no
preference evidence until Phase 3 and Phase 4 are re-run — they will show up in
place listings, ratings and search, but will not influence recommendations or
itineraries. This script prints the remaining commands when it finishes.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
PHASE2 = REPO_ROOT / "scripts" / "run_phase2_preprocessing.py"

# The schema Phase 2 reads. Only the first four are required.
REQUIRED = ["review_id", "place_name", "review_text", "source"]
OPTIONAL = [
    "city",
    "category",
    "review_rating",
    "place_avg_rating",
    "review_date",
    "review_language",
    "traveler_type",
    "user_location",
    "nights_stayed",
    "reviewer_num_reviews",
    "reviewer_is_local_guide",
    "review_likes",
    "source_url",
    "address",
    # Multilingual provenance (see resolve_text_columns).
    "review_text_original",
    "original_language",
]

# Review-body fields, by what they are known to contain. Actors disagree on
# naming: some emit `text` (original) + `textTranslated`, others emit `text`
# (translated) + `originalText`. Naming the unambiguous fields explicitly is
# what lets resolve_text_columns tell the two layouts apart.
ORIGINAL_TEXT_FIELDS = ["review_text_original", "originalText", "textOriginal", "text_original"]
TRANSLATED_TEXT_FIELDS = ["textTranslated", "translatedText", "text_translated"]
PLAIN_TEXT_FIELDS = ["review_text", "text", "reviewText", "comment"]
ORIGINAL_LANGUAGE_FIELDS = ["original_language", "originalLanguage", "languageOriginal"]

# Best-effort aliases for the field names Apify's Google Maps and Booking.com
# actors emit. Anything not covered here can be mapped with --map old=new.
ALIASES = {
    # place
    "title": "place_name",
    "name": "place_name",
    "hotelName": "place_name",
    "placeName": "place_name",
    "categoryName": "category",
    "type": "category",
    # review body: handled by resolve_text_columns, not by renaming, so that
    # an original and its translation can never collapse into one column.
    # ratings
    "stars": "review_rating",
    "rating": "review_rating",
    "score": "review_rating",
    "totalScore": "place_avg_rating",
    "averageRating": "place_avg_rating",
    # dates
    "publishedAtDate": "review_date",
    "publishedAt": "review_date",
    "reviewDate": "review_date",
    "date": "review_date",
    # identity / provenance
    "reviewId": "review_id",
    "reviewUrl": "source_url",
    "url": "source_url",
    "placeUrl": "source_url",
    # reviewer
    "reviewerNumberOfReviews": "reviewer_num_reviews",
    "isLocalGuide": "reviewer_is_local_guide",
    "likesCount": "review_likes",
    "originalLanguage": "review_language",
    "language": "review_language",
    # booking extras
    "travelerType": "traveler_type",
    "userLocation": "user_location",
    "numberOfNights": "nights_stayed",
    "checkInDate": "review_date",
}


def make_review_id(row: pd.Series) -> str:
    """Stable id from the review's own content.

    Content-derived rather than random so that re-importing the same export
    produces the same ids and is caught as a duplicate instead of silently
    doubling the corpus.
    """
    seed = "|".join(
        str(row.get(field, "")) for field in ("source", "place_name", "review_text", "review_date")
    )
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:16]


def _first_present(df: pd.DataFrame, fields: list[str]) -> str | None:
    return next((f for f in fields if f in df.columns), None)


def _blank_to_na(series: pd.Series) -> pd.Series:
    as_text = series.astype("string")
    return as_text.where(as_text.str.strip().fillna("") != "", pd.NA)


def resolve_text_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Split the review body into `review_text` (analysis) and `review_text_original`.

    Three export layouts are recognised:

    1. An explicit original field (`originalText`, ...). The plain `text`
       field is then the translation; analysis text = translation if given,
       else the original.
    2. An explicit translated field (`textTranslated`, ...) and no original
       field. The plain `text` field is then what the reviewer wrote.
    3. Neither. The export cannot say whether `text` was translated, so the
       original is left empty and a note tells the user to enable the actor's
       original-text output. Guessing here would silently label machine
       translations as reviewer language.
    """
    notes: list[str] = []
    orig_col = _first_present(df, ORIGINAL_TEXT_FIELDS)
    trans_col = _first_present(df, TRANSLATED_TEXT_FIELDS)
    plain_col = _first_present(df, PLAIN_TEXT_FIELDS)
    if plain_col is None and orig_col is None and trans_col is None:
        return df, notes  # nothing to resolve; the REQUIRED check reports it

    plain = _blank_to_na(df[plain_col]) if plain_col else pd.Series(pd.NA, index=df.index, dtype="string")
    trans = _blank_to_na(df[trans_col]) if trans_col else pd.Series(pd.NA, index=df.index, dtype="string")

    if orig_col is not None:
        original = _blank_to_na(df[orig_col])
        # Rows already in the scrape language often carry no separate original.
        original = original.fillna(plain) if trans_col is None else original.fillna(plain.where(trans.isna()))
        analysis = trans.fillna(plain).fillna(original)
        layout = f"original from `{orig_col}`"
    elif trans_col is not None:
        original = plain
        analysis = trans.fillna(plain)
        layout = f"original from `{plain_col}`, translation from `{trans_col}`"
    else:
        original = None
        analysis = plain
        layout = None

    consumed = {c for c in (orig_col, trans_col, plain_col) if c}
    df = df.drop(columns=sorted(consumed))
    df["review_text"] = analysis
    if layout is not None:
        df["review_text_original"] = original

    lang_col = _first_present(df, ORIGINAL_LANGUAGE_FIELDS)
    if lang_col is not None:
        df["original_language"] = _blank_to_na(df[lang_col])
        if lang_col != "original_language":
            # Keep the platform tag too, as review_language always was.
            df = df.rename(columns={lang_col: "review_language"}) if "review_language" not in df.columns else df.drop(columns=[lang_col])

    if layout is None:
        notes.append(
            "WARNING: the export has no original-text or translation field, so the reviewer's "
            "own words cannot be separated from a Google translation. review_text_original "
            "is left empty. Re-scrape with the actor's original-text output enabled "
            "(see docs/BUILD_PLAN.txt, Phase 2)."
        )
    else:
        kept = int(original.notna().sum())
        differs = int((original.notna() & analysis.notna() & (original != analysis)).sum())
        notes.append(
            f"kept original-language text for {kept} row(s) ({layout}); "
            f"{differs} differ from the analysis text, i.e. were translated"
        )
    return df, notes


def normalize_columns(df: pd.DataFrame, extra_map: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    mapping = {**ALIASES, **extra_map}
    renames = {c: mapping[c] for c in df.columns if c in mapping and mapping[c] not in df.columns}
    if renames:
        df = df.rename(columns=renames)
        notes.append(f"renamed {len(renames)} column(s): " + ", ".join(f"{k}->{v}" for k, v in renames.items()))
    keep = [c for c in df.columns if c in REQUIRED + OPTIONAL]
    dropped = [c for c in df.columns if c not in keep]
    if dropped:
        notes.append(f"dropped {len(dropped)} unrecognised column(s): {', '.join(dropped[:8])}")
    return df[keep].copy(), notes


def existing_review_ids(data_dir: Path, skip: Path | None = None) -> set[str]:
    ids: set[str] = set()
    for path in sorted(data_dir.glob("real_reviews_*.csv")):
        if skip is not None and path.resolve() == skip.resolve():
            continue
        try:
            ids |= set(pd.read_csv(path, usecols=["review_id"])["review_id"].astype(str))
        except (ValueError, pd.errors.EmptyDataError):
            continue
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv", help="the new export to import")
    parser.add_argument("--source", help="value for the source column, e.g. google_maps")
    parser.add_argument("--name", help="batch name (default: the file's own name)")
    parser.add_argument(
        "--rating-scale",
        type=float,
        default=5.0,
        help="scale the export's ratings are on (use 10 for Booking.com; default 5)",
    )
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="extra column rename, repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing anything")
    parser.add_argument(
        "--no-preprocess", action="store_true", help="skip the Phase 2 re-run afterwards"
    )
    args = parser.parse_args()

    source_path = Path(args.csv).expanduser()
    if not source_path.exists():
        print(f"error: {source_path} does not exist")
        return 1

    extra_map = {}
    for pair in args.map:
        if "=" not in pair:
            print(f"error: --map expects OLD=NEW, got {pair!r}")
            return 1
        old, new = pair.split("=", 1)
        extra_map[old] = new

    print(f"Importing {source_path.name}")
    df = pd.read_csv(source_path)
    print(f"  {len(df)} row(s), {len(df.columns)} column(s)")

    # --map renames first, so a user can point an odd field at a known name.
    if extra_map:
        df = df.rename(columns={k: v for k, v in extra_map.items() if k in df.columns})
    df, text_notes = resolve_text_columns(df)
    df, notes = normalize_columns(df, extra_map)
    notes = text_notes + notes

    if "source" not in df.columns:
        if not args.source:
            print(
                "error: the export has no `source` column and --source was not given.\n"
                "       Pass e.g. --source google_maps so reviews can be traced to a platform."
            )
            return 1
        df["source"] = args.source
        notes.append(f"set source={args.source} for every row")
    elif args.source:
        df["source"] = args.source
        notes.append(f"overrode source={args.source} for every row")

    missing = [c for c in REQUIRED if c not in df.columns and c != "review_id"]
    if missing:
        print(f"error: required column(s) missing after mapping: {', '.join(missing)}")
        print(f"       columns present: {', '.join(df.columns)}")
        print("       map them with --map OLD=NEW")
        return 1

    if "review_id" not in df.columns or df["review_id"].isna().any():
        if "review_id" not in df.columns:
            df["review_id"] = pd.NA
        generated = df["review_id"].isna()
        df.loc[generated, "review_id"] = df[generated].apply(make_review_id, axis=1)
        notes.append(f"generated {int(generated.sum())} content-derived review_id(s)")
    df["review_id"] = df["review_id"].astype(str)

    if args.rating_scale != 5.0 and "review_rating" in df.columns:
        factor = 5.0 / args.rating_scale
        for column in ("review_rating", "place_avg_rating"):
            if column in df.columns:
                df[column] = (pd.to_numeric(df[column], errors="coerce") * factor).round(2)
        notes.append(f"converted ratings from a 1-{args.rating_scale:g} scale to 1-5")

    over_five = pd.to_numeric(df.get("review_rating"), errors="coerce").max()
    if over_five is not None and over_five > 5:
        print(
            f"  WARNING: highest review_rating is {over_five} — if this export is out of 10, "
            "re-run with --rating-scale 10"
        )

    before = len(df)
    df = df.drop_duplicates(subset=["review_id"], keep="first")
    if len(df) != before:
        notes.append(f"dropped {before - len(df)} row(s) duplicated inside the export itself")

    known = existing_review_ids(DATA_DIR)
    already = df["review_id"].isin(known)
    if already.any():
        notes.append(f"skipped {int(already.sum())} row(s) already in the corpus")
        df = df[~already]

    if df.empty:
        print("  nothing new to add — every row is already in the corpus")
        for note in notes:
            print(f"    - {note}")
        return 0

    name = args.name or source_path.stem
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    target = DATA_DIR / f"real_reviews_{safe}.csv"
    if target.exists() and not args.dry_run:
        print(f"error: {target.name} already exists — pass a different --name")
        return 1

    for note in notes:
        print(f"  - {note}")
    print(f"  {len(df)} new review(s) across {df['place_name'].nunique()} place(s)")
    print(f"    places: {', '.join(sorted(df['place_name'].astype(str).unique())[:6])}")

    if args.dry_run:
        print(f"\n  --dry-run: would write data/{target.name}, then re-run Phase 2")
        return 0

    df.to_csv(target, index=False)
    print(f"  wrote data/{target.name}")

    if args.no_preprocess:
        print(f"\n  Next: .venv/bin/python {PHASE2.relative_to(REPO_ROOT)}")
        return 0

    print("\nRe-running Phase 2 over every batch")
    result = subprocess.run([sys.executable, str(PHASE2)], cwd=REPO_ROOT)
    if result.returncode != 0:
        print("\n  Phase 2 failed — the batch file was written, fix the error and re-run it")
        return result.returncode

    print(
        "\nStill to do, in order:\n"
        "  1. .venv/bin/python scripts/run_phase3_huggingface_bertopic.py     # cluster the new reviews\n"
        "  2. .venv/bin/python scripts/run_phase4_preference_classification.py # needs a Gemini/OpenAI key\n"
        "  3. .venv/bin/python scripts/run_phase5_bidirectional_validation.py  # optional, refreshes validation\n"
        "  4. .venv/bin/python scripts/run_phase6_sensitivity_analysis.py      # optional\n"
        "  5. .venv/bin/python scripts/run_phase7_statistics_visualization.py  # optional, refreshes charts\n"
        "  6. .venv/bin/python scripts/build_phase8_database.py                # required — rebuilds the app's DB\n"
        "\nSteps 1-2 are what give the new reviews preference evidence. Until then they\n"
        "count in totals and ratings but not in recommendations or itineraries.\n"
        "If any new place had a blank city, add it to data/place_geography.csv too."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
