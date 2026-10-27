"""Where the data is thin: coverage of Bangladesh's 64 districts.

A hidden-gem engine can only find gems where people have written reviews. A
district with no reviewed place is not a district without gems; it is one the
engine cannot see. This table makes those blind spots explicit, so the next
collection round (YouTube, blogs, more places) goes where it is needed rather
than deeper into Cox's Bazar.

Per district:
    places, reviews           reviewed places there, and their reviews
    recent_reviews            reviews inside the recency window
    bangla_share              share of those reviews written in Bangla or Banglish
    mentions                  places, foods, activities... found in those reviews
    gem_candidates            gem candidates found in reviews of places there
    status                    no data | thin | covered

`thin` is fewer than THIN_REVIEWS reviews or a single reviewed place: fixed in
advance, round numbers, not fitted to the result.

Outputs:
    data/coverage_by_district.csv
    data/coverage_report.md / .json

Run:
    .venv/bin/python scripts/coverage_gaps.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import RECENCY_WINDOW_YEARS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_DISTRICTS = DATA_DIR / "bd_districts.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"
IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_QUEUE = DATA_DIR / "phase4_verification_queue.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"

OUT_CSV = DATA_DIR / "coverage_by_district.csv"
OUT_REPORT_MD = DATA_DIR / "coverage_report.md"
OUT_REPORT_JSON = DATA_DIR / "coverage_report.json"

THIN_REVIEWS = 100
BANGLA_LABELS = {"bn", "bn-en-mixed"}

COLUMNS = ["district", "division", "places", "reviews", "recent_reviews", "bangla_share",
           "mentions", "gem_candidates", "status", "place_names"]


def coverage(districts: pd.DataFrame, corpus: pd.DataFrame, geography: pd.DataFrame,
             mentions: pd.DataFrame | None, queue: pd.DataFrame | None,
             variants: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per district, including the ones with no reviews at all."""
    district_of = dict(zip(geography["place_name"].astype(str), geography["district"].astype(str)))
    reviews = corpus.assign(district=corpus["place_name"].astype(str).map(district_of))
    dates = pd.to_datetime(reviews["review_date"], errors="coerce", utc=True)
    cutoff = dates.max() - pd.DateOffset(years=RECENCY_WINDOW_YEARS)
    reviews = reviews.assign(recent=dates >= cutoff,
                             bangla=reviews["detected_language"].astype(str).isin(BANGLA_LABELS))

    mention_counts, gem_counts = pd.Series(dtype=int), pd.Series(dtype=int)
    if mentions is not None and not mentions.empty:
        place_of = dict(zip(corpus["review_id"].astype(str), corpus["place_name"].astype(str)))
        hosts = mentions.assign(district=mentions["review_id"].astype(str).map(place_of).map(district_of))
        mention_counts = hosts["district"].value_counts()
        # A gem counts once in every district whose reviews mention it.
        if queue is not None and not queue.empty and variants is not None:
            to_entity = dict(zip(variants["surface"].astype(str), variants["entity_id"].astype(str)))
            gems = set(queue["entity_id"].astype(str))
            hosts = hosts.assign(entity_id=hosts["surface"].astype(str).map(to_entity))
            hosts = hosts[hosts["entity_id"].isin(gems)]
            gem_counts = hosts.drop_duplicates(["district", "entity_id"])["district"].value_counts()

    rows = []
    for _, d in districts.iterrows():
        name = d["district"]
        part = reviews[reviews["district"] == name]
        places = sorted(part["place_name"].astype(str).unique())
        n = len(part)
        status = "no data" if n == 0 else ("thin" if n < THIN_REVIEWS or len(places) < 2 else "covered")
        rows.append({
            "district": name,
            "division": d["division"],
            "places": len(places),
            "reviews": n,
            "recent_reviews": int(part["recent"].sum()),
            "bangla_share": round(float(part["bangla"].mean()), 3) if n else None,
            "mentions": int(mention_counts.get(name, 0)),
            "gem_candidates": int(gem_counts.get(name, 0)),
            "status": status,
            "place_names": "|".join(places),
        })
    order = {"no data": 0, "thin": 1, "covered": 2}
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.assign(_o=out["status"].map(order)).sort_values(
        ["_o", "reviews", "division", "district"]).drop(columns="_o").reset_index(drop=True)


