"""Entity typing, Bangla place names and the food / activity lexicon.

Three changes made the gem engine read Bangla and stop ranking tips as gems, and
each has a way of quietly going wrong:

  1. Bangla word boundaries. Python's \\w does not cover Bengali vowel signs, so a
     naive boundary lets "আম" (mango) match inside "আমি" (I). A Bangla term may be
     followed only by a case ending ("ইলিশের"), and the ending is not stored.
  2. Bangla self-mentions. "বান্দরবান" in a review of Bandarban is the review
     talking about its own subject, exactly the bug that once made 51% of
     "discoveries" self-mentions. The own-place test must see through the script.
  3. Reviewed lists. Only `accept` rows are used, every `reject` carries a
     reason, and re-mining never overwrites a decision a person recorded.

It also checks the real outputs: only places are scored as gems, and every place
attribute carries a sentence from a real review.

Run:
    .venv/bin/python scripts/test_entity_typing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import extract_mentions as em  # noqa: E402
import mine_bangla_place_names as mine  # noqa: E402
import resolve_entities as res  # noqa: E402
from gem_schema import ATTRIBUTE_TYPES, ENTITY_TYPES, GEM_TYPES, term_pattern  # noqa: E402

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


def found(term: str, text: str) -> list[str]:
    return [m.group(0) for m in term_pattern(term).finditer(text)]


def test_boundaries() -> None:
    print("word boundaries")
    check("'আম' does not match inside 'আমি'", found("আম", "আমি গিয়েছিলাম") == [])
    check("'আম' does not match inside 'আমরা'", found("আম", "আমরা খেলাম") == [])
    check("'ইলিশ' matches 'ইলিশের', storing the stem only",
          found("ইলিশ", "পদ্মার ইলিশের স্বাদ") == ["ইলিশ"])
    check("'দই' does not match the particle in 'আনন্দই'", found("দই", "আনন্দই আলাদা") == [])
    check("'ডাব' does not match inside 'ডাবল'", found("ডাব", "ডাবল বেড") == [])
    check("a Bangla term followed by Latin punctuation matches", found("ডাব", "ডাব, ফুচকা") == ["ডাব"])
    check("an English plural matches, storing the singular",
          found("boat ride", "the boat rides were fun") == ["boat ride"])
    check("'corn' does not match inside 'corner'", found("corn", "the north west corner") == [])
    check("English matching ignores case", found("bbq", "BBQ on the beach") == ["BBQ"])
    check("'trek' does not match inside 'trekking'", found("trek", "trekking is hard") == [])


def test_extraction() -> None:
    print("\nextraction")
    aliases = {"বান্দরবান": "Bandarban"}
    lexicon = [("guava", "FOOD"), ("boat ride", "ACTIVITY")]
    gazetteer = ["Bandarban", "Nilgiri", "Bhimruli Floating Guava Market"]

    own = em.extract_gazetteer("বান্দরবানের নীলগিরি সুন্দর", "Bandarban", gazetteer, aliases, lexicon)
    check("a Bangla name of the review's own place is not a mention",
          not [c for c in own if c["entity_type"] == "PLACE"], str(own))

    other = em.extract_gazetteer("বান্দরবানের পথে", "Nilgiri", gazetteer, aliases, lexicon)
    check("the same Bangla name in another place's review is a mention",
          [c["surface"] for c in other if c["entity_type"] == "PLACE"] == ["বান্দরবান"], str(other))

    food = em.extract_gazetteer("Fresh guava everywhere", "Bhimruli Floating Guava Market",
                                gazetteer, aliases, lexicon)
    check("a food in a review of its own place is kept (an attribute, not a discovery)",
          [c["surface"] for c in food if c["entity_type"] == "FOOD"] == ["guava"], str(food))

    claimed = em.extract_gazetteer("We went to Bhimruli Floating Guava Market by boat ride",
                                   "Nilgiri", gazetteer, aliases, lexicon)
    types = sorted((c["entity_type"], c["surface"]) for c in claimed)
    check("a lexicon term inside a place name is not extracted twice",
          ("FOOD", "Guava") not in types and ("PLACE", "Bhimruli Floating Guava Market") in types, str(types))
    check("a lexicon term outside it still is", ("ACTIVITY", "boat ride") in types, str(types))


def test_mining() -> None:
    print("\nmining Bangla place names")
    mined = mine.mine(["আলুটিলায় গেলাম। আলুটিলা গুহা", "লোকাল বাস"], ["Alutila", "Lalakhal"])
    check("an inflected form is folded into its stem", ("আলুটিলা", "Alutila") in mined
          and not any(b != "আলুটিলা" and p == "Alutila" for b, p in mined), str(mined))
    check("the inflected and plain forms count as reviews, not occurrences",
          mined.get(("আলুটিলা", "Alutila")) == 1, str(mined))
    check("a key collision is still proposed (a person decides)", ("লোকাল", "Lalakhal") in mined)

    existing = pd.DataFrame([{"bangla": "লোকাল", "place": "Lalakhal", "reviews": 47,
                              "decision": "reject", "reason": "ordinary word: 'local'"}])
    merged = mine.merge_decisions({("লোকাল", "Lalakhal"): 50, ("আলুটিলা", "Alutila"): 3}, existing)
    row = merged.set_index("bangla").loc["লোকাল"]
    check("re-mining keeps a recorded decision and its reason",
          row["decision"] == "reject" and "local" in row["reason"], str(row.to_dict()))
    check("re-mining refreshes the count", int(row["reviews"]) == 50)
    check("a new candidate starts as pending",
          merged.set_index("bangla").loc["আলুটিলা", "decision"] == "pending")


def test_reviewed_lists() -> None:
    print("\nthe reviewed lists")
    for path, key in ((DATA / "place_names_bn.csv", "bangla"), (DATA / "food_activity_lexicon.csv", "surface")):
        if not path.exists():
            check(f"{path.name} exists", False)
            continue
        frame = pd.read_csv(path)
        check(f"{path.name}: every decision is accept, reject or pending",
              set(frame["decision"]) <= {"accept", "reject", "pending"}, str(set(frame["decision"])))
        rejects = frame[frame["decision"] == "reject"]
        check(f"{path.name}: every reject says why",
              rejects["reason"].fillna("").astype(str).str.strip().ne("").all(),
              str(rejects[rejects["reason"].isna()][key].tolist()))
        check(f"{path.name}: no spelling appears twice",
              not frame.duplicated(subset=[key] + (["place"] if "place" in frame else ["entity_type"])).any())

    lexicon = pd.read_csv(DATA / "food_activity_lexicon.csv")
    check("lexicon types are entity types and never PLACE",
          set(lexicon["entity_type"]) <= set(ATTRIBUTE_TYPES), str(set(lexicon["entity_type"])))
    check("an ambiguous Bangla word is rejected, not used ('পান' = get/drink)",
          lexicon.set_index("surface").loc["পান", "decision"] == "reject")

    loaded = dict(em.load_lexicon())
    check("only accepted lexicon rows are loaded", "পান" not in loaded and "ফুচকা" in loaded)
    names = em.load_bangla_names()
    check("only accepted Bangla names are loaded", "লোকাল" not in names and names.get("বান্দরবান") == "Bandarban")


def test_resolution() -> None:
    print("\nresolution")
    mentions = pd.DataFrame([
        {"review_id": "r1", "entity_type": "ACTIVITY", "surface": "boat ride", "phonetic_key": ""},
        {"review_id": "r2", "entity_type": "ACTIVITY", "surface": "নৌকা ভ্রমণ", "phonetic_key": ""},
        {"review_id": "r3", "entity_type": "ACTIVITY", "surface": "নৌকা ভ্রমণ", "phonetic_key": ""},
        {"review_id": "r4", "entity_type": "ACTIVITY", "surface": "swimming", "phonetic_key": ""},
    ])
    equivalents = {("ACTIVITY", "boat ride"): "Boat ride", ("ACTIVITY", "নৌকা ভ্রমণ"): "Boat ride"}
    groups = res.build_surface_groups(mentions, None, None, equivalents)
    clusters, _ = res.resolve(groups)
    together = [m for m in clusters.values() if "boat ride" in m]
    check("reviewed synonyms across scripts are one entity",
          together and "নৌকা ভ্রমণ" in together[0], str(clusters))
    check("an unrelated activity stays separate",
          any(m == ["swimming"] for m in clusters.values()), str(clusters))

    equivalents = res.load_equivalents()
    check("the real reviewed lists load as equivalences",
          equivalents.get(("PLACE", "বান্দরবান")) == "Bandarban"
          and equivalents.get(("FOOD", "ফুচকা")) == "Fuchka", str(len(equivalents)))


def test_real_outputs() -> None:
    print("\nthe real outputs")
    scores = DATA / "phase4_gem_scores.csv"
    if scores.exists():
        frame = pd.read_csv(scores)
        check("only places are ranked as gems",
              set(frame["entity_type"]) <= set(GEM_TYPES), str(set(frame["entity_type"])))
        check("'Best Time to Visit' is no longer a gem candidate",
              not frame["canonical_name"].str.lower().str.contains("best time").any())
    else:
        check("gem scores exist", False, "run scripts/score_gems.py")

    mentions = pd.read_csv(DATA / "phase4_mentions.csv")
    check("every mention type is a known entity type", set(mentions["entity_type"]) <= set(ENTITY_TYPES))
    check("foods are extracted", (mentions["entity_type"] == "FOOD").any())
    check("activities are extracted", (mentions["entity_type"] == "ACTIVITY").any())
    check("Bangla-script mentions are extracted",
          mentions["surface"].astype(str).str.contains(r"[ঀ-৿]").any())

    attributes = DATA / "phase4_place_attributes.csv"
    if attributes.exists():
        frame = pd.read_csv(attributes)
        corpus = pd.read_csv(DATA / "processed_reviews.csv", low_memory=False)
        texts = dict(zip(corpus["review_id"].astype(str),
                         corpus["review_text_original"].fillna(corpus["review_text_clean"]).astype(str)))
        check("no place attribute is a place", not (frame["entity_type"] == "PLACE").any())
        check("every attribute carries an example sentence",
              frame["example_sentence"].fillna("").str.strip().ne("").all())
        # Grounding, end to end: the quoted sentence's words are the reviewer's.
        # Sentences are whitespace-squeezed, so compare on squeezed text.
        squeeze = lambda s: " ".join(str(s).split())  # noqa: E731
        sample = frame.head(200)
        bad = [r["example_review_id"] for _, r in sample.iterrows()
               if squeeze(r["example_sentence"]) not in squeeze(texts.get(str(r["example_review_id"]), ""))]
        check("example sentences are found verbatim in their review", not bad, str(bad[:3]))
    else:
        check("place attributes exist", False, "run scripts/place_attributes.py")


def main() -> None:
    print("Entity typing tests (BUILD_PLAN 5.1, 5.2)\n")
    test_boundaries()
    test_extraction()
    test_mining()
    test_reviewed_lists()
    test_resolution()
    test_real_outputs()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All entity typing tests passed.")


if __name__ == "__main__":
    main()
