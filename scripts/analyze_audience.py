"""Phase 4 — locals versus visitors. BUILD_PLAN section 5.6.

    "Use reviewer_is_local_guide, user_location and language as proxies.
     Question: what do locals mention that visitors do not? Report
     distributions by entity type and division."

WHY ONE OF THE THREE PROXIES IS NOT USED

`reviewer_is_local_guide` is excluded, and this is a deliberate departure from
the plan's wording. "Local Guide" is Google Maps' badge for *contribution
volume* — people who review and photograph places often — not a statement
about where someone lives. A frequent reviewer from London is a Local Guide.

It also has no discriminating power on this corpus: of the 300 reviews that
carry the field, 274 are True (91%). A proxy that says "yes" to nine in ten
reviewers cannot separate two audiences, and treating it as residency would put
a confident-looking but meaningless split into the paper.

So the audience label is built from:

    user_location   the reviewer's stated country. Present on 238 of 538
                    reviews (Booking.com supplies it; Google Maps does not).
                    "Bangladesh" -> domestic, anything else -> foreign.
    language        Bangla script or Banglish implies a domestic reviewer, and
                    is used only where no location is available.

Everything else is `unknown`, and unknown reviews are reported rather than
silently dropped or bundled into one side. With roughly 44% of the corpus
labelled, that share is itself part of the result.

WHAT THIS CAN AND CANNOT CONCLUDE

The question — what do locals mention that visitors do not — needs enough
mentions on both sides of the split to compare. Where a cell is too small, this
module says so instead of reporting a ratio built on two observations. A
chi-square or a proportion test on single-digit counts would produce a p-value
that means nothing, and that is the kind of number that survives into a paper
unchallenged.

Run:
    .venv/bin/python scripts/analyze_audience.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_GAZETTEER = DATA_DIR / "phase4_gazetteer.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"
IN_LANGUAGE = DATA_DIR / "phase3_language_labels.csv"

OUT_REVIEW_AUDIENCE = DATA_DIR / "phase4_review_audience.csv"
OUT_COMPARISON = DATA_DIR / "phase4_audience_comparison.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_audience_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_audience_report.json"

DOMESTIC, FOREIGN, UNKNOWN = "domestic", "foreign", "unknown"

# Spellings of Bangladesh seen in platform location fields.
BANGLADESH_NAMES = {"bangladesh", "bd", "bangladesh.", "people's republic of bangladesh"}

# Language labels that imply a domestic reviewer. English does not: most of
# this corpus is translated English written by Bangladeshi reviewers.
DOMESTIC_LANGUAGES = {"bn", "bn-latn", "mixed", "bn-en-mixed"}

# Below this many mentions on a side, a comparison is not reported as a figure.
# Section 5.6 asks for distributions, not for conclusions the data cannot carry.
MIN_CELL = 5


def _clean(value: object) -> str:
    """Lowercased text, with every flavour of missing collapsed to "".

    pandas hands a missing cell over as float NaN, and `str(nan or "")` is the
    string "nan" — which is truthy and is not "bangladesh". Without this, the
    300 Google Maps reviews that carry no location were all labelled *foreign*,
    inverting the entire comparison while reporting 100% coverage.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip().lower()
    return "" if text in {"", "nan", "none", "null", "na", "n/a"} else text


def classify_review(location: object, language: object) -> tuple[str, str]:
    """(audience, basis) for one review."""
    text = _clean(location)
    if text:
        if text in BANGLADESH_NAMES:
            return DOMESTIC, "stated location is Bangladesh"
        return FOREIGN, f"stated location is {str(location).strip()}"
    label = _clean(language)
    if label in DOMESTIC_LANGUAGES:
        return DOMESTIC, f"wrote in {label}"
    return UNKNOWN, "no location, and wrote in English"