def by_division(table: pd.DataFrame) -> pd.DataFrame:
    return (table.groupby("division")
            .agg(districts=("district", "size"),
                 no_data=("status", lambda s: int((s == "no data").sum())),
                 thin=("status", lambda s: int((s == "thin").sum())),
                 covered=("status", lambda s: int((s == "covered").sum())),
                 reviews=("reviews", "sum"), places=("places", "sum"))
            .reset_index().sort_values(["no_data", "division"], ascending=[False, True]))


def write_report(table: pd.DataFrame, divisions: pd.DataFrame) -> None:
    counts = table["status"].value_counts().to_dict()
    total_reviews = int(table["reviews"].sum())
    top3 = table.sort_values("reviews", ascending=False).head(3)
    payload = {
        "n_districts": int(len(table)),
        "by_status": {k: int(v) for k, v in counts.items()},
        "thin_reviews": THIN_REVIEWS,
        "reviews_in_top_3_districts": int(top3["reviews"].sum()),
        "top_3_districts": top3["district"].tolist(),
        "total_reviews_placed": total_reviews,
        "top_3_share": round(int(top3["reviews"].sum()) / total_reviews, 3) if total_reviews else None,
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Where the data is thin",
        "",
        "Coverage of Bangladesh's 64 districts. The gem engine can only find gems where",
        "people have written reviews, so a district with no data is a blind spot, not an",
        "empty district.",
        "",
        f"- Districts with **no reviewed place: {counts.get('no data', 0)} of {len(table)}**",
        f"- Thin (under {THIN_REVIEWS} reviews or a single place): {counts.get('thin', 0)}",
        f"- Covered: {counts.get('covered', 0)}",
        f"- The three busiest districts ({', '.join(payload['top_3_districts'])}) hold "
        f"{payload['top_3_share']:.0%} of all reviews",
        "",
        "## By division",
        "",
        "| division | districts | no data | thin | covered | places | reviews |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [f"| {r['division']} | {r['districts']} | {r['no_data']} | {r['thin']} | {r['covered']} | "
              f"{r['places']} | {r['reviews']} |" for _, r in divisions.iterrows()]
    lines += [
        "",
        "## Every district",
        "",
        "| district | division | status | places | reviews | recent | Bangla share | mentions | gem candidates |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in table.iterrows():
        share = "—" if pd.isna(r["bangla_share"]) else f"{r['bangla_share']:.0%}"
        lines.append(f"| {r['district']} | {r['division']} | {r['status']} | {r['places']} | {r['reviews']} | "
                     f"{r['recent_reviews']} | {share} | {r['mentions']} | {r['gem_candidates']} |")
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for path in (IN_DISTRICTS, IN_CORPUS, IN_GEOGRAPHY):
        if not path.exists():
            print(f"error: {path.name} does not exist")
            return 1
    table = coverage(
        pd.read_csv(IN_DISTRICTS), pd.read_csv(IN_CORPUS, low_memory=False), pd.read_csv(IN_GEOGRAPHY),
        pd.read_csv(IN_MENTIONS) if IN_MENTIONS.exists() else None,
        pd.read_csv(IN_QUEUE) if IN_QUEUE.exists() else None,
        pd.read_csv(IN_VARIANTS) if IN_VARIANTS.exists() else None,
    )
    divisions = by_division(table)
    counts = table["status"].value_counts().to_dict()
    print(f"Coverage: {len(table)} districts  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    unknown = set(pd.read_csv(IN_GEOGRAPHY)["district"].dropna()) - set(table["district"])
    if unknown:
        print(f"  warning: place_geography.csv names district(s) not in {IN_DISTRICTS.name}: {sorted(unknown)}")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    table.to_csv(OUT_CSV, index=False, encoding="utf-8")
    write_report(table, divisions)
    print(f"  wrote {OUT_CSV.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
