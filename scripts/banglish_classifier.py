"""Banglish classifier — BUILD_PLAN section 4.1.

    "Banglish classifier: hand-label about 500 Latin-script texts (mostly from
     YouTube) as Banglish/English/mixed. Train a character 1-4-gram TF-IDF +
     logistic regression. Report its F1. The labelled set becomes part of the
     released dataset."

Character n-grams rather than words because romanised Bangla has no fixed
spelling: "bhalo"/"valo"/"balo" are the same word, and a word-level model would
treat them as three unrelated features. Character 1-4-grams share the substrings.

The labels come from `scripts/label_banglish_sample.py`, which writes
`data/banglish_labels/labels_<annotator>.csv`. **That file is the human input
this module waits on**, and nothing here fabricates it:

* `train` refuses a single-class dataset rather than producing a model that
  always answers the same thing and an F1 that looks like a result.
* `language_id.classify` falls back to a transparent lexicon heuristic when no
  model has been trained, so the pipeline runs end to end today and the
  fallback is visible in the `language_method` column rather than being passed
  off as a classifier decision.

The corpus currently has no Banglish at all (Google served translated English),
so the pool to label arrives with the YouTube pass in Phase 2. Until then this
trains and tests on whatever labels exist and reports honestly that it cannot.

Run:
    .venv/bin/python scripts/banglish_classifier.py --train
    .venv/bin/python scripts/banglish_classifier.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

LABELS_DIR = DATA_DIR / "banglish_labels"
MODEL_PATH = DATA_DIR / "banglish_classifier.pkl"
REPORT_JSON = DATA_DIR / "phase3_banglish_classifier_report.json"
REPORT_MD = DATA_DIR / "phase3_banglish_classifier_report.md"

# The three classes section 4.1 names.
CLASSES = ["banglish", "english", "mixed"]

# Section 4.1's "about 500". Training on fewer is allowed — it simply reports
# the count so the paper does not overstate it.
TARGET_LABELS = 500

SEED = 42


@dataclass
class TrainingResult:
    """What a training run produced, so it can be reported without re-running."""

    n_labels: int
    classes: list[str]
    macro_f1: float
    per_class: dict[str, dict[str, float]]
    confusion: list[list[int]]
    n_folds: int
    annotators: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "n_labels": self.n_labels,
            "classes": self.classes,
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {
                k: {m: round(v, 4) for m, v in scores.items()}
                for k, scores in self.per_class.items()
            },
            "confusion": self.confusion,
            "n_folds": self.n_folds,
            "annotators": self.annotators,
            "target_labels": TARGET_LABELS,
            "meets_target": self.n_labels >= TARGET_LABELS,
        }


class BanglishModel:
    """A fitted pipeline plus the interface `language_id.classify` expects."""

    def __init__(self, pipeline, classes: list[str]):
        self.pipeline = pipeline
        self.classes = classes

    def predict_one(self, text: str) -> tuple[bool, float]:
        """(is_banglish, confidence) for one text.

        `mixed` counts as Banglish here: both mean the reviewer was writing
        romanised Bangla, and `classify` makes the final mixed-vs-bn-latn call
        itself by looking for an English clause. Keeping that decision in one
        place stops the two disagreeing.
        """
        probabilities = self.pipeline.predict_proba([text])[0]
        by_class = dict(zip(self.pipeline.classes_, probabilities))
        banglish_p = float(by_class.get("banglish", 0.0) + by_class.get("mixed", 0.0))
        # Plain bool, not numpy.bool_: callers and tests compare with `is True`,
        # which a numpy scalar fails even when it is truthy.
        return bool(banglish_p >= 0.5), banglish_p

    def predict(self, texts: list[str]) -> list[str]:
        return list(self.pipeline.predict(texts))

    def save(self, path: Path = MODEL_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump({"pipeline": self.pipeline, "classes": self.classes}, handle)
        return path


def load_model(path: Path = MODEL_PATH) -> BanglishModel | None:
    """Load the trained classifier, or None when it has not been trained yet.

    Returns None rather than raising: a pipeline run before the hand labels
    exist must still work, with the fallback recorded in `language_method`.
    """
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            blob = pickle.load(handle)
        return BanglishModel(blob["pipeline"], blob["classes"])
    except Exception:
        return None


def read_labels(labels_dir: Path = LABELS_DIR):
    """Every annotator's Banglish labels, as (texts, labels, annotators).

    Where annotators disagree the majority wins and ties are dropped, matching
    how compute_human_agreement.py treats the Phase 5 sample: a tie is not a
    label and inventing one would hide the disagreement.
    """
    import pandas as pd

    if not labels_dir.exists():
        return [], [], []

    frames = []
    annotators = []
    for path in sorted(labels_dir.glob("labels_*.csv")):
        try:
            frame = pd.read_csv(path)
        except (ValueError, pd.errors.EmptyDataError):
            continue
        if not {"text", "label"} <= set(frame.columns):
            continue
        frame = frame[frame["label"].astype("string").str.strip().isin(CLASSES)]
        if frame.empty:
            continue
        frames.append(frame[["text", "label"]])
        annotators.append(path.stem.replace("labels_", ""))

    if not frames:
        return [], [], []

    combined = pd.concat(frames, ignore_index=True)
    consensus = []
    for text, group in combined.groupby("text", sort=True):
        counts = group["label"].value_counts()
        if len(counts) > 1 and counts.iloc[0] == counts.iloc[1]:
            continue  # tie: no consensus label
        consensus.append((text, counts.index[0]))

    texts = [t for t, _ in consensus]
    labels = [label for _, label in consensus]
    return texts, labels, annotators


def build_pipeline():
    """Character 1-4-gram TF-IDF + logistic regression, as section 4.1 specifies."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(1, 4),
            min_df=1,
            sublinear_tf=True,
            lowercase=True,
        )),
        ("clf", LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=SEED,
        )),
    ])


