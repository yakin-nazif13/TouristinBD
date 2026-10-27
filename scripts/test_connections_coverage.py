"""Place connections, district coverage, and the wider Bangla name mining.

  1. Connections: a link is counted in distinct reviews, never in mentions; a
     review's own place never links to itself; a link below the bar is not
     reported; every link carries a real sentence.
  2. Coverage: all 64 districts appear, including those with no data, and the
     status rule is the stated one.
  3. Mining: the loose key meets the spellings the exact key missed
     (সুন্দরবন / Sundarbans, জাফলং / Jaflong) without touching the shared
     phonetic key; a translation pair proposes the Bangla spelling of the place
     its translation names; hand-added rows and their source survive re-mining.

Run:
    .venv/bin/python scripts/test_connections_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import coverage_gaps as cg  # noqa: E402
import mine_bangla_place_names as mine  # noqa: E402
import place_connections as pc  # noqa: E402
from language_id import phonetic_key  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []
DATA = REPO_ROOT / "data"


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def test_connections() -> None:
    print("connections")
    frame = pd.DataFrame([
        # Two Kuakata reviews mention Gangamati; one names Fatrar Chor beside it.
        {"review_id": "r1", "host": "Kuakata Sea Beach", "mentioned": "Gangamati", "sentence": "Visit Gangamati."},
        {"review_id": "r1", "host": "Kuakata Sea Beach", "mentioned": "Gangamati", "sentence": "Gangamati again."},
        {"review_id": "r1", "host": "Kuakata Sea Beach", "mentioned": "Fatrar Chor", "sentence": "Fatrar Chor too."},
        {"review_id": "r2", "host": "Kuakata Sea Beach", "mentioned": "Gangamati", "sentence": "Gangamati forest."},
        {"review_id": "r2", "host": "Kuakata Sea Beach", "mentioned": "Fatrar Chor", "sentence": "and Fatrar Chor."},
        {"review_id": "r3", "host": "Kuakata Sea Beach", "mentioned": "Kuakata Sea Beach", "sentence": "self"},
        {"review_id": "r4", "host": "Lalbagh Fort", "mentioned": "Ahsan Manzil", "sentence": "once only"},
    ])
    links = pc.connections(frame, min_reviews=2).set_index(["place_a", "place_b"])
    check("a place mentioned in two reviews of another is linked",
          ("Gangamati", "Kuakata Sea Beach") in links.index, str(list(links.index)))
    check("a link counts reviews, not mentions",
          links.loc[("Gangamati", "Kuakata Sea Beach"), "n_reviews"] == 2)
    check("two places named in the same reviews are linked as 'together'",
          links.loc[("Fatrar Chor", "Gangamati"), "n_together"] == 2)
    check("a review's own place never links to itself",
          not any(a.casefold() == b.casefold() for a, b in links.index))
    check("a link from a single review is not reported", ("Ahsan Manzil", "Lalbagh Fort") not in links.index)
    check("every link carries a sentence", links["example_sentence"].str.len().gt(0).all())

    gems = pd.DataFrame([{"canonical_name": "Gangamati", "visibility": "V0"},
                         {"canonical_name": "Kuakata Sea Beach", "visibility": "V3"}])
    lesser = pc.links_to_lesser_known(pc.connections(frame, 2), gems)
    check("links to lesser-known places name the gem end",
          set(lesser["gem"]) == {"Gangamati"}, str(lesser.to_dict("records")))

    real = DATA / "phase4_place_connections.csv"
    if real.exists():
        table = pd.read_csv(real)
        check("real links all meet the bar", (table["n_reviews"] >= pc.MIN_REVIEWS).all())
        check("real links are never self-links",
              not (table["place_a"].str.casefold() == table["place_b"].str.casefold()).any())
        check("real link counts add up",
              (table["n_reviews"] <= table["n_found_in"] + table["n_together"]).all())


def test_coverage() -> None:
    print("\ncoverage")
    districts = pd.read_csv(DATA / "bd_districts.csv")
    check("the district list has all 64 districts", len(districts) == 64 and districts["district"].is_unique)
    check("and all 8 divisions", districts["division"].nunique() == 8)
    corpus = pd.DataFrame([
        {"review_id": f"r{i}", "place_name": "A", "review_date": "2026-01-01", "detected_language": "bn"}
        for i in range(120)
    ] + [
        {"review_id": "s1", "place_name": "B", "review_date": "2018-01-01", "detected_language": "en"},
    ])
    geography = pd.DataFrame([{"place_name": "A", "district": "Sylhet"},
                              {"place_name": "B", "district": "Bhola"}])
    table = cg.coverage(districts, corpus, geography, None, None).set_index("district")
    check("every district appears, data or not", len(table) == 64)
    check("a district with no reviewed place is 'no data'", table.loc["Barguna", "status"] == "no data")
    check("one place is 'thin' however many reviews it has", table.loc["Sylhet", "status"] == "thin")
    check("under the review bar is 'thin'", table.loc["Bhola", "status"] == "thin")
    check("the Bangla share is computed", table.loc["Sylhet", "bangla_share"] == 1.0)
    check("old reviews are not recent", table.loc["Bhola", "recent_reviews"] == 0)

    real = DATA / "coverage_by_district.csv"
    if real.exists():
        frame = pd.read_csv(real)
        geo = pd.read_csv(DATA / "place_geography.csv")
        check("every geography district is a known district",
              set(geo["district"].dropna()) <= set(districts["district"]),
              str(set(geo["district"].dropna()) - set(districts["district"])))
        check("the real table covers all 64", len(frame) == 64)


def test_mining() -> None:
    print("\nwider Bangla name mining")
    for bangla, english in (("সুন্দরবন", "Sundarbans"), ("জাফলং", "Jaflong"), ("মহাস্থানগড়", "Mahasthangarh")):
        check(f"the loose key meets {bangla} and {english}", mine.loose_key(bangla) == mine.loose_key(english),
              f"{mine.loose_key(bangla)} vs {mine.loose_key(english)}")
    check("the shared phonetic key is unchanged (Sundarbans keeps its s)", phonetic_key("Sundarbans").endswith("s"))
    found = mine.mine_with_source(["সুন্দরবনের গহীনে", "জাফলং যাবো"], ["Sundarbans", "Jaflong"])
    check("loose matches are labelled as such",
          found.get(("সুন্দরবন", "Sundarbans"), (None, ""))[1] == "loose sound", str(found))

    aligned = mine.mine_aligned([("কক্সবাজার সমুদ্র সৈকত সুন্দর", "Cox's Bazar sea beach is beautiful")],
                                ["Cox's Bazar"], ["কক্সবাজার সমুদ্র সৈকত সুন্দর", "কক্সবাজার যাবো"])
    check("a translation pair proposes the spelling as written, not over-cut",
          ("কক্সবাজার", "Cox's Bazar") in aligned, str(aligned))
    check("and counts the reviews it appears in", aligned.get(("কক্সবাজার", "Cox's Bazar")) == 2)
    check("ঃ used as a colon is not part of a name", mine.bangla_words("রামসাগরঃ সুন্দর") == ["রামসাগর", "সুন্দর"])

    existing = pd.DataFrame([{"bangla": "শশী লজ", "place": "Shashi Lodge", "reviews": 0, "decision": "accept",
                              "reason": "added by hand", "found_by": "by hand"}])
    merged = mine.merge_decisions({}, existing, {}, ["শশী লজকেও দেখুন", "অন্য কথা"])
    row = merged.iloc[0]
    check("a hand-added row survives re-mining with its source",
          row["decision"] == "accept" and row["found_by"] == "by hand")
    check("and gets its review count from the extractor's matcher", int(row["reviews"]) == 1, str(row["reviews"]))

    names = pd.read_csv(DATA / "place_names_bn.csv")
    check("place_names_bn.csv records how every row was found",
          names["found_by"].notna().all()
          and set(names["found_by"]) <= {"sound", "loose sound", "translation pair", "by hand"},
          str(set(names["found_by"])))


def main() -> None:
    print("Connections, coverage and wider name mining tests\n")
    test_connections()
    test_coverage()
    test_mining()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All connection and coverage tests passed.")


if __name__ == "__main__":
    main()
