"""Language pipeline tests — BUILD_PLAN sections 4.1 and 4.2.

The cases are taken from the plan and from the committed corpus rather than
invented, so a pass means the thing the plan actually asks for works:

  * section 4.1's four-way label, including the `bn-latn` case the current
    detector gets wrong ("Khub sundor jayga" -> en);
  * section 4.2's normalisation, on the vowel-sign and nukta sequences that
    render identically and compare unequal;
  * the phonetic key collapsing the real variant groups the plan names:
    Guliakhali / Guliyakhali / Gulyakhali (line 67) and Chor Bijoy / Char
    Bijoy (line 318), and a Bangla name meeting its own romanisation;
  * the Dutch review in the corpus not being labelled English.

Run:
    .venv/bin/python scripts/test_language_id.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from language_id import (  # noqa: E402
    SHORT_TEXT_MAX,
    classify,
    normalize_bangla,
    phonetic_key,
    script_shares,
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def test_four_way_label() -> None:
    print("section 4.1 — the four-way label")

    bn = classify("গিজার কাজ করে না")  # a real topic keyword from Phase 3
    check("Bangla script -> bn", bn.label == "bn", f"{bn.label} via {bn.method}")

    # The bug this whole section exists to fix.
    banglish = classify("Khub sundor jayga, onek valo lagche")
    check("Banglish -> bn-latn (not en)", banglish.label == "bn-latn",
          f"{banglish.label} via {banglish.method}")

    english = classify("The sunset view from the beach was stunning and we walked for hours")
    check("English -> en", english.label == "en", f"{english.label} via {english.method}")

    mixed_script = classify("রুম ভালো but the staff was rude এবং নোংরা")
    check("Bangla + English script -> mixed", mixed_script.label == "mixed",
          f"{mixed_script.label} via {mixed_script.method}")

    mixed_latin = classify("khub bhalo ache kintu the room was dirty and the staff was rude")
    check("Banglish with an English clause -> mixed", mixed_latin.label == "mixed",
          f"{mixed_latin.label} via {mixed_latin.method}")

    # One stray English word must not make a Bangla sentence code-mixed.
    check("a lone English word stays bn",
          classify("আমরা hotel টা খুব পছন্দ করেছি").label == "bn",
          classify("আমরা hotel টা খুব পছন্দ করেছি").label)

    check("empty text gets no label", classify("").label == "")
    check("punctuation only gets no label", classify("!!! ... ???").label == "")


def test_short_text_guard() -> None:
    print("\nthe short-text guard (Phase 2's rule, not a new one)")
    import run_phase2_preprocessing as phase2

    check("SHORT_TEXT_MAX matches Phase 2's value",
          SHORT_TEXT_MAX == phase2.SHORT_TEXT_MAX,
          f"language_id={SHORT_TEXT_MAX} phase2={phase2.SHORT_TEXT_MAX}")

    try:
        from langdetect import DetectorFactory, detect
        DetectorFactory.seed = 0
    except ImportError:
        check("langdetect available (skipped)", True, "not installed")
        return

    # The three real rows langdetect gets wrong on the committed corpus.
    for text in ("Exceptional. Beautyful", "Very poor. Dirty property", "Good. Good. Good"):
        guess = classify(text, langdetect_fn=detect)
        check(f"short English stays en: {text!r}", guess.label == "en",
              f"{guess.label} ({guess.iso}) via {guess.method}")

    # The guard must not swallow short Banglish — the classifier runs first.
    short_banglish = classify("khub valo jayga")
    check("short Banglish is still bn-latn", short_banglish.label == "bn-latn",
          f"{short_banglish.label} via {short_banglish.method}")


def test_other_language() -> None:
    print("\nthe corpus's Dutch review is not English")
    try:
        from langdetect import DetectorFactory, detect
        DetectorFactory.seed = 0
    except ImportError:
        check("langdetect available (skipped)", True, "not installed")
        return
    dutch = (
        "Het hotel was schoon en het personeel was vriendelijk, maar de kamer "
        "was erg klein en het ontbijt viel een beetje teleur."
    )
    guess = classify(dutch, langdetect_fn=detect)
    check("Dutch -> other, not en", guess.label == "other", f"{guess.label} ({guess.iso})")
    check("the ISO code is recorded", guess.iso == "nl", guess.iso)


def test_normalisation() -> None:
    print("\nsection 4.2 — Bangla normalisation")
    # These pairs render identically and compare unequal. That is the failure
    # mode section 4.2 calls "silently break matching".
    composed, sequence = "ো", "ো"          # o vs e+aa
    check("the o vowel sign is composed",
          normalize_bangla("ক" + sequence) == normalize_bangla("ক" + composed),
          repr(normalize_bangla("ক" + sequence)))

    nukta_pairs = [("ড়", "ড়"), ("ঢ়", "ঢ়"), ("য়", "য়")]
    check("nukta forms are composed",
          all(normalize_bangla(a) == normalize_bangla(b) for a, b in nukta_pairs))

    check("zero-width joiners are stripped",
          normalize_bangla("গুলি‌য়াখালি") == normalize_bangla("গুলিয়াখালি"))
    check("the BOM is stripped", normalize_bangla("﻿কক") == "কক")
    check("whitespace is collapsed", normalize_bangla("  ক   খ  ") == "ক খ")
    check("non-strings give empty", normalize_bangla(None) == "")


def test_phonetic_key() -> None:
    print("\nsection 4.2 — the phonetic matching key")

    # BUILD_PLAN line 67: these three spellings of one place already appear.
    variants = ["Guliakhali", "Guliyakhali", "Gulyakhali"]
    keys = {phonetic_key(v) for v in variants}
    check("the three Guliakhali spellings share one key", len(keys) == 1,
          str({v: phonetic_key(v) for v in variants}))

    # BUILD_PLAN line 318.
    check("Chor Bijoy and Char Bijoy share a key",
          phonetic_key("Chor Bijoy") == phonetic_key("Char Bijoy"),
          f"{phonetic_key('Chor Bijoy')} vs {phonetic_key('Char Bijoy')}")

    check("Srimangal and Sreemangal share a key",
          phonetic_key("Srimangal") == phonetic_key("Sreemangal"),
          f"{phonetic_key('Srimangal')} vs {phonetic_key('Sreemangal')}")

    # The cross-script case: this is what lets a Bangla mention of a place meet
    # an English one during Phase 4 entity resolution.
    check("a Bangla name meets its romanisation",
          phonetic_key("কুয়াকাটা") == phonetic_key("Kuakata"),
          f"{phonetic_key('কুয়াকাটা')} vs {phonetic_key('Kuakata')}")

    # And the negative: unrelated places must not collide, or resolution would
    # merge them.
    check("unrelated places do not collide",
          phonetic_key("Kuakata") != phonetic_key("Jaflong"))
    check("empty text gives an empty key", phonetic_key("") == "")


def test_script_shares() -> None:
    print("\nscript shares")
    bengali, latin = script_shares("কক ab")
    check("shares are computed over letters only", abs(bengali - 0.5) < 1e-9 and abs(latin - 0.5) < 1e-9,
          f"{bengali}/{latin}")
    check("digits and punctuation do not count", script_shares("123 !!!") == (0.0, 0.0))


def main() -> None:
    print("Language pipeline tests (BUILD_PLAN 4.1, 4.2)\n")
    test_four_way_label()
    test_short_text_guard()
    test_other_language()
    test_normalisation()
    test_phonetic_key()
    test_script_shares()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All language pipeline tests passed.")


if __name__ == "__main__":
    main()
