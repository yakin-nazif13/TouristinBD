"""Which places are talked about together.

The whole hidden-gem idea rests on one observation: visitors to a famous place
mention the lesser-known places around it. Gangamati is found in reviews of
Kuakata; Fatrar Chor too. This makes those links a table that can be read,
ranked and drawn on the map, instead of a property of individual gems.

Two kinds of link, both counted in distinct reviews:

  found_in   a place mentioned inside a review OF another place
             (Gangamati, in a Kuakata Sea Beach review)
  together   two places named in the same review
             (Gangamati and Fatrar Chor, both in one Kuakata review)

A link needs at least MIN_REVIEWS independent reviews, the same bar the gem
score uses for a candidate: one review naming two places is one person's
itinerary, not a pattern. Every link carries a sentence from a real review.

Outputs:
    data/phase4_place_connections.csv
    data/phase4_place_connections_report.md / .json

Run:
    .venv/bin/python scripts/place_connections.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import MIN_INDEPENDENT_MENTIONS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEMS = DATA_DIR / "phase4_gem_scores.csv"

OUT_CSV = DATA_DIR / "phase4_place_connections.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_place_connections_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_place_connections_report.json"

MIN_REVIEWS = MIN_INDEPENDENT_MENTIONS

COLUMNS = ["place_a", "place_b", "n_reviews", "n_found_in", "n_together",
           "example_review_id", "example_sentence"]


def place_mentions(mentions: pd.DataFrame, variants: pd.DataFrame, entities: pd.DataFrame,
                   corpus: pd.DataFrame) -> pd.DataFrame:
    """PLACE mentions with the canonical name of what was mentioned and of the
    place the review is about."""
    to_entity = dict(zip(variants["surface"].astype(str), variants["entity_id"].astype(str)))
    names = dict(zip(entities["entity_id"].astype(str), entities["canonical_name"].astype(str)))
    host = dict(zip(corpus["review_id"].astype(str), corpus["place_name"].astype(str)))
    frame = mentions[mentions["entity_type"].astype(str) == "PLACE"].copy()
    frame["review_id"] = frame["review_id"].astype(str)
    frame["mentioned"] = frame["surface"].astype(str).map(to_entity).map(names)
    frame["host"] = frame["review_id"].map(host)
    return frame.dropna(subset=["mentioned", "host"])


def connections(frame: pd.DataFrame, min_reviews: int = MIN_REVIEWS) -> pd.DataFrame:
    """One row per pair of places linked by at least `min_reviews` reviews."""
    found_in: dict[tuple[str, str], set[str]] = defaultdict(set)
    together: dict[tuple[str, str], set[str]] = defaultdict(set)
    example: dict[tuple[str, str], tuple[str, str]] = {}

    def pair(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a.casefold() <= b.casefold() else (b, a)

    for review_id, group in frame.groupby("review_id", sort=True):
        host = str(group["host"].iloc[0])
        sentences = dict(zip(group["mentioned"], group["sentence"].astype(str)))
        mentioned = sorted(set(group["mentioned"]))
        for name in mentioned:
            if name.casefold() == host.casefold():
                continue
            key = pair(host, name)
            found_in[key].add(review_id)
            example.setdefault(key, (review_id, sentences[name]))
        for a, b in combinations(mentioned, 2):
            if a.casefold() == b.casefold():
                continue
            key = pair(a, b)
            together[key].add(review_id)
            example.setdefault(key, (review_id, sentences[a]))

    rows = []
    for key in set(found_in) | set(together):
        reviews = found_in.get(key, set()) | together.get(key, set())
        if len(reviews) < min_reviews:
            continue
        review_id, sentence = example[key]
        rows.append({
            "place_a": key[0], "place_b": key[1], "n_reviews": len(reviews),
            "n_found_in": len(found_in.get(key, set())), "n_together": len(together.get(key, set())),
            "example_review_id": review_id, "example_sentence": " ".join(sentence.split()),
        })
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values(["n_reviews", "place_a", "place_b"], ascending=[False, True, True]).reset_index(drop=True)


def hubs(links: pd.DataFrame) -> pd.DataFrame:
    """Places by how many other places they are linked to."""
    ends = pd.concat([links[["place_a", "n_reviews"]].rename(columns={"place_a": "place"}),
                      links[["place_b", "n_reviews"]].rename(columns={"place_b": "place"})])
    return (ends.groupby("place").agg(links=("n_reviews", "size"), reviews=("n_reviews", "sum"))
            .reset_index().sort_values(["links", "reviews", "place"], ascending=[False, False, True]))


def links_to_lesser_known(links: pd.DataFrame, gems: pd.DataFrame | None) -> pd.DataFrame:
    """Links where one end is a gem candidate that is not already well known.

    These are the ones the project is about: the path from a place everyone
    visits to one few people write about.
    """
    if gems is None or gems.empty:
        return links.iloc[0:0].assign(gem="", visibility="")
    lesser = gems[gems["visibility"].isin(["V0", "V1", "V2"])]
    level = dict(zip(lesser["canonical_name"].astype(str), lesser["visibility"].astype(str)))
    rows = []
    for _, r in links.iterrows():
        for end in (r["place_a"], r["place_b"]):
            if end in level:
                rows.append({**r.to_dict(), "gem": end, "visibility": level[end]})
                break
    return pd.DataFrame(rows, columns=[*links.columns, "gem", "visibility"])


def write_report(links: pd.DataFrame, hub_table: pd.DataFrame, lesser: pd.DataFrame) -> None:
    payload = {
        "n_links": int(len(links)),
        "n_places": int(len(hub_table)),
        "min_reviews": MIN_REVIEWS,
        "n_found_in_links": int((links["n_found_in"] > 0).sum()),
        "n_together_links": int((links["n_together"] > 0).sum()),
        "n_links_to_lesser_known": int(len(lesser)),
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Which places are talked about together",
        "",
        "Links between places, counted in distinct reviews: a place mentioned inside a review",
        "of another (`found in`), or two places named in the same review (`together`).",
        f"A link needs at least {MIN_REVIEWS} reviews. Every one carries a real sentence.",
        "",
        f"- Links: **{payload['n_links']}** between **{payload['n_places']}** places",
        "",
        "## Strongest links",
        "",
        "| place | place | reviews | found in | together | from a review |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in links.head(30).iterrows():
        quote = r["example_sentence"].replace("|", "/")
        quote = quote if len(quote) <= 110 else quote[:107] + "..."
        lines.append(f"| {r['place_a']} | {r['place_b']} | {r['n_reviews']} | {r['n_found_in']} | "
                     f"{r['n_together']} | {quote} |")
    lines += [
        "",
        "## Links that lead to lesser-known places",
        "",
        "One end is a gem candidate at V0-V2: the path from a place people visit to one few",
        "write about. This is the pattern the gem engine is built on, made visible.",
        "",
        "| lesser-known place | level | linked with | reviews | from a review |",
        "| --- | --- | --- | --- | --- |",
    ]
    for _, r in lesser.head(25).iterrows():
        other = r["place_b"] if r["gem"] == r["place_a"] else r["place_a"]
        quote = r["example_sentence"].replace("|", "/")
        quote = quote if len(quote) <= 110 else quote[:107] + "..."
        lines.append(f"| {r['gem']} | {r['visibility']} | {other} | {r['n_reviews']} | {quote} |")
    lines += [
        "",
        "## Hubs — places whose reviews lead to the most other places",
        "",
        "| place | linked places | reviews |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {r['place']} | {r['links']} | {r['reviews']} |" for _, r in hub_table.head(15).iterrows()]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for path in (IN_MENTIONS, IN_VARIANTS, IN_ENTITIES, IN_CORPUS):
        if not path.exists():
            print(f"error: {path.name} does not exist; run the earlier Phase 4 steps first")
            return 1
    frame = place_mentions(pd.read_csv(IN_MENTIONS), pd.read_csv(IN_VARIANTS),
                           pd.read_csv(IN_ENTITIES), pd.read_csv(IN_CORPUS, low_memory=False))
    links = connections(frame)
    hub_table = hubs(links)
    lesser = links_to_lesser_known(links, pd.read_csv(IN_GEMS) if IN_GEMS.exists() else None)
    print(f"Place connections: {len(links)} link(s) between {len(hub_table)} place(s)")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    links.to_csv(OUT_CSV, index=False, encoding="utf-8")
    write_report(links, hub_table, lesser)
    print(f"  wrote {OUT_CSV.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
