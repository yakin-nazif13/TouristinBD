"""Phase 4 — entity resolution. BUILD_PLAN section 5.3.

    "Cluster mentions that are the same real thing, using:
       * normalised string similarity (rapidfuzz) on original and
         back-transliterated forms
       * embedding similarity of the mention plus its sentence
       * geographic context (co-mentioned anchor, district)
     Evaluate on a hand-made set of variant groups (Guliakhali / Guliyakhali /
     Gulyakhali, Chor Bijoy / Char Bijoy, local vs official names). Report
     cluster purity and B-cubed F1."

Why this phase exists: the gazetteer run found `Kaptai` and `kaptai` as
separate surfaces, `Saint Martin` separately from `Saint Martin's Island`, and
`Srimangal` separately from `Sreemangal`. Counted as different places they
split one place's evidence several ways, and section 5.5 requires 2-3
*independent* mentions before anything becomes a candidate — so unresolved
variants suppress exactly the gems the project is looking for.

Three signals, combined as a weighted score with the weights fixed here and
reported, in the same spirit as section 5.5's gem score:

    phonetic    the section 4.2 consonant key — an exact key match is strong
                evidence, and it is the only signal that crosses scripts
                (কুয়াকাটা and Kuakata share a key)
    string      rapidfuzz token-set ratio on the normalised surfaces
    geography   whether the mentions appear in reviews of the same district or
                division; co-location raises confidence, distance lowers it

Embedding similarity is the fourth signal section 5.3 names, and it is
*optional* here: it needs torch, which cannot load on every contributor's
machine. Resolution runs without it and records which signals were available,
so a run is never silently weaker than it looks.

Clustering is single-link over pairs above the threshold (union-find). Single
link is the right choice for spelling variants: A-B and B-C both being variants
of one name makes A-C one too, even when A and C look least alike
(Gulyakhali / Guliyakhali / Guliakhali is exactly that chain).

Run:
    .venv/bin/python scripts/resolve_entities.py
    .venv/bin/python scripts/resolve_entities.py --evaluate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import strip_qualifier  # noqa: E402
from language_id import phonetic_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"
IN_GOLD = DATA_DIR / "entity_resolution_gold.csv"
OUT_ENTITIES = DATA_DIR / "phase4_entities.csv"
OUT_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_resolution_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_resolution_report.json"

# Fixed in advance and reported, like section 5.5's gem-score weights.
WEIGHTS = {"phonetic": 0.40, "string": 0.25, "containment": 0.20, "geography": 0.15}
MERGE_THRESHOLD = 0.72

# Category words an official name appends to a local one: "Kuakata" becomes
# "Kuakata Beach", "Ratargul" becomes "Ratargul Swamp Forest". This is the
# "local vs official names" case section 5.3 lists, and it is the one the
# phonetic key cannot catch, because the suffix changes the consonant
# skeleton. Only these words count — if the extra tokens are anything else,
# the two names are two places.
CATEGORY_WORDS = {
    "beach", "sea", "lake", "river", "island", "forest", "swamp", "hill",
    "hills", "point", "zero", "garden", "gardens", "tea", "museum", "fort",
    "palace", "temple", "mosque", "park", "national", "centre", "center",
    "wildlife", "reserved", "tourist", "complex", "bari", "ghat", "bazar",
    "station", "resort", "hotel", "inn", "suites",
}

# Below this, rapidfuzz agreement is noise on short Bangladeshi place names
# ("Mongla" vs "Mangal" scores surprisingly well).
MIN_STRING_RATIO = 70.0


def _fuzz_ratio(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    # token_set_ratio so "Saint Martin" and "Saint Martin's Island" agree on
    # their shared tokens rather than being penalised for length.
    return float(max(fuzz.token_set_ratio(a, b), fuzz.ratio(a, b)))


def _is_bengali(text: str) -> bool:
    """True when the name is written in Bengali script."""
    from language_id import script_shares

    bengali, latin = script_shares(text)
    return bengali > latin


def _is_official_form(a: str, b: str) -> bool:
    """True when one name is the other plus only category words.

    "kuakata" / "kuakata beach" -> True.
    "kuakata" / "kuakata bazar road" -> False, because "road" is not a
    category word in the list and so the pair is not an official/local pair.
    "jaflong" / "jaflong zero point" -> True.
    """
    tokens_a = {t for t in a.split() if t}
    tokens_b = {t for t in b.split() if t}
    if not tokens_a or not tokens_b or tokens_a == tokens_b:
        return False
    shorter, longer = (tokens_a, tokens_b) if len(tokens_a) < len(tokens_b) else (tokens_b, tokens_a)
    if not shorter < longer:
        return False
    return (longer - shorter) <= CATEGORY_WORDS


def pair_score(
    a: dict, b: dict, embeddings: dict[str, object] | None = None
) -> tuple[float, dict[str, float]]:
    """Similarity of two mention groups, with each signal's contribution."""
    signals: dict[str, float] = {}

    # Token-level rather than all-or-nothing. An official name appends a
    # category word, which changes the whole consonant skeleton
    # ("kkt" -> "kkt bc"), so exact key equality scores zero on precisely the
    # local-vs-official pairs section 5.3 asks to resolve. Comparing token sets
    # gives the shared name its credit while still requiring full containment.
    tokens_a = {t for t in str(a["phonetic"]).split() if t}
    tokens_b = {t for t in str(b["phonetic"]).split() if t}
    if tokens_a and tokens_a == tokens_b:
        signals["phonetic"] = 1.0
    elif tokens_a and tokens_b and (tokens_a < tokens_b or tokens_b < tokens_a):
        signals["phonetic"] = 0.75
    else:
        signals["phonetic"] = 0.0

    # Across scripts, string similarity and the category-word rule cannot say
    # anything: "Kuakata" and "কুয়াকাটা" share no characters and no tokens. They
    # are marked not-applicable rather than scored 0, because a signal that
    # cannot apply must not count as evidence against a merge — otherwise the
    # phonetic key, the one signal built to cross scripts, can never carry a
    # pair on its own, and every Bangla mention stays orphaned from its
    # English name.
    cross_script = _is_bengali(a["normalized"]) != _is_bengali(b["normalized"])
    if cross_script:
        signals["string"] = None
        signals["containment"] = None
    else:
        ratio = _fuzz_ratio(a["normalized"], b["normalized"])
        signals["string"] = ratio / 100.0 if ratio >= MIN_STRING_RATIO else 0.0
        signals["containment"] = 1.0 if _is_official_form(a["normalized"], b["normalized"]) else 0.0

    # Geography: same district is strong, same division weaker, different
    # division is evidence *against* a merge rather than neutral — two
    # similarly-spelled places in different divisions are usually two places.
    districts_a, districts_b = a["districts"], b["districts"]
    divisions_a, divisions_b = a["divisions"], b["divisions"]
    if districts_a & districts_b:
        signals["geography"] = 1.0
    elif divisions_a & divisions_b:
        signals["geography"] = 0.6
    elif districts_a and districts_b:
        signals["geography"] = -0.5
    else:
        signals["geography"] = 0.0

    # Weighted average over the signals that apply, so the threshold means the
    # same thing whether or not every signal could be computed.
    applicable = {k: v for k, v in signals.items() if v is not None}
    total_weight = sum(WEIGHTS[name] for name in applicable)
    score = (
        sum(WEIGHTS[name] * value for name, value in applicable.items()) / total_weight
        if total_weight else 0.0
    )

    if embeddings:
        vector_a, vector_b = embeddings.get(a["surface"]), embeddings.get(b["surface"])
        if vector_a is not None and vector_b is not None:
            import numpy as np

            cosine = float(np.dot(vector_a, vector_b))
            signals["embedding"] = cosine
            # Averaged in rather than added, so adding the signal cannot push
            # every pair over the threshold and silently change the clustering.
            score = (score + cosine) / 2.0

    return score, signals


