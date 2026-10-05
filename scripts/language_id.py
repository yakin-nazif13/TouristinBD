"""Language identification, Bangla normalisation and phonetic keys.

BUILD_PLAN section 4.1 asks for a four-way label on the reviewer's own text:

    bn        Bangla script
    bn-latn   Banglish (romanised Bangla)   <- currently invisible
    en        English
    mixed     code-mixed

A fifth value, `other`, is returned for Latin-script text that is confidently
some third language. The committed corpus contains one Dutch review, and
labelling it `en` would be a false label in the very column the paper's
language-mix table is built from. The four-way vocabulary is what section 4.1
specifies; `other` exists so the plan's four labels can each stay true.

Why the pieces are arranged this way:

* **Script comes first and is decisive.** Bengali-script text needs no
  classifier, and no classifier should be allowed to overrule it.
* **English vs Banglish is a trained decision**, not a rule. `langdetect` and
  fastText both answer "English" for "Khub sundor jayga" because it is Latin
  script with no English words they know. `classify` therefore takes an
  optional `banglish` model (trained by run_phase3_language_pipeline.py) and
  falls back to a transparent lexicon heuristic when none has been trained
  yet, so the pipeline runs end to end before the hand labels exist.
* **fastText is optional.** lid.176 is the section 4.1 recommendation and is
  used when importable, but it is a source build that needs a C++ compiler and
  does not install on every contributor's machine. `langdetect`, already a
  project dependency, covers the same job less well. Neither is asked to
  decide English vs Banglish.

Nothing here imports torch, so the whole module runs on any machine.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- script ranges -------------------------------------------------------

BENGALI_RE = re.compile(r"[ঀ-৿]")
LATIN_RE = re.compile(r"[A-Za-z]")

# Characters that carry no phonetic weight but break string matching when they
# survive into a key: zero-width joiners, the BOM and the soft hyphen.
INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿­]")

LABELS = ["bn", "bn-latn", "en", "mixed", "other"]

# Code-mixing is counted in words, not letters. A single English word in a
# Bangla sentence ("আমরা hotel টা পছন্দ করেছি") is borrowing, not code-mixing,
# and on letter counts it lands right on any sensible threshold because Latin
# words are longer. Both a minimum count and a minimum share must be met.
MIXED_MIN_WORDS = 2
MIXED_MIN_SHARE = 0.25

# Below this many characters, Latin-script text that is not Banglish is taken
# as English without consulting a language detector.
#
# This is not a shortcut — it is Phase 2's hard-won rule, and dropping it is a
# regression. `langdetect` on the committed corpus calls "Exceptional.
# Beautyful" Romanian and "Very poor. Dirty property" Afrikaans; 81 of the
# corpus's Latin rows are under this length, and without the guard 15 of them
# are labelled `other`. Must stay equal to run_phase2_preprocessing's
# SHORT_TEXT_MAX; test_language_id asserts that it does.
SHORT_TEXT_MAX = 50


# --- Bangla normalisation (section 4.2) ----------------------------------

# Composed forms that Unicode also allows to be written as a sequence. Both
# spellings look identical on screen and compare unequal, which is how
# "silently break matching" in section 4.2 actually happens in practice.
_COMPOSE = {
    "ো": "ো",        # e + aa  -> o
    "ৌ": "ৌ",        # e + au length mark -> au
    "ড়": "ড়",        # da + nukta  -> dda
    "ঢ়": "ঢ়",        # dha + nukta -> ddha
    "য়": "য়",        # ya + nukta  -> yya
}


def normalize_bangla(text: str) -> str:
    """Canonical form for Bangla text, safe to use as a matching key.

    NFC alone is not enough: the vowel-sign and nukta sequences above are not
    Unicode-canonical equivalents, so NFC leaves them as distinct sequences
    that render identically. They are composed explicitly.
    """
    if not isinstance(text, str):
        return ""
    out = unicodedata.normalize("NFC", text)
    out = INVISIBLE_RE.sub("", out)
    for sequence, composed in _COMPOSE.items():
        out = out.replace(sequence, composed)
    return re.sub(r"\s+", " ", out).strip()


# --- phonetic key (section 4.2) ------------------------------------------

# Bengali -> Latin phonemes. Deliberately lossy: the key exists so that
# "গুলিয়াখালি", "Guliakhali" and "Gulyakhali" collide, not so that it can be
# read back. Conjuncts are handled by dropping the virama, which is what makes
# "Chandranath" and "চন্দ্রনাথ" meet.
_BENGALI_TO_LATIN = {
    "অ": "a", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u", "ঊ": "u", "ঋ": "ri",
    "এ": "e", "ঐ": "oi", "ও": "o", "ঔ": "ou",
    "ক": "k", "খ": "k", "গ": "g", "ঘ": "g", "ঙ": "n",
    "চ": "c", "ছ": "c", "জ": "j", "ঝ": "j", "ঞ": "n",
    "ট": "t", "ঠ": "t", "ড": "d", "ঢ": "d", "ণ": "n",
    "ত": "t", "থ": "t", "দ": "d", "ধ": "d", "ন": "n",
    "প": "p", "ফ": "f", "ব": "b", "ভ": "b", "ম": "m",
    "য": "j", "র": "r", "ল": "l", "শ": "s", "ষ": "s", "স": "s", "হ": "h",
    # Written as escapes on purpose: these three are single codepoints that can
    # also be typed as letter+nukta. A literal here could be stored as the
    # two-codepoint form, which a per-character lookup would never match.
    "ড়": "r", "ঢ়": "r", "য়": "y",
    "ৎ": "t", "ং": "n", "ঃ": "h", "ঁ": "",
    # dependent vowel signs
    "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u", "ৃ": "ri",
    "ে": "e", "ৈ": "oi", "ো": "o", "ৌ": "ou", "্": "",
}

# Aspirated digraphs that romanisations spell inconsistently. Applied
# longest-first so "chh" is consumed before "ch", and "ch" before "h".
_LATIN_FOLD = [
    ("chh", "c"), ("ssh", "s"), ("sh", "s"), ("ch", "c"), ("kh", "k"),
    ("gh", "g"), ("jh", "j"), ("th", "t"), ("dh", "d"), ("ph", "f"),
    ("bh", "b"), ("v", "b"), ("z", "j"), ("w", "b"), ("q", "k"), ("x", "ks"),
]

# Dropped from the key entirely. Romanisations of Bangladeshi place names
# disagree about vowels constantly — Guliakhali / Gulyakhali, Chor / Char,
# Srimangal / Sreemangal — while agreeing about consonants. `y` goes too: it is
# a glide standing for a vowel as often as not (Gul-ya- vs Guli-a-).
_VOWELS_AND_GLIDES = set("aeiouy")


def phonetic_key(text: str) -> str:
    """Script-independent consonant key for fuzzy place-name matching.

    Both scripts are reduced to the same phoneme alphabet and then to their
    consonant skeleton, so a Bangla name and any of its romanisations produce
    one key. A leading vowel is kept, because it is the one position where
    romanisations do agree and dropping it would merge names that start
    differently.

    This is a **candidate-generation** key, not an identity test: it is
    deliberately lossy and two different places can share one. Section 5.3
    combines it with embedding similarity and geographic context before
    anything is treated as the same entity.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    text = normalize_bangla(text).lower()

    pieces: list[str] = []
    for char in text:
        if char in _BENGALI_TO_LATIN:
            pieces.append(_BENGALI_TO_LATIN[char])
        elif char.isalnum():
            pieces.append(char)
        elif char.isspace():
            pieces.append(" ")
    key = "".join(pieces)

    for source, target in _LATIN_FOLD:
        key = key.replace(source, target)

    out_words: list[str] = []
    for word in key.split():
        skeleton = [
            char
            for index, char in enumerate(word)
            if index == 0 or char not in _VOWELS_AND_GLIDES
        ]
        collapsed = re.sub(r"(.)\1+", r"\1", "".join(skeleton))
        if collapsed:
            out_words.append(collapsed)
    return " ".join(out_words)