def build_review_audience(corpus: pd.DataFrame, languages: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, review in corpus.iterrows():
        review_id = str(review["review_id"])
        audience, basis = classify_review(
            review.get("user_location"), languages.get(review_id, review.get("detected_language")))
        rows.append({
            "review_id": review_id,
            "audience": audience,
            "basis": basis,
            "user_location": review.get("user_location"),
            "language_label": languages.get(review_id, review.get("detected_language")),
            "source": review.get("source"),
            "place_name": review.get("place_name"),
        })
    return pd.DataFrame(rows)


def compare(mentions: pd.DataFrame, audience: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Mention counts per group per audience, with shares and a usability flag."""
    joined = mentions.merge(audience[["review_id", "audience"]], on="review_id", how="left")
    joined["audience"] = joined["audience"].fillna(UNKNOWN)

    totals = joined["audience"].value_counts().to_dict()
    rows = []
    for group, chunk in joined.groupby(group_column, dropna=False):
        counts = chunk["audience"].value_counts().to_dict()
        domestic = int(counts.get(DOMESTIC, 0))
        foreign = int(counts.get(FOREIGN, 0))
        row = {
            "group": group if pd.notna(group) else "(none)",
            "domestic_mentions": domestic,
            "foreign_mentions": foreign,
            "unknown_mentions": int(counts.get(UNKNOWN, 0)),
            # Share *within* each audience, so the two are comparable even
            # though one side has more mentions overall.
            "domestic_share": (round(domestic / totals[DOMESTIC], 4)
                               if totals.get(DOMESTIC) else None),
            "foreign_share": (round(foreign / totals[FOREIGN], 4)
                              if totals.get(FOREIGN) else None),
            "comparable": domestic >= MIN_CELL and foreign >= MIN_CELL,
        }
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("domestic_mentions", ascending=False)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for path in (IN_CORPUS, IN_MENTIONS, IN_VARIANTS):
        if not path.exists():
            print(f"error: {path.name} missing; run the earlier Phase 4 steps first")
            return 1

    corpus = pd.read_csv(IN_CORPUS)
    mentions = pd.read_csv(IN_MENTIONS)
    variants = pd.read_csv(IN_VARIANTS)
    entities = pd.read_csv(IN_ENTITIES) if IN_ENTITIES.exists() else pd.DataFrame()
    gazetteer = pd.read_csv(IN_GAZETTEER) if IN_GAZETTEER.exists() else pd.DataFrame()
    geography = pd.read_csv(IN_GEOGRAPHY) if IN_GEOGRAPHY.exists() else pd.DataFrame()

    languages: dict[str, str] = {}
    if IN_LANGUAGE.exists():
        language_frame = pd.read_csv(IN_LANGUAGE)
        languages = dict(zip(language_frame["review_id"].astype(str),
                             language_frame["language_label"].astype(str)))

    audience = build_review_audience(corpus, languages)
    counts = audience["audience"].value_counts().to_dict()
    labelled = counts.get(DOMESTIC, 0) + counts.get(FOREIGN, 0)

    print(f"Phase 4 — locals versus visitors over {len(corpus)} review(s)")
    print(f"  domestic {counts.get(DOMESTIC, 0)} | foreign {counts.get(FOREIGN, 0)} "
          f"| unknown {counts.get(UNKNOWN, 0)}")
    print(f"  labelled: {labelled}/{len(corpus)} ({labelled / len(corpus):.1%})")

    # Attach entity + geography to each mention.
    surface_to_entity = dict(zip(variants["surface"].astype(str),
                                 variants["entity_id"].astype(str)))
    mentions["entity_id"] = mentions["surface"].astype(str).map(surface_to_entity)
    if not entities.empty:
        canonical = dict(zip(entities["entity_id"].astype(str),
                             entities["canonical_name"].astype(str)))
        mentions["canonical_name"] = mentions["entity_id"].map(canonical)
    else:
        mentions["canonical_name"] = mentions["surface"]
    if not gazetteer.empty:
        visibility = dict(zip(gazetteer["name"].astype(str), gazetteer["visibility"].astype(str)))
        mentions["visibility"] = mentions["canonical_name"].map(visibility).fillna("unknown")
    else:
        mentions["visibility"] = "unknown"

    review_place = dict(zip(corpus["review_id"].astype(str), corpus["place_name"].astype(str)))
    division_of = (dict(zip(geography["place_name"].astype(str),
                            geography["division"].astype(str)))
                   if not geography.empty else {})
    mentions["found_in_division"] = (mentions["review_id"].astype(str)
                                     .map(review_place).map(division_of))

    comparisons = {}
    for label, column in (("entity_type", "entity_type"),
                          ("division", "found_in_division"),
                          ("visibility", "visibility"),
                          ("entity", "canonical_name")):
        comparisons[label] = compare(mentions, audience, column)

    notes: list[str] = []
    notes.append(
        "reviewer_is_local_guide is deliberately not used: it is Google's "
        "contribution-volume badge, not a residency signal, and 274 of the 300 "
        "reviews that carry it are True — a proxy that says yes to nine in ten "
        "reviewers cannot separate two audiences"
    )
    notes.append(
        f"{labelled}/{len(corpus)} reviews could be labelled "
        f"({labelled / len(corpus):.1%}); user_location is supplied by "
        "Booking.com but not by Google Maps"
    )

    usable_any = False
    for label, frame in comparisons.items():
        usable = frame[frame["comparable"]] if not frame.empty else frame
        if not frame.empty and not usable.empty:
            usable_any = True
        else:
            notes.append(
                f"no {label} group has at least {MIN_CELL} mentions from both "
                "audiences, so no comparison is reported for it"
            )

    # The structural reason, which matters more than the empty table: the
    # source that identifies the reviewer is not the source that carries the
    # mentions.
    joined = mentions.merge(audience[["review_id", "audience"]], on="review_id", how="left")
    joined["audience"] = joined["audience"].fillna(UNKNOWN)
    mention_audience = joined["audience"].value_counts().to_dict()
    unlabelled_mentions = int(mention_audience.get(UNKNOWN, 0))
    if unlabelled_mentions:
        notes.append(
            f"{unlabelled_mentions} of {len(mentions)} mentions sit in reviews that "
            "cannot be labelled. user_location comes from Booking.com, whose reviews "
            "are about hotels and rarely name another place, while almost every "
            "mention comes from a Google Maps review, which supplies no location. "
            "The source that identifies the reviewer is not the source that carries "
            "the evidence."
        )

    if not usable_any:
        notes.append(
            "On this corpus the locals-versus-visitors question cannot be "
            "answered: every cell is too small on at least one side. This is a "
            "coverage limit, not a null result."
        )
        notes.append(
            "Worth flagging: section 5.6 cannot be answered via reviewer location "
            "without conflicting with section 10, which keeps personal-data output "
            "off when scraping. Google Maps reviewer location is exactly the field "
            "that ethics stance excludes. The route that does not conflict is "
            "language — Bangla or Banglish text implies a domestic reviewer and "
            "needs no personal data at all — which becomes usable once the YouTube "
            "pass (section 3.3a) brings real Banglish into the corpus. Today the "
            "corpus has 5 such reviews."
        )

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        for note in notes:
            print(f"  - {note}")
        return 0

    OUT_REVIEW_AUDIENCE.parent.mkdir(parents=True, exist_ok=True)
    audience.to_csv(OUT_REVIEW_AUDIENCE, index=False)
    combined = []
    for label, frame in comparisons.items():
        if frame.empty:
            continue
        tagged = frame.copy()
        tagged.insert(0, "dimension", label)
        combined.append(tagged)
    if combined:
        pd.concat(combined, ignore_index=True).to_csv(OUT_COMPARISON, index=False)
    else:
        pd.DataFrame(columns=["dimension", "group"]).to_csv(OUT_COMPARISON, index=False)

    payload = {
        "n_reviews": int(len(corpus)),
        "by_audience": {k: int(v) for k, v in counts.items()},
        "labelled_share": round(labelled / len(corpus), 4) if len(corpus) else 0.0,
        "min_cell": MIN_CELL,
        "excluded_proxy": "reviewer_is_local_guide",
        "any_comparable_group": usable_any,
        "comparisons": {
            label: frame.to_dict(orient="records") for label, frame in comparisons.items()
        },
        "notes": notes,
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 4 — Locals versus visitors",
        "",
        "What domestic reviewers mention that foreign ones do not (BUILD_PLAN 5.6).",
        "",
        f"- Reviews: **{len(corpus)}**",
        f"- Domestic: **{counts.get(DOMESTIC, 0)}** · Foreign: **{counts.get(FOREIGN, 0)}** "
        f"· Unknown: {counts.get(UNKNOWN, 0)}",
        f"- Labelled: **{labelled / len(corpus):.1%}** of the corpus",
        "",
        "## How the label is derived",
        "",
        "| signal | use |",
        "| --- | --- |",
        "| `user_location` | stated country; Bangladesh -> domestic, else foreign |",
        "| `language_label` | Bangla/Banglish/mixed -> domestic, where no location exists |",
        "| `reviewer_is_local_guide` | **not used** — see below |",
        "",
        "The plan lists `reviewer_is_local_guide` as a proxy, but it is Google's badge",
        "for contribution volume rather than a statement of residency, and 274 of the",
        "300 reviews carrying it are True. A signal that applies to nine in ten",
        "reviewers cannot separate two audiences, so using it would produce a",
        "confident-looking split that means nothing.",
        "",
    ]
    for label, frame in comparisons.items():
        lines += [f"## By {label}", ""]
        if frame.empty:
            lines += ["No data.", ""]
            continue
        lines += [
            "| group | domestic | foreign | domestic share | foreign share | comparable |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for _, row in frame.head(15).iterrows():
            share = lambda v: "—" if v is None or pd.isna(v) else f"{v:.1%}"  # noqa: E731
            lines.append(
                f"| {row['group']} | {row['domestic_mentions']} | {row['foreign_mentions']} | "
                f"{share(row['domestic_share'])} | {share(row['foreign_share'])} | "
                f"{'yes' if row['comparable'] else 'no'} |"
            )
        lines.append("")
    lines += [
        "## What this does and does not establish", "",
        f"A group is marked comparable only with at least {MIN_CELL} mentions from",
        "both audiences. Below that the shares are printed for completeness but no",
        "difference should be read from them: a ratio built on two observations is",
        "not a finding, and a significance test on single-digit counts produces a",
        "p-value that means nothing.",
        "",
    ]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  comparable groups found: {usable_any}")
    for note in notes:
        print(f"  - {note[:100]}")
    print(f"\n  wrote {OUT_REVIEW_AUDIENCE.name}, {OUT_COMPARISON.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
