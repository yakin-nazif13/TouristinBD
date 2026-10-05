"""Entity resolution tests — BUILD_PLAN section 5.3.

Resolution is the step that decides how much evidence a candidate gem has, and
section 5.5 will not promote anything under 2-3 independent mentions. So both
directions matter and both are tested: failing to merge variants starves a real
gem, and merging two different places invents one.

  1. the metrics themselves (B-cubed, purity) against hand-computable cases —
     a metric that is wrong makes every later number wrong;
  2. the signals: phonetic token containment, the category-word rule, and
     geography voting *against* a merge;
  3. single-link clustering across a chain (A~B, B~C, so A~C), which is how
     the plan's Guliakhali / Guliyakhali / Gulyakhali group behaves;
  4. the merges that must not happen: different entity types, and the places
     whose names resemble each other across divisions;
  5. the real corpus, scored against data/entity_resolution_gold.csv.

Run:
    .venv/bin/python scripts/test_resolve_entities.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import resolve_entities as res  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def group(surface, phonetic, entity_type="PLACE", districts=(), divisions=(), mentions=1):
    return {
        "surface": surface,
        "entity_type": entity_type,
        "normalized": surface.lower(),
        "phonetic": phonetic,
        "mentions": mentions,
        "review_ids": set(),
        "districts": set(districts),
        "divisions": set(divisions),
        "languages": set(),
        "from_text": True,
    }


def test_metrics() -> None:
    print("the metrics (hand-computable cases)")
    perfect = {"a": 0, "b": 0, "c": 1}
    check("a perfect clustering scores 1.0",
          res.bcubed(perfect, perfect) == (1.0, 1.0, 1.0), str(res.bcubed(perfect, perfect)))
    check("and has purity 1.0", res.purity(perfect, perfect) == 1.0)

    # Everything in one cluster: recall is perfect, precision is not.
    lumped = {"a": 0, "b": 0, "c": 0}
    precision, recall, _ = res.bcubed(lumped, perfect)
    check("over-merging costs precision, not recall",
          precision < 1.0 and recall == 1.0, f"P={precision} R={recall}")

    # Everything separate: precision is perfect, recall is not.
    split = {"a": 0, "b": 1, "c": 2}
    precision, recall, _ = res.bcubed(split, perfect)
    check("over-splitting costs recall, not precision",
          precision == 1.0 and recall < 1.0, f"P={precision} R={recall}")

    # B-cubed recall is proportional, not superlinear: each item scores the
    # share of its gold group that landed in its own cluster. Splitting a group
    # in half gives 0.5 whatever the group's size, and splitting it into
    # singletons gives 1/size. Asserted exactly, since getting this wrong would
    # silently rescale every resolution number reported later.
    big_gold = {k: 0 for k in "abcd"}
    _, recall_halves, _ = res.bcubed({"a": 0, "b": 0, "c": 1, "d": 1}, big_gold)
    check("splitting a group in half gives recall 0.5",
          abs(recall_halves - 0.5) < 1e-9, str(recall_halves))
    _, recall_singletons, _ = res.bcubed({"a": 0, "b": 1, "c": 2, "d": 3}, big_gold)
    check("splitting it into singletons gives recall 1/size",
          abs(recall_singletons - 0.25) < 1e-9, str(recall_singletons))
    check("so a worse split scores lower", recall_singletons < recall_halves)

    check("no shared items gives NaN rather than a number",
          all(v != v for v in res.bcubed({"x": 0}, {"y": 0})), str(res.bcubed({"x": 0}, {"y": 0})))
    check("purity with no shared items is NaN", res.purity({"x": 0}, {"y": 0}) != res.purity({"x": 0}, {"y": 0}))


def test_official_form_rule() -> None:
    print("\nthe category-word rule (local vs official names)")
    check("kuakata / kuakata beach is an official pair",
          res._is_official_form("kuakata", "kuakata beach"))
    check("the order does not matter",
          res._is_official_form("kuakata beach", "kuakata"))
    check("jaflong / jaflong zero point is an official pair",
          res._is_official_form("jaflong", "jaflong zero point"))
    check("ratargul / ratargul swamp forest is an official pair",
          res._is_official_form("ratargul", "ratargul swamp forest"))
    # The negative that keeps the rule honest: an extra word that is not a
    # category word means the two names are two things.
    check("an extra non-category word is not an official pair",
          not res._is_official_form("kuakata", "kuakata fish market"),
          "'market' is a category word but 'fish' is not")
    check("identical names are not an official pair",
          not res._is_official_form("kuakata", "kuakata"))
    check("unrelated names are not an official pair",
          not res._is_official_form("kuakata", "jaflong"))
    check("an empty name is not an official pair", not res._is_official_form("", "kuakata"))


def test_signals() -> None:
    print("\nthe signals")
    # Exact phonetic match across scripts is the strongest single signal.
    a = group("Kuakata", "kkt", districts=["Patuakhali"])
    b = group("কুয়াকাটা", "kkt", districts=["Patuakhali"])
    score, signals = res.pair_score(a, b)
    check("a cross-script phonetic match is 1.0", signals["phonetic"] == 1.0, str(signals))
    check("string similarity is not-applicable across scripts, not zero",
          signals["string"] is None, str(signals))
    check("and the pair merges on phonetics alone", score >= res.MERGE_THRESHOLD, str(score))

    # But a cross-script match in a different district still must not merge:
    # two places can share a name.
    far = group("কুয়াকাটা", "kkt", districts=["Sylhet"])
    distant_score, _ = res.pair_score(a, far)
    check("a cross-script match in another district does not merge",
          distant_score < res.MERGE_THRESHOLD, str(distant_score))

    # Token containment gets partial credit, which is what makes the
    # local-vs-official pairs reachable at all.
    short = group("Kuakata", "kkt", districts=["Patuakhali"])
    official = group("Kuakata Beach", "kkt bc", districts=["Patuakhali"])
    score, signals = res.pair_score(short, official)
    check("phonetic token containment scores 0.75", signals["phonetic"] == 0.75, str(signals))
    check("the containment signal fires", signals["containment"] == 1.0, str(signals))
    check("the pair merges", score >= res.MERGE_THRESHOLD, str(score))

    # Geography voting against: similar names in different districts are
    # usually different places, so the signal is negative, not neutral.
    here = group("Mongla", "mngl", districts=["Bagerhat"])
    there = group("Mangal", "mngl", districts=["Sylhet"])
    _, signals = res.pair_score(here, there)
    check("different districts vote against a merge", signals["geography"] < 0, str(signals))

    check("same division but different district is weaker than same district",
          res.pair_score(
              group("X", "x", districts=["A"], divisions=["D"]),
              group("Y", "y", districts=["B"], divisions=["D"]),
          )[1]["geography"] == 0.6)

    # Weights are fixed and reported, like the gem score's.
    check("the weights sum to 1", abs(sum(res.WEIGHTS.values()) - 1.0) < 1e-9, str(res.WEIGHTS))


def test_clustering() -> None:
    print("\nclustering")
    # The plan's own chain: Gulyakhali is least like Guliakhali, but both are
    # like Guliyakhali, so single link must pull all three together.
    groups = {
        "Guliakhali": group("Guliakhali", "glkl", districts=["Chattogram"]),
        "Guliyakhali": group("Guliyakhali", "glkl", districts=["Chattogram"]),
        "Gulyakhali": group("Gulyakhali", "glkl", districts=["Chattogram"]),
    }
    clusters, pairs = res.resolve(groups)
    check("the three-spelling chain becomes one entity", len(clusters) == 1, str(clusters))

    # Entity types never merge: the kotkoti sweet and a shop named for it are
    # two different things.
    typed = {
        "kotkoti": group("kotkoti", "ktkt", entity_type="FOOD"),
        "Kotkoti": group("Kotkoti", "ktkt", entity_type="PLACE"),
    }
    clusters, _ = res.resolve(typed)
    check("different entity types never merge", len(clusters) == 2, str(clusters))

    # Unrelated places stay apart.
    apart = {
        "Kuakata": group("Kuakata", "kkt", districts=["Patuakhali"]),
        "Jaflong": group("Jaflong", "jflng", districts=["Sylhet"]),
    }
    clusters, _ = res.resolve(apart)
    check("unrelated places stay apart", len(clusters) == 2, str(clusters))

    check("a single surface yields a single entity",
          len(res.resolve({"X": group("X", "x")})[0]) == 1)
    check("no mentions yields no entities", res.resolve({})[0] == {})


def test_corpus_evaluation() -> None:
    print("\nagainst the real corpus and the gold variant groups")
    mentions_path = REPO_ROOT / "data" / "phase4_mentions.csv"
    if not mentions_path.exists():
        check("mentions artifact exists", False, "run scripts/extract_mentions.py")
        return

    mentions = pd.read_csv(mentions_path)
    corpus = pd.read_csv(REPO_ROOT / "data" / "processed_reviews.csv")
    geography = pd.read_csv(REPO_ROOT / "data" / "place_geography.csv")
    gold = pd.read_csv(REPO_ROOT / "data" / "entity_resolution_gold.csv")
    gold_map = dict(zip(gold["surface"].astype(str), gold["group_id"].astype(int)))

    groups = res.build_surface_groups(mentions, geography, corpus)
    check("the corpus's own place names are in the pool",
          "Kuakata Beach" in groups,
          "without them the local-vs-official case cannot be resolved at all")
    check("a place name carries no mentions of its own",
          groups["Kuakata Beach"]["mentions"] == 0,
          "a place having reviews is not its name being mentioned")

    clusters, _ = res.resolve(groups)
    evaluation = res.evaluate(clusters, gold_map)

    check("most gold surfaces are present to be scored",
          evaluation["gold_surfaces_present_in_corpus"] >= 30,
          str(evaluation["gold_surfaces_present_in_corpus"]))
    check("B-cubed F1 is above 0.9", evaluation["bcubed_f1"] > 0.9, str(evaluation["bcubed_f1"]))

    # The specific merges section 5.3 asks for, checked individually so a
    # regression names itself rather than moving an aggregate.
    assignment = {}
    for index, (_, members) in enumerate(sorted(clusters.items())):
        for member in members:
            assignment[member] = index

    for short, official in [
        ("Kuakata", "Kuakata Beach"),
        ("Jaflong", "Jaflong Zero Point"),
        ("Kaptai", "Kaptai Lake"),
        ("Ratargul", "Ratargul Swamp Forest"),
    ]:
        if short in assignment and official in assignment:
            check(f"{short} resolves to {official}",
                  assignment[short] == assignment[official],
                  f"{assignment[short]} vs {assignment[official]}")

    check("Guliakhali and Guliyakhali resolve together",
          assignment.get("Guliakhali") == assignment.get("Guliyakhali"),
          f"{assignment.get('Guliakhali')} vs {assignment.get('Guliyakhali')}")
    check("Srimangal and Sreemangal resolve together",
          assignment.get("Srimangal") == assignment.get("Sreemangal"),
          f"{assignment.get('Srimangal')} vs {assignment.get('Sreemangal')}")

    # Containment is not equivalence: Karamjal sits inside the Sundarbans but
    # is its own site, and merging them would hide it from the register.
    check("Karamjal does not absorb into Sundarbans",
          assignment.get("Karamjal") != assignment.get("Sundarbans"),
          f"{assignment.get('Karamjal')} vs {assignment.get('Sundarbans')}")
    check("Mongla stays separate from everything else",
          sum(1 for s, c in assignment.items() if c == assignment.get("Mongla")) == 1,
          "Mongla merged with something")


def main() -> None:
    print("Entity resolution tests (BUILD_PLAN 5.3)\n")
    test_metrics()
    test_official_form_rule()
    test_signals()
    test_clustering()
    test_corpus_evaluation()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All entity resolution tests passed.")


if __name__ == "__main__":
    main()
