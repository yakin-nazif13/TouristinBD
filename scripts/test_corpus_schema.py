"""Provenance schema tests — BUILD_PLAN section 3.5.

Section 3.5 adds six columns to the corpus: source_type, collected_at,
anchor_place, discovery_round, lat and lng. The two committed batches were
collected before any of them existed, so the thing most worth testing is that
adding them did not change what the old corpus produces, while a new batch
carrying them survives the whole way to processed_reviews.csv.

Checks, none of which need torch, a network or an API key:

  1. source_type derivation from the legacy `source` column, including the
     "booking.com" -> "booking" case the committed corpus actually contains;
  2. with_provenance fills every column and never invents a coordinate or a
     collection date;
  3. the Bangladesh bounding box rejects a swapped lat/lng pair;
  4. an import carrying coordinates and a snowball round reaches
     processed_reviews.csv with those values intact, while rows from the
     pre-3.5 batches stay blank rather than being back-filled with guesses;
  5. --discovery-round rejects a negative round.

Everything heavy runs on a throwaway copy of `data/` (TOURISTINBD_DATA_DIR);
the real corpus is never touched.

Run:
    .venv/bin/python scripts/test_corpus_schema.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

from corpus_schema import (  # noqa: E402
    PROVENANCE_COLUMNS,
    in_bangladesh,
    source_type_of,
    with_provenance,
)

DATA_DIR = REPO_ROOT / "data"
ADD_REVIEWS = REPO_ROOT / "scripts" / "add_reviews.py"
PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def test_source_type() -> None:
    print("source_type derivation")
    check("google_maps maps to itself", source_type_of("google_maps") == "google_maps")
    check("the corpus's 'booking.com' becomes 'booking'", source_type_of("booking.com") == "booking",
          source_type_of("booking.com"))
    check("case and padding are ignored", source_type_of("  Google Maps ") == "google_maps",
          source_type_of("  Google Maps "))
    check("an empty source gives an empty type", source_type_of(None) == "")
    # An unforeseen source must stay visible rather than being bucketed, so the
    # health report shows it as itself.
    check("an unknown source passes through", source_type_of("Reddit") == "reddit",
          source_type_of("Reddit"))


def test_with_provenance() -> None:
    print("\nwith_provenance")
    df = pd.DataFrame({
        "review_id": ["a", "b"],
        "source": ["google_maps", "booking.com"],
        "review_text_clean": ["x", "y"],
    })
    out = with_provenance(df)
    check("every provenance column is present", all(c in out.columns for c in PROVENANCE_COLUMNS),
          str([c for c in PROVENANCE_COLUMNS if c not in out.columns]))
    check("source_type is derived per row",
          list(out["source_type"]) == ["google_maps", "booking"], str(list(out["source_type"])))
    check("discovery_round defaults to 0 (anchor)", list(out["discovery_round"]) == [0, 0],
          str(list(out["discovery_round"])))
    # The important negative: a missing coordinate or scrape date must stay
    # missing. A fabricated one could not later be told apart from a real one.
    check("no coordinate is invented", out["lat"].isna().all() and out["lng"].isna().all())
    check("no collection date is invented", out["collected_at"].isna().all())
    check("no anchor place is invented", out["anchor_place"].isna().all())
    check("the input frame is not mutated", "source_type" not in df.columns)

    explicit = with_provenance(pd.DataFrame({
        "source": ["google_maps"], "source_type": ["youtube"], "discovery_round": [2],
    }))
    check("an explicit source_type is not overwritten by the derived one",
          explicit.loc[0, "source_type"] == "youtube", explicit.loc[0, "source_type"])
    check("an explicit discovery_round survives", int(explicit.loc[0, "discovery_round"]) == 2)


def test_bounding_box() -> None:
    print("\nBangladesh bounding box")
    check("Kuakata is inside", in_bangladesh(21.8123, 90.1234))
    check("Dhaka is inside", in_bangladesh(23.8103, 90.4125))
    # The most common real-world corruption: the pair arrives the wrong way round.
    check("a swapped pair is rejected", not in_bangladesh(90.1234, 21.8123))
    check("a coordinate in India is rejected", not in_bangladesh(28.6139, 77.2090))
    check("blank values are rejected", not in_bangladesh(None, None))
    check("non-numeric values are rejected", not in_bangladesh("x", "y"))


def test_import_carries_provenance() -> None:
    print("\nan import carrying 3.5 provenance")
    tmp = Path(tempfile.mkdtemp(prefix="touristinbd_schema_"))
    try:
        data = tmp / "data"
        data.mkdir()
        for name in ("real_reviews_batch1.csv", "real_reviews_booking_batch1.csv",
                     "place_geography.csv"):
            shutil.copy(DATA_DIR / name, data / name)

        export = tmp / "snowball.csv"
        export.write_text(
            "reviewId,title,text,textTranslated,originalLanguage,stars,publishedAtDate,"
            "location/lat,location/lng\n"
            "s1,Fatrar Chor,Khub sundor jayga,Very beautiful place,bn,5,2026-02-01,21.8123,90.1234\n"
            "s2,Fatrar Chor,Boat ride was great,,en,4,2026-02-02,21.8123,90.1234\n",
            encoding="utf-8",
        )

        env = dict(os.environ, TOURISTINBD_DATA_DIR=str(data))
        res = subprocess.run(
            [sys.executable, str(ADD_REVIEWS), str(export), "--source", "google_maps",
             "--name", "schema_test", "--source-type", "google_maps",
             "--anchor-place", "Kuakata Beach", "--discovery-round", "1"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        )
        check("the import succeeds", res.returncode == 0, res.stderr[-400:])
        check("the coordinate alias location/lat is recognised",
              "location/lat->lat" in res.stdout, res.stdout[-400:])

        out = pd.read_csv(data / "processed_reviews.csv")
        new = out[out["review_id"].isin(["s1", "s2"])]
        check("both new rows arrive", len(new) == 2, str(len(new)))
        check("source_type survives to the corpus",
              set(new["source_type"]) == {"google_maps"}, str(set(new["source_type"])))
        check("anchor_place survives", set(new["anchor_place"]) == {"Kuakata Beach"},
              str(set(new["anchor_place"])))
        check("the snowball round survives", set(new["discovery_round"]) == {1},
              str(set(new["discovery_round"])))
        check("coordinates survive and are inside Bangladesh",
              all(in_bangladesh(r.lat, r.lng) for r in new.itertuples()))
        check("collected_at is stamped", new["collected_at"].notna().all())

        # The regression that matters: pre-3.5 rows must not be back-filled.
        legacy = out[~out["review_id"].isin(["s1", "s2"])]
        check("legacy rows keep an empty source_type", legacy["source_type"].isna().all(),
              str(legacy["source_type"].dropna().unique()[:3]))
        check("legacy rows keep empty coordinates", legacy["lat"].isna().all())
        check("legacy rows are not claimed to come from an anchor page",
              legacy["anchor_place"].isna().all())
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_negative_round_refused() -> None:
    print("\nbad input")
    tmp = Path(tempfile.mkdtemp(prefix="touristinbd_schema_neg_"))
    try:
        data = tmp / "data"
        data.mkdir()
        export = tmp / "x.csv"
        export.write_text("reviewId,title,text,stars\nn1,Somewhere,Nice,5\n", encoding="utf-8")
        env = dict(os.environ, TOURISTINBD_DATA_DIR=str(data))
        res = subprocess.run(
            [sys.executable, str(ADD_REVIEWS), str(export), "--source", "google_maps",
             "--name", "neg", "--discovery-round", "-1"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        )
        check("a negative discovery round is refused", res.returncode != 0, res.stdout[-300:])
        check("the refusal explains itself", "discovery-round" in (res.stdout + res.stderr),
              res.stdout[-300:])
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    print("Corpus provenance schema tests (BUILD_PLAN 3.5)\n")
    test_source_type()
    test_with_provenance()
    test_bounding_box()
    test_import_carries_provenance()
    test_negative_round_refused()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All provenance schema tests passed.")


if __name__ == "__main__":
    main()