class NotEnoughLabels(RuntimeError):
    """Raised instead of training a model that cannot mean anything."""


def train(texts: list[str], labels: list[str], annotators: list[str] | None = None):
    """Fit the classifier and cross-validate it. Returns (model, TrainingResult).

    Raises NotEnoughLabels when the data cannot support a model: fewer than two
    classes, or fewer than two examples of some class. Both would still "train"
    in scikit-learn and produce an F1, which is exactly the number that must
    not reach a paper.
    """
    import numpy as np
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    present = sorted(set(labels))
    if len(present) < 2:
        raise NotEnoughLabels(
            f"only one class present ({present or 'none'}). A classifier needs at "
            f"least two of {CLASSES}. The corpus has no Banglish yet — the pool to "
            f"label arrives with the YouTube pass (BUILD_PLAN 3.3a)."
        )
    counts = {c: labels.count(c) for c in present}
    too_few = {c: n for c, n in counts.items() if n < 2}
    if too_few:
        raise NotEnoughLabels(
            f"these classes have fewer than 2 examples: {too_few}. "
            f"Cross-validation cannot estimate F1 from that."
        )

    n_folds = max(2, min(5, min(counts.values())))
    pipeline = build_pipeline()
    predicted = cross_val_predict(
        pipeline, texts, labels,
        cv=StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=SEED),
    )
    report = classification_report(labels, predicted, output_dict=True, zero_division=0)
    matrix = confusion_matrix(labels, predicted, labels=present)

    # Fit on everything for the model that actually gets used; the F1 above is
    # the out-of-fold estimate, not this fit's training score.
    pipeline.fit(texts, labels)

    result = TrainingResult(
        n_labels=len(texts),
        classes=present,
        macro_f1=float(report["macro avg"]["f1-score"]),
        per_class={
            c: {
                "precision": float(report[c]["precision"]),
                "recall": float(report[c]["recall"]),
                "f1": float(report[c]["f1-score"]),
                "support": float(report[c]["support"]),
            }
            for c in present if c in report
        },
        confusion=np.asarray(matrix).tolist(),
        n_folds=n_folds,
        annotators=sorted(annotators or []),
    )
    return BanglishModel(pipeline, present), result


def write_report(result: TrainingResult) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 3 — Banglish classifier",
        "",
        "Character 1-4-gram TF-IDF + logistic regression (BUILD_PLAN 4.1).",
        f"F1 is the out-of-fold estimate from {result.n_folds}-fold stratified",
        "cross-validation, not a training score.",
        "",
        f"- Labelled texts: **{result.n_labels}** (section 4.1 asks for about {TARGET_LABELS})",
        f"- Annotators: {', '.join(result.annotators) or 'none recorded'}",
        f"- Classes present: {', '.join(result.classes)}",
        f"- **Macro F1: {result.macro_f1:.3f}**",
        "",
        "| class | precision | recall | F1 | support |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, scores in result.per_class.items():
        lines.append(
            f"| {name} | {scores['precision']:.3f} | {scores['recall']:.3f} | "
            f"{scores['f1']:.3f} | {int(scores['support'])} |"
        )
    if result.n_labels < TARGET_LABELS:
        lines += [
            "",
            f"> Fewer than {TARGET_LABELS} labels, so treat this F1 as provisional. "
            "Report the label count beside it in any write-up.",
        ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", action="store_true", help="train from data/banglish_labels/ and save the model")
    parser.add_argument("--report", action="store_true", help="show the last training report")
    args = parser.parse_args()

    if args.report and not args.train:
        if REPORT_MD.exists():
            print(REPORT_MD.read_text(encoding="utf-8"))
            return 0
        print(f"no report yet at {REPORT_MD}; run with --train first")
        return 1

    texts, labels, annotators = read_labels()
    print(f"Banglish classifier — {len(texts)} consensus label(s) from {len(annotators)} annotator(s)")
    if not texts:
        print(
            f"\nNothing to train on yet. {LABELS_DIR} holds no usable labels.\n"
            "  1. build a pool:   python scripts/label_banglish_sample.py --build-pool\n"
            "  2. label it:       python scripts/label_banglish_sample.py --annotator <name>\n"
            "\nThe corpus currently contains no Banglish (Google served translated\n"
            "English), so the pool worth labelling arrives with the YouTube pass\n"
            "(BUILD_PLAN 3.3a). Until a model exists, language_id falls back to a\n"
            "lexicon heuristic and records `heuristic` in language_method."
        )
        return 1

    try:
        model, result = train(texts, labels, annotators)
    except NotEnoughLabels as exc:
        print(f"\ncannot train: {exc}")
        return 1

    path = model.save()
    write_report(result)
    print(f"  classes: {result.classes}")
    print(f"  macro F1 ({result.n_folds}-fold): {result.macro_f1:.3f}")
    print(f"  model:  {path}")
    print(f"  report: {REPORT_MD}")
    if result.n_labels < TARGET_LABELS:
        print(f"  note: {result.n_labels} labels, section 4.1 asks for about {TARGET_LABELS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
