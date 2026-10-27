"""Translation loss: the paired comparison of originals and Google's translations.

The measurement is only worth reporting if three things hold:

  1. The pairing is right: only reviews Google gave in two different versions,
     split into Bangla script and Banglish by what the reviewer actually typed.
  2. The comparison is fair: the same concept counts once whichever language
     names it (কটকা and Kotka), and English-only cue patterns are left out,
     since they could only ever fire on the translation.
  3. The statistics are honest: the interval and the significance test are
     computed, not assumed, and a recorded human judgement is never overwritten.

Run:
    .venv/bin/python scripts/test_translation_loss.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import translation_loss as tl  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []
DATA = REPO_ROOT / "data"


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def finder() -> tl.ConceptFinder:
    return tl.ConceptFinder(
        gazetteer=["Kotka", "Kuakata"],
        aliases={"কটকা": "Kotka"},
        lexicon=[("fuchka", "FOOD"), ("ফুচকা", "FOOD"), ("launch", "ACCESS"), ("লঞ্চ", "ACCESS")],
        equivalents={("FOOD", "fuchka"): "Fuchka", ("FOOD", "ফুচকা"): "Fuchka",
                     ("ACCESS", "launch"): "Launch", ("ACCESS", "লঞ্চ"): "Launch",
                     ("PLACE", "কটকা"): "Kotka"},
    )


def test_pairing() -> None:
    print("pairing")
    corpus = pd.DataFrame([
        {"review_id": "a", "original_language": "bn", "review_text_original": "কটকা খুব সুন্দর জায়গা",
         "review_text_clean": "Katka is a very beautiful place"},
        {"review_id": "b", "original_language": "bn", "review_text_original": "Onek onek sundor",
         "review_text_clean": "One piece one piece"},
        {"review_id": "c", "original_language": "bn", "review_text_original": "সুন্দর",
         "review_text_clean": "সুন্দর"},
        {"review_id": "d", "original_language": "en", "review_text_original": "Lovely",
         "review_text_clean": "Lovely beach"},
        {"review_id": "e", "original_language": "bn", "review_text_original": None,
         "review_text_clean": "Nice"},
    ])
    bangla, banglish = tl.paired_reviews(corpus)
    check("a Bangla review with a translation is a Bangla-script pair", list(bangla["review_id"]) == ["a"])
    check("a Banglish review with a translation is a Banglish pair", list(banglish["review_id"]) == ["b"])
    check("an untranslated review is not a pair", "c" not in set(bangla["review_id"]) | set(banglish["review_id"]))
    check("a non-Bangla review is not a pair", "d" not in set(bangla["review_id"]))


def test_comparison() -> None:
    print("\ncomparison")
    f = finder()
    check("a Bangla name and its English name are one concept",
          set(f.find("কটকা সৈকত")) == set(f.find("Kotka beach")) == {("PLACE", "kotka")})
    check("a Bangla and an English food are one concept",
          set(f.find("ফুচকা খেলাম")) == set(f.find("ate fuchka")) == {("FOOD", "fuchka")})
    check("English-only TIP cues are left out", not any(t == "TIP" for t, _ in f.find("Best time to visit is winter")))

    pairs = pd.DataFrame([
        {"review_id": "r1", "place_name": "Kuakata Sea Beach",
         "review_text_original": "কটকা যেতে লঞ্চ লাগে", "review_text_clean": "Katka needs a launch"},
        {"review_id": "r2", "place_name": "Somewhere",
         "review_text_original": "ফুচকা দারুণ", "review_text_clean": "The fuchka is great, near Kuakata"},
    ])
    rows = tl.compare(pairs, f).set_index(["review_id", "concept"])
    check("a respelled place is lost, and classed as respelled",
          rows.loc[("r1", "kotka"), "outcome"] == "lost_respelled", str(rows.loc[("r1", "kotka")].to_dict()))
    check("a concept in both versions is kept", rows.loc[("r1", "launch"), "outcome"] == "kept")
    check("a concept only in the translation is reported as such",
          rows.loc[("r2", "kuakata"), "outcome"] == "only_in_translation")
    check("only places can be respelled",
          tl.classify_loss("FOOD", "fuchka", "fuchka-like snack") == "translated_or_dropped")
    check("a name turned into a description is translated_or_dropped",
          tl.classify_loss("PLACE", "sada matir pahar", "the white clay hills are lovely") == "translated_or_dropped")
    check("the review's own place is marked, not counted as a discovery",
          rows.loc[("r1", "kotka"), "own_place"] == False)  # noqa: E712


def test_statistics() -> None:
    print("\nstatistics")
    check("Fisher exact matches a known value (R: fisher.test(matrix(c(3,1,1,3),2)) p=0.4857)",
          abs(tl.fisher_exact(3, 1, 1, 3) - 0.4857) < 0.001, str(tl.fisher_exact(3, 1, 1, 3)))
    check("Fisher exact is 1 for identical rows", abs(tl.fisher_exact(2, 2, 2, 2) - 1.0) < 1e-9)
    rows = pd.DataFrame({"review_id": ["a", "a", "b", "c"], "in_original": [True] * 4,
                         "in_translation": [True, False, True, False]})
    check("retention is the share of originals kept", tl.retention(rows) == 0.5)
    low, high = tl.bootstrap_interval(rows)
    check("the bootstrap interval contains the estimate", low <= 0.5 <= high, f"{low}-{high}")
    check("the bootstrap is reproducible", tl.bootstrap_interval(rows) == (low, high))


def test_judgements_kept() -> None:
    print("\nreviewed Banglish list")
    pairs = pd.DataFrame([
        {"review_id": "x", "place_name": "P", "review_text_original": "sei gorom", "review_text_clean": "six o'clock"},
        {"review_id": "y", "place_name": "P", "review_text_original": "Onek sundor", "review_text_clean": "One sundor"},
    ])
    existing = pd.DataFrame([{"review_id": "x", "place_name": "P", "original": "sei gorom",
                              "google_translation": "six o'clock", "judgement": "meaning_lost",
                              "reason": "means 'so hot'"}])
    merged = tl.merge_banglish(pairs, existing).set_index("review_id")
    check("a recorded judgement and its reason are kept",
          merged.loc["x", "judgement"] == "meaning_lost" and "so hot" in merged.loc["x", "reason"])
    check("a new pair starts as pending", merged.loc["y", "judgement"] == "pending")

    path = DATA / "banglish_translation_check.csv"
    if path.exists():
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        check("every judgement is a known value", set(frame["judgement"]) <= set(tl.BANGLISH_JUDGEMENTS),
              str(set(frame["judgement"])))
        decided = frame[frame["judgement"] != "pending"]
        check("every recorded judgement says why", decided["reason"].str.strip().ne("").all())


def test_real_outputs() -> None:
    print("\nthe real outputs")
    path = DATA / "translation_loss_pairs.csv"
    if not path.exists():
        check("translation loss has been run", False, "run scripts/translation_loss.py")
        return
    rows = pd.read_csv(path)
    check("only comparable types are reported", set(rows["entity_type"]) <= set(tl.COMPARED_TYPES))
    check("every row is found on at least one side", (rows["in_original"] | rows["in_translation"]).all())
    outcomes = {"kept", "lost_respelled", "lost_translated_or_dropped", "only_in_translation"}
    check("every outcome is a known value", set(rows["outcome"]) <= outcomes, str(set(rows["outcome"])))
    consistent = (
        ((rows["outcome"] == "kept") == (rows["in_original"] & rows["in_translation"]))
        & ((rows["outcome"] == "only_in_translation") == (~rows["in_original"] & rows["in_translation"]))
    )
    check("outcomes agree with the two flags", consistent.all())
    # Grounding: whatever was found in a version is really written in it.
    found = rows[rows["in_original"]]
    ungrounded = found[[str(s) not in str(t) for s, t in zip(found["original_surface"], found["original_text"])]]
    check("every surface found in an original is in that original", ungrounded.empty,
          str(ungrounded["concept"].tolist()[:3]))


def main() -> None:
    print("Translation loss tests\n")
    test_pairing()
    test_comparison()
    test_statistics()
    test_judgements_kept()
    test_real_outputs()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All translation loss tests passed.")


if __name__ == "__main__":
    main()
