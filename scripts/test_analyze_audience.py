"""Locals-versus-visitors tests — BUILD_PLAN section 5.6.

The first version of this module reported 100% coverage and labelled every one
of the 538 reviews, which looked like a success and was the opposite. pandas
hands a missing cell over as float NaN, `str(nan or "")` is the truthy string
"nan", and "nan" is not "bangladesh" — so the 300 Google Maps reviews with no
location were all silently labelled *foreign*, inverting the comparison.

So the tests here are mostly about missing data being recognised as missing,
plus the rule that a cell too small to compare is not reported as a finding.

Run:
    .venv/bin/python scripts/test_analyze_audience.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analyze_audience as aa  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def test_missing_values() -> None:
    print("missing data is recognised as missing (the bug this module shipped with)")
    for value, name in [(np.nan, "numpy NaN"), (float("nan"), "float nan"),
                        (None, "None"), (pd.NA, "pandas NA"), ("", "empty string"),
                        ("   ", "whitespace"), ("nan", "the string 'nan'"),
                        ("NULL", "the string 'NULL'"), ("N/A", "the string 'N/A'")]:
        check(f"{name} cleans to empty", aa._clean(value) == "", repr(aa._clean(value)))

    check("a real value survives", aa._clean("  Bangladesh ") == "bangladesh")
    check("a real foreign value survives", aa._clean("United Kingdom") == "united kingdom")


def test_classification() -> None:
    print("\nthe audience label")
    audience, basis = aa.classify_review("Bangladesh", "en")
    check("a Bangladesh location is domestic", audience == aa.DOMESTIC, audience)
    check("and the basis names the location", "Bangladesh" in basis, basis)

    audience, basis = aa.classify_review("United Kingdom", "en")
    check("a foreign location is foreign", audience == aa.FOREIGN, audience)
    check("and the basis names it", "United Kingdom" in basis, basis)

    # The case that was broken: no location, English text.
    audience, basis = aa.classify_review(np.nan, "en")
    check("no location plus English is unknown, not foreign",
          audience == aa.UNKNOWN, f"{audience} ({basis})")

    # Language is the fallback, and the only ethically available signal once
    # personal-data output is off.
    for label in ("bn", "bn-latn", "mixed"):
        got = aa.classify_review(np.nan, label)[0]
        check(f"no location but {label} text is domestic", got == aa.DOMESTIC, got)

    check("no location and `other` language is unknown",
          aa.classify_review(np.nan, "other")[0] == aa.UNKNOWN)
    check("a location beats the language signal",
          aa.classify_review("Germany", "bn")[0] == aa.FOREIGN,
          "a stated location is the stronger claim")


def test_small_cells_not_reported() -> None:
    print("\na cell too small to compare is not a finding")
    mentions = pd.DataFrame({
        "review_id": ["r1", "r2", "r3"],
        "entity_type": ["PLACE", "PLACE", "PLACE"],
    })
    audience = pd.DataFrame({
        "review_id": ["r1", "r2", "r3"],
        "audience": [aa.DOMESTIC, aa.FOREIGN, aa.UNKNOWN],
    })
    frame = aa.compare(mentions, audience, "entity_type")
    row = frame.iloc[0]
    check("one mention each side is not comparable", not row["comparable"],
          f"domestic={row['domestic_mentions']} foreign={row['foreign_mentions']}")
    check("the counts are still reported for completeness",
          row["domestic_mentions"] == 1 and row["foreign_mentions"] == 1, str(dict(row)))
    check("unknown mentions are counted separately, not dropped",
          row["unknown_mentions"] == 1, str(row["unknown_mentions"]))

    # With enough on both sides it becomes comparable.
    n = aa.MIN_CELL
    big = pd.DataFrame({
        "review_id": [f"d{i}" for i in range(n)] + [f"f{i}" for i in range(n)],
        "entity_type": ["PLACE"] * (2 * n),
    })
    big_audience = pd.DataFrame({
        "review_id": big["review_id"],
        "audience": [aa.DOMESTIC] * n + [aa.FOREIGN] * n,
    })
    row = aa.compare(big, big_audience, "entity_type").iloc[0]
    check(f"{n} each side is comparable", row["comparable"], str(dict(row)))
    # Shares are within-audience, so an imbalanced split is still readable.
    check("shares are computed within each audience",
          abs(row["domestic_share"] - 1.0) < 1e-9 and abs(row["foreign_share"] - 1.0) < 1e-9,
          str(dict(row)))


def test_local_guide_excluded() -> None:
    print("\nthe excluded proxy")
    source = (REPO_ROOT / "scripts" / "analyze_audience.py").read_text(encoding="utf-8")
    check("reviewer_is_local_guide is never read as a signal",
          "review.get(\"reviewer_is_local_guide\")" not in source
          and "row['reviewer_is_local_guide']" not in source,
          "it is referenced as data, not just discussed")
    check("the exclusion is documented in the module",
          "contribution volume" in source, "no rationale recorded")

    corpus = pd.read_csv(REPO_ROOT / "data" / "processed_reviews.csv")
    flag = corpus["reviewer_is_local_guide"].dropna()
    if len(flag):
        true_share = (flag.astype(str).str.lower() == "true").mean()
        check("the flag really is near-constant on this corpus, as claimed",
              true_share > 0.85, f"{true_share:.1%} True")


def test_real_output() -> None:
    print("\nagainst the real output")
    path = REPO_ROOT / "data" / "phase4_review_audience.csv"
    if not path.exists():
        check("audience output exists", False, "run scripts/analyze_audience.py")
        return
    frame = pd.read_csv(path)
    counts = frame["audience"].value_counts().to_dict()

    check("all three labels are used", set(counts) <= {aa.DOMESTIC, aa.FOREIGN, aa.UNKNOWN},
          str(counts))
    # The regression guard: unknown must not be zero on a corpus where 300
    # reviews have no location.
    check("unknown is not empty", counts.get(aa.UNKNOWN, 0) > 0,
          "every review got labelled, which was the original bug")
    check("fewer than all reviews are labelled",
          counts.get(aa.DOMESTIC, 0) + counts.get(aa.FOREIGN, 0) < len(frame),
          "100% coverage means missing values are being misread again")

    corpus = pd.read_csv(REPO_ROOT / "data" / "processed_reviews.csv")
    with_location = corpus["user_location"].notna().sum()
    labelled_by_location = (frame["basis"].astype(str).str.startswith("stated location")).sum()
    check("the location-labelled count matches the corpus",
          labelled_by_location == with_location,
          f"{labelled_by_location} labelled vs {with_location} with a location")

    check("every row records how it was decided", frame["basis"].notna().all())


def main() -> None:
    print("Locals-versus-visitors tests (BUILD_PLAN 5.6)\n")
    test_missing_values()
    test_classification()
    test_small_cells_not_reported()
    test_local_guide_excluded()
    test_real_output()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All locals-versus-visitors tests passed.")


if __name__ == "__main__":
    main()
