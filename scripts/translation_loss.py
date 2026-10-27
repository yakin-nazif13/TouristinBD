"""What is lost when reviews are read through Google's translation.

Section 4.4 says entity extraction must always run on the original text. This
measures why, on the corpus's own evidence rather than by assertion.

Google Maps gives some reviews twice: the reviewer's own words
(`review_text_original`) and Google's English translation of them
(`review_text_clean`). That is a paired sample with nothing to control for —
the same review, the same reviewer, the same day — so the same extractor is run
over both versions and the difference is what translation did.

Two measurements:

  1. Bangla-script reviews. For every place, food, activity and transport mode
     found in either version: was it found in the original, the translation,
     or both? A place found only in the original was *lost in translation*:
     কটকা becomes "Katka" (the map knows Kotka), সাদা মাটির পাহাড় becomes
     "the white clay hills". A place found only in the translation is usually a
     gap in our own Bangla name list (সুন্দরবন is not in it yet), and is
     reported as that, not as something translation added.

  2. Banglish reviews (Bangla in English letters). Google mostly cannot read
     these at all. Every pair is listed in data/banglish_translation_check.csv
     with a judgement a person can change: meaning_kept, meaning_lost or
     untranslated.

Only the gazetteer and the reviewed food / activity list are compared. The TIP
and ACCESS cue patterns are English-only regular expressions, so they would
"find" things in the translation that the original could never match, and are
left out. Retention comes with a bootstrap 95% interval over reviews, because
the sample is a few hundred reviews, not thousands.

Outputs:
    data/translation_loss_pairs.csv       one row per (review, thing found)
    data/banglish_translation_check.csv   reviewed list: each Banglish pair
    data/translation_loss_report.md / .json

Run:
    .venv/bin/python scripts/translation_loss.py
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_mentions as em  # noqa: E402
from language_id import script_shares  # noqa: E402
from resolve_entities import _equivalence_key, load_equivalents  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GAZETTEER = DATA_DIR / "phase4_gazetteer.csv"
OUT_PAIRS = DATA_DIR / "translation_loss_pairs.csv"
BANGLISH_CHECK = DATA_DIR / "banglish_translation_check.csv"
OUT_REPORT_MD = DATA_DIR / "translation_loss_report.md"
OUT_REPORT_JSON = DATA_DIR / "translation_loss_report.json"

COMPARED_TYPES = ["PLACE", "FOOD", "ACTIVITY", "ACCESS"]

# A script share above this decides which kind of pair a review is.
SCRIPT_SHARE = 0.8

# A lost place whose name still appears, respelled, in the translation
# ("Katka" for Kotka). rapidfuzz partial_ratio, 0-100.
RESPELLED_SIMILARITY = 75

BOOTSTRAP_SAMPLES = 2000
SEED = 13

BANGLISH_JUDGEMENTS = ["meaning_kept", "meaning_lost", "untranslated", "pending"]

PAIR_COLUMNS = [
    "review_id", "place_name", "entity_type", "concept", "in_original", "in_translation",
    "outcome", "own_place", "original_surface", "translation_surface",
    "original_text", "translation_text",
]


def paired_reviews(corpus: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(Bangla-script pairs, Banglish pairs): reviews Google gave in two versions."""
    original = corpus["review_text_original"]
    has_both = original.notna() & (
        original.astype(str).str.strip() != corpus["review_text_clean"].astype(str).str.strip())
    bangla = corpus[has_both & (corpus["original_language"].astype(str) == "bn")].copy()
    shares = bangla["review_text_original"].astype(str).map(script_shares)
    bengali = shares.map(lambda s: s[0] > SCRIPT_SHARE)
    latin = shares.map(lambda s: s[1] > SCRIPT_SHARE)
    return bangla[bengali].reset_index(drop=True), bangla[latin].reset_index(drop=True)


