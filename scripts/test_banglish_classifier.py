"""Banglish classifier tests — BUILD_PLAN section 4.1.

What matters here is less the accuracy (which depends on hand labels that do
not exist yet) than the refusals. A classifier trained on one class still
"trains" in scikit-learn and still reports an F1, and that number reaching a
paper would be worse than having no classifier at all. So the suite checks:

  1. a single-class dataset is refused, with a message naming the reason;
  2. a class with one example is refused, because cross-validation cannot
     estimate F1 from it;
  3. a two-class dataset trains, cross-validates and round-trips through disk;
  4. the trained model plugs into language_id.classify and changes its verdict
     from the heuristic's — the whole point of training it;
  5. tie votes between annotators are dropped rather than resolved;
  6. the pool builder is deterministic and never includes Bangla-script text.

The training texts below are romanised Bangla and English written for the test.
They are *not* a substitute for section 4.1's 500 hand labels and are never
written into data/ — read_labels only ever reads the annotators' own files.

Run:
    .venv/bin/python scripts/test_banglish_classifier.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import banglish_classifier as bc  # noqa: E402
from language_id import BANGLISH_MARKERS, classify  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []

BANGLISH = [
    "khub sundor jayga ami onek valo laglo",
    "amader hotel ta onek bhalo chilo",
    "ei jaygay onek manush ase prottidin",
    "kuakata theke boat niye jete hoy",
    "amar mone hoy ei jayga ta sob cheye sundor",
    "sokale gelam onek bhalo lagche dekhte",
    "ekta chotto dukan ache sekhane kheyechi",
    "tomar jonno ei jayga ta valo hobe",
]
ENGLISH = [
    "the sunset view from the beach was absolutely stunning",
    "clean rooms and the staff were very helpful during our stay",
    "we walked along the shore for hours and enjoyed the breeze",
    "the entry gate and the old architecture were really attractive",
    "good value for money but the breakfast was disappointing",
    "a must visit place for anyone interested in history",
    "the boat ride through the forest was the highlight of the trip",
    "parking was difficult and the crowd was overwhelming",
]


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def test_refusals() -> None:
    print("refusals (the numbers that must never reach a paper)")

    try:
        bc.train(ENGLISH, ["english"] * len(ENGLISH))
        check("a single-class dataset is refused", False, "it trained anyway")
    except bc.NotEnoughLabels as exc:
        check("a single-class dataset is refused", True)
        check("the refusal names the one class present", "english" in str(exc), str(exc)[:120])
        check("the refusal points at the YouTube pass", "YouTube" in str(exc), str(exc)[:160])

    try:
        bc.train(ENGLISH[:4] + BANGLISH[:1], ["english"] * 4 + ["banglish"])
        check("a class with one example is refused", False, "it trained anyway")
    except bc.NotEnoughLabels as exc:
        check("a class with one example is refused", True)
        check("the refusal explains cross-validation", "F1" in str(exc), str(exc)[:160])


def test_training() -> None:
    print("\ntraining on two classes")
    texts = BANGLISH + ENGLISH
    labels = ["banglish"] * len(BANGLISH) + ["english"] * len(ENGLISH)
    model, result = bc.train(texts, labels, annotators=["tester"])

    check("both classes are recorded", result.classes == ["banglish", "english"], str(result.classes))
    check("the label count is reported", result.n_labels == len(texts), str(result.n_labels))
    check("F1 is an out-of-fold estimate, not 1.0 by construction",
          0.0 <= result.macro_f1 <= 1.0, str(result.macro_f1))
    check("the fold count is recorded", result.n_folds >= 2, str(result.n_folds))
    check("falling short of 500 is flagged", result.as_dict()["meets_target"] is False)
    check("the annotator is recorded", result.annotators == ["tester"], str(result.annotators))

    is_banglish, confidence = model.predict_one("khub bhalo jayga ami gelam")
    check("the model calls romanised Bangla Banglish", is_banglish, f"confidence={confidence:.3f}")
    is_banglish_en, _ = model.predict_one("the room was clean and the staff were helpful")
    check("the model calls English English", not is_banglish_en)

    tmp = Path(tempfile.mkdtemp(prefix="banglish_"))
    try:
        path = model.save(tmp / "model.pkl")
        reloaded = bc.load_model(path)
        check("the model round-trips through disk", reloaded is not None)
        check("a reloaded model agrees with the original",
              reloaded.predict_one("khub bhalo jayga ami gelam")[0] is True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    check("a missing model file loads as None",
          bc.load_model(Path("does-not-exist.pkl")) is None)


def test_plugs_into_classify() -> None:
    print("\nthe trained model drives language_id.classify")
    texts = BANGLISH + ENGLISH
    labels = ["banglish"] * len(BANGLISH) + ["english"] * len(ENGLISH)
    model, _ = bc.train(texts, labels)

    # Romanised Bangla containing none of the heuristic's marker words. The
    # heuristic has nothing to fire on and gets it wrong; the classifier reads
    # character n-grams and gets it right. This is precisely why section 4.1
    # asks for a trained model rather than a word list.
    unseen = "dokane cha kheyechilam dam besi"
    check("the probe sentence really is marker-free",
          not any(w in BANGLISH_MARKERS for w in unseen.split()),
          str([w for w in unseen.split() if w in BANGLISH_MARKERS]))
    heuristic = classify(unseen)
    trained = classify(unseen, banglish=model)
    check("the heuristic misses an unmarked Banglish sentence",
          heuristic.label != "bn-latn", f"{heuristic.label} via {heuristic.method}")
    check("the trained classifier catches it",
          trained.label == "bn-latn", f"{trained.label} via {trained.method}")
    check("the method is recorded as classifier", trained.method == "classifier", trained.method)

    # Script must still win: a model is never allowed to overrule Bangla script.
    check("Bangla script still wins over the classifier",
          classify("গিজার কাজ করে না", banglish=model).label == "bn")


def test_consensus() -> None:
    print("\nreading labels from several annotators")
    tmp = Path(tempfile.mkdtemp(prefix="banglish_labels_"))
    try:
        labels_dir = tmp / "banglish_labels"
        labels_dir.mkdir(parents=True)
        pd.DataFrame({"text": ["a", "b", "c"], "label": ["banglish", "english", "banglish"]}).to_csv(
            labels_dir / "labels_one.csv", index=False)
        pd.DataFrame({"text": ["a", "b", "c"], "label": ["banglish", "banglish", "english"]}).to_csv(
            labels_dir / "labels_two.csv", index=False)

        texts, labels, annotators = bc.read_labels(labels_dir)
        pairs = dict(zip(texts, labels))
        check("both annotators are found", annotators == ["one", "two"], str(annotators))
        check("an agreed label survives", pairs.get("a") == "banglish", str(pairs))
        # b is english/banglish and c is banglish/english: both 1-1 ties.
        check("tied votes are dropped, not resolved", "b" not in pairs and "c" not in pairs, str(pairs))
        check("an invalid label is ignored", bc.read_labels(tmp / "nope") == ([], [], []))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pool_builder() -> None:
    print("\nthe shared pool")
    tmp = Path(tempfile.mkdtemp(prefix="banglish_pool_"))
    try:
        data = tmp / "data"
        data.mkdir()
        shutil.copy(REPO_ROOT / "data" / "processed_reviews.csv", data / "processed_reviews.csv")
        os.environ["TOURISTINBD_DATA_DIR"] = str(data)

        import importlib

        import label_banglish_sample as lbs
        importlib.reload(lbs)

        check("the pool builds", lbs.build_pool() == 0)
        first = pd.read_csv(data / "banglish_pool.csv")
        check("the pool is non-empty", len(first) > 0, str(len(first)))
        check("the pool spans many places", first["place_name"].nunique() > 10,
              str(first["place_name"].nunique()))
        check("short texts are excluded",
              first["text"].str.len().min() >= lbs.MIN_CHARS, str(first["text"].str.len().min()))
        check("no duplicate texts", first["text"].duplicated().sum() == 0)

        # Bangla-script rows must not be in a pool whose question is
        # "Banglish or English?" — script already answers that.
        from language_id import script_shares
        bengali_rows = sum(1 for t in first["text"] if script_shares(t)[0] > 0.2)
        check("no Bangla-script text is in the pool", bengali_rows == 0, str(bengali_rows))

        lbs.build_pool()
        second = pd.read_csv(data / "banglish_pool.csv")
        check("the pool is deterministic across runs", first.equals(second))
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    print("Banglish classifier tests (BUILD_PLAN 4.1)\n")
    test_refusals()
    test_training()
    test_plugs_into_classify()
    test_consensus()
    test_pool_builder()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Banglish classifier tests passed.")


if __name__ == "__main__":
    main()
