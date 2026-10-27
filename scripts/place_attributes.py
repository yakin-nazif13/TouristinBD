"""Phase 4 — what each place offers: foods, activities, transport and tips.

The gem score ranks places only (gem_schema.GEM_TYPES). Everything else the
extractor finds describes a place rather than being one, so it is attached to the
place the review is about: a Saint Martin's review naming the green coconut
(ডাব) is evidence about Saint Martin's. This is what a place
card shows, and every row carries a real sentence from a real review, so a claim
on the card can be checked.

It also names **local specialities**: foods whose reviews come mostly from one
district (Mahasthangarh's kotkoti, the Bhimruli guava). A food mentioned
everywhere, like fuchka, is not a speciality of anywhere.

Every row says how fresh its evidence is: the first and last year it was
mentioned and how many reviews fall inside the recency window. The reviews go
back to 2011, and a 2017 "take the launch from X" can mislead a visitor today, so
the example sentence comes from a recent review whenever there is one, and a
card can mark transport or prices with no recent evidence as old.

Outputs:
    data/phase4_place_attributes.csv     one row per (place, entity)
    data/phase4_place_attributes_report.md

Run:
    .venv/bin/python scripts/place_attributes.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import ATTRIBUTE_TYPES, RECENCY_WINDOW_YEARS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"

OUT_CSV = DATA_DIR / "phase4_place_attributes.csv"
OUT_SPECIALITIES = DATA_DIR / "phase4_local_specialities.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_place_attributes_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_place_attributes_report.json"

COLUMNS = [
    "place_name", "district", "division", "entity_type", "entity_id", "name",
    "n_reviews", "n_mentions", "first_year", "last_year", "n_recent_reviews",
    "example_review_id", "example_sentence", "example_year",
]

# A speciality needs several independent reviews and most of them in one
# district. Fixed here, before looking at which foods pass.
SPECIALITY_MIN_REVIEWS = 3
SPECIALITY_MIN_SHARE = 0.6

# Example sentences: long enough to say something, short enough for a card.
EXAMPLE_TARGET_LENGTH = 120


def pick_example(rows: pd.DataFrame) -> pd.Series:
    """The row whose sentence is closest to the target length, recent ones first.

    Recent reviews are preferred so a card never quotes a 2017 price or route
    when a 2025 review says something about the same thing. Ties by review id.
    """
    candidates = rows[rows["sentence"].astype(str).str.len() >= 20]
    if candidates.empty:
        candidates = rows
    if "recent" in candidates and candidates["recent"].any():
        candidates = candidates[candidates["recent"]]
    order = candidates.assign(
        _distance=(candidates["sentence"].astype(str).str.len() - EXAMPLE_TARGET_LENGTH).abs(),
        _id=candidates["review_id"].astype(str),
    ).sort_values(["_distance", "_id"])
    return order.iloc[0]


def _year(value) -> int | None:
    return None if pd.isna(value) else int(value)


def build(mentions: pd.DataFrame, variants: pd.DataFrame, entities: pd.DataFrame,
          corpus: pd.DataFrame, geography: pd.DataFrame | None) -> pd.DataFrame:
    """One row per (host place, attribute entity)."""
    surface_to_entity = dict(zip(variants["surface"].astype(str), variants["entity_id"].astype(str)))
    name_of = dict(zip(entities["entity_id"].astype(str), entities["canonical_name"].astype(str)))
    place_of = dict(zip(corpus["review_id"].astype(str), corpus["place_name"].astype(str)))
    dates = pd.to_datetime(corpus.get("review_date"), errors="coerce", utc=True)
    date_of = dict(zip(corpus["review_id"].astype(str), dates))
    cutoff = dates.max() - pd.DateOffset(years=RECENCY_WINDOW_YEARS) if dates.notna().any() else None

    frame = mentions[mentions["entity_type"].astype(str).isin(ATTRIBUTE_TYPES)].copy()
    frame["review_id"] = frame["review_id"].astype(str)
    frame["entity_id"] = frame["surface"].astype(str).map(surface_to_entity)
    frame["place_name"] = frame["review_id"].map(place_of)
    frame = frame.dropna(subset=["entity_id", "place_name"])
    frame["date"] = pd.to_datetime(frame["review_id"].map(date_of), utc=True)
    frame["year"] = frame["date"].dt.year
    frame["recent"] = (frame["date"] >= cutoff) if cutoff is not None else False

    district_of, division_of = {}, {}
    if geography is not None:
        district_of = dict(zip(geography["place_name"].astype(str), geography["district"].astype(str)))
        division_of = dict(zip(geography["place_name"].astype(str), geography["division"].astype(str)))

    rows = []
    for (place, entity_id), group in frame.groupby(["place_name", "entity_id"], sort=True):
        example = pick_example(group)
        rows.append({
            "place_name": place,
            "district": district_of.get(place, ""),
            "division": division_of.get(place, ""),
            "entity_type": str(group["entity_type"].iloc[0]),
            "entity_id": entity_id,
            "name": name_of.get(entity_id, str(group["surface"].iloc[0])),
            "n_reviews": int(group["review_id"].nunique()),
            "n_mentions": int(len(group)),
            "first_year": _year(group["year"].min()),
            "last_year": _year(group["year"].max()),
            "n_recent_reviews": int(group.loc[group["recent"], "review_id"].nunique()),
            "example_review_id": str(example["review_id"]),
            "example_sentence": str(example["sentence"]),
            "example_year": _year(example["year"]),
        })
    out = pd.DataFrame(rows, columns=COLUMNS)
    for column in ("first_year", "last_year", "example_year"):
        out[column] = out[column].astype("Int64")
    return out.sort_values(["place_name", "entity_type", "n_reviews", "name"],
                           ascending=[True, True, False, True]).reset_index(drop=True)


def local_specialities(attributes: pd.DataFrame) -> pd.DataFrame:
    """Foods whose reviews come mostly from one district."""
    food = attributes[(attributes["entity_type"] == "FOOD") & (attributes["district"] != "")]
    rows = []
    for (entity_id, name), group in food.groupby(["entity_id", "name"]):
        total = int(group["n_reviews"].sum())
        if total < SPECIALITY_MIN_REVIEWS:
            continue
        by_district = group.groupby("district")["n_reviews"].sum().sort_values(ascending=False)
        top_district, top_reviews = by_district.index[0], int(by_district.iloc[0])
        share = top_reviews / total
        if share < SPECIALITY_MIN_SHARE:
            continue
        places = group[group["district"] == top_district].sort_values("n_reviews", ascending=False)
        rows.append({
            "entity_id": entity_id,
            "name": name,
            "district": top_district,
            "division": str(places["division"].iloc[0]),
            "reviews_in_district": top_reviews,
            "reviews_total": total,
            "share": round(share, 3),
            "places": "|".join(places["place_name"].astype(str)),
            "example_sentence": str(places["example_sentence"].iloc[0]),
        })
    columns = ["entity_id", "name", "district", "division", "reviews_in_district",
               "reviews_total", "share", "places", "example_sentence"]
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["reviews_in_district", "name"], ascending=[False, True]).reset_index(drop=True)


def write_report(attributes: pd.DataFrame, specialities: pd.DataFrame) -> None:
    national = (attributes.groupby(["entity_type", "name"])
                .agg(reviews=("n_reviews", "sum"), places=("place_name", "nunique"))
                .reset_index())
    payload = {
        "n_rows": int(len(attributes)),
        "n_places": int(attributes["place_name"].nunique()) if not attributes.empty else 0,
        "by_type": {k: int(v) for k, v in attributes.groupby("entity_type")["n_reviews"].sum().items()},
        "speciality_rule": {"min_reviews": SPECIALITY_MIN_REVIEWS, "min_share_in_one_district": SPECIALITY_MIN_SHARE},
        "n_local_specialities": int(len(specialities)),
        "recency_window_years": RECENCY_WINDOW_YEARS,
        "rows_without_recent_evidence": {
            k: int(v) for k, v in
            attributes[attributes["n_recent_reviews"] == 0].groupby("entity_type").size().items()
        },
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 4 — What each place offers",
        "",
        "Foods, activities, transport and tips found in reviews, attached to the place",
        "each review is about. Places alone are ranked as gems; these describe them.",
        "Every row in `phase4_place_attributes.csv` carries a sentence from a real review.",
        "",
        f"- Place / attribute pairs: **{payload['n_rows']}** across **{payload['n_places']}** places",
        f"- With no review in the last {RECENCY_WINDOW_YEARS} years (shown as old on a card): "
        + (", ".join(f"{k} {v}" for k, v in payload["rows_without_recent_evidence"].items()) or "none"),
        "",
    ]
    for entity_type in ["FOOD", "ACTIVITY", "ACCESS"]:
        top = national[national["entity_type"] == entity_type].sort_values(
            ["reviews", "name"], ascending=[False, True]).head(15)
        if top.empty:
            continue
        lines += [f"## {entity_type.title()} — most reviewed", "",
                  "| name | reviews | places |", "| --- | --- | --- |"]
        lines += [f"| {r['name']} | {r['reviews']} | {r['places']} |" for _, r in top.iterrows()]
        lines.append("")
    lines += [
        "## Local specialities",
        "",
        f"Foods with at least {SPECIALITY_MIN_REVIEWS} reviews, at least "
        f"{SPECIALITY_MIN_SHARE:.0%} of them from one district. Fixed before looking at",
        "which foods pass. A food reviewed everywhere is not anywhere's speciality.",
        "",
    ]
    if specialities.empty:
        lines += ["None pass the rule on this corpus.", ""]
    else:
        lines += ["| food | district | reviews there / total | where | from a review |",
                  "| --- | --- | --- | --- | --- |"]
        for _, r in specialities.iterrows():
            quote = r["example_sentence"].replace("|", "/")
            if len(quote) > 140:
                quote = quote[:137] + "..."
            lines.append(f"| {r['name']} | {r['district']} | {r['reviews_in_district']} / "
                         f"{r['reviews_total']} | {r['places'].replace('|', ', ')} | {quote} |")
        lines.append("")
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for path in (IN_MENTIONS, IN_VARIANTS, IN_ENTITIES, IN_CORPUS):
        if not path.exists():
            print(f"error: {path.name} does not exist; run the earlier Phase 4 steps first")
            return 1
    mentions = pd.read_csv(IN_MENTIONS)
    variants = pd.read_csv(IN_VARIANTS)
    entities = pd.read_csv(IN_ENTITIES)
    corpus = pd.read_csv(IN_CORPUS, low_memory=False)
    geography = pd.read_csv(IN_GEOGRAPHY) if IN_GEOGRAPHY.exists() else None

    attributes = build(mentions, variants, entities, corpus, geography)
    specialities = local_specialities(attributes)
    print(f"Phase 4 — place attributes: {len(attributes)} place/attribute pair(s), "
          f"{len(specialities)} local speciality(ies)")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    attributes.to_csv(OUT_CSV, index=False, encoding="utf-8")
    specialities.to_csv(OUT_SPECIALITIES, index=False, encoding="utf-8")
    write_report(attributes, specialities)
    print(f"  wrote {OUT_CSV.name}, {OUT_SPECIALITIES.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
