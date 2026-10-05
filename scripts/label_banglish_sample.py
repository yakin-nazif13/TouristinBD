"""Label Latin-script texts as Banglish / English / mixed — BUILD_PLAN 4.1.

Section 4.1 asks for about 500 hand-labelled Latin-script texts to train the
Banglish classifier, and says the labelled set becomes part of the released
dataset. This is the tool that collects them, built like
`label_validation_sample.py`: blinded, resumable, shuffled per annotator, and
saving after every answer.

Blinded means the heuristic's own guess is never shown. The classifier is meant
to learn a human judgement, so seeing "the current rule thinks this is English"
would anchor the annotator to the thing being replaced.

Two steps:

    python scripts/label_banglish_sample.py --build-pool
    python scripts/label_banglish_sample.py --annotator yourname

The pool is every Latin-script text in the corpus, sampled for place and source
diversity so one chatty hotel cannot dominate the training set. It is written
once and committed, so every annotator labels the same texts and agreement can
be computed.

Keys:  b = Banglish   e = English   m = mixed   s = skip   n = note   q = quit
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_id import script_shares  # noqa: E402

DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
CORPUS = DATA_DIR / "processed_reviews.csv"
POOL = DATA_DIR / "banglish_pool.csv"
LABELS_DIR = DATA_DIR / "banglish_labels"

POOL_TARGET = 500
SEED = 42

# Shorter than this and even a person cannot tell Banglish from English
# ("Good", "Nice"), so they are not worth an annotator's attention.
MIN_CHARS = 12

ANSWERS = {"b": "banglish", "e": "english", "m": "mixed"}
QUESTION = (
    "Is this Banglish (romanised Bangla), English, or mixed?\n"
    "  b = Banglish   e = English   m = mixed   s = skip   n = note   q = save and quit"
)


def labels_path(annotator: str) -> Path:
    return LABELS_DIR / f"labels_{annotator}.csv"


def build_pool() -> int:
    """Sample Latin-script texts from the corpus into a stable, shared pool."""
    if not CORPUS.exists():
        print(f"error: {CORPUS} does not exist; run Phase 2 first")
        return 1

    corpus = pd.read_csv(CORPUS)
    # Prefer the reviewer's own words where they were kept; section 4.1 labels
    # the original, not a translation of it.
    if "review_text_original" in corpus.columns:
        text = corpus["review_text_original"].fillna(corpus["review_text_clean"])
    else:
        text = corpus["review_text_clean"]
    corpus = corpus.assign(_text=text.astype("string"))

    latin = corpus[corpus["_text"].fillna("").map(lambda t: script_shares(t)[1] > 0.8)]
    latin = latin[latin["_text"].str.len() >= MIN_CHARS]
    latin = latin.drop_duplicates(subset="_text")
    if latin.empty:
        print("error: no Latin-script texts in the corpus")
        return 1

    # Round-robin over places so no single venue dominates, then over sources.
    # Deterministic: every annotator must get the same pool.
    groups = [
        group.sample(frac=1.0, random_state=SEED)
        for _, group in latin.groupby(["source", "place_name"], sort=True)
    ]
    picked: list[pd.Series] = []
    index = 0
    while len(picked) < min(POOL_TARGET, len(latin)):
        progressed = False
        for group in groups:
            if index < len(group):
                picked.append(group.iloc[index])
                progressed = True
                if len(picked) >= min(POOL_TARGET, len(latin)):
                    break
        if not progressed:
            break
        index += 1

    pool = pd.DataFrame(picked)[["review_id", "source", "place_name", "_text"]]
    pool = pool.rename(columns={"_text": "text"}).reset_index(drop=True)
    pool.insert(0, "pool_order", range(1, len(pool) + 1))
    POOL.parent.mkdir(parents=True, exist_ok=True)
    pool.to_csv(POOL, index=False)

    print(f"wrote {POOL} with {len(pool)} text(s)")
    print(f"  from {pool['place_name'].nunique()} place(s), {pool['source'].nunique()} source(s)")
    if len(pool) < POOL_TARGET:
        print(
            f"\n  note: section 4.1 asks for about {POOL_TARGET}; the corpus only has "
            f"{len(pool)} distinct Latin-script texts.\n"
            "  The corpus is currently translated English with no Banglish in it, so\n"
            "  labelling this pool alone cannot train the classifier — it would be\n"
            "  single-class. Rebuild the pool after the YouTube pass (BUILD_PLAN 3.3a),\n"
            "  which is where romanised Bangla actually lives."
        )
    return 0


def load_or_create(annotator: str) -> pd.DataFrame:
    """This annotator's sheet, shuffled with their own seed and resumable."""
    path = labels_path(annotator)
    if path.exists():
        return pd.read_csv(path)

    if not POOL.exists():
        raise FileNotFoundError(
            f"{POOL} does not exist. Build it first:\n"
            "  python scripts/label_banglish_sample.py --build-pool"
        )
    pool = pd.read_csv(POOL)
    # Per-annotator order, so two people do not drift together through a shared
    # sequence; derived from the name so it is reproducible.
    seed = abs(hash(annotator)) % (2**31) if annotator else SEED
    sheet = pool.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    sheet["order"] = range(1, len(sheet) + 1)
    sheet["label"] = pd.NA
    sheet["note"] = pd.NA
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(path, index=False)
    return sheet


