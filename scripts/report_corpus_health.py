"""Corpus health report — run after every import, before re-running Phase 3.

Read-only. Looks at data/processed_reviews.csv (and place_geography.csv) and says
whether the corpus is in a state the later phases can use, and where it is thin:

  * reviews / places per division — which divisions still have no coverage
  * places missing from place_geography.csv (they would have no division, so the
    itinerary planner cannot place them)
  * language mix, and how many reviews carry the reviewer's original text
  * places with very few reviews (a topic needs several reviews to form)
  * rough Phase 3 settings this corpus size implies

Writes data/corpus_health_report.md and prints the same text.

Run:
    .venv/bin/python scripts/report_corpus_health.py
    .venv/bin/python scripts/report_corpus_health.py --min-place-reviews 30
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

DIVISIONS = ["Barishal", "Chattogram", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"]


def build_report(data_dir: Path, min_place_reviews: int, min_division_places: int) -> tuple[str, list[str]]:
    reviews = pd.read_csv(data_dir / "processed_reviews.csv")
    geo_path = data_dir / "place_geography.csv"
    geo = pd.read_csv(geo_path) if geo_path.exists() else pd.DataFrame(columns=["place_name", "division"])

    problems: list[str] = []
    n = len(reviews)
    places = reviews["place_name"].dropna().unique()

    # --- geography ---------------------------------------------------------
    geo_division = geo.set_index("place_name")["division"] if len(geo) else pd.Series(dtype=object)
    missing_geo = sorted(p for p in places if p not in geo_division.index or pd.isna(geo_division.get(p)))
    if missing_geo:
        problems.append(f"{len(missing_geo)} place(s) have no division in place_geography.csv")

    per_place = reviews.groupby("place_name").size().sort_values(ascending=False)
    per_place_df = per_place.rename("reviews").to_frame()
    per_place_df["division"] = [geo_division.get(p) if p in geo_division.index else None for p in per_place_df.index]

    div_rows = []
    for d in DIVISIONS:
        sub = per_place_df[per_place_df["division"] == d]
        div_rows.append((d, len(sub), int(sub["reviews"].sum())))
        if len(sub) < min_division_places:
            problems.append(f"{d}: {len(sub)} place(s), want at least {min_division_places}")

    thin = per_place[per_place < min_place_reviews]
    if len(thin):
        problems.append(f"{len(thin)} place(s) under {min_place_reviews} reviews")

    # --- language ----------------------------------------------------------
    lang = reviews["detected_language"].fillna("unknown").value_counts()
    non_en = int(n - lang.get("en", 0))
    has_original = (
        int(reviews["review_text_original"].notna().sum()) if "review_text_original" in reviews.columns else 0
    )

    # --- sources / duplicates ---------------------------------------------
    by_source = reviews["source"].value_counts()
    dup_ids = int(reviews["review_id"].duplicated().sum())
    if dup_ids:
        problems.append(f"{dup_ids} duplicate review_id value(s)")

    # --- Phase 3 implications ---------------------------------------------
    suggested_topic_size = max(6, round(n * 0.004))

    lines = [
        "# Corpus health report",
        "",
        f"- Reviews: **{n}** across **{len(places)}** places",
        f"- Sources: " + ", ".join(f"{k} {v}" for k, v in by_source.items()),
        f"- Reviews with the reviewer's original text kept: **{has_original}** of {n}",
        f"- Not English (by detected language): **{non_en}** ({non_en / n:.1%})",
        f"- Suggested BERTopic min_topic_size for this size: **{suggested_topic_size}** "
        "(Phase 3 computes this itself; shown for reference)",
        "",
        "## Divisions",
        "",
        "| Division | Places | Reviews |",
        "|---|---:|---:|",
    ]
    lines += [f"| {d} | {p} | {r} |" for d, p, r in div_rows]
    lines += ["", "## Language mix", "", "| Language | Reviews |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in lang.items()]

    if missing_geo:
        lines += ["", "## Places missing from place_geography.csv", ""]
        lines += [f"- {p}" for p in missing_geo]
    if len(thin):
        lines += ["", f"## Places under {min_place_reviews} reviews", ""]
        lines += [f"- {p}: {c}" for p, c in thin.items()]

    lines += ["", "## Verdict", ""]
    lines += [f"- {p}" for p in problems] if problems else ["- no problems found"]
    return "\n".join(lines) + "\n", problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-place-reviews", type=int, default=20)
    parser.add_argument("--min-division-places", type=int, default=1,
                        help="warn when a division has fewer places than this (plan target: 5)")
    parser.add_argument("--no-write", action="store_true", help="print only; do not write the .md file")
    args = parser.parse_args()

    if not (DATA_DIR / "processed_reviews.csv").exists():
        print(f"{DATA_DIR / 'processed_reviews.csv'} not found — run Phase 2 first", file=sys.stderr)
        return 1

    text, problems = build_report(DATA_DIR, args.min_place_reviews, args.min_division_places)
    print(text)
    if not args.no_write:
        out = DATA_DIR / "corpus_health_report.md"
        out.write_text(text, encoding="utf-8")
        print(f"(written to {out})")
    # Missing geography is the only hard failure; everything else is advisory.
    return 2 if any("no division" in p for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
