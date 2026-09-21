"""
Phase 5 — label the 50-pair human validation sample, blind and independently.

Each annotator gets their own file, `data/human_labels/labels_<name>.csv`, and
answers one question per pair:

    Does this TOPIC genuinely express this TOURIST PREFERENCE?   1 = yes, 0 = no

What an annotator sees for each pair:
  * the topic's keywords, size, main places and a few real reviews from it
  * the preference's category, name and description

What an annotator never sees, because each would bias the judgement:
  * the embedding similarity, the pair type (positive / hard negative / ...),
    the pipeline's expected answer, the LLM's own label for the topic
  * anyone else's labels

Pairs are shown in a different order for every annotator (seeded by name), so
fatigue and order effects do not line up across the team.

Two ways to label (both write the same file, so you can switch):

    # Interactive, in the terminal. Resumable: quit any time with q.
    python scripts/label_validation_sample.py --annotator yakin

    # Spreadsheet: writes the file with all context columns and an empty
    # human_label column. Open it in Excel / Google Sheets, fill human_label
    # with 1 or 0, and save it back under the SAME name as CSV.
    python scripts/label_validation_sample.py --annotator farhan --export-sheet

Then, once everyone is done:

    python scripts/compute_human_agreement.py

Protocol (see docs/HUMAN_VALIDATION.md): label alone, do not discuss pairs
until everyone has submitted, do not ask an LLM, and do not open the Phase 5
reports while labelling.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import textwrap
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

SAMPLE_CSV = DATA_DIR / "phase5_manual_review_sample.csv"
TOPICS_CSV = DATA_DIR / "topics_summary.csv"
REVIEWS_CSV = DATA_DIR / "reviews_with_topics.csv"
PREFERENCES_CSV = DATA_DIR / "preference_classification.csv"
LABELS_DIR = DATA_DIR / "human_labels"

EXAMPLES_PER_TOPIC = 4
EXAMPLE_MIN_CHARS, EXAMPLE_MAX_CHARS = 60, 420

# The columns written to each annotator's file. Deliberately excludes
# similarity, pair_type, expected_relation and interpreted_label.
LABEL_COLUMNS = [
    "order",
    "pair_key",
    "topic_id",
    "preference_id",
    "topic_keywords",
    "topic_size",
    "topic_main_places",
    "topic_examples",
    "preference_category",
    "preference",
    "preference_description",
    "human_label",
    "note",
    "labeled_at",
]
HIDDEN_COLUMNS = {"similarity", "pair_type", "expected_relation", "interpreted_label"}

QUESTION = "Does this TOPIC genuinely express this TOURIST PREFERENCE?"


def pair_key(topic_id: object, preference_id: object) -> str:
    return f"T{int(topic_id)}-{preference_id}"


def safe_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9_-]", "", raw.strip().lower())
    if not name:
        raise SystemExit("--annotator must contain letters or digits, e.g. --annotator yakin")
    return name


def labels_path(name: str) -> Path:
    return LABELS_DIR / f"labels_{name}.csv"


# ---------------------------------------------------------------------------
# Context


def topic_examples(reviews: pd.DataFrame, topic_id: int) -> list[str]:
    """A few real reviews from the topic, chosen deterministically.

    Medium-length reviews, at most one per place first, so an annotator sees
    the topic's spread rather than four reviews of one hotel.
    """
    rows = reviews[reviews["topic_id"] == topic_id].copy()
    rows["text"] = rows["review_text_clean"].fillna("").astype(str)
    rows = rows[rows["text"].str.len().between(EXAMPLE_MIN_CHARS, EXAMPLE_MAX_CHARS)]
    rows = rows.sort_values("review_id")
    picked: list[str] = []
    seen_places: set[str] = set()
    for _, row in rows.iterrows():
        if row["place_name"] in seen_places:
            continue
        seen_places.add(row["place_name"])
        picked.append(row["text"])
        if len(picked) == EXAMPLES_PER_TOPIC:
            return picked
    for text in rows["text"]:
        if len(picked) == EXAMPLES_PER_TOPIC:
            break
        if text not in picked:
            picked.append(text)
    return picked


def build_blinded_sheet(annotator: str) -> pd.DataFrame:
    sample = pd.read_csv(SAMPLE_CSV)
    topics = pd.read_csv(TOPICS_CSV).rename(columns={"Topic": "topic_id", "Count": "topic_size"})
    reviews = pd.read_csv(REVIEWS_CSV)
    prefs = pd.read_csv(PREFERENCES_CSV)

    keys = [pair_key(t, p) for t, p in zip(sample["topic_id"], sample["preference_id"])]
    if len(set(keys)) != len(keys):
        raise SystemExit(f"{SAMPLE_CSV.name} contains duplicate topic/preference pairs")

    topic_info = topics.set_index("topic_id")
    pref_info = prefs.set_index("preference_id")
    rows = []
    for key, (_, pair) in zip(keys, sample.iterrows()):
        tid, pid = int(pair["topic_id"]), str(pair["preference_id"])
        in_topic = reviews[reviews["topic_id"] == tid]
        places = in_topic["place_name"].value_counts().head(4)
        rows.append({
            "pair_key": key,
            "topic_id": tid,
            "preference_id": pid,
            "topic_keywords": topic_info.loc[tid, "top_keywords"] if tid in topic_info.index else "",
            "topic_size": int(topic_info.loc[tid, "topic_size"]) if tid in topic_info.index else len(in_topic),
            "topic_main_places": "; ".join(f"{name} ({n})" for name, n in places.items()),
            "topic_examples": " || ".join(topic_examples(reviews, tid)),
            "preference_category": (
                f"{pref_info.loc[pid, 'category']} > {pref_info.loc[pid, 'subcategory']}"
                if pid in pref_info.index else ""
            ),
            "preference": pref_info.loc[pid, "preference"] if pid in pref_info.index else pid,
            "preference_description": pref_info.loc[pid, "description"] if pid in pref_info.index else "",
            "human_label": pd.NA,
            "note": "",
            "labeled_at": "",
        })

    order = list(range(len(rows)))
    random.Random(zlib.crc32(annotator.encode("utf-8"))).shuffle(order)
    sheet = pd.DataFrame([rows[i] for i in order])
    sheet.insert(0, "order", range(1, len(sheet) + 1))
    assert not HIDDEN_COLUMNS & set(sheet.columns)
    return sheet[LABEL_COLUMNS]


def load_or_create(annotator: str) -> pd.DataFrame:
    path = labels_path(annotator)
    if path.exists():
        sheet = pd.read_csv(path, dtype={"note": "string", "labeled_at": "string"})
        missing = set(LABEL_COLUMNS) - set(sheet.columns)
        if missing:
            raise SystemExit(f"{path.name} is missing column(s) {sorted(missing)}; delete it to start over")
        return normalize_types(sheet)
    sheet = normalize_types(build_blinded_sheet(annotator))
    save(sheet, annotator)
    return sheet


def normalize_types(sheet: pd.DataFrame) -> pd.DataFrame:
    sheet["human_label"] = pd.to_numeric(sheet["human_label"], errors="coerce").astype("Int64")
    for col in ("note", "labeled_at"):
        sheet[col] = sheet[col].astype("string").fillna("")
    return sheet


def save(sheet: pd.DataFrame, annotator: str) -> None:
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = labels_path(annotator).with_suffix(".tmp")
    sheet.to_csv(tmp, index=False)
    tmp.replace(labels_path(annotator))  # atomic: a crash never leaves half a file


# ---------------------------------------------------------------------------
# Interactive session


def show(row: pd.Series, done: int, total: int) -> None:
    width = 92
    wrap = lambda s, indent="    ": textwrap.fill(str(s), width, initial_indent=indent, subsequent_indent=indent)
    print("\n" + "=" * width)
    print(f"Pair {int(row['order'])} of {total}   ({done} labelled)")
    print("-" * width)
    print(f"TOPIC  ({int(row['topic_size'])} reviews)   keywords: {row['topic_keywords']}")
    print(wrap(f"main places: {row['topic_main_places']}"))
    print("  example reviews:")
    for ex in str(row["topic_examples"]).split(" || "):
        print(wrap(f"- {ex}", "    "))
    print("-" * width)
    print(f"PREFERENCE  [{row['preference_category']}]")
    print(wrap(str(row["preference"]).upper()))
    print(wrap(row["preference_description"]))
    print("-" * width)
    print(QUESTION)


def interactive(annotator: str) -> None:
    sheet = load_or_create(annotator)
    total = len(sheet)
    print(f"Labelling as '{annotator}' -> {labels_path(annotator)}")
    print("Keys: 1 = yes   0 = no   n = add a note   b = back one   q = save and quit")
    pending = sheet.index[sheet["human_label"].isna()].tolist()
    if not pending:
        print(f"All {total} pairs are already labelled. To change an answer, edit the CSV directly.")
        return
    i = pending[0]
    while True:
        pending = sheet.index[sheet["human_label"].isna()].tolist()
        if not pending and i >= total:
            break
        if i >= total:
            i = pending[0]
        row = sheet.loc[i]
        done = int(sheet["human_label"].notna().sum())
        show(row, done, total)
        if pd.notna(row["human_label"]):
            print(f"(current answer: {int(row['human_label'])}; press Enter to keep)")
        answer = input("> ").strip().lower()
        if answer == "q":
            break
        if answer == "b":
            i = max(0, i - 1)
            continue
        if answer == "n":
            sheet.loc[i, "note"] = input("note: ").strip()
            save(sheet, annotator)
            continue
        if answer == "" and pd.notna(row["human_label"]):
            i += 1
            continue
        if answer not in {"1", "0"}:
            print("Please type 1, 0, n, b or q.")
            continue
        sheet.loc[i, "human_label"] = int(answer)
        sheet.loc[i, "labeled_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save(sheet, annotator)
        i += 1
        if sheet["human_label"].notna().all() and i >= total:
            break

    done = int(sheet["human_label"].notna().sum())
    print(f"\nSaved. {done}/{total} pairs labelled.")
    if done == total:
        print("All done — thank you. Do not discuss your answers until everyone has finished.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotator", required=True, help="your first name, e.g. yakin")
    parser.add_argument("--export-sheet", action="store_true",
                        help="write the blinded sheet for spreadsheet labelling and exit")
    parser.add_argument("--status", action="store_true", help="show your progress and exit")
    args = parser.parse_args()
    annotator = safe_name(args.annotator)

    if args.export_sheet:
        if labels_path(annotator).exists():
            sheet = pd.read_csv(labels_path(annotator))
            print(f"{labels_path(annotator).name} already exists with "
                  f"{int(sheet['human_label'].notna().sum())}/{len(sheet)} labels — open that file.")
            return
        sheet = load_or_create(annotator)
        print(f"Wrote {labels_path(annotator)}\nFill human_label with 1 or 0 and save it back as CSV "
              "under the same name.")
        return
    if args.status:
        sheet = load_or_create(annotator)
        print(f"{annotator}: {int(sheet['human_label'].notna().sum())}/{len(sheet)} labelled")
        return
    try:
        interactive(annotator)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Everything answered so far is saved.")


if __name__ == "__main__":
    sys.exit(main())