class ConceptFinder:
    """Finds the places, foods, activities and transport a text names.

    Each is reduced to the name a reviewed list says it stands for, so "কটকা"
    in the original and "Kotka" in a translation are the same concept.
    """

    def __init__(self, gazetteer: list[str], aliases: dict[str, str],
                 lexicon: list[tuple[str, str]], equivalents: dict[tuple[str, str], str]):
        self.gazetteer = gazetteer
        self.aliases = aliases
        self.lexicon = lexicon
        self.equivalents = equivalents
        self.lexicon_keys = {(t, _equivalence_key(s)) for s, t in lexicon}

    def find(self, text: str, own_place: str = "") -> dict[tuple[str, str], str]:
        """(type, concept) -> the surface it was found as."""
        found: dict[tuple[str, str], str] = {}
        for match in em.extract_gazetteer(str(text or ""), own_place, self.gazetteer,
                                          self.aliases, self.lexicon):
            entity_type, surface = match["entity_type"], match["surface"]
            if entity_type not in COMPARED_TYPES:
                continue
            key = _equivalence_key(surface)
            # ACCESS also comes from English-only cue patterns; only the
            # reviewed transport words are comparable across languages.
            if entity_type == "ACCESS" and (entity_type, key) not in self.lexicon_keys:
                continue
            target = (self.equivalents.get((entity_type, key))
                      or self.aliases.get(surface) or surface)
            found.setdefault((entity_type, str(target).strip().lower()), surface)
        return found


def classify_loss(entity_type: str, concept: str, translation: str) -> str:
    """Why a concept found in the original is missing from the translation.

    `respelled` only for places, and only when a run of words of the same
    length in the translation spells nearly the same name ("Katka beach" for
    Kotka). A fuzzy name matcher might recover these, so they are reported as
    recoverable; everything else was turned into a description or left out.
    """
    if entity_type != "PLACE":
        return "translated_or_dropped"
    words = [w.strip(".,;:!?\"'()") for w in str(translation).lower().split()]
    size = len(concept.split())
    for i in range(max(0, len(words) - size + 1)):
        if fuzz.ratio(concept.lower(), " ".join(words[i:i + size])) >= RESPELLED_SIMILARITY:
            return "respelled"
    return "translated_or_dropped"


def compare(pairs: pd.DataFrame, finder: ConceptFinder) -> pd.DataFrame:
    """One row per (review, concept found in either version)."""
    rows = []
    for _, review in pairs.iterrows():
        original, translation = str(review["review_text_original"]), str(review["review_text_clean"])
        in_original, in_translation = finder.find(original), finder.find(translation)
        # Found again with the review's own place excluded = a secondary mention,
        # the kind the gem engine is built on.
        place = str(review.get("place_name") or "")
        secondary = set(finder.find(original, place)) | set(finder.find(translation, place))
        for key in sorted(set(in_original) | set(in_translation)):
            entity_type, concept = key
            if key in in_original and key in in_translation:
                outcome = "kept"
            elif key in in_original:
                outcome = "lost_" + classify_loss(entity_type, concept, translation)
            else:
                outcome = "only_in_translation"
            rows.append({
                "review_id": review["review_id"],
                "place_name": place,
                "entity_type": entity_type,
                "concept": concept,
                "in_original": key in in_original,
                "in_translation": key in in_translation,
                "outcome": outcome,
                "own_place": key not in secondary,
                "original_surface": in_original.get(key, ""),
                "translation_surface": in_translation.get(key, ""),
                "original_text": original,
                "translation_text": translation,
            })
    return pd.DataFrame(rows, columns=PAIR_COLUMNS)


def retention(rows: pd.DataFrame) -> float | None:
    """Share of what the original names that the translation still names."""
    found = rows[rows["in_original"]]
    return float(found["in_translation"].mean()) if len(found) else None


def bootstrap_interval(rows: pd.DataFrame, samples: int = BOOTSTRAP_SAMPLES,
                       seed: int = SEED) -> tuple[float, float] | None:
    """95% interval for retention, resampling whole reviews."""
    found = rows[rows["in_original"]]
    if found.empty:
        return None
    groups = [g["in_translation"].tolist() for _, g in found.groupby("review_id")]
    rng = random.Random(seed)
    values = []
    for _ in range(samples):
        drawn = [x for _ in groups for x in rng.choice(groups)]
        values.append(sum(drawn) / len(drawn))
    values.sort()
    return values[int(0.025 * samples)], values[int(0.975 * samples) - 1]