# --- language classification (section 4.1) -------------------------------


@dataclass(frozen=True)
class LanguageGuess:
    """One label plus how it was reached, so a row can be audited later."""

    label: str
    confidence: float
    method: str
    iso: str = ""

    def as_row(self) -> dict[str, object]:
        return {
            "language_label": self.label,
            "language_confidence": round(self.confidence, 4),
            "language_method": self.method,
            "detected_iso": self.iso,
        }


def script_shares(text: str) -> tuple[float, float]:
    """Fraction of the text's letters that are Bengali, and that are Latin."""
    bengali = len(BENGALI_RE.findall(text or ""))
    latin = len(LATIN_RE.findall(text or ""))
    total = bengali + latin
    if total == 0:
        return 0.0, 0.0
    return bengali / total, latin / total


def script_word_counts(text: str) -> tuple[int, int]:
    """Words that are predominantly Bengali, and predominantly Latin.

    A word counts for whichever script supplies more of its letters, so a
    Bangla word carrying an English suffix is not double-counted.
    """
    bengali_words = latin_words = 0
    for word in (text or "").split():
        bengali = len(BENGALI_RE.findall(word))
        latin = len(LATIN_RE.findall(word))
        if bengali == 0 and latin == 0:
            continue
        if bengali >= latin:
            bengali_words += 1
        else:
            latin_words += 1
    return bengali_words, latin_words


