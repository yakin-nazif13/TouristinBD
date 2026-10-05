"""Phase 3 — the language pipeline. BUILD_PLAN sections 4.1 and 4.2.

Labels every review with the four-way vocabulary, normalises its Bangla and
derives a phonetic matching key, then writes one artifact the later phases join
on:

    data/phase3_language_labels.csv
        review_id, language_label, language_confidence, language_method,
        detected_iso, text_basis, text_normalized, phonetic_key

Why a separate artifact instead of new columns in processed_reviews.csv:

* Phase 2's output is asserted byte for byte by test_phase2_preprocessing, and
  that reproduction check is worth more than the convenience of one wide file.
* It matches how Phase 3's topic step already behaves (reviews_with_topics.csv
  is a separate file), so the pipeline keeps one shape.
* Re-running this phase cannot corrupt the corpus it reads.

`text_basis` records which text was labelled — the reviewer's own words when
Phase 2 kept them (`original`), otherwise the analysis text (`clean`). Section
4.4 requires the original wherever it exists, and recording the fallback keeps
the language-mix table honest about which rows are really translations.

Human input this phase waits on, both clearly isolated:

* `data/banglish_labels/labels_*.csv` trains the classifier (section 4.1's 500
  hand labels). Without it the four-way label still runs, with a lexicon
  heuristic recorded as `heuristic` in `language_method`.
* `data/language_label_overrides.csv` (review_id, language_label) lets a human
  correct any individual row without touching code, like Phase 2's
  language_overrides.csv.

Run:
    .venv/bin/python scripts/run_phase3_language_pipeline.py
    .venv/bin/python scripts/run_phase3_language_pipeline.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banglish_classifier import load_model  # noqa: E402
from language_id import LABELS, classify, normalize_bangla, phonetic_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
OUT_CSV = DATA_DIR / "phase3_language_labels.csv"
OUT_REPORT_MD = DATA_DIR / "phase3_language_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase3_language_report.json"
OVERRIDES_CSV = DATA_DIR / "language_label_overrides.csv"
FASTTEXT_MODEL = DATA_DIR / "lid.176.ftz"

OUTPUT_COLUMNS = [
    "review_id",
    "language_label",
    "language_confidence",
    "language_method",
    "detected_iso",
    "text_basis",
    "text_normalized",
    "place_phonetic_key",
]


def _langdetect_fn():
    """Seeded langdetect returning (iso, probability), or None if unavailable.

    Seeded for the same reason Phase 2 does it: langdetect is probabilistic and
    an unseeded run gives one review two different languages on two runs.

    `detect_langs` rather than `detect` so the row carries a real probability.
    With `detect` the artifact had no confidence to record, and filling the gap
    with the Latin-script share reported 1.0 for every English review — a
    fabricated certainty in a column the paper's language-mix table reads.
    """
    try:
        from langdetect import DetectorFactory, detect_langs
    except ImportError:
        return None
    DetectorFactory.seed = 0

    def detect(text: str):
        ranked = detect_langs(text)
        if not ranked:
            return "", None
        return ranked[0].lang, float(ranked[0].prob)

    return detect


def choose_basis(corpus: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(text to label, which text it was) per row."""
    clean = corpus["review_text_clean"].astype("string").fillna("")
    if "review_text_original" in corpus.columns:
        original = corpus["review_text_original"].astype("string")
        basis = original.where(original.notna() & (original.str.strip() != ""), clean)
        which = pd.Series(
            ["original" if isinstance(v, str) and v.strip() else "clean" for v in original],
            index=corpus.index,
        )
        return basis, which
    return clean, pd.Series("clean", index=corpus.index)


def apply_overrides(frame: pd.DataFrame) -> list[str]:
    """Apply hand corrections from language_label_overrides.csv."""
    notes: list[str] = []
    if not OVERRIDES_CSV.exists():
        return notes
    try:
        overrides = pd.read_csv(OVERRIDES_CSV)
    except (ValueError, pd.errors.EmptyDataError):
        notes.append(f"{OVERRIDES_CSV.name} could not be read; ignored")
        return notes
    if not {"review_id", "language_label"} <= set(overrides.columns):
        notes.append(f"{OVERRIDES_CSV.name} lacks review_id/language_label; ignored")
        return notes

    bad = overrides[~overrides["language_label"].isin(LABELS)]
    if not bad.empty:
        notes.append(
            f"{OVERRIDES_CSV.name}: {len(bad)} row(s) have a label outside "
            f"{LABELS} and were ignored"
        )
        overrides = overrides[overrides["language_label"].isin(LABELS)]

    mapping = dict(zip(overrides["review_id"].astype(str), overrides["language_label"]))
    known = frame["review_id"].astype(str).isin(mapping)
    if known.any():
        frame.loc[known, "language_label"] = frame.loc[known, "review_id"].astype(str).map(mapping)
        frame.loc[known, "language_method"] = "human-override"
        frame.loc[known, "language_confidence"] = 1.0
        notes.append(f"applied {int(known.sum())} human override(s)")
    unknown = len(mapping) - int(known.sum())
    if unknown:
        notes.append(f"{unknown} override(s) name a review_id not in the corpus; ignored")
    return notes


