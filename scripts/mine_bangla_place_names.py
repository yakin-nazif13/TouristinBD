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

The exact key misses names whose English spelling carries letters Bangla does
not write: "Sundarbans" (sndrbns) against সুন্দরবন (sndrbn), "Jaflong" (jflng)
against জাফলং (jfln), "Mahasthangarh" against মহাস্থানগড়. So a second, looser
key is compared as well, used here only: the shared phonetic key, on which entity
resolution's F1 rests, is left alone.

A third source is the reviews Google returned in two versions. When the English
translation names a known place and the Bangla original does not match it, the
Bangla words that sound most like it are proposed: the translation says which
place the review is about, which the sound alone cannot. This is how কুয়াকাটা
(key "kt", too short to trust on its own) is found for Kuakata.

Output: data/place_names_bn.csv

    bangla     the spelling as reviewers write it (case ending removed)
    place      the gazetteer name it stands for
    reviews    distinct reviews containing it
    decision   accept | reject | pending
    reason     why, for a reject
    found_by   sound | loose sound | translation pair

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
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_mentions import load_gazetteer  # noqa: E402
# The same endings the extractor allows after a match, so a mined spelling and an
# extracted one are cut at the same place.
from gem_schema import BANGLA_SUFFIXES, term_pattern  # noqa: E402
from language_id import normalize_bangla, phonetic_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
OUT_NAMES = DATA_DIR / "place_names_bn.csv"

COLUMNS = ["bangla", "place", "reviews", "decision", "reason", "found_by"]
DECISIONS = {"accept", "reject", "pending"}

# A key this short pairs too many ordinary words with places to be worth reviewing.
MIN_KEY_LETTERS = 3

# How alike a Bangla phrase and an English name must sound, as loose keys, to be
# proposed from a translation pair (rapidfuzz ratio, 0-100).
ALIGNED_MIN_SIMILARITY = 75

# Bengali letters and vowel signs only. The block's digits and currency signs are
# left out, or "মসজিদ৷" (with a look-alike danda) is a different word from "মসজিদ".
BENGALI_WORD_RE = re.compile(r"[ঁ-ৣৰৱ]+")


def bangla_words(text: str) -> list[str]:
    """Bangla words of a text, with ঃ dropped where it is used as a colon.

    Reviewers write "রামসাগরঃ" for "Ramsagar:"; the visarga is punctuation
    there, not part of the name.
    """
    words = [w.rstrip("ঃ") for w in BENGALI_WORD_RE.findall(normalize_bangla(text))]
    return [w for w in words if w]


def strip_suffix(word: str) -> str:
    """Remove one case ending, keeping at least two letters of the stem."""
    for suffix in BANGLA_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[: -len(suffix)]
    return word


def loose_key(text: str) -> str:
    """The phonetic key with the spelling habits Bangla does not share removed.

    Per word: "ng" and "n" are one sound (ং is written as "ng"), "ck" is "k"
    ("Cox"), and a final "s" or "h" is dropped ("Sundarbans", "-garh"). Applied
    to both sides, so it can only make more pairs meet, never fewer.
    """
    words = []
    for word in phonetic_key(text).split():
        word = word.replace("ng", "n").replace("ck", "k")
        if len(word) > 3 and word[-1] in "sh":
            word = word[:-1]
        words.append(word)
    return " ".join(words)


def _letters(key: str) -> int:
    return len(key.replace(" ", ""))


def mine(texts: list[str], names: list[str]) -> dict[tuple[str, str], int]:
    """(bangla phrase, gazetteer name) -> distinct reviews containing the phrase."""
    return {pair: len(reviews) for pair, (reviews, _) in mine_with_source(texts, names).items()}


def mine_with_source(texts: list[str], names: list[str]) -> dict[tuple[str, str], tuple[set[int], str]]:
    """Like `mine`, also saying whether the exact or the loose key found each pair."""
    by_key: dict[str, list[str]] = defaultdict(list)
    by_loose: dict[str, list[str]] = defaultdict(list)
    for name in names:
        key = phonetic_key(name)
        if _letters(key) >= MIN_KEY_LETTERS:
            by_key[key].append(name)
            by_loose[loose_key(name)].append(name)
    source: dict[tuple[str, str], str] = {}

    found: dict[tuple[str, str], set[int]] = defaultdict(set)
    for index, text in enumerate(texts):
        words = bangla_words(text)
        for size in (1, 2, 3):
            for start in range(len(words) - size + 1):
                gram = words[start:start + size]
                # The word as written first: "কাপ্তাই" ends in a letter that is
                # also a particle, and stripping it would store a name nobody wrote.
                for last in dict.fromkeys([gram[-1], strip_suffix(gram[-1])]):
                    phrase = " ".join(gram[:-1] + [last])
                    targets, how = by_key.get(phonetic_key(phrase)), "sound"
                    if not targets and _letters(loose_key(phrase)) >= MIN_KEY_LETTERS:
                        targets, how = by_loose.get(loose_key(phrase)), "loose sound"
                    if targets:
                        # One spelling can only stand for one place. Where the key
                        # is shared ("Sreemangal" and "Srimangal"), the first name
                        # in sorted order is used and resolution merges the rest.
                        pair = (phrase, sorted(targets)[0])
                        found[pair].add(index)
                        source.setdefault(pair, how)
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
    return {pair: (reviews, source.get(pair, "sound")) for pair, reviews in found.items()}


