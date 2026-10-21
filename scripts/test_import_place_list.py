"""Place list import tests.

The importer decides one final name per place, so every later count, rating and
itinerary depends on it being right. These tests cover:

  1. the rule: where one location has several names, the LONGER name is final;
  2. the building blocks: name matching, list validation, same-spot merging,
     and the split of ~9,500 reviews across places;
  3. the whole thing on a throwaway copy of the data: registry, geography with
     coordinates, scrape batches, a safe re-run, Phase 2 and add_reviews applying
     the final names, and the real `data/` folder left alone.

Run:
    .venv/bin/python scripts/test_import_place_list.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import import_place_list as ipl  # noqa: E402
import place_names as pn  # noqa: E402
import test_submissions as ts  # noqa: E402  (shared helpers: copy_data, run_script, fingerprint_dir)

DATA_DIR = REPO_ROOT / "data"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def make_list(path: Path, rows: list[dict]) -> Path:
    base = {"id": 0, "category": "Test", "google_rating": "4.4", "google_maps_url": "https://maps.example/?q=place_id:X"}
    pd.DataFrame([{**base, "id": i + 1, **r} for i, r in enumerate(rows)]).to_csv(path, index=False)
    return path


KUAKATA = dict(name="Kuakata Sea Beach", division="Barishal", district="Patuakhali", review_count=6898,
               latitude=21.8137, longitude=90.1224, place_id="PID_KUAKATA")
LALBAGH = dict(name="Lalbagh Fort", division="Dhaka", district="Dhaka", review_count=32191,
               latitude=23.7188, longitude=90.3881, place_id="PID_LALBAGH")
SITAKUNDA = dict(name="Chandranath Hill", division="Chattogram", district="Chattogram (Sitakunda)", review_count=2400,
                 latitude=22.8498, longitude=91.6372, place_id="PID_CHANDRA")
TINY = dict(name="Padma Garden Footbridge", division="Rajshahi", district="Rajshahi", review_count=28,
            latitude=24.3623, longitude=88.5969, place_id="PID_TINY")
RANGPUR = dict(name="Tajhat Palace", division="Rangpur", district="Rangpur", review_count=6068,
               latitude=25.7252, longitude=89.2799, place_id="PID_TAJHAT")


# ---------------------------------------------------------------------------
def test_names() -> None:
    print("\nnames: matching and the longer-name rule")
    check("case, spacing and curly quotes do not matter", pn.norm("  Saint  Martin’s ISLAND ") == "saint martin's island", pn.norm("  Saint  Martin’s ISLAND "))

    final, _ = ipl.choose_final("Kuakata Sea Beach", ["Kuakata Beach"], [])
    check("the longer name wins (list name longer than the corpus name)", final == "Kuakata Sea Beach", final)
    final, _ = ipl.choose_final("Karamjal", ["Sundarbans (Karamjal Wildlife Centre)"], [])
    check("…and the corpus name wins when it is the longer one", final == "Sundarbans (Karamjal Wildlife Centre)", final)
    final, _ = ipl.choose_final("Ab Cd", ["Ef Gh"], [])
    check("a tie goes to the name already in the corpus", final == "Ef Gh", final)
    final, _ = ipl.choose_final("Short", [], ["A much longer alias", "Mid alias"])
    check("an alias can win too", final == "A much longer alias", final)
    final, why = ipl.choose_final("Only Name", [], [])
    check("a place with one name keeps it", final == "Only Name" and why == "only name", f"{final} {why}")

    check("'Chattogram (Sitakunda)' splits into district and town", ipl.split_district("Chattogram (Sitakunda)") == ("Chattogram", "Sitakunda"))
    check("a plain district is also the town", ipl.split_district("Sylhet") == ("Sylhet", "Sylhet"))

    reg = pn.Registry(by_name={pn.norm("Kuakata Beach"): "Kuakata Sea Beach", pn.norm("Kuakata Sea Beach"): "Kuakata Sea Beach"},
                      by_id={"PID_K": "Kuakata Sea Beach"})
    names = pd.Series(["Kuakata Beach", "Lalbagh Fort", "kuakata  beach", "Unlisted Place", None], dtype="object")
    out, changed = pn.canonicalize(names, reg)
    check("known aliases become the final name (any spacing or case)",
          list(out[:3]) == ["Kuakata Sea Beach", "Lalbagh Fort", "Kuakata Sea Beach"], str(list(out)))
    check("unknown names pass through untouched", out[3] == "Unlisted Place" and pd.isna(out[4]))
    check("only real changes are reported", set(changed) == {"Kuakata Beach", "kuakata  beach"}, str(changed))
    out2, changed2 = pn.canonicalize(out, reg)
    check("applying it twice changes nothing (idempotent)", list(out2[:3]) == list(out[:3]) and not changed2, str(changed2))
    by_id, _ = pn.canonicalize(pd.Series(["Whatever Google Calls It"]), reg, pd.Series(["PID_K"]))
    check("a Google place_id beats the title", by_id[0] == "Kuakata Sea Beach", str(list(by_id)))
    empty_out, empty_changed = pn.canonicalize(names, pn.Registry())
    check("with no registry nothing changes", list(empty_out.fillna("∅")) == list(names.fillna("∅")) and not empty_changed)


def test_articles() -> None:
    print("\n'The Sundarbans' vs 'the Sundarbans' vs 'Sundarbans'")
    import build_gazetteer as bg
    import extract_mentions as em
    import gem_schema as gs

    check("a leading 'the' is dropped, any case or spacing",
          gs.strip_article("The Sundarbans") == "Sundarbans" and gs.strip_article("the   sundarbans") == "sundarbans")
    check("a word that merely starts with 'the' is left alone", gs.strip_article("Theatre Road") == "Theatre Road")
    check("a name that is only 'the' is not emptied", gs.strip_article("The") == "The")
    forms = bg.query_forms("the Sundarbans")
    check("the map lookup also searches without the article", "Sundarbans" in forms and forms[0] == "the Sundarbans", str(forms))
    check("…and still handles qualifiers", "Sundarbans" in bg.query_forms("Sundarbans (Karamjal Wildlife Centre)"))

    corpus = pd.DataFrame({"place_name": ["The Sundarbans", "Lalbagh Fort"]})
    pool = em.load_gazetteer(corpus)
    check("the extractor's name pool holds no 'the ...' names", not [n for n in pool if n.lower().startswith("the ")], str([n for n in pool if n.lower().startswith("the ")][:3]))
    check("…it holds the plain name instead", "Sundarbans" in pool)
    text = "We took a boat into the Sundarbans after Jaflong, and the Sundarbans were wild."
    found = [c for c in em.extract_gazetteer(text, "Lalbagh Fort", pool) if c["entity_type"] == "PLACE" and c["surface"] == "Sundarbans"]
    check("a review saying 'the Sundarbans' is recorded as 'Sundarbans', twice, with exact positions",
          len(found) == 2 and all(text[c["start"]:c["end"]] == "Sundarbans" for c in found), str(found))
    own = em.extract_gazetteer(text, "The Sundarbans", pool)
    check("a review of The Sundarbans itself does not count it as a discovery",
          not [c for c in own if c["surface"] == "Sundarbans"], str(own))


def test_list_and_merging(tmp: Path) -> None:
    print("\nthe list: validation, same-spot merging, allocation")

    def read(rows, **kw):
        return ipl.read_list(make_list(tmp / "l.csv", rows))

    _, errors, _ = read([{**KUAKATA, "division": "Atlantis"}])
    check("an unknown division is an error", any("Atlantis" in e for e in errors), str(errors))
    _, errors, _ = read([{**KUAKATA, "latitude": 90.1224, "longitude": 21.8137}])
    check("swapped coordinates are caught (outside Bangladesh)", any("outside Bangladesh" in e for e in errors), str(errors))
    _, errors, _ = read([{**KUAKATA, "latitude": "north"}])
    check("non-numeric coordinates are an error", bool(errors), str(errors))
    pd.DataFrame([{"name": "x", "division": "Dhaka"}]).to_csv(tmp / "bad.csv", index=False)
    _, errors, _ = ipl.read_list(tmp / "bad.csv")
    check("a missing column is named", any("missing column" in e and "place_id" in e for e in errors), str(errors))
    df, errors, notes = read([KUAKATA, {**KUAKATA, "name": "Kuakata repeated"}, LALBAGH, SITAKUNDA])
    check("a repeated place_id is dropped and reported", len(df) == 3 and any("repeated" in n for n in notes), str(notes))
    check("a clean list has no errors", not errors, str(errors))
    check("the town comes out of the district", df.loc[df.name == "Chandranath Hill", "city"].iloc[0] == "Sitakunda")

    # same spot listed twice (close, similar names) is one place; two viewpoints on one hill are two
    spot = dict(KUAKATA)
    twin = {**KUAKATA, "name": "Kuakata Sea Beach (main)", "place_id": "PID_TWIN", "review_count": 100,
            "latitude": KUAKATA["latitude"] + 0.0003}
    other = {**KUAKATA, "name": "Sunset Point", "place_id": "PID_SUNSET", "review_count": 300,
             "latitude": KUAKATA["latitude"] + 0.0012}
    df, _, _ = read([spot, twin, other])
    merged_df, merged, near = ipl.merge_close_duplicates(df)
    check("the same spot listed twice is merged", len(merged_df) == 2 and len(merged) == 1, str(merged))
    check("the busier entry keeps its place_id; the other id is remembered",
          "PID_TWIN" in merged_df.loc[merged_df.place_id == "PID_KUAKATA", "other_place_ids"].iloc[0], str(merged_df.other_place_ids.tolist()))
    check("a nearby but differently named spot stays separate and is reported", "Sunset Point" in set(merged_df.name) and near, str(near))

    alloc = ipl.weighted_waterfill([10.0, 10.0, 10.0], [100, 100, 100], 90)
    check("an even split of 90 is 30 each", alloc == [30, 30, 30], str(alloc))
    alloc = ipl.weighted_waterfill([1.0, 1.0, 1.0], [5, 100, 100], 90)
    check("a small place gives all it has and the rest is shared", alloc[0] == 5 and sum(alloc) == 90, str(alloc))
    alloc = ipl.weighted_waterfill([3.0, 1.0], [1000, 1000], 100)
    check("a heavier weight gets more", alloc[0] > alloc[1] and sum(alloc) == 100, str(alloc))
    alloc = ipl.weighted_waterfill([1.0, 1.0], [3, 4], 1000)
    check("asking for more than exists returns everything, not more", alloc == [3, 4], str(alloc))

    # two Chattogram places (one busy, one quiet) plus places in other divisions
    quiet = {**SITAKUNDA, "name": "Quiet Hill", "place_id": "PID_QUIET", "review_count": 120}
    frame = pd.DataFrame([KUAKATA, LALBAGH, SITAKUNDA, quiet, TINY, RANGPUR])
    frame["review_count"] = frame["review_count"].astype(int)
    left = {"PID_LALBAGH": 20}
    target = ipl.allocate(frame, left, 1000)
    check("the plan never exceeds the total", 0 < int(target.sum()) <= 1000, str(target.tolist()))
    check("a division's share is filled when its places can supply it",
          abs(int(target[frame.division == "Chattogram"].sum()) - round(1000 * ipl.DEFAULT_SHARES["Chattogram"] / sum(ipl.DEFAULT_SHARES.values()))) <= 1,
          str(target.tolist()))
    check("no place is asked for more than it has left",
          all(t <= rc - left.get(pid, 0) for t, rc, pid in zip(target, frame.review_count, frame.place_id)), str(target.tolist()))
    check("the tiny place gives at most what it has", int(target[frame.place_id == "PID_TINY"].iloc[0]) <= 28)
    check("within a division, the busier place gets more",
          int(target[frame.place_id == "PID_CHANDRA"].iloc[0]) > int(target[frame.place_id == "PID_QUIET"].iloc[0]), str(target.tolist()))
    forced = ipl.allocate(frame, left, 1000, {"Rangpur": 7})
    check("a --quota overrides one division", int(forced[frame.division == "Rangpur"].sum()) == 7, str(forced.tolist()))
    check("tiers round up to a size an Apify run can use", ipl.tier_for(60, 1000) == 100 and ipl.tier_for(5000, 9000) == 1600
          and ipl.tier_for(500, 30) == 50, f"{ipl.tier_for(60, 1000)} {ipl.tier_for(5000, 9000)} {ipl.tier_for(500, 30)}")


def synthetic_data_dir(root: Path) -> Path:
    """A tiny, self-contained data folder, so the test does not depend on the real corpus."""
    data = root / "data"
    data.mkdir(parents=True)
    rows = []
    for i, (place, source) in enumerate([("Kuakata Beach", "google_maps")] * 3 + [("Lalbagh Fort", "google_maps")] * 2
                                         + [("Hotel Blue", "booking.com")] * 2):
        rows.append({"review_id": f"S{i}", "place_name": place, "city": "", "category": "Test", "review_rating": 4,
                     "review_text": f"Review number {i} of {place}: a pleasant visit with friendly staff and lovely views.",
                     "review_date": "2026-01-01", "source": source})
    pd.DataFrame(rows).to_csv(data / "real_reviews_batch1.csv", index=False)
    pd.DataFrame([{"review_id": r["review_id"], "place_name": r["place_name"], "topic_id": 1} for r in rows]).to_csv(
        data / "reviews_with_topics.csv", index=False)
    pd.DataFrame([
        {"place_name": "Kuakata Beach", "city": "Kuakata", "district": "Patuakhali", "division": "Barishal", "place_kind": "attraction", "notes": "kept note"},
        {"place_name": "Lalbagh Fort", "city": "Dhaka", "district": "Dhaka", "division": "Dhaka", "place_kind": "attraction", "notes": ""},
        {"place_name": "Hotel Blue", "city": "Dhaka", "district": "Dhaka", "division": "Dhaka", "place_kind": "accommodation", "notes": ""},
    ]).to_csv(data / "place_geography.csv", index=False)
    (data / "place_aliases.csv").write_text("alias,place_id,note\nKuakata Beach,PID_KUAKATA,same beach\n")
    return data


def test_end_to_end(tmp: Path) -> None:
    print("\nthe whole import on a throwaway data folder")
    real_before = ts.fingerprint_dir(DATA_DIR)
    data = synthetic_data_dir(tmp)
    listing = make_list(tmp / "list.csv", [KUAKATA, LALBAGH, SITAKUNDA, TINY, RANGPUR])

    base = ts.run_script("run_phase2_preprocessing.py", data_dir=data)
    check("the starting corpus builds", base.returncode == 0, base.stderr[-300:])
    corpus_before = pd.read_csv(data / "processed_reviews.csv")
    check("it starts with the OLD name", "Kuakata Beach" in set(corpus_before.place_name), str(set(corpus_before.place_name)))

    def run(*extra):
        return ts.run_script("import_place_list.py", str(listing), "--total", "400", "--no-refresh", *extra, data_dir=data)

    dry = run("--dry-run")
    check("a dry run succeeds and says so", dry.returncode == 0 and "nothing written" in dry.stdout, dry.stdout[-300:] + dry.stderr[-300:])
    check("…and writes nothing", not (data / "place_names.csv").exists() and not (data / "scrape_batches").exists()
          and not (data / "scrape_plan.csv").exists())

    bad = ts.run_script("import_place_list.py", str(make_list(tmp / "bad.csv", [{**KUAKATA, "division": "Nowhere"}])),
                        "--no-refresh", data_dir=data)
    check("a bad list stops with exit 1 and a clear message", bad.returncode == 1 and "Nowhere" in bad.stdout, bad.stdout[-300:])
    check("…and writes nothing", not (data / "place_names.csv").exists())

    r = run()
    check("the import succeeds", r.returncode == 0, r.stdout[-500:] + r.stderr[-500:])
    if r.returncode != 0:
        return
    check("it reports the rename that is needed in the existing data",
          "'Kuakata Beach' -> 'Kuakata Sea Beach'" in r.stdout, r.stdout[-700:])
    check("hotels are not offered as look-alikes of tourist spots", "Hotel Blue" not in r.stdout.split("In the corpus but not matched")[-1]
          if "In the corpus but not matched" in r.stdout else True)

    reg = pd.read_csv(data / "place_names.csv", dtype=str).fillna("")
    row = reg[reg.place_id == "PID_KUAKATA"].iloc[0]
    check("the registry holds the final name and the other name", row.canonical_name == "Kuakata Sea Beach" and "Kuakata Beach" in row.aliases.split("|"), str(row.to_dict()))
    check("coordinates and the district are in the registry", float(row.lat) == KUAKATA["latitude"] and row.district == "Patuakhali")
    check("a town in brackets is split out", reg[reg.place_id == "PID_CHANDRA"].iloc[0].city == "Sitakunda")

    geo = pd.read_csv(data / "place_geography.csv", dtype=str).fillna("")
    check("the existing geography row was renamed, not duplicated",
          (geo.place_name == "Kuakata Sea Beach").sum() == 1 and (geo.place_name == "Kuakata Beach").sum() == 0, str(geo.place_name.tolist()))
    kua = geo[geo.place_name == "Kuakata Sea Beach"].iloc[0]
    check("…it gained coordinates and the place_id, and kept its own note", kua.lat == str(KUAKATA["latitude"]) and kua.place_id == "PID_KUAKATA" and kua.notes == "kept note", str(kua.to_dict()))
    check("a new place gets a full geography row", geo[geo.place_name == "Tajhat Palace"].iloc[0].division == "Rangpur"
          and geo[geo.place_name == "Tajhat Palace"].iloc[0].lat != "")
    check("a place that is not in the list (a hotel) is left alone", geo[geo.place_name == "Hotel Blue"].iloc[0].place_kind == "accommodation")

    plan = pd.read_csv(data / "scrape_plan.csv")
    check("the plan never asks for more than a place has", (plan.target_new <= plan.google_review_count).all(), str(plan.to_dict("records")[:2]))
    check("the plan stays within the requested total", 0 < plan.target_new.sum() <= 400, str(plan.target_new.sum()))
    check("reviews already in the corpus are counted against a place",
          int(plan.loc[plan.place_id == "PID_KUAKATA", "existing_reviews"].iloc[0]) == 3, str(plan.existing_reviews.tolist()))
    batches = sorted((data / "scrape_batches").rglob("*.json"))
    check("batch files and a pilot were written", batches and (data / "scrape_batches" / "pilot.json").exists(), str(len(batches)))
    first = json.loads(next(b for b in batches if "relevant" in str(b)).read_text())
    check("a batch is a valid Apify input with personal data off",
          "placeIds" in first and first["personalData"] is False and first["maxReviews"] in ipl.TIERS and first["reviewsSort"] == "mostRelevant", str(first)[:200])
    bangla = json.loads(next(b for b in batches if "bangla" in str(b)).read_text())
    check("the Bangla pass asks for Bangla", bangla["language"] == "bn", str(bangla)[:150])
    ids = {i for b in batches if "pilot" not in b.name for i in json.loads(b.read_text()).get("placeIds", [])}
    check("every batched id is a place in the list", ids <= set(reg.place_id), str(ids - set(reg.place_id)))
    targets = pd.read_csv(data / "scrape_targets.csv", dtype=str).fillna("")
    check("scrape_targets.csv lists every place; ones already scraped are 'partial'",
          len(targets) == 5 and targets[targets.place_name == "Lalbagh Fort"].iloc[0].status == "partial"
          and targets[targets.place_name == "Tajhat Palace"].iloc[0].status == "todo", str(targets.status.tolist()))
    check("the report file is written", (data / "place_import_report.md").exists())

    tracked = ("place_names.csv", "place_geography.csv", "scrape_plan.csv", "scrape_targets.csv")
    before = {n: (data / n).read_bytes() for n in tracked}
    batch_before = {str(p.relative_to(data)): p.read_bytes() for p in (data / "scrape_batches").rglob("*.json")}
    r2 = run()
    check("running it again changes nothing (safe to repeat)", r2.returncode == 0
          and before == {n: (data / n).read_bytes() for n in tracked}
          and batch_before == {str(p.relative_to(data)): p.read_bytes() for p in (data / "scrape_batches").rglob("*.json")},
          r2.stdout[-300:])

    # Phase 2 now gives every batch the final name; raw files are never edited
    raw_before = (data / "real_reviews_batch1.csv").read_bytes()
    p2 = ts.run_script("run_phase2_preprocessing.py", data_dir=data)
    check("Phase 2 runs", p2.returncode == 0, p2.stderr[-300:])
    corpus_after = pd.read_csv(data / "processed_reviews.csv")
    check("the same reviews are there, in the same order", list(corpus_after.review_id) == list(corpus_before.review_id))
    moved = corpus_before.place_name != corpus_after.place_name
    check("only the matched place was renamed", set(corpus_before.loc[moved, "place_name"]) == {"Kuakata Beach"}
          and set(corpus_after.loc[moved, "place_name"]) == {"Kuakata Sea Beach"} and int(moved.sum()) == 3, str(set(corpus_after.loc[moved, "place_name"])))
    other = [c for c in corpus_after.columns if c != "place_name"]
    check("nothing else about any review changed", corpus_before[other].equals(corpus_after[other]))
    check("the raw scrape file was not edited", (data / "real_reviews_batch1.csv").read_bytes() == raw_before)

    # derived files: only place_name values change
    topics = data / "reviews_with_topics.csv"
    snapshot = pd.read_csv(topics, dtype=str, keep_default_na=False)
    n = ipl.rewrite_place_column(topics, pn.load_registry(data))
    rewritten = pd.read_csv(topics, dtype=str, keep_default_na=False)
    check("derived files get the final name too", n == 3 and (rewritten.place_name == "Kuakata Sea Beach").sum() == 3, str(n))
    check("…and nothing else in them changes", snapshot.drop(columns="place_name").equals(rewritten.drop(columns="place_name")))
    check("rewriting again changes nothing", ipl.rewrite_place_column(topics, pn.load_registry(data)) == 0)

    # a new Apify export: the title differs, the place_id identifies it
    export = pd.DataFrame([
        {"title": "Kuakata Sea Beach, Bangladesh", "placeId": "PID_KUAKATA", "stars": 5, "text": "A calm evening on the sand, watched the sunrise too.",
         "textTranslated": "", "publishedAtDate": "2026-09-01", "reviewId": "R1"},
        {"title": "kuakata beach", "stars": 4, "text": "Second visit, the sunset point was the best part of the day.",
         "textTranslated": "", "publishedAtDate": "2026-09-02", "reviewId": "R2"},
        {"title": "Some Unlisted Ghat", "stars": 3, "text": "Boats leave early in the morning from this small ghat, bring cash.",
         "textTranslated": "", "publishedAtDate": "2026-09-03", "reviewId": "R3"},
    ])
    export.to_csv(tmp / "export.csv", index=False)
    add = ts.run_script("add_reviews.py", str(tmp / "export.csv"), "--source", "google_maps", "--name", "t1", "--no-preprocess", data_dir=data)
    check("add_reviews accepts the export", add.returncode == 0, add.stdout[-400:] + add.stderr[-300:])
    batch = pd.read_csv(data / "real_reviews_t1.csv")
    check("a place_id gives the final name whatever the title says", batch.loc[batch.review_id == "R1", "place_name"].iloc[0] == "Kuakata Sea Beach")
    check("a known alias gives the final name when there is no place_id", batch.loc[batch.review_id == "R2", "place_name"].iloc[0] == "Kuakata Sea Beach")
    check("an unknown place keeps its title", batch.loc[batch.review_id == "R3", "place_name"].iloc[0] == "Some Unlisted Ghat")
    check("the user is warned about the unknown place only", "Some Unlisted Ghat" in add.stdout and "place_aliases.csv" in add.stdout
          and "'Kuakata Sea Beach, Bangladesh'" not in add.stdout.split("not in data/place_names.csv")[-1], add.stdout[-500:])
    check("coordinates are filled from the list", abs(float(batch.loc[batch.review_id == "R1", "lat"].iloc[0]) - KUAKATA["latitude"]) < 1e-6)
    check("…but not invented for an unknown place", pd.isna(batch.loc[batch.review_id == "R3", "lat"].iloc[0]))

    check("the real data folder was not touched", ts.fingerprint_dir(DATA_DIR) == real_before, "")


def main() -> None:
    print("Place list import tests\n")
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        test_names()
        test_articles()
        test_list_and_merging(tmp)
        test_end_to_end(tmp)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All place list import tests passed.")


if __name__ == "__main__":
    main()