# Function words that appear in romanised Bangla and not in English. Used only
# when no classifier has been trained; `run_phase3_language_pipeline.py --train`
# replaces this with a measured model and reports its F1.
BANGLISH_MARKERS = {
    "ache", "ase", "achhe", "khub", "onek", "valo", "bhalo", "kori", "korte",
    "korbo", "jabo", "jete", "jayga", "jaiga", "sundor", "shundor", "ki", "kew",
    "amar", "amader", "tomar", "apnar", "ekta", "theke", "jonno", "hoy", "hobe",
    "nai", "naai", "chilo", "gelam", "dekhte", "dekhlam", "boshe", "kheyechi",
    "ta", "te", "er", "ei", "oi", "shob", "sob", "kichu", "mone", "lagche",
}

# Words that look like the markers above but are ordinary English. Without this
# the heuristic calls half the English corpus Banglish ("ki" is rare, "ta" and
# "te" are not).
ENGLISH_DECOYS = {"ta", "te", "er", "ei", "oi", "ki"}


def _banglish_heuristic(text: str) -> tuple[bool, float]:
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return False, 0.0
    strong = BANGLISH_MARKERS - ENGLISH_DECOYS
    hits = sum(1 for w in words if w in strong)
    share = hits / len(words)
    # Two markers, or one in a short text, is the point where precision stops
    # being embarrassing on the committed corpus; it is a stopgap, not a result.
    return (hits >= 2 or (hits == 1 and len(words) <= 6)), min(1.0, share * 3)


def classify(
    text: str,
    banglish=None,
    fasttext_model=None,
    langdetect_fn=None,
) -> LanguageGuess:
    """Label one piece of text with the section 4.1 vocabulary.

    `banglish` is any object with `predict_one(text) -> (bool, float)`; passing
    the trained classifier is what turns the fallback heuristic off. The two
    language detectors are only consulted for Latin-script text that is not
    Banglish, to tell English from a third language.
    """
    text = normalize_bangla(text or "")
    if not text:
        return LanguageGuess("", 0.0, "empty")

    bengali_share, latin_share = script_shares(text)
    if bengali_share == 0.0 and latin_share == 0.0:
        return LanguageGuess("", 0.0, "no-letters")

    # Both scripts present in meaningful quantity: code-mixed, and no further
    # question needs answering.
    bengali_words, latin_words = script_word_counts(text)
    total_words = bengali_words + latin_words
    minority = min(bengali_words, latin_words)
    if (
        total_words
        and minority >= MIXED_MIN_WORDS
        and minority / total_words >= MIXED_MIN_SHARE
    ):
        return LanguageGuess("mixed", minority / total_words * 2, "script-mix")

    if bengali_share > latin_share:
        return LanguageGuess("bn", bengali_share, "script", "bn")

    # Latin-dominant. Banglish or a real Latin-script language?
    if banglish is not None:
        is_banglish, confidence = banglish.predict_one(text)
        method = "classifier"
    else:
        is_banglish, confidence = _banglish_heuristic(text)
        method = "heuristic"
    if is_banglish:
        # Romanised Bangla with an English clause in it is still code-mixed.
        label = "mixed" if _has_english_clause(text) else "bn-latn"
        return LanguageGuess(label, confidence, method, "bn-latn")

    # Too short for any detector to be trusted (see SHORT_TEXT_MAX).
    if len(text) < SHORT_TEXT_MAX:
        return LanguageGuess("en", latin_share, "short-text", "en")

    iso, iso_confidence = _detect_latin_language(text, fasttext_model, langdetect_fn)
    if iso and iso != "en":
        return LanguageGuess("other", iso_confidence, "lid", iso)
    return LanguageGuess("en", iso_confidence or latin_share, "lid" if iso else "script", iso or "en")


# A handful of unambiguous English function words. Their presence alongside
# Banglish markers is what separates "Kuakata khub sundor" (bn-latn) from
# "the food was good kintu the room was dirty" (mixed).
_ENGLISH_CLAUSE_RE = re.compile(
    r"\b(the|and|was|were|is|are|this|that|with|from|very|hotel|room|staff|place|food)\b"
)


def _has_english_clause(text: str) -> bool:
    return len(_ENGLISH_CLAUSE_RE.findall(text.lower())) >= 2


def _detect_latin_language(text, fasttext_model, langdetect_fn) -> tuple[str, float]:
    """Best available guess at a Latin-script language, or ("", 0.0)."""
    if fasttext_model is not None:
        try:
            labels, scores = fasttext_model.predict(text.replace("\n", " "), k=1)
            return labels[0].replace("__label__", ""), float(scores[0])
        except Exception:
            pass
    if langdetect_fn is not None:
        try:
            return langdetect_fn(text), 0.0
        except Exception:
            pass
    return "", 0.0


def load_fasttext(path):
    """Load lid.176 if both the package and the model file are available.

    Returns None rather than raising: section 4.1 prefers fastText, but it is a
    source build that does not install everywhere, and the pipeline must still
    run without it.
    """
    try:
        import fasttext  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return fasttext.load_model(str(path))
    except Exception:
        return None
