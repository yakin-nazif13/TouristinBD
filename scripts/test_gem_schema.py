"""Entity-layer tests — BUILD_PLAN section 5, focused on the grounding rule.

Section 5.2 promises that "every entity must be an exact substring of the
source text, or it is dropped", and calls that the project's no-hallucination
guarantee. These tests are that guarantee:

  1. an invented place name is dropped, not kept with a guess at offsets;
  2. a kept mention's offsets really index the source, so quoted evidence is
     the reviewer's words;
  3. the surface is re-read from the source, so a case or whitespace variant is
     stored as written rather than as the extractor typed it;
  4. the drop rate is reported, because section 6.1 wants it as a number;
  5. Bangla text grounds through normalisation, since composed and decomposed
     vowel signs render identically;
  6. the generic-name guard from section 5.1 ("the beach" vs a named stretch).

Cases use real strings from the corpus and the plan's own examples.

Run:
    .venv/bin/python scripts/test_gem_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gem_schema import (  # noqa: E402
    ENTITY_TYPES,
    MIN_INDEPENDENT_MENTIONS,
    PUBLISHABLE_STATES,
    VERIFICATION_STATES,
    VISIBILITY_LEVELS,
    GroundingReport,
    find_span,
    ground,
    is_generic,
    sentence_around,
    strip_qualifier,
)

PASSED: list[str] = []
FAILED: list[str] = []

# From BUILD_PLAN section 0: the kind of review the engine exists to mine.
REVIEW = (
    "Kuakata was lovely. We also took a boat to Fatrar Chor, which almost nobody "
    "visits. Get off at Fokirhat Bazar and take a CNG from there. The kotkoti "
    "shops near the gate are worth trying. Best season is winter."
)


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def test_vocabulary() -> None:
    print("section 5 vocabulary")
    check("the five entity types are those of 5.1",
          ENTITY_TYPES == ["PLACE", "FOOD", "ACTIVITY", "ACCESS", "TIP"], str(ENTITY_TYPES))
    check("the four visibility levels are those of 5.4",
          VISIBILITY_LEVELS == ["V0", "V1", "V2", "V3"], str(VISIBILITY_LEVELS))
    check("the four queue states are those of 5.7",
          VERIFICATION_STATES == ["candidate", "verified", "rejected", "sensitive"],
          str(VERIFICATION_STATES))
    # Section 5.7: sensitive items stay in the government register only.
    check("only `verified` is publishable", PUBLISHABLE_STATES == ["verified"],
          str(PUBLISHABLE_STATES))
    check("`sensitive` is never publishable", "sensitive" not in PUBLISHABLE_STATES)
    check("5.5's independent-mention minimum is at least 2", MIN_INDEPENDENT_MENTIONS >= 2,
          str(MIN_INDEPENDENT_MENTIONS))


def test_grounding_keeps_real_mentions() -> None:
    print("\ngrounding keeps what is really there")
    candidates = [
        {"surface": "Fatrar Chor", "entity_type": "PLACE"},
        {"surface": "kotkoti", "entity_type": "FOOD"},
        {"surface": "took a boat", "entity_type": "ACTIVITY"},
        {"surface": "Get off at Fokirhat Bazar and take a CNG", "entity_type": "ACCESS"},
        {"surface": "Best season is winter", "entity_type": "TIP"},
    ]
    mentions, report = ground("r1", REVIEW, candidates, extractor="test")
    check("all five real mentions survive", len(mentions) == 5, str(len(mentions)))
    check("nothing was dropped", report.dropped == 0, str(report.as_dict()))
    check("the drop rate is 0", report.drop_rate == 0.0, str(report.drop_rate))

    # The guarantee that makes evidence quotable.
    bad = [m for m in mentions if REVIEW[m.start:m.end] != m.surface]
    check("every offset really indexes the source text", not bad, str(bad[:2]))

    by_type = {m.entity_type: m.surface for m in mentions}
    check("the place is found", by_type.get("PLACE") == "Fatrar Chor", str(by_type))
    check("the food is found", by_type.get("FOOD") == "kotkoti", str(by_type))
    check("the access instruction is found",
          "Fokirhat Bazar" in by_type.get("ACCESS", ""), str(by_type))

    place = next(m for m in mentions if m.entity_type == "PLACE")
    check("the mention carries its sentence for evidence",
          "Fatrar Chor" in place.sentence and "Kuakata was lovely" not in place.sentence,
          place.sentence)
    check("the mention carries a phonetic key", place.phonetic != "", place.phonetic)
    check("the row shape is serialisable", set(place.as_row()) >= {
        "review_id", "entity_type", "surface", "start", "end", "match_kind", "sentence"})


def test_grounding_drops_hallucinations() -> None:
    print("\ngrounding drops what is not there (the no-hallucination guarantee)")
    candidates = [
        {"surface": "Fatrar Chor", "entity_type": "PLACE"},        # real
        {"surface": "Nilgiri Hills", "entity_type": "PLACE"},      # not in this review
        {"surface": "Cox's Bazar", "entity_type": "PLACE"},        # plausible, absent
        {"surface": "", "entity_type": "PLACE"},                   # empty
        {"surface": "kotkoti", "entity_type": "SNACK"},            # unknown type
    ]
    mentions, report = ground("r1", REVIEW, candidates, extractor="test")
    check("only the real mention survives", len(mentions) == 1, str([m.surface for m in mentions]))
    check("four candidates are dropped", report.dropped == 4, str(report.as_dict()))
    check("an invented place is recorded as not-in-source",
          report.dropped_reasons.get("not-in-source") == 2, str(report.dropped_reasons))
    check("an empty surface is its own reason",
          report.dropped_reasons.get("empty-surface") == 1, str(report.dropped_reasons))
    check("an unknown entity type is its own reason",
          any(k.startswith("unknown-type") for k in report.dropped_reasons),
          str(report.dropped_reasons))
    check("the drop rate is reported for 6.1", abs(report.drop_rate - 0.8) < 1e-9,
          str(report.drop_rate))
    check("dropped surfaces are sampled for diagnosis",
          "Nilgiri Hills" in report.dropped_surfaces, str(report.dropped_surfaces))


def test_match_kinds() -> None:
    print("\nhow forgiving the match is, and what it records")
    check("an exact hit is recorded as exact", find_span(REVIEW, "Fatrar Chor")[2] == "exact")
    check("a case variant is recorded as case", find_span(REVIEW, "fatrar chor")[2] == "case")
    check("extra internal whitespace is recorded as whitespace",
          find_span(REVIEW, "Fatrar  Chor")[2] == "whitespace")
    check("something absent returns None", find_span(REVIEW, "Nilgiri") is None)
    check("an empty surface returns None", find_span(REVIEW, "") is None)
    check("empty text returns None", find_span("", "anything") is None)

    # The surface is re-read from the source, so the stored form is the
    # reviewer's casing, not the extractor's.
    mentions, _ = ground("r1", REVIEW, [{"surface": "fatrar chor", "entity_type": "PLACE"}])
    check("a case variant is stored as the reviewer wrote it",
          mentions[0].surface == "Fatrar Chor", mentions[0].surface)

    # "Fatrar Chor" appears once in REVIEW, so a second claim of it is a claim
    # the text does not support.
    mentions, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE"},
        {"surface": "fatrar chor", "entity_type": "PLACE"},
    ])
    check("a second claim of a once-occurring name is dropped", len(mentions) == 1,
          str(len(mentions)))
    check("and is recorded as not-in-source",
          report.dropped_reasons.get("not-in-source") == 1, str(report.dropped_reasons))


def test_repeated_mentions() -> None:
    print("\na name said twice gives two mentions (not one and a phantom duplicate)")
    # The real corpus case: a Cox's Bazar review naming Cox's Bazar at two
    # positions. Collapsing them onto the first hit would under-count the
    # mentions section 5.5 scores on.
    twice = "Fatrar Chor was quiet. Later we returned to Fatrar Chor at sunset."
    mentions, report = ground("r9", twice, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE"},
        {"surface": "Fatrar Chor", "entity_type": "PLACE"},
    ])
    check("both occurrences become mentions", len(mentions) == 2, str(len(mentions)))
    check("nothing is dropped", report.dropped == 0, str(report.dropped_reasons))
    check("the two mentions have different spans",
          mentions[0].start != mentions[1].start,
          f"{mentions[0].start} vs {mentions[1].start}")
    check("both offsets index the source",
          all(twice[m.start:m.end] == "Fatrar Chor" for m in mentions))
    check("a third claim is dropped, since the text has only two",
          ground("r9", twice, [{"surface": "Fatrar Chor", "entity_type": "PLACE"}] * 3)[1].dropped == 1)

    # search_from is what makes that work.
    first = find_span(twice, "Fatrar Chor")
    second = find_span(twice, "Fatrar Chor", first[1])
    check("find_span resumes past an earlier hit", second is not None and second[0] > first[0],
          f"{first} then {second}")
    check("and returns None once they are exhausted",
          find_span(twice, "Fatrar Chor", second[1]) is None)


def test_offsets_are_verified_not_trusted() -> None:
    print("\noffsets from an extractor are verified, never trusted")
    # An extractor that knows where it matched passes the span through, which
    # is what keeps repeated mentions distinct. It is still checked.
    ok, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE",
         "start": REVIEW.find("Fatrar Chor"), "end": REVIEW.find("Fatrar Chor") + 11},
    ])
    check("a correct span is accepted", len(ok) == 1, str(report.dropped_reasons))

    bad, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE", "start": 0, "end": 11},
    ])
    check("a span that does not hold the surface is dropped", len(bad) == 0, str(len(bad)))
    check("with its own reason",
          report.dropped_reasons.get("offsets-do-not-hold-surface") == 1,
          str(report.dropped_reasons))

    out_of_range, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE", "start": 10_000, "end": 10_011},
    ])
    check("an out-of-range span is dropped", len(out_of_range) == 0)
    check("with its own reason",
          report.dropped_reasons.get("offsets-out-of-range") == 1, str(report.dropped_reasons))

    garbage, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE", "start": "x", "end": "y"},
    ])
    check("non-numeric offsets are dropped", len(garbage) == 0)
    check("with their own reason",
          report.dropped_reasons.get("bad-offsets") == 1, str(report.dropped_reasons))

    # The same span offered twice is a genuine duplicate.
    start = REVIEW.find("Fatrar Chor")
    twice, report = ground("r1", REVIEW, [
        {"surface": "Fatrar Chor", "entity_type": "PLACE", "start": start, "end": start + 11},
        {"surface": "Fatrar Chor", "entity_type": "PLACE", "start": start, "end": start + 11},
    ])
    check("an identical span is not counted twice", len(twice) == 1, str(len(twice)))
    check("and is recorded as a duplicate span",
          report.dropped_reasons.get("duplicate-span") == 1, str(report.dropped_reasons))


def test_bangla_grounding() -> None:
    print("\ngrounding Bangla text")
    bangla = "কুয়াকাটা থেকে নৌকা নিয়ে ফাতরার চর গিয়েছিলাম। খুব সুন্দর জায়গা।"
    mentions, report = ground("r2", bangla, [
        {"surface": "ফাতরার চর", "entity_type": "PLACE"},
        {"surface": "নৌকা", "entity_type": "ACTIVITY"},
    ], language="bn")
    check("Bangla mentions ground", len(mentions) == 2, str([m.surface for m in mentions]))
    check("offsets index the Bangla source",
          all(bangla[m.start:m.end] == m.surface for m in mentions))
    check("the language is carried", all(m.language == "bn" for m in mentions))

    # The danda must end a sentence, or evidence for a Bangla mention would be
    # the whole review.
    place = next(m for m in mentions if m.entity_type == "PLACE")
    check("the danda ends a sentence", "খুব সুন্দর" not in place.sentence, place.sentence)

    # A decomposed vowel sign renders identically to its composed form and
    # compares unequal, which is section 4.2's whole point. The review carries
    # the composed spelling; the extractor returns the decomposed one.
    composed_text = "ভালো জায়গা কোথা আছে এখানে"          # ো is U+09CB
    decomposed_surface = "কোথা"                 # same word, e + aa
    check("the two spellings really do differ as strings",
          decomposed_surface != "কোথা", "they were identical, so the test proves nothing")
    check("an exact search for the decomposed form fails",
          composed_text.find(decomposed_surface) == -1)

    located = find_span(composed_text, decomposed_surface)
    check("but grounding locates it through normalisation", located is not None, "not found")
    if located:
        start, end, kind = located
        check("the match kind is recorded as normalized", kind == "normalized", kind)
        check("the recovered span is the composed spelling in the review",
              composed_text[start:end] == "কোথা", repr(composed_text[start:end]))

    mentions, _ = ground("r3", composed_text, [
        {"surface": decomposed_surface, "entity_type": "PLACE"},
    ])
    check("the mention survives grounding", len(mentions) == 1, str(len(mentions)))
    check("and is stored as the reviewer spelled it",
          mentions and mentions[0].surface == "কোথা",
          repr(mentions[0].surface) if mentions else "no mention")


def test_generic_guard() -> None:
    print("\nthe generic-name guard (5.1's 'the beach' edge case)")
    check("'the beach' is generic", is_generic("the beach"))
    check("'The Beach' is generic regardless of case", is_generic("The Beach"))
    check("trailing punctuation does not hide it", is_generic("the beach."))
    check("a named stretch is not generic", not is_generic("Guliakhali Sea Beach"))
    check("'Fatrar Chor' is not generic", not is_generic("Fatrar Chor"))
    check("'kotkoti' is not generic", not is_generic("kotkoti"))
    check("an empty string counts as generic", is_generic(""))


def test_helpers() -> None:
    print("\nhelpers")
    check("a parenthetical qualifier is stripped",
          strip_qualifier("Sundarbans (Karamjal Wildlife Centre)") == "Sundarbans",
          strip_qualifier("Sundarbans (Karamjal Wildlife Centre)"))
    check("a name without one is unchanged",
          strip_qualifier("Lalbagh Fort") == "Lalbagh Fort")
    check("sentence_around handles a span at the start",
          sentence_around(REVIEW, 0, 7).startswith("Kuakata"), sentence_around(REVIEW, 0, 7))
    check("sentence_around handles a span at the end",
          "winter" in sentence_around(REVIEW, len(REVIEW) - 8, len(REVIEW) - 1),
          sentence_around(REVIEW, len(REVIEW) - 8, len(REVIEW) - 1))
    check("an empty report has a zero drop rate", GroundingReport().drop_rate == 0.0)


def main() -> None:
    print("Entity layer tests (BUILD_PLAN section 5)\n")
    test_vocabulary()
    test_grounding_keeps_real_mentions()
    test_grounding_drops_hallucinations()
    test_match_kinds()
    test_repeated_mentions()
    test_offsets_are_verified_not_trusted()
    test_bangla_grounding()
    test_generic_guard()
    test_helpers()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All entity layer tests passed.")


if __name__ == "__main__":
    main()
