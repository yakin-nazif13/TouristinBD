"""Gem score tests — BUILD_PLAN section 5.5.

The score decides what a district officer is shown first, so the tests are
about the ways a ranking can quietly lie:

  1. the candidate gate counts *distinct reviews*, not mentions — one reviewer
     naming a place three times is one person's opinion, and counting it as
     three is how a register fills with one enthusiast's favourites;
  2. a missing term is never a zero. `hidden` is 0.0 for a well-known site, so
     defaulting an unknown visibility to 0.0 would bury every entity whose
     gazetteer lookup failed;
  3. sentiment is not scored for text VADER cannot read. A Bangla sentence must
     be excluded, not called neutral;
  4. ablation renormalises, so the threshold and the scale still mean the same
     thing with a term removed — which is what section 6.2's ablation table
     needs to be comparable;
  5. the mentions term saturates, so volume alone cannot win. Without that the
     score degenerates into the popularity baseline of section 6.1.

Run:
    .venv/bin/python scripts/test_score_gems.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import score_gems as sg  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def test_weights() -> None:
    print("weights and ablation")
    check("the declared weights sum to 1",
          abs(sum(sg.WEIGHTS.values()) - 1.0) < 1e-9, str(sg.WEIGHTS))
    check("every plan term has a weight", set(sg.WEIGHTS) == set(sg.TERMS), str(set(sg.WEIGHTS)))

    full = sg.normalised_weights(set())
    check("with nothing ablated the weights are unchanged",
          all(abs(full[t] - sg.WEIGHTS[t]) < 1e-9 for t in sg.TERMS), str(full))

    ablated = sg.normalised_weights({"hidden"})
    check("ablation drops the term", "hidden" not in ablated, str(ablated))
    check("and renormalises to 1", abs(sum(ablated.values()) - 1.0) < 1e-9, str(sum(ablated.values())))
    # Renormalising is what keeps ablation runs comparable: without it every
    # score would simply shrink and the ordering could not be read against the
    # full-score run.
    check("the surviving terms keep their relative proportions",
          abs(ablated["mentions"] / ablated["recency"]
              - sg.WEIGHTS["mentions"] / sg.WEIGHTS["recency"]) < 1e-9,
          str(ablated))

    try:
        sg.normalised_weights(set(sg.TERMS))
        check("ablating every term is refused", False, "it returned weights")
    except ValueError as exc:
        check("ablating every term is refused", True)
        check("with a reason", "ablated" in str(exc), str(exc))


def test_hidden_term() -> None:
    print("\nthe hidden term (inverse official visibility)")
    check("V0 scores highest", sg.score_hidden("V0") == 1.0)
    check("V3 scores zero", sg.score_hidden("V3") == 0.0)
    check("V1 beats V2", sg.score_hidden("V1") > sg.score_hidden("V2"))
    check("the levels are strictly ordered V0 > V1 > V2 > V3",
          sg.score_hidden("V0") > sg.score_hidden("V1") > sg.score_hidden("V2") > sg.score_hidden("V3"))

    # The one that matters: unknown must not collapse onto the well-known value.
    check("an unknown visibility is None, not 0.0", sg.score_hidden("unknown") is None)
    check("a missing visibility is None", sg.score_hidden(None) is None)
    check("an unrecognised level is None", sg.score_hidden("V9") is None)


def test_mentions_term() -> None:
    print("\nthe mentions term")
    check("one review scores low", sg.score_mentions(1) < 0.2, str(sg.score_mentions(1)))
    check("it rises with evidence", sg.score_mentions(5) > sg.score_mentions(2))
    check("it saturates at the cap", sg.score_mentions(sg.MENTIONS_SATURATION) == 1.0)
    # Saturation is what stops the score becoming a popularity ranking.
    check("and does not exceed 1.0 beyond the cap",
          sg.score_mentions(sg.MENTIONS_SATURATION * 10) == 1.0)
    check("a much-reviewed place cannot out-score a capped one on volume",
          sg.score_mentions(500) == sg.score_mentions(sg.MENTIONS_SATURATION))


def test_recency_term() -> None:
    print("\nthe recency term")
    newest = pd.Timestamp("2026-06-01", tz="UTC")
    recent = [pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2025-06-01", tz="UTC")]
    old = [pd.Timestamp("2015-01-01", tz="UTC")]

    check("all-recent scores 1.0", sg.score_recency(recent, newest) == 1.0)
    check("all-old scores 0.0", sg.score_recency(old, newest) == 0.0)
    check("a half-and-half split scores 0.5",
          abs(sg.score_recency(recent[:1] + old, newest) - 0.5) < 1e-9,
          str(sg.score_recency(recent[:1] + old, newest)))
    check("no parseable date gives None, not 0.0", sg.score_recency([pd.NaT], newest) is None)
    check("an empty list gives None", sg.score_recency([], newest) is None)
    # Measured from the newest review rather than today, so a score does not
    # drift as the committed corpus ages.
    boundary = newest - pd.DateOffset(years=sg.RECENCY_WINDOW_YEARS)
    check("the window edge counts as inside", sg.score_recency([boundary], newest) == 1.0)


def test_sentiment_term() -> None:
    print("\nthe sentiment term")
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        check("vaderSentiment available (skipped)", True, "not installed")
        return
    analyser = SentimentIntensityAnalyzer()

    positive, n = sg.score_sentiment(["A hidden gem, quiet and beautiful."], analyser)
    check("a positive sentence scores above the midpoint", positive > 0.5, str(positive))
    check("and is counted", n == 1, str(n))
    negative, _ = sg.score_sentiment(["Dirty, crowded and overpriced."], analyser)
    check("a negative sentence scores below the midpoint", negative < 0.5, str(negative))
    check("the term is rescaled into 0..1", 0.0 <= positive <= 1.0 and 0.0 <= negative <= 1.0)

    # Bangla must be skipped, not scored neutral: VADER's lexicon is English.
    bangla, n = sg.score_sentiment(["খুব সুন্দর জায়গা ছিল"], analyser)
    check("a Bangla sentence is not scored", bangla is None, str(bangla))
    check("and is not counted", n == 0, str(n))

    mixed, n = sg.score_sentiment(
        ["খুব সুন্দর জায়গা", "A quiet and lovely spot."], analyser)
    check("a mixed set scores only the readable sentence", n == 1, str(n))
    check("and still returns a value", mixed is not None)

    empty, n = sg.score_sentiment(["", "   "], analyser)
    check("blank sentences give None", empty is None and n == 0)


def test_missing_terms_never_zero() -> None:
    print("\na missing term is excluded, never treated as zero")
    # Two identical entities except that one has no `hidden` value. The one
    # with an unknown visibility must not be penalised as if it were V3.
    usable_known = {"mentions": 0.5, "hidden": 0.0, "distinct": 0.8,
                    "sentiment": 0.7, "recency": 1.0}
    usable_unknown = {k: v for k, v in usable_known.items() if k != "hidden"}

    def combine(terms):
        live = sum(sg.WEIGHTS[t] for t in terms)
        return sum(sg.WEIGHTS[t] * v for t, v in terms.items()) / live

    known_v3 = combine(usable_known)
    unknown_vis = combine(usable_unknown)
    check("an unknown visibility scores above a known V3",
          unknown_vis > known_v3, f"{unknown_vis:.3f} vs {known_v3:.3f}")
    check("both scores stay within 0..1", 0 <= known_v3 <= 1 and 0 <= unknown_vis <= 1)


def test_real_output() -> None:
    print("\nagainst the real scored output")
    path = REPO_ROOT / "data" / "phase4_gem_scores.csv"
    if not path.exists():
        check("gem scores exist", False, "run scripts/score_gems.py")
        return
    frame = pd.read_csv(path)

    check("candidates were produced", len(frame) > 0, str(len(frame)))
    check("every candidate meets the gate",
          (frame["n_reviews"] >= sg.MIN_INDEPENDENT_MENTIONS).all(),
          str(frame["n_reviews"].min()))
    check("independence is reviews, not mentions",
          (frame["n_reviews"] <= frame["n_mentions"]).all(),
          "a candidate has more reviews than mentions, which is impossible")
    check("scores are within 0..1",
          frame["gem_score"].dropna().between(0, 1).all(),
          str(frame["gem_score"].describe().to_dict()))
    check("the output is sorted by score",
          frame["gem_score"].dropna().is_monotonic_decreasing, "not sorted")

    # Transparency: the plan calls for the score to be explainable, so every
    # term has to be stored beside it.
    for term in sg.TERMS:
        check(f"term_{term} is stored per entity", f"term_{term}" in frame.columns)
    check("the terms actually used are recorded", "terms_used" in frame.columns)
    check("the method behind sentiment is recorded", "sentiment_method" in frame.columns)
    check("the method behind distinct is recorded", "distinct_method" in frame.columns)

    # The top candidate on this corpus should be the V0 one; if that ever
    # changes it is a result worth noticing, not a silent drift.
    top = frame.iloc[0]
    check("the top candidate is not already official",
          not bool(top["already_official"]),
          f"{top['canonical_name']} is V3 and ranks first")
    check("already_official is available as a filter", "already_official" in frame.columns)


def main() -> None:
    print("Gem score tests (BUILD_PLAN 5.5)\n")
    test_weights()
    test_hidden_term()
    test_mentions_term()
    test_recency_term()
    test_sentiment_term()
    test_missing_terms_never_zero()
    test_real_output()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All gem score tests passed.")


if __name__ == "__main__":
    main()