class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a

    def groups(self) -> dict:
        out = defaultdict(list)
        for item in self.parent:
            out[self.find(item)].append(item)
        return dict(out)


def build_surface_groups(mentions: pd.DataFrame, geography: pd.DataFrame | None,
                         corpus: pd.DataFrame | None) -> dict[str, dict]:
    """One record per distinct surface form, with its geographic footprint."""
    district_of: dict[str, str] = {}
    division_of: dict[str, str] = {}
    if geography is not None:
        for _, row in geography.iterrows():
            name = str(row.get("place_name") or "")
            district_of[name] = str(row.get("district") or "")
            division_of[name] = str(row.get("division") or "")

    review_place: dict[str, str] = {}
    if corpus is not None:
        review_place = dict(zip(corpus["review_id"].astype(str),
                                corpus["place_name"].astype(str)))

    groups: dict[str, dict] = {}
    for _, row in mentions.iterrows():
        surface = str(row["surface"])
        record = groups.setdefault(surface, {
            "surface": surface,
            "entity_type": str(row["entity_type"]),
            "normalized": strip_qualifier(surface).lower(),
            "phonetic": str(row.get("phonetic_key") or phonetic_key(surface)),
            "mentions": 0,
            "review_ids": set(),
            "districts": set(),
            "divisions": set(),
            "languages": set(),
            "from_text": False,
        })
        record["mentions"] += 1
        record["from_text"] = True
        review_id = str(row["review_id"])
        record["review_ids"].add(review_id)
        if row.get("language"):
            record["languages"].add(str(row["language"]))
        # The mention's geography is that of the review it came from: the
        # anchor place whose page it was found on (section 3.2).
        place = review_place.get(review_id, "")
        if place:
            if district_of.get(place):
                record["districts"].add(district_of[place])
            if division_of.get(place):
                record["divisions"].add(division_of[place])

    # The corpus's own place names are added as surfaces carrying no mentions.
    #
    # They have to be here or resolution cannot do the job section 5.3 names
    # last: "local vs official names". Extraction deliberately skips a review's
    # own place, so "Kuakata Beach" never appears as a mention while "Kuakata"
    # appears 32 times — and without the official form in the pool there is
    # nothing for the short form to resolve against.
    #
    # mentions stays 0 for these: a place having reviews is not the same as its
    # name being mentioned in someone's text, and conflating the two would
    # inflate the evidence counts section 5.5 scores on.
    for place, district in district_of.items():
        if not place:
            continue
        record = groups.setdefault(place, {
            "surface": place,
            "entity_type": "PLACE",
            "normalized": strip_qualifier(place).lower(),
            "phonetic": phonetic_key(place),
            "mentions": 0,
            "review_ids": set(),
            "districts": set(),
            "divisions": set(),
            "languages": set(),
            "from_text": False,
        })
        if district:
            record["districts"].add(district)
        if division_of.get(place):
            record["divisions"].add(division_of[place])
    return groups