def mine_aligned(pairs: list[tuple[str, str]], names: list[str],
                 texts: list[str]) -> dict[tuple[str, str], int]:
    """Bangla spellings proposed from (Bangla original, English translation) pairs.

    For each known place the translation names, the Bangla 1-3 word phrase of
    the original whose loose key is most like the place's is proposed, if it is
    alike enough. Ties go to the phrase whose length is closest to the name's.
    Counts are distinct reviews in `texts` that contain the phrase.
    """
    patterns = {name: re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])", re.IGNORECASE)
                for name in names}
    proposed: set[tuple[str, str]] = set()
    for original, translation in pairs:
        words = bangla_words(original)
        # Each phrase as written and with its ending removed. The more alike
        # sound wins, so "কক্সবাজার" beats the over-cut "কক্সবাজা"; on a tie
        # the base form wins, since an ending like ে changes no letter of the
        # key and the extractor allows it anyway: "সুন্দরবন", not "সুন্দরবনে".
        grams: dict[str, int] = {}
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                grams.setdefault(" ".join(gram), 0)
                base = " ".join(gram[:-1] + [strip_suffix(gram[-1])])
                if base != " ".join(gram):
                    grams[base] = 1
        for name in names:
            if not patterns[name].search(translation):
                continue
            target = loose_key(name)
            scored = [(fuzz.ratio(loose_key(g), target), -abs(_letters(loose_key(g)) - _letters(target)),
                       is_base, g)
                      for g, is_base in grams.items() if _letters(loose_key(g)) >= 2]
            if not scored:
                continue
            similarity, _, _, best = max(scored)
            if similarity >= ALIGNED_MIN_SIMILARITY:
                proposed.add((best, name))
    return {(phrase, place): count_reviews(phrase, texts) for phrase, place in proposed}


def count_reviews(phrase: str, texts: list[str]) -> int:
    """Reviews in `texts` the extractor's own matcher finds the phrase in."""
    pattern = term_pattern(phrase)
    return sum(1 for t in texts if pattern.search(normalize_bangla(t)))


def merge_decisions(mined: dict[tuple[str, str], int], existing: pd.DataFrame,
                    found_by: dict[tuple[str, str], str] | None = None,
                    texts: list[str] | None = None) -> pd.DataFrame:
    """New counts, old decisions. A recorded decision is never overwritten."""
    found_by = found_by or {}
    previous = {}
    if not existing.empty:
        for _, row in existing.iterrows():
            reason = row.get("reason")
            source = row.get("found_by")
            previous[(str(row["bangla"]), str(row["place"]))] = (
                str(row.get("decision") or "pending").strip(),
                "" if pd.isna(reason) else str(reason),
                "" if pd.isna(source) else str(source),
            )
    rows = []
    for (bangla, place), reviews in mined.items():
        decision, reason, source = previous.pop((bangla, place), ("pending", "", ""))
        rows.append({"bangla": bangla, "place": place, "reviews": reviews,
                     "decision": decision, "reason": reason,
                     "found_by": source or found_by.get((bangla, place), "sound")})
    # A decided row the miner did not propose this time (its phrase no longer
    # occurs, or a person added it by hand) is kept, so the decision survives a
    # corpus change rather than being re-asked later. A hand-added row gets its
    # count from the extractor's own matcher, so it is not shown as unused.
    for (bangla, place), (decision, reason, source) in previous.items():
        rows.append({"bangla": bangla, "place": place, "reviews": count_reviews(bangla, texts),
                     "decision": decision, "reason": reason, "found_by": source or "sound"})
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
    with_source = mine_with_source(texts, names)
    mined = {pair: len(reviews) for pair, (reviews, _) in with_source.items()}
    found_by = {pair: how for pair, (_, how) in with_source.items()}

    # Reviews Google gave in two versions: the translation says which place.
    original = corpus["review_text_original"]
    both = corpus[original.notna() & (original.astype(str).str.strip()
                                      != corpus["review_text_clean"].astype(str).str.strip())]
    pairs = [(o, t) for o, t in zip(both["review_text_original"].astype(str),
                                    both["review_text_clean"].astype(str))
             if BENGALI_WORD_RE.search(o)]
    aligned = mine_aligned(pairs, names, texts)
    new_from_pairs = 0
    for pair, count in aligned.items():
        if pair not in mined and count:
            mined[pair] = count
            found_by[pair] = "translation pair"
            new_from_pairs += 1
    print(f"  {len(pairs)} translation pair(s) proposed {new_from_pairs} new spelling(s)")

    existing = pd.read_csv(OUT_NAMES) if OUT_NAMES.exists() else pd.DataFrame(columns=COLUMNS)
    frame = merge_decisions(mined, existing, found_by, texts)

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