def save(sheet: pd.DataFrame, annotator: str) -> None:
    sheet.to_csv(labels_path(annotator), index=False)


def show(row: pd.Series, done: int, total: int) -> None:
    import textwrap

    width = 92
    print("\n" + "=" * width)
    print(f"Text {int(row['order'])} of {total}   ({done} labelled)")
    print("-" * width)
    print(textwrap.fill(str(row["text"]), width, initial_indent="  ", subsequent_indent="  "))
    print("-" * width)
    print(QUESTION)


def interactive(annotator: str) -> int:
    sheet = load_or_create(annotator)
    total = len(sheet)
    print(f"Labelling as '{annotator}' -> {labels_path(annotator)}")
    print("Keys: b = Banglish  e = English  m = mixed  s = skip  n = note  q = save and quit")

    while True:
        pending = sheet.index[sheet["label"].isna()].tolist()
        if not pending:
            print(f"\nAll {total} texts are labelled. Train with:")
            print("  python scripts/banglish_classifier.py --train")
            break
        i = pending[0]
        row = sheet.loc[i]
        done = int(sheet["label"].notna().sum())
        show(row, done, total)

        answer = input("> ").strip().lower()
        if answer == "q":
            save(sheet, annotator)
            print(f"saved: {done}/{total} labelled")
            break
        if answer == "n":
            sheet.loc[i, "note"] = input("note: ").strip()
            save(sheet, annotator)
            continue
        if answer == "s":
            # Skipped rows stay unlabelled rather than being guessed; a text no
            # one can judge is not training data.
            sheet.loc[i, "label"] = "skip"
            save(sheet, annotator)
            continue
        if answer not in ANSWERS:
            print("Please type b, e, m, s, n or q.")
            continue
        sheet.loc[i, "label"] = ANSWERS[answer]
        save(sheet, annotator)
    return 0


def status(annotator: str) -> int:
    path = labels_path(annotator)
    if not path.exists():
        print(f"{annotator}: nothing started ({path} does not exist)")
        return 1
    sheet = pd.read_csv(path)
    labelled = sheet["label"].notna().sum()
    print(f"{annotator}: {labelled}/{len(sheet)} labelled")
    counts = sheet["label"].value_counts(dropna=True).to_dict()
    if counts:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


def export_sheet(annotator: str) -> int:
    sheet = load_or_create(annotator)
    path = labels_path(annotator)
    sheet.to_csv(path, index=False)
    print(f"wrote {path}")
    print("Fill only the `label` column with banglish, english or mixed, then save as CSV.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-pool", action="store_true", help="build the shared pool and exit")
    parser.add_argument("--annotator", help="your first name, e.g. unaiza")
    parser.add_argument("--status", action="store_true", help="show progress and exit")
    parser.add_argument("--export-sheet", action="store_true", help="write the sheet for spreadsheet labelling")
    args = parser.parse_args()

    if args.build_pool:
        return build_pool()
    if not args.annotator:
        parser.error("--annotator is required unless --build-pool is given")
    if args.status:
        return status(args.annotator)
    if args.export_sheet:
        return export_sheet(args.annotator)
    return interactive(args.annotator)


if __name__ == "__main__":
    sys.exit(main())