def resolve(groups: dict[str, dict], embeddings=None, threshold: float = MERGE_THRESHOLD):
    """Cluster surface forms. Returns (clusters, pair log)."""
    surfaces = list(groups)
    union = UnionFind(surfaces)
    pairs: list[dict] = []

    for i, left in enumerate(surfaces):
        for right in surfaces[i + 1:]:
            a, b = groups[left], groups[right]
            # Types never merge: a FOOD and a PLACE sharing a name are two
            # things (the kotkoti shop and the kotkoti sweet).
            if a["entity_type"] != b["entity_type"]:
                continue
            score, signals = pair_score(a, b, embeddings)
            if score >= threshold:
                union.union(left, right)
                pairs.append({
                    "surface_a": left, "surface_b": right,
                    "score": round(score, 4),
                    **{f"signal_{k}": round(v, 4) for k, v in signals.items()},
                })
    return union.groups(), pairs


# --- evaluation (cluster purity and B-cubed F1) --------------------------


def bcubed(predicted: dict[str, int], gold: dict[str, int]) -> tuple[float, float, float]:
    """B-cubed precision, recall and F1 over items present in both labellings.

    B-cubed is per-item rather than per-cluster, which is what makes it the
    right metric here: splitting one place into two clusters is penalised in
    proportion to how many mentions were split, not counted as one mistake.
    """
    shared = [item for item in predicted if item in gold]
    if not shared:
        return float("nan"), float("nan"), float("nan")

    precisions, recalls = [], []
    for item in shared:
        same_predicted = [o for o in shared if predicted[o] == predicted[item]]
        same_gold = [o for o in shared if gold[o] == gold[item]]
        overlap = len(set(same_predicted) & set(same_gold))
        precisions.append(overlap / len(same_predicted))
        recalls.append(overlap / len(same_gold))

    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def purity(predicted: dict[str, int], gold: dict[str, int]) -> float:
    """Share of items whose cluster's majority gold label is their own."""
    shared = [item for item in predicted if item in gold]
    if not shared:
        return float("nan")
    by_cluster: dict[int, list[str]] = defaultdict(list)
    for item in shared:
        by_cluster[predicted[item]].append(item)
    correct = 0
    for members in by_cluster.values():
        counts: dict[int, int] = defaultdict(int)
        for member in members:
            counts[gold[member]] += 1
        correct += max(counts.values())
    return correct / len(shared)