def build(corpus: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []

    model = load_model()
    if model is None:
        notes.append(
            "no trained Banglish classifier; using the lexicon heuristic "
            "(train it with scripts/banglish_classifier.py --train)"
        )
    else:
        notes.append("using the trained Banglish classifier")

    fasttext_model = None
    if FASTTEXT_MODEL.exists():
        from language_id import load_fasttext

        fasttext_model = load_fasttext(FASTTEXT_MODEL)
        notes.append(
            "using fastText lid.176" if fasttext_model is not None
            else f"{FASTTEXT_MODEL.name} present but fasttext is not importable; using langdetect"
        )
    else:
        notes.append("fastText lid.176 not present; using langdetect for Latin-script languages")

    langdetect_fn = _langdetect_fn()
    if langdetect_fn is None:
        notes.append("langdetect is not installed; non-English Latin text cannot be identified")

    basis, which = choose_basis(corpus)
    guesses = [
        classify(text, banglish=model, fasttext_model=fasttext_model, langdetect_fn=langdetect_fn)
        for text in basis
    ]

    frame = pd.DataFrame([g.as_row() for g in guesses], index=corpus.index)
    frame.insert(0, "review_id", corpus["review_id"].astype(str).values)
    frame["text_basis"] = which.values
    frame["text_normalized"] = [normalize_bangla(t) for t in basis]
    # The phonetic key belongs to a *name*, not to a review body. Keyed on the
    # whole text it produces a thousand-character consonant run that matches
    # nothing; section 5.3 uses it to cluster mentions of the same place. Until
    # Phase 4 extracts mentions, the place name is the name each review carries.
    frame["place_phonetic_key"] = [
        phonetic_key(name) for name in corpus.get("place_name", pd.Series("", index=corpus.index))
    ]

    notes += apply_overrides(frame)
    return frame[OUTPUT_COLUMNS], notes


def write_reports(frame: pd.DataFrame, corpus: pd.DataFrame, notes: list[str]) -> None:
    label_counts = Counter(frame["language_label"])
    method_counts = Counter(frame["language_method"])
    basis_counts = Counter(frame["text_basis"])

    payload = {
        "n_reviews": int(len(frame)),
        "by_label": {k: int(v) for k, v in sorted(label_counts.items())},
        "by_method": {k: int(v) for k, v in sorted(method_counts.items())},
        "by_text_basis": {k: int(v) for k, v in sorted(basis_counts.items())},
        "original_text_share": round(basis_counts.get("original", 0) / max(1, len(frame)), 4),
        "bangla_or_banglish_share": round(
            sum(label_counts.get(k, 0) for k in ("bn", "bn-latn", "mixed")) / max(1, len(frame)), 4
        ),
        "notes": notes,
    }
    OUT_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    share = payload["bangla_or_banglish_share"]
    lines = [
        "# Phase 3 — Language pipeline",
        "",
        "Four-way label (BUILD_PLAN 4.1) on the reviewer's own text where Phase 2",
        "kept it, plus section 4.2 normalisation and a phonetic matching key.",
        "",
        f"- Reviews: **{len(frame)}**",
        f"- Bangla / Banglish / mixed: **{share:.1%}** "
        f"(section 3 targets at least 20% of the collected corpus)",
        f"- Labelled from the reviewer's original text: {payload['original_text_share']:.1%}",
        "",
        "## By label",
        "",
        "| label | reviews |",
        "| --- | --- |",
    ]
    for label, count in sorted(label_counts.items()):
        lines.append(f"| {label or '(none)'} | {count} |")
    lines += ["", "## How each label was reached", "", "| method | reviews |", "| --- | --- |"]
    for method, count in sorted(method_counts.items()):
        lines.append(f"| {method} | {count} |")
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    if share < 0.20:
        lines += [
            "",
            "> Below the 20% Bangla/Banglish target. The corpus was collected through",
            "> Google's translation, so the reviewer's own words were mostly never",
            "> stored (weakness W6). The YouTube pass in section 3.3a is what changes",
            "> this, not a better classifier.",
        ]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report without writing anything")
    args = parser.parse_args()

    if not IN_CORPUS.exists():
        print(f"error: {IN_CORPUS} does not exist; run Phase 2 first")
        return 1

    corpus = pd.read_csv(IN_CORPUS)
    print(f"Phase 3 — language pipeline over {len(corpus)} review(s)")

    frame, notes = build(corpus)
    for note in notes:
        print(f"  - {note}")

    counts = Counter(frame["language_label"])
    print("  labels: " + ", ".join(f"{k or '(none)'}={v}" for k, v in sorted(counts.items())))

    if args.dry_run:
        print(f"\n  --dry-run: would write {OUT_CSV.name}, {OUT_REPORT_MD.name}, {OUT_REPORT_JSON.name}")
        return 0

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_CSV, index=False)
    write_reports(frame, corpus, notes)
    print(f"\n  wrote {OUT_CSV.name}, {OUT_REPORT_MD.name}, {OUT_REPORT_JSON.name}")
    print("\nNext: rebuild the database so the API serves the new labels")
    print("  .venv/bin/python scripts/build_phase8_database.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