def merge_banglish(pairs: pd.DataFrame, existing: pd.DataFrame | None) -> pd.DataFrame:
    """The Banglish list, keeping every judgement a person already recorded."""
    known = {} if existing is None else {
        str(r["review_id"]): (str(r["judgement"]), "" if pd.isna(r["reason"]) else str(r["reason"]))
        for _, r in existing.iterrows()
    }
    rows = []
    for _, review in pairs.iterrows():
        judgement, reason = known.get(str(review["review_id"]), ("pending", ""))
        rows.append({
            "review_id": review["review_id"],
            "place_name": review["place_name"],
            "original": " ".join(str(review["review_text_original"]).split()),
            "google_translation": " ".join(str(review["review_text_clean"]).split()),
            "judgement": judgement,
            "reason": reason,
        })
    return pd.DataFrame(rows, columns=["review_id", "place_name", "original", "google_translation",
                                       "judgement", "reason"])


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table [[a, b], [c, d]]."""
    from math import comb
    row1, col1, total = a + b, a + c, a + b + c + d

    def probability(x: int) -> float:
        return comb(col1, x) * comb(total - col1, row1 - x) / comb(total, row1)

    observed = probability(a)
    low, high = max(0, row1 + col1 - total), min(row1, col1)
    return min(1.0, sum(probability(x) for x in range(low, high + 1)
                        if probability(x) <= observed * (1 + 1e-9)))


def visibility_contrast(rows: pd.DataFrame, visibility: dict[str, str]) -> dict:
    """How well known the places on each side are: lost to translation, or
    missing from our Bangla lists.

    If translation mostly loses little-known local names while our Bangla gaps
    are famous places, reading the original matters most exactly where the gem
    engine looks. Tested on little-known (V0-V1) against known (V2-V3).
    """
    places = rows[rows["entity_type"] == "PLACE"].copy()
    places["visibility"] = places["concept"].map(visibility)
    sides = {
        "lost_in_translation": places[places["outcome"].str.startswith("lost")],
        "missing_from_bangla_lists": places[places["outcome"] == "only_in_translation"],
    }
    out: dict = {}
    for side, part in sides.items():
        counts = part["visibility"].fillna("not checked").value_counts()
        rated = part["visibility"].isin(["V0", "V1", "V2", "V3"])
        little = int(part["visibility"].isin(["V0", "V1"]).sum())
        out[side] = {
            "by_visibility": {k: int(v) for k, v in counts.items()},
            "little_known": little,
            "rated": int(rated.sum()),
            "little_known_share": little / int(rated.sum()) if rated.sum() else None,
        }
    lost, gap = out["lost_in_translation"], out["missing_from_bangla_lists"]
    out["fisher_p_two_sided"] = fisher_exact(
        lost["little_known"], lost["rated"] - lost["little_known"],
        gap["little_known"], gap["rated"] - gap["little_known"],
    ) if lost["rated"] and gap["rated"] else None
    return out


def summarise(rows: pd.DataFrame, n_reviews: int, banglish: pd.DataFrame,
              visibility: dict[str, str] | None = None) -> dict:
    by_type = {}
    for entity_type in COMPARED_TYPES:
        part = rows[rows["entity_type"] == entity_type]
        interval = bootstrap_interval(part)
        by_type[entity_type] = {
            "in_original": int(part["in_original"].sum()),
            "in_translation": int(part["in_translation"].sum()),
            "kept": int((part["outcome"] == "kept").sum()),
            "lost": int(part["outcome"].str.startswith("lost").sum()),
            "only_in_translation": int((part["outcome"] == "only_in_translation").sum()),
            "retention": retention(part),
            "retention_95ci": list(interval) if interval else None,
        }
    secondary = rows[~rows["own_place"]]
    overall_interval = bootstrap_interval(rows)
    judged = banglish[banglish["judgement"] != "pending"]
    # Best case: every respelled place is recovered by fuzzy matching.
    found = rows[rows["in_original"]]
    best_case = (float(found["outcome"].isin(["kept", "lost_respelled"]).mean())
                 if len(found) else None)
    return {
        "n_bangla_script_pairs": int(n_reviews),
        "n_banglish_pairs": int(len(banglish)),
        "by_type": by_type,
        "overall_retention": retention(rows),
        "overall_retention_95ci": list(overall_interval) if overall_interval else None,
        "retention_if_respelled_recovered": best_case,
        "secondary_mentions": {
            "in_original": int(secondary["in_original"].sum()),
            "lost": int(secondary["outcome"].str.startswith("lost").sum()),
            "retention": retention(secondary),
        },
        "loss_reasons": {k: int(v) for k, v in rows.loc[rows["outcome"].str.startswith("lost"), "outcome"]
                         .value_counts().items()},
        "visibility_contrast": visibility_contrast(rows, visibility or {}),
        "banglish_judgements": {k: int(v) for k, v in banglish["judgement"].value_counts().items()},
        "banglish_meaning_kept": int((judged["judgement"] == "meaning_kept").sum()),
        "banglish_judged": int(len(judged)),
        "method": {
            "compared_types": COMPARED_TYPES,
            "respelled_similarity": RESPELLED_SIMILARITY,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "seed": SEED,
        },
    }


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def _excerpt(text: str, surface: str, width: int = 70) -> str:
    """A window of the text around `surface`, or its start."""
    text = " ".join(str(text).split())
    at = text.find(surface) if surface else -1
    start = max(0, at - width // 2) if at >= 0 else 0
    piece = text[start:start + width]
    return ("…" if start else "") + piece.replace("|", "/") + ("…" if start + width < len(text) else "")


def write_report(summary: dict, rows: pd.DataFrame, banglish: pd.DataFrame) -> None:
    OUT_REPORT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    places = summary["by_type"]["PLACE"]
    ci = summary["overall_retention_95ci"]
    lines = [
        "# What translation loses",
        "",
        "The same extractor run over the reviewer's own words and over Google's English",
        "translation of the same review. The sample is every review Google Maps returned",
        "in both versions, so nothing else differs.",
        "",
        f"- Bangla-script reviews compared: **{summary['n_bangla_script_pairs']}**",
        f"- Of the places, foods, activities and transport named in the original, the "
        f"translation still names **{_pct(summary['overall_retention'])}**"
        + (f" (95% interval {_pct(ci[0])}–{_pct(ci[1])}, bootstrap over reviews)" if ci else ""),
        f"- Even if every respelled name were recovered by fuzzy matching, at most "
        f"**{_pct(summary['retention_if_respelled_recovered'])}** would survive",
        f"- Places alone: **{places['kept']} of {places['in_original']}** survive "
        f"({_pct(places['retention'])})",
        f"- Banglish reviews: **{summary['n_banglish_pairs']}**; Google kept the meaning of "
        f"**{summary['banglish_meaning_kept']} of {summary['banglish_judged']}** judged",
        "",
        "| type | in original | in translation | kept | lost | only in translation | retention (95% CI) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entity_type, s in summary["by_type"].items():
        interval = s["retention_95ci"]
        lines.append(
            f"| {entity_type} | {s['in_original']} | {s['in_translation']} | {s['kept']} | {s['lost']} | "
            f"{s['only_in_translation']} | {_pct(s['retention'])}"
            + (f" ({_pct(interval[0])}–{_pct(interval[1])})" if interval else "") + " |")

    contrast = summary["visibility_contrast"]
    lost_side, gap_side = contrast["lost_in_translation"], contrast["missing_from_bangla_lists"]
    p_value = contrast["fisher_p_two_sided"]
    lines += [
        "",
        "## Which places each side misses",
        "",
        "Places translation lost, against places our Bangla lists missed, by how well",
        "known they already are (gazetteer visibility, V0 = on no map, V3 = famous).",
        "",
        "| | little known (V0-V1) | known (V2-V3) | share little known |",
        "| --- | --- | --- | --- |",
        f"| lost in translation | {lost_side['little_known']} | {lost_side['rated'] - lost_side['little_known']} "
        f"| {_pct(lost_side['little_known_share'])} |",
        f"| missing from our Bangla lists | {gap_side['little_known']} | "
        f"{gap_side['rated'] - gap_side['little_known']} | {_pct(gap_side['little_known_share'])} |",
        "",
        (f"Fisher exact test, two-sided: p = {p_value:.3f}. "
         + ("The difference is unlikely to be chance at this sample size."
            if p_value < 0.05 else
            "At this sample size the difference could be chance; it is a direction to "
            "test on more data, not a result.")) if p_value is not None else "Too few rated places to test.",
    ]

    lost = rows[rows["outcome"].str.startswith("lost")]
    lines += [
        "",
        "## Lost in translation",
        "",
        "`respelled`: the name is still there, spelled so the map cannot find it.",
        "`translated_or_dropped`: the name was turned into a description, or left out.",
        "",
        "| concept | outcome | original | translation |",
        "| --- | --- | --- | --- |",
    ]
    shown = lost.drop_duplicates(["concept", "outcome"]).head(25)
    for _, r in shown.iterrows():
        lines.append(f"| {r['concept']} | {r['outcome'].replace('lost_', '')} | "
                     f"{_excerpt(r['original_text'], r['original_surface'])} | "
                     f"{_excerpt(r['translation_text'], '')} |")

    gained = rows[rows["outcome"] == "only_in_translation"]
    lines += [
        "",
        "## Found only in the translation — gaps in our own Bangla lists",
        "",
        "These are not things translation added. The original names them in Bangla, and",
        "our reviewed Bangla name list or food / activity list does not have that spelling",
        "yet. Each is a candidate to add.",
        "",
        "| concept | type | reviews |",
        "| --- | --- | --- |",
    ]
    for (concept, entity_type), group in (gained.groupby(["concept", "entity_type"])
                                          .size().sort_values(ascending=False).head(20).items()):
        lines.append(f"| {concept} | {entity_type} | {group} |")

    lines += [
        "",
        "## Banglish through Google Translate",
        "",
        f"Every pair, from `{BANGLISH_CHECK.name}`. The judgement column is a person's call",
        "and can be changed there.",
        "",
        "| reviewer wrote | Google's English | judgement |",
        "| --- | --- | --- |",
    ]
    for _, r in banglish.iterrows():
        lines.append(f"| {r['original'].replace('|', '/')} | {r['google_translation'].replace('|', '/')} | "
                     f"{r['judgement']} |")

    lines += [
        "",
        "## Limits",
        "",
        "- Our Bangla name list was mined from Bangla reviews, including some of these, so",
        "  matching on the original has a home advantage for names already on it. The",
        "  'only in translation' column is the opposite effect, so both are reported.",
        "- Matching is by name, not meaning: a description like 'the white clay hills' is",
        "  counted as lost even though a reader would recognise it.",
        f"- {summary['n_bangla_script_pairs']} reviews is a small sample, hence the intervals.",
        "- Only Google Maps' own translation is measured, not other translators.",
    ]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not IN_CORPUS.exists():
        print(f"error: {IN_CORPUS.name} does not exist; run Phase 2 first")
        return 1
    corpus = pd.read_csv(IN_CORPUS, low_memory=False)
    bangla, banglish_pairs = paired_reviews(corpus)
    finder = ConceptFinder(em.load_gazetteer(corpus), em.load_bangla_names(), em.load_lexicon(),
                           load_equivalents())
    rows = compare(bangla, finder)
    existing = pd.read_csv(BANGLISH_CHECK, dtype=str, keep_default_na=False) if BANGLISH_CHECK.exists() else None
    banglish = merge_banglish(banglish_pairs, existing)
    visibility = {}
    if IN_GAZETTEER.exists():
        gazetteer = pd.read_csv(IN_GAZETTEER)
        visibility = dict(zip(gazetteer["name"].astype(str).str.lower(), gazetteer["visibility"].astype(str)))
    summary = summarise(rows, len(bangla), banglish, visibility)

    print(f"Translation loss: {len(bangla)} Bangla-script pair(s), {len(banglish)} Banglish pair(s)")
    print(f"  overall retention {_pct(summary['overall_retention'])}"
          f"  places {summary['by_type']['PLACE']['kept']}/{summary['by_type']['PLACE']['in_original']}")
    pending = int((banglish["judgement"] == "pending").sum())
    if pending:
        print(f"  {pending} Banglish pair(s) await a judgement in {BANGLISH_CHECK.name}")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    rows.to_csv(OUT_PAIRS, index=False, encoding="utf-8")
    banglish.to_csv(BANGLISH_CHECK, index=False, encoding="utf-8")
    write_report(summary, rows, banglish)
    print(f"  wrote {OUT_PAIRS.name}, {BANGLISH_CHECK.name}, {OUT_REPORT_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