def read_gold() -> dict[str, int]:
    """The hand-made variant groups, as surface -> group id."""
    if not IN_GOLD.exists():
        return {}
    frame = pd.read_csv(IN_GOLD)
    if not {"surface", "group_id"} <= set(frame.columns):
        return {}
    return dict(zip(frame["surface"].astype(str), frame["group_id"].astype(int)))


def evaluate(clusters: dict, gold: dict[str, int]) -> dict:
    predicted: dict[str, int] = {}
    for index, (_, members) in enumerate(sorted(clusters.items())):
        for member in members:
            predicted[member] = index

    covered = [s for s in gold if s in predicted]
    precision, recall, f1 = bcubed(predicted, gold)
    return {
        "gold_surfaces": len(gold),
        "gold_surfaces_present_in_corpus": len(covered),
        "missing_from_corpus": sorted(s for s in gold if s not in predicted),
        "bcubed_precision": None if precision != precision else round(precision, 4),
        "bcubed_recall": None if recall != recall else round(recall, 4),
        "bcubed_f1": None if f1 != f1 else round(f1, 4),
        "purity": None if purity(predicted, gold) != purity(predicted, gold)
        else round(purity(predicted, gold), 4),
    }


def write_reports(clusters: dict, groups: dict[str, dict], pairs: list[dict],
                  evaluation: dict | None, notes: list[str]) -> pd.DataFrame:
    entity_rows, variant_rows = [], []
    for index, (_, members) in enumerate(sorted(clusters.items()), start=1):
        entity_id = f"E{index:04d}"
        # The canonical name is the most-mentioned variant, with the longest
        # winning a tie: "Saint Martin's Island" reads better in a register
        # than "Saint Martin".
        ranked = sorted(members, key=lambda s: (-groups[s]["mentions"], -len(s), s))
        canonical = ranked[0]
        reviews = set()
        districts, divisions, languages = set(), set(), set()
        mentions = 0
        for member in members:
            record = groups[member]
            reviews |= record["review_ids"]
            districts |= record["districts"]
            divisions |= record["divisions"]
            languages |= record["languages"]
            mentions += record["mentions"]
            variant_rows.append({
                "entity_id": entity_id,
                "surface": member,
                "mentions": record["mentions"],
                "phonetic_key": record["phonetic"],
                "is_canonical": member == canonical,
            })
        entity_rows.append({
            "entity_id": entity_id,
            "canonical_name": canonical,
            "entity_type": groups[canonical]["entity_type"],
            "n_variants": len(members),
            "n_mentions": mentions,
            "n_reviews": len(reviews),
            "districts": "|".join(sorted(d for d in districts if d)),
            "divisions": "|".join(sorted(d for d in divisions if d)),
            "languages": "|".join(sorted(l for l in languages if l)),
        })

    entities = pd.DataFrame(entity_rows).sort_values("n_mentions", ascending=False)
    entities.to_csv(OUT_ENTITIES, index=False)
    pd.DataFrame(variant_rows).to_csv(OUT_VARIANTS, index=False)

    merged = [e for e in entity_rows if e["n_variants"] > 1]

    # A cluster whose variants differ only by letter case is a trivial win and
    # must not be presented as evidence that resolution works. The substantive
    # ones are the spelling and local-vs-official cases section 5.3 is about.
    variants_by_entity: dict[str, list[str]] = defaultdict(list)
    for row in variant_rows:
        variants_by_entity[row["entity_id"]].append(row["surface"])
    substantive = [
        entity for entity in merged
        if len({s.lower() for s in variants_by_entity[entity["entity_id"]]}) > 1
    ]
    case_only = [e for e in merged if e not in substantive]
    payload = {
        "n_surfaces": len(groups),
        "n_entities": len(entity_rows),
        "n_merged_entities": len(merged),
        "n_substantive_merges": len(substantive),
        "n_case_only_merges": len(case_only),
        "weights": WEIGHTS,
        "merge_threshold": MERGE_THRESHOLD,
        "n_pairs_merged": len(pairs),
        "evaluation": evaluation,
        "notes": notes,
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 4 — Entity resolution",
        "",
        "Clusters mentions of the same real thing (BUILD_PLAN 5.3). Unresolved",
        "spelling variants split one place's evidence, and section 5.5 needs 2-3",
        "independent mentions before anything becomes a candidate — so this step is",
        "what stops variants suppressing the gems the project is looking for.",
        "",
        f"- Distinct surface forms in: **{len(groups)}**",
        f"- Entities out: **{len(entity_rows)}**",
        f"- Entities with more than one variant: **{len(merged)}**",
        f"  - of which substantive (not just letter case): **{len(substantive)}**",
        f"  - case-only: {len(case_only)}",
        "",
        f"Weights (fixed in advance): {WEIGHTS}, merge threshold {MERGE_THRESHOLD}.",
        "",
        "Surfaces carrying 0 mentions are the corpus's own place names, added so a",
        "short form found in someone else's review has an official name to resolve",
        "against. A place having reviews is not the same as its name being mentioned,",
        "so they contribute no mentions to the evidence counts.",
        "",
    ]
    if substantive:
        lines += [
            "## Substantive variant groups",
            "",
            "Spelling and local-vs-official cases — what section 5.3 is actually about.",
            "",
            "| entity | variants | mentions |", "| --- | --- | --- |",
        ]
        for entity in sorted(substantive, key=lambda e: -e["n_mentions"]):
            members = variants_by_entity[entity["entity_id"]]
            lines.append(
                f"| {entity['canonical_name']} | {', '.join(sorted(members))} | {entity['n_mentions']} |"
            )
        lines.append("")
    if case_only:
        lines += [
            "## Case-only groups",
            "",
            "Trivially easy; listed separately so they are not read as evidence that",
            "resolution works.",
            "",
            *[f"- {', '.join(sorted(variants_by_entity[e['entity_id']]))}" for e in case_only],
            "",
        ]
    if evaluation:
        lines += [
            "## Evaluation against the hand-made variant groups",
            "",
            f"- Gold surfaces: {evaluation['gold_surfaces']} "
            f"({evaluation['gold_surfaces_present_in_corpus']} present in the corpus)",
            f"- B-cubed precision: {evaluation['bcubed_precision']}",
            f"- B-cubed recall: {evaluation['bcubed_recall']}",
            f"- **B-cubed F1: {evaluation['bcubed_f1']}**",
            f"- Cluster purity: {evaluation['purity']}",
            "",
        ]
        if evaluation["missing_from_corpus"]:
            lines += [
                "Gold surfaces the corpus does not contain, so they could not be scored:",
                "",
                *[f"- `{s}`" for s in evaluation["missing_from_corpus"]],
                "",
            ]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entities


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float, default=MERGE_THRESHOLD)
    parser.add_argument("--evaluate", action="store_true", help="score against the gold variant groups")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not IN_MENTIONS.exists():
        print(f"error: {IN_MENTIONS} does not exist; run scripts/extract_mentions.py first")
        return 1

    mentions = pd.read_csv(IN_MENTIONS)
    corpus = pd.read_csv(IN_CORPUS) if IN_CORPUS.exists() else None
    geography = pd.read_csv(IN_GEOGRAPHY) if IN_GEOGRAPHY.exists() else None
    notes: list[str] = []
    if geography is None:
        notes.append("place_geography.csv missing: the geography signal is unavailable")
    notes.append("embedding signal unavailable (needs torch); phonetic + string + geography only")

    print(f"Phase 4 — resolving {len(mentions)} mention(s)")
    groups = build_surface_groups(mentions, geography, corpus)
    print(f"  distinct surfaces: {len(groups)}")

    clusters, pairs = resolve(groups, embeddings=None, threshold=args.threshold)
    print(f"  entities: {len(clusters)}  (merged {len(groups) - len(clusters)} surface(s))")

    evaluation = None
    if args.evaluate:
        gold = read_gold()
        if not gold:
            print(f"  no gold file at {IN_GOLD.name}; skipping evaluation")
        else:
            evaluation = evaluate(clusters, gold)
            print(f"  B-cubed F1: {evaluation['bcubed_f1']}  purity: {evaluation['purity']}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0

    entities = write_reports(clusters, groups, pairs, evaluation, notes)
    print(f"\n  wrote {OUT_ENTITIES.name}, {OUT_VARIANTS.name}, {OUT_REPORT_MD.name}")
    multi = entities[entities["n_variants"] > 1]
    if not multi.empty:
        print("\n  variant groups found:")
        for _, row in multi.head(10).iterrows():
            print(f"    {row['canonical_name']}  ({row['n_variants']} variants, {row['n_mentions']} mentions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
