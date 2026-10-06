"""Phase 4 — the gem score. BUILD_PLAN section 5.5.

    "Gem score (transparent and ablatable, not a black box)
       mentions   independent mentions (distinct authors, sources, years)
       sentiment  mean sentiment of mention sentences
       hidden     inverse official visibility (V0 highest)
       distinct   semantic distinctiveness vs its anchor (reuse SDD)
       recency    share of mentions in the last 2-3 years
     Minimum 2-3 independent mentions before anything becomes a candidate.
     Weights are fixed in advance and reported, and every term is ablated in
     Phase 5."

Three properties the plan asks for, and how each is met:

  transparent  every term is stored per entity alongside the final score, so a
               ranking can be explained to a district officer term by term
               rather than asserted.
  ablatable    --ablate drops any term and renormalises the remaining weights,
               which is what section 6.2's ablation table needs.
  not a black box
               no learned weights. They are constants below, reported in every
               output, and chosen before seeing the ranking.

THE CANDIDATE GATE

Nothing with fewer than MIN_INDEPENDENT_MENTIONS distinct reviews is scored at
all. Independence is counted in *distinct reviews*, not mentions: a single
reviewer who names a place three times in one review is one person's opinion,
and treating that as three pieces of evidence is how a register fills up with
things one enthusiast mentioned.

Reviewer identity is deliberately not used, even though it would be the
strongest independence signal. Section 10 of the plan keeps personal-data
output off, so no reviewer names are stored. Distinct reviews, sources and
years are the available proxies.

A NOTE ON TWO TERMS

`distinct` is specified as "reuse SDD", which in Phase 4 is 1 - max cosine
similarity to an abundant topic, computed from sentence embeddings. Embeddings
need torch, which cannot load on every contributor's machine, so this computes
a **lexical** distinctiveness instead: TF-IDF cosine distance between the
mention's sentence and the centroid of the host place's other reviews. It
answers the same question — is this mention saying something unusual for this
place? — with scikit-learn rather than torch, and the method used is recorded
in the output so the two are never confused.

`sentiment` uses VADER, which is English-lexicon-based. For a Bangla or
Banglish sentence it is not meaningful, so those mentions are *excluded* from
the mean rather than scored 0.0 — a neutral score and "we cannot tell" are
different claims. If no mention of an entity can be scored, the term is marked
unavailable for that entity and the weights renormalise.

Run:
    .venv/bin/python scripts/score_gems.py
    .venv/bin/python scripts/score_gems.py --ablate hidden
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import MIN_INDEPENDENT_MENTIONS, VISIBILITY_LEVELS  # noqa: E402
from language_id import script_shares  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_MENTIONS = DATA_DIR / "phase4_mentions.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_GAZETTEER = DATA_DIR / "phase4_gazetteer.csv"
IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_LANGUAGE = DATA_DIR / "phase3_language_labels.csv"

OUT_CSV = DATA_DIR / "phase4_gem_scores.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_gem_score_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_gem_score_report.json"

TERMS = ["mentions", "sentiment", "hidden", "distinct", "recency"]

# Fixed in advance, before any ranking was inspected. `hidden` carries the most
# weight because V0 — absent from every public list — is what distinguishes a
# discovery from a site the BTB already publishes, which is the whole point.
# `mentions` is next, because a claim with more independent support is one a
# district officer can act on.
WEIGHTS = {
    "mentions": 0.30,
    "hidden": 0.30,
    "distinct": 0.15,
    "sentiment": 0.15,
    "recency": 0.10,
}

# Saturating point for the mentions term: at or above this many distinct
# reviews the term is 1.0. Without a cap, one much-discussed place would
# dominate the ranking on volume alone, which is the behaviour of the
# popularity baseline section 6.1 compares against.
MENTIONS_SATURATION = 10

# V0 highest, as the plan specifies.
HIDDEN_BY_VISIBILITY = {"V0": 1.0, "V1": 0.65, "V2": 0.30, "V3": 0.0}

# "the last 2-3 years" (section 5.5). Three years, measured from the newest
# review in the corpus rather than today's date, so the score does not drift
# as the file ages on disk.
RECENCY_WINDOW_YEARS = 3

# Below this share of Latin letters, VADER's English lexicon says nothing
# useful about a sentence.
VADER_MIN_LATIN_SHARE = 0.8


def normalised_weights(ablate: set[str]) -> dict[str, float]:
    """Weights over the terms still in play, summing to 1."""
    live = {term: weight for term, weight in WEIGHTS.items() if term not in ablate}
    total = sum(live.values())
    if not total:
        raise ValueError("every term was ablated; nothing left to score with")
    return {term: weight / total for term, weight in live.items()}


def score_mentions(n_reviews: int) -> float:
    """Independent-evidence term, saturating at MENTIONS_SATURATION."""
    return min(1.0, n_reviews / MENTIONS_SATURATION)


def score_hidden(visibility: str | None) -> float | None:
    """Inverse official visibility. None when visibility is unknown.

    An unknown visibility must not score 0.0: that is the value for a
    well-known site, and defaulting to it would quietly bury every entity whose
    gazetteer lookup failed.
    """
    if visibility not in HIDDEN_BY_VISIBILITY:
        return None
    return HIDDEN_BY_VISIBILITY[visibility]


def score_recency(dates: list[pd.Timestamp], newest: pd.Timestamp) -> float | None:
    """Share of mentions inside the recency window. None if no dates parsed."""
    usable = [d for d in dates if pd.notna(d)]
    if not usable:
        return None
    cutoff = newest - pd.DateOffset(years=RECENCY_WINDOW_YEARS)
    return sum(1 for d in usable if d >= cutoff) / len(usable)


def score_sentiment(sentences: list[str], analyser) -> tuple[float | None, int]:
    """Mean VADER compound over English sentences, rescaled to 0..1.

    Returns (score, n_scored). Non-Latin sentences are skipped rather than
    scored neutral, so a Bangla-only entity reports None instead of a
    fabricated 0.5.
    """
    scores = []
    for sentence in sentences:
        text = str(sentence or "").strip()
        if not text:
            continue
        if script_shares(text)[1] < VADER_MIN_LATIN_SHARE:
            continue
        scores.append(analyser.polarity_scores(text)["compound"])
    if not scores:
        return None, 0
    # compound is -1..1; the score must be 0..1 like every other term.
    return (sum(scores) / len(scores) + 1.0) / 2.0, len(scores)


def build_distinctiveness(corpus: pd.DataFrame, mentions: pd.DataFrame) -> dict[int, float]:
    """Lexical distinctiveness of each mention's sentence vs its host place.

    TF-IDF cosine distance between the sentence and the centroid of the host
    place's reviews. High means the mention says something unusual for that
    place, which is what makes it worth looking at: a Kuakata review that reads
    like every other Kuakata review is not reporting a discovery.

    Returns {mention_id -> 0..1}. mention_id here is the row index of the
    mentions frame, which is the order the database also assigns.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    review_text = dict(zip(corpus["review_id"].astype(str),
                           corpus["review_text_clean"].astype(str)))
    review_place = dict(zip(corpus["review_id"].astype(str),
                            corpus["place_name"].astype(str)))

    sentences = [str(s or "") for s in mentions["sentence"]]
    corpus_texts = [str(t or "") for t in corpus["review_text_clean"]]
    # One vectoriser over everything, so sentences and reviews share a space.
    vectoriser = TfidfVectorizer(stop_words="english", min_df=1, sublinear_tf=True)
    matrix = vectoriser.fit_transform(corpus_texts + sentences)
    review_vectors = matrix[:len(corpus_texts)]
    sentence_vectors = matrix[len(corpus_texts):]

    # Centroid per place, over that place's reviews.
    place_rows: dict[str, list[int]] = {}
    for index, review_id in enumerate(corpus["review_id"].astype(str)):
        place_rows.setdefault(review_place.get(review_id, ""), []).append(index)
    centroids = {
        place: review_vectors[rows].mean(axis=0)
        for place, rows in place_rows.items() if rows
    }

    import numpy as np

    out: dict[int, float] = {}
    for position, (_, mention) in enumerate(mentions.iterrows()):
        host = review_place.get(str(mention["review_id"]), "")
        centroid = centroids.get(host)
        if centroid is None or not str(mention.get("sentence") or "").strip():
            continue
        similarity = float(cosine_similarity(
            sentence_vectors[position], np.asarray(centroid)
        )[0][0])
        out[position] = max(0.0, min(1.0, 1.0 - similarity))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ablate", action="append", default=[], choices=TERMS,
                        help="drop a term and renormalise the rest (repeatable)")
    parser.add_argument("--min-reviews", type=int, default=MIN_INDEPENDENT_MENTIONS,
                        help=f"candidate gate (default {MIN_INDEPENDENT_MENTIONS})")
    parser.add_argument("--out-suffix", default="",
                        help="suffix for the output files, for ablation runs")
    args = parser.parse_args()

    for path in (IN_ENTITIES, IN_MENTIONS, IN_CORPUS):
        if not path.exists():
            print(f"error: {path.name} does not exist; run the earlier Phase 4 steps first")
            return 1

    ablate = set(args.ablate)
    weights = normalised_weights(ablate)

    entities = pd.read_csv(IN_ENTITIES)
    mentions = pd.read_csv(IN_MENTIONS).reset_index(drop=True)
    corpus = pd.read_csv(IN_CORPUS)
    variants = pd.read_csv(IN_VARIANTS) if IN_VARIANTS.exists() else pd.DataFrame()
    gazetteer = pd.read_csv(IN_GAZETTEER) if IN_GAZETTEER.exists() else pd.DataFrame()

    notes: list[str] = []
    if gazetteer.empty:
        notes.append("no gazetteer: the `hidden` term is unavailable for every entity")

    # Attach entity_id to mentions via the variants mapping, as the database does.
    if not variants.empty:
        surface_to_entity = dict(zip(variants["surface"].astype(str),
                                     variants["entity_id"].astype(str)))
        mentions["entity_id"] = mentions["surface"].astype(str).map(surface_to_entity)
    else:
        print("error: entity variants are missing; run scripts/resolve_entities.py")
        return 1

    visibility_of = (dict(zip(gazetteer["name"].astype(str), gazetteer["visibility"].astype(str)))
                     if not gazetteer.empty else {})
    review_date = dict(zip(corpus["review_id"].astype(str),
                           pd.to_datetime(corpus["review_date"], errors="coerce", utc=True)))
    review_source = dict(zip(corpus["review_id"].astype(str), corpus["source"].astype(str)))
    newest = max((d for d in review_date.values() if pd.notna(d)),
                 default=pd.Timestamp.now(tz=timezone.utc))

    distinctiveness = {}
    if "distinct" not in ablate:
        try:
            distinctiveness = build_distinctiveness(corpus, mentions)
            notes.append(f"`distinct` computed lexically (TF-IDF) for {len(distinctiveness)} mention(s)")
        except Exception as exc:
            notes.append(f"`distinct` unavailable: {type(exc).__name__}: {exc}")

    analyser = None
    if "sentiment" not in ablate:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            analyser = SentimentIntensityAnalyzer()
        except ImportError:
            notes.append("vaderSentiment not installed; the `sentiment` term is unavailable")

    print(f"Phase 4 — gem score over {len(entities)} entit(ies)")
    print(f"  weights: { {k: round(v, 3) for k, v in weights.items()} }")
    if ablate:
        print(f"  ablated: {sorted(ablate)}")
    print(f"  candidate gate: {args.min_reviews}+ distinct reviews")

    rows = []
    for _, entity in entities.iterrows():
        entity_id = str(entity["entity_id"])
        own = mentions[mentions["entity_id"] == entity_id]
        review_ids = {str(r) for r in own["review_id"]}
        n_reviews = len(review_ids)

        if n_reviews < args.min_reviews:
            continue

        name = str(entity["canonical_name"])
        dates = [review_date.get(r) for r in review_ids]
        sources = {review_source.get(r, "") for r in review_ids}
        years = {d.year for d in dates if pd.notna(d)}

        terms: dict[str, float | None] = {}
        terms["mentions"] = score_mentions(n_reviews)
        terms["hidden"] = score_hidden(visibility_of.get(name))
        terms["recency"] = score_recency(dates, newest)
        if analyser is not None:
            terms["sentiment"], n_sentiment = score_sentiment(
                own["sentence"].tolist(), analyser)
        else:
            terms["sentiment"], n_sentiment = None, 0
        if distinctiveness:
            values = [distinctiveness[i] for i in own.index if i in distinctiveness]
            terms["distinct"] = sum(values) / len(values) if values else None
        else:
            terms["distinct"] = None

        # Score over the terms that both survive ablation and have a value, with
        # the weights renormalised, so a missing term is not silently a zero.
        usable = {t: v for t, v in terms.items() if t not in ablate and v is not None}
        live_weight = sum(WEIGHTS[t] for t in usable)
        score = (sum(WEIGHTS[t] * v for t, v in usable.items()) / live_weight
                 if live_weight else None)

        rows.append({
            "entity_id": entity_id,
            "canonical_name": name,
            "entity_type": entity["entity_type"],
            "gem_score": None if score is None else round(score, 4),
            "n_reviews": n_reviews,
            "n_mentions": len(own),
            "n_sources": len([s for s in sources if s]),
            "n_years": len(years),
            "visibility": visibility_of.get(name, "unknown"),
            # A filter, not a score adjustment. A V3 entity is already on
            # official lists, so it is not a discovery whatever it scores —
            # and on this corpus two V3 entities do outrank every V2 and V1,
            # because `mentions` saturates for a much-reviewed famous place.
            # The register can exclude these without the score being retuned
            # to hide the behaviour.
            "already_official": visibility_of.get(name) == "V3",
            **{f"term_{t}": (None if terms[t] is None else round(terms[t], 4)) for t in TERMS},
            "terms_used": "|".join(sorted(usable)),
            "n_sentiment_sentences": n_sentiment,
            "sentiment_method": "vader-en" if n_sentiment else "unavailable",
            "distinct_method": "tfidf-lexical" if terms["distinct"] is not None else "unavailable",
        })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("gem_score", ascending=False, na_position="last")

        # A term with no spread contributes nothing but still carries weight.
        # Reported rather than silently corrected: on this corpus `recency` is
        # 1.0 for almost every candidate, because nearly all reviews fall
        # inside the three-year window. That is a fact about the corpus, and
        # dropping the term now would be tuning to it.
        for term in TERMS:
            column = frame[f"term_{term}"].dropna()
            if len(column) >= 3 and column.nunique() == 1:
                notes.append(
                    f"`{term}` is identical ({column.iloc[0]:.2f}) for all "
                    f"{len(column)} scored candidate(s), so it does not affect "
                    f"the ranking on this corpus despite carrying weight "
                    f"{WEIGHTS[term]}"
                )
            elif len(column) >= 3 and column.std() < 0.05:
                notes.append(
                    f"`{term}` has very little spread (sd {column.std():.3f}) "
                    f"across candidates, so its weight {WEIGHTS[term]} is doing "
                    "little work here"
                )

        official = frame[frame["already_official"]]
        if not official.empty:
            best_official = official.iloc[0]
            better_than = frame[frame["gem_score"] < best_official["gem_score"]]
            outranked = better_than[~better_than["already_official"]]
            if len(outranked):
                notes.append(
                    f"{len(official)} candidate(s) are already official (V3), and the "
                    f"highest of them ({best_official['canonical_name']}, "
                    f"{best_official['gem_score']:.2f}) outranks {len(outranked)} "
                    "candidate(s) that are not — `mentions` saturates for a much-"
                    "reviewed famous place. Use already_official to filter the "
                    "register; the weights were not retuned after seeing this."
                )

    suffix = args.out_suffix
    out_csv = OUT_CSV.with_name(OUT_CSV.stem + suffix + OUT_CSV.suffix)
    out_md = OUT_REPORT_MD.with_name(OUT_REPORT_MD.stem + suffix + OUT_REPORT_MD.suffix)
    out_json = OUT_REPORT_JSON.with_name(OUT_REPORT_JSON.stem + suffix + OUT_REPORT_JSON.suffix)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_csv, index=False)

    by_visibility = frame["visibility"].value_counts().to_dict() if not frame.empty else {}
    payload = {
        "n_entities_considered": int(len(entities)),
        "n_candidates": int(len(frame)),
        "candidate_gate_min_reviews": args.min_reviews,
        "weights_declared": WEIGHTS,
        "weights_used": {k: round(v, 4) for k, v in weights.items()},
        "ablated": sorted(ablate),
        "mentions_saturation": MENTIONS_SATURATION,
        "recency_window_years": RECENCY_WINDOW_YEARS,
        "hidden_by_visibility": HIDDEN_BY_VISIBILITY,
        "by_visibility": {k: int(v) for k, v in by_visibility.items()},
        "notes": notes,
    }
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 4 — Gem score",
        "",
        "Five terms, fixed weights, every term stored per entity so a ranking can be",
        "explained rather than asserted (BUILD_PLAN 5.5).",
        "",
        f"- Entities considered: {len(entities)}",
        f"- Candidates (>= {args.min_reviews} distinct reviews): **{len(frame)}**",
        f"- Ablated this run: {sorted(ablate) or 'none'}",
        "",
        "These weights were chosen before any ranking was inspected and have not",
        "been changed since. Section 6.2 ablates every term against human-verified",
        "gems, which is how the weighting gets settled empirically rather than by",
        "whichever ordering looks most convincing.",
        "",
        "## Weights",
        "",
        "| term | weight | what it measures |",
        "| --- | --- | --- |",
        f"| mentions | {WEIGHTS['mentions']} | distinct reviews, saturating at {MENTIONS_SATURATION} |",
        f"| hidden | {WEIGHTS['hidden']} | inverse official visibility (V0 = 1.0) |",
        f"| distinct | {WEIGHTS['distinct']} | how unusual the mention is for its host place |",
        f"| sentiment | {WEIGHTS['sentiment']} | mean sentiment of the mention sentences |",
        f"| recency | {WEIGHTS['recency']} | share of mentions in the last {RECENCY_WINDOW_YEARS} years |",
        "",
        "A term with no value for an entity is excluded and the remaining weights are",
        "renormalised, so a missing term never acts as a zero.",
        "",
    ]
    if not frame.empty:
        lines += [
            "## Ranked candidates",
            "",
            "| # | entity | score | vis | reviews | mentions | hidden | distinct | sentiment | recency |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for position, (_, row) in enumerate(frame.iterrows(), start=1):
            fmt = lambda v: "—" if pd.isna(v) else f"{v:.2f}"  # noqa: E731
            lines.append(
                f"| {position} | {row['canonical_name']} | **{fmt(row['gem_score'])}** | "
                f"{row['visibility']} | {row['n_reviews']} | {row['n_mentions']} | "
                f"{fmt(row['term_hidden'])} | {fmt(row['term_distinct'])} | "
                f"{fmt(row['term_sentiment'])} | {fmt(row['term_recency'])} |"
            )
        lines.append("")
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  candidates: {len(frame)} of {len(entities)}")
    if not frame.empty:
        print("\n  top candidates:")
        for _, row in frame.head(8).iterrows():
            print(f"    {row['gem_score']:.3f}  {row['visibility']:<4} {row['canonical_name']}")
    print(f"\n  wrote {out_csv.name}, {out_md.name}, {out_json.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
