"""Bangla spellings of known places, mined from the corpus's own Bangla reviews.

The gazetteer extractor matches known names, and every known name was English, so
the ~4,000 Bangla-script reviews contributed no mentions at all: a reviewer writing
"বান্দরবান" was invisible to the hidden-gem engine. This finds how reviewers
actually spell each known place in Bangla.

Method: every 1-3 word Bangla phrase in a Bangla-script review is reduced to the
section 4.2 phonetic key (after stripping a case ending from its last word, so
"সাজেকের" and "সাজেক" meet) and compared with the keys of the gazetteer's
English names. An exact key match is a *candidate*, nothing more. The key is lossy
on purpose, so it also pairs ordinary words with places that sound alike —
লোকাল ("local") with Lalakhal, পসরা ("wares") with Pashur. A person decides.

Output: data/place_names_bn.csv

    bangla     the spelling as reviewers write it (case ending removed)
    place      the gazetteer name it stands for
    reviews    distinct reviews containing it
    decision   accept | reject | pending
    reason     why, for a reject

Only `accept` rows are used by extract_mentions.py. Re-running keeps every
recorded decision and adds new candidates as `pending`, so a review is never lost
and nothing unreviewed reaches the register.

Run:
    .venv/bin/python scripts/mine_bangla_place_names.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_mentions import load_gazetteer  # noqa: E402
# The same endings the extractor allows after a match, so a mined spelling and an
# extracted one are cut at the same place.
from gem_schema import BANGLA_SUFFIXES  # noqa: E402
from language_id import normalize_bangla, phonetic_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
OUT_NAMES = DATA_DIR / "place_names_bn.csv"

COLUMNS = ["bangla", "place", "reviews", "decision", "reason"]
DECISIONS = {"accept", "reject", "pending"}

# A key this short pairs too many ordinary words with places to be worth reviewing.
MIN_KEY_LETTERS = 3

# Bengali letters and vowel signs only. The block's digits and currency signs are
# left out, or "মসজিদ৷" (with a look-alike danda) is a different word from "মসজিদ".
BENGALI_WORD_RE = re.compile(r"[ঁ-ৣৰৱ]+")


def strip_suffix(word: str) -> str:
    """Remove one case ending, keeping at least two letters of the stem."""
    for suffix in BANGLA_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[: -len(suffix)]
    return word


def mine(texts: list[str], names: list[str]) -> dict[tuple[str, str], int]:
    """(bangla phrase, gazetteer name) -> distinct reviews containing the phrase."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for name in names:
        key = phonetic_key(name)
        if len(key.replace(" ", "")) >= MIN_KEY_LETTERS:
            by_key[key].append(name)

    found: dict[tuple[str, str], set[int]] = defaultdict(set)
    for index, text in enumerate(texts):
        words = BENGALI_WORD_RE.findall(normalize_bangla(text))
        for size in (1, 2, 3):
            for start in range(len(words) - size + 1):
                gram = words[start:start + size]
                # The word as written first: "কাপ্তাই" ends in a letter that is
                # also a particle, and stripping it would store a name nobody wrote.
                for last in dict.fromkeys([gram[-1], strip_suffix(gram[-1])]):
                    phrase = " ".join(gram[:-1] + [last])
                    targets = by_key.get(phonetic_key(phrase))
                    if targets:
                        # One spelling can only stand for one place. Where the key
                        # is shared ("Sreemangal" and "Srimangal"), the first name
                        # in sorted order is used and resolution merges the rest.
                        found[(phrase, sorted(targets)[0])].add(index)
                        break

    # The key ignores endings, so "আলুটিলায়" matches as written. Where the form
    # without its ending was found for the same place too, the inflected one is
    # folded into it: the extractor allows the ending after a match anyway.
    # Every ending is tried, not only the longest: "লেকে" ends in both "কে" and
    # "ে", and only the second leaves the real word.
    for phrase, place in sorted(found, key=lambda pair: -len(pair[0])):
        words = phrase.split(" ")
        for suffix in BANGLA_SUFFIXES:
            if not words[-1].endswith(suffix) or len(words[-1]) - len(suffix) < 2:
                continue
            base = " ".join(words[:-1] + [words[-1][: -len(suffix)]])
            if (base, place) in found:
                found[(base, place)] |= found.pop((phrase, place))
                break
    return {pair: len(reviews) for pair, reviews in found.items()}


def merge_decisions(mined: dict[tuple[str, str], int], existing: pd.DataFrame) -> pd.DataFrame:
    """New counts, old decisions. A recorded decision is never overwritten."""
    previous = {}
    if not existing.empty:
        for _, row in existing.iterrows():
            reason = row.get("reason")
            previous[(str(row["bangla"]), str(row["place"]))] = (
                str(row.get("decision") or "pending").strip(),
                "" if pd.isna(reason) else str(reason),
            )
    rows = []
    for (bangla, place), reviews in mined.items():
        decision, reason = previous.pop((bangla, place), ("pending", ""))
        rows.append({"bangla": bangla, "place": place, "reviews": reviews,
                     "decision": decision, "reason": reason})
    # A decided row whose phrase no longer occurs is kept with 0 reviews, so the
    # decision survives a corpus change rather than being re-asked later.
    for (bangla, place), (decision, reason) in previous.items():
        rows.append({"bangla": bangla, "place": place, "reviews": 0,
                     "decision": decision, "reason": reason})
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.sort_values(["place", "reviews", "bangla"], ascending=[True, False, True]).reset_index(drop=True)


def load_accepted(path: Path = OUT_NAMES) -> dict[str, str]:
    """Accepted Bangla spelling -> the place it stands for."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    accepted = frame[frame["decision"].astype(str).str.strip() == "accept"]
    return dict(zip(accepted["bangla"].astype(str), accepted["place"].astype(str)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not IN_CORPUS.exists():
        print(f"error: {IN_CORPUS} does not exist; run Phase 2 first")
        return 1
    corpus = pd.read_csv(IN_CORPUS, low_memory=False)
    texts = corpus["review_text_original"].fillna("").astype(str)
    texts = texts[texts.str.contains(BENGALI_WORD_RE)].tolist()
    names = load_gazetteer(corpus)

    print(f"Mining Bangla place names from {len(texts)} Bangla-script review(s) against {len(names)} names")
    mined = mine(texts, names)
    existing = pd.read_csv(OUT_NAMES) if OUT_NAMES.exists() else pd.DataFrame(columns=COLUMNS)
    frame = merge_decisions(mined, existing)

    bad = set(frame["decision"]) - DECISIONS
    if bad:
        print(f"error: unknown decision value(s) {sorted(bad)}; use accept, reject or pending")
        return 1
    counts = frame["decision"].value_counts().to_dict()
    print(f"  candidates: {len(frame)}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    frame.to_csv(OUT_NAMES, index=False, encoding="utf-8")
    print(f"  wrote {OUT_NAMES.name}")
    if counts.get("pending"):
        print(f"  {counts['pending']} pending: set decision to accept or reject before they are used")
    return 0


if __name__ == "__main__":
    sys.exit(main())
