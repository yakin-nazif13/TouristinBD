"""Gazetteer and visibility tests — BUILD_PLAN section 5.4.

V0 means "not on any map or list", and section 5.5 scores it highest. It is
therefore a claim the project makes about the *absence* of a record, and the
thing most worth testing is that we never make it carelessly:

    "we looked and it is not there"  ->  V0
    "we could not look"              ->  unknown

A rate-limited request, a network error or an uncached name in offline mode
must never become V0. Otherwise an outage on our side manufactures discoveries,
and a district officer is handed a register of places that were never checked.

Also covered: the threshold table against the real probe values, parenthetical
name handling (two UNESCO sites in this corpus depend on it), cache hygiene,
and the rule that only entities actually found in review text get scored.

No network: every test either calls a pure function or stubs the HTTP layer.

Run:
    .venv/bin/python scripts/test_gazetteer.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import build_gazetteer as gz  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f" -> {detail}" if detail else ""))


def record(**kwargs) -> dict:
    base = {
        "osm_status": "ok", "wikidata_status": "ok",
        "osm_found": False, "wikidata_found": False,
        "osm_importance": 0.0, "wikidata_sitelinks": 0,
    }
    base.update(kwargs)
    return base


def test_unknown_is_never_v0() -> None:
    print("the invariant: an unchecked place is never V0")

    both_down = record(osm_status="unavailable: HTTP 429",
                       wikidata_status="unavailable: timeout")
    level, reason = gz.assign_visibility(both_down)
    check("both sources unreachable -> unknown", level == gz.UNKNOWN, level)
    check("and the reason says so", "could be reached" in reason, reason)

    # The subtle one: one source worked and found nothing, the other failed.
    # That is still not enough to claim absence.
    half = record(osm_status="ok", osm_found=False,
                  wikidata_status="unavailable: HTTP 429")
    level, reason = gz.assign_visibility(half)
    check("one source down and the other empty -> unknown", level == gz.UNKNOWN, level)
    check("the reason names which source was unreachable",
          "unreachable" in reason, reason)

    not_cached = record(osm_status="not-cached", wikidata_status="not-cached")
    check("an uncached name in offline mode -> unknown",
          gz.assign_visibility(not_cached)[0] == gz.UNKNOWN)

    # And the positive case: both consulted, neither has it.
    level, reason = gz.assign_visibility(record())
    check("both consulted and empty -> V0", level == "V0", level)
    check("the V0 reason names both sources",
          "OpenStreetMap" in reason and "Wikidata" in reason, reason)


def test_thresholds() -> None:
    print("\nthe threshold table, against the real probe values")
    # Values measured from the live APIs while designing this.
    cases = [
        ("Lalbagh Fort", record(osm_found=True, osm_importance=0.4118,
                                wikidata_found=True, wikidata_sitelinks=30), "V3"),
        ("Kuakata", record(osm_found=True, osm_importance=0.16,
                           wikidata_found=True, wikidata_sitelinks=9), "V2"),
        ("Saint Martin's Island", record(osm_found=False, wikidata_found=True,
                                         wikidata_sitelinks=15), "V2"),
        ("Guliakhali Sea Beach", record(), "V0"),
        ("Fatrar Chor", record(), "V0"),
    ]
    for name, rec, expected in cases:
        actual = gz.assign_visibility(rec)[0]
        check(f"{name} -> {expected}", actual == expected, actual)

    # On the map but barely documented.
    barely = record(osm_found=True, osm_importance=0.02, wikidata_found=False)
    check("on the map with low importance -> V1",
          gz.assign_visibility(barely)[0] == "V1", gz.assign_visibility(barely)[0])

    # A Wikidata entity whose sitelink count could not be fetched is recorded
    # as None, and must not be read as zero.
    unknown_links = record(wikidata_found=True, wikidata_sitelinks=None)
    check("a found entity with an unknown sitelink count is at least V1",
          gz.assign_visibility(unknown_links)[0] == "V1",
          gz.assign_visibility(unknown_links)[0])

    check("every level used is from the plan's vocabulary",
          {gz.assign_visibility(r)[0] for _, r, _ in cases} <= set(gz.VISIBILITY_LEVELS))


def test_query_forms() -> None:
    print("\nname forms (two UNESCO sites in this corpus depend on these)")
    forms = gz.query_forms("Sompur Mahavihar (Paharpur)")
    check("the full name is tried first", forms[0] == "Sompur Mahavihar (Paharpur)", str(forms))
    check("the qualifier is stripped", "Sompur Mahavihar" in forms, str(forms))
    check("the parenthetical text is tried too", "Paharpur" in forms, str(forms))

    forms = gz.query_forms("Sundarbans (Karamjal Wildlife Centre)")
    check("Sundarbans is tried on its own", "Sundarbans" in forms, str(forms))
    check("Karamjal Wildlife Centre is tried", "Karamjal Wildlife Centre" in forms, str(forms))

    check("a plain name yields just itself", gz.query_forms("Kuakata") == ["Kuakata"])
    check("no duplicate forms", len(gz.query_forms("Kuakata")) == len(set(gz.query_forms("Kuakata"))))


def test_osm_match_filtering() -> None:
    print("\nOSM match filtering (a wrong match is not a find)")
    # Nominatim matched the string "Mongla" to a railway station with
    # importance 0.0. Only place-like categories count.
    check("railway is not a place category", "railway" not in gz.PLACE_CATEGORIES)
    check("place is", "place" in gz.PLACE_CATEGORIES)
    check("natural is", "natural" in gz.PLACE_CATEGORIES)
    check("historic is", "historic" in gz.PLACE_CATEGORIES)

    captured: list[str] = []

    def fake_get(url):
        captured.append(url)
        return [
            {"category": "railway", "type": "station", "importance": 0.0,
             "lat": "22.47", "lon": "89.59", "display_name": "a station"},
            {"category": "place", "type": "town", "importance": 0.21,
             "lat": "22.48", "lon": "89.60", "display_name": "the town"},
        ]

    original = gz._get_with_backoff
    gz._get_with_backoff = fake_get
    try:
        result = gz.query_nominatim("Mongla")
        check("the railway hit is skipped for the town",
              result.get("osm_type") == "town", str(result))
        check("the town's importance is taken", result.get("osm_importance") == 0.21, str(result))
        check("coordinates are recorded", result.get("lat") is not None)

        # A coordinate outside Bangladesh means the wrong place entirely.
        gz._get_with_backoff = lambda url: [
            {"category": "place", "type": "town", "importance": 0.5,
             "lat": "28.61", "lon": "77.20", "display_name": "Delhi"}
        ]
        check("a match outside Bangladesh is rejected",
              gz.query_nominatim("Somewhere")["osm_found"] is False)
    finally:
        gz._get_with_backoff = original


def test_cache_hygiene() -> None:
    print("\ncache hygiene")
    tmp = Path(tempfile.mkdtemp(prefix="gz_cache_"))
    try:
        cache_path = tmp / "gazetteer_cache.json"
        cache_path.write_text(json.dumps({
            "Good": {"osm_status": "ok", "wikidata_status": "ok", "osm_found": True},
            "RateLimited": {"osm_status": "ok", "wikidata_status": "unavailable: HTTP 429"},
            "Broken": "not a dict",
        }), encoding="utf-8")
        original = gz.CACHE
        gz.CACHE = cache_path
        try:
            cache = gz.load_cache()
            check("a complete record is kept", "Good" in cache, str(cache.keys()))
            check("a rate-limited record is dropped so it retries",
                  "RateLimited" not in cache, str(cache.keys()))
            check("a malformed record is dropped", "Broken" not in cache)
        finally:
            gz.CACHE = original

        check("a missing cache file is empty, not an error", gz.load_cache() is not None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_offline_never_touches_network() -> None:
    print("\noffline mode")
    original = gz._get_with_backoff

    def explode(url):
        raise AssertionError(f"offline mode made a request to {url}")

    gz._get_with_backoff = explode
    try:
        result = gz.lookup("Anything At All", {}, offline=True)
        check("offline mode makes no request", True)
        check("and reports not-cached rather than not-found",
              result["osm_status"] == "not-cached", str(result))
        check("which assigns unknown", gz.assign_visibility(result)[0] == gz.UNKNOWN)
    except AssertionError as exc:
        check("offline mode makes no request", False, str(exc))
    finally:
        gz._get_with_backoff = original


def test_only_discovered_entities() -> None:
    print("\nonly entities found in review text are scored")
    entities_path = REPO_ROOT / "data" / "phase4_entities.csv"
    gazetteer_path = REPO_ROOT / "data" / "phase4_gazetteer.csv"
    if not (entities_path.exists() and gazetteer_path.exists()):
        check("artifacts exist to check", False, "run resolve_entities and build_gazetteer")
        return

    entities = pd.read_csv(entities_path)
    gazetteer = pd.read_csv(gazetteer_path)
    scored = set(gazetteer["name"].astype(str))

    zero_mention = entities[pd.to_numeric(entities["n_mentions"], errors="coerce").fillna(0) == 0]
    leaked = sorted(scored & set(zero_mention["canonical_name"].astype(str)))
    check("no zero-mention entity is scored", not leaked, str(leaked[:4]))

    # The specific failure this rule prevents: the corpus's hotels appearing as
    # undocumented discoveries.
    v0_names = set(gazetteer[gazetteer["visibility"] == "V0"]["name"].astype(str))
    hotelish = [n for n in v0_names
                if any(w in n.lower() for w in ("hotel", "inn", "resort", "suites", "tower"))]
    check("no accommodation is listed as an undocumented place", not hotelish, str(hotelish))

    non_place = gazetteer.merge(
        entities[["canonical_name", "entity_type"]],
        left_on="name", right_on="canonical_name", how="left")
    types = set(non_place["entity_type"].dropna().astype(str).str.upper())
    check("only PLACE entities are scored", types <= {"PLACE"}, str(types))

    check("no row is left unknown after a complete run",
          "unknown" not in set(gazetteer["visibility"]),
          str(gazetteer[gazetteer["visibility"] == "unknown"]["name"].tolist()))


def test_place_list() -> None:
    print("\nour own Google Maps place list")
    listed = {
        "t badh": {"place": "T-Badh", "reviews": 7902, "lat": 24.36, "lng": 88.6},
        "kantajew temple": {"place": "Kantajew Temple", "reviews": 4827, "lat": 25.79, "lng": 88.67},
        "shashi lodge": {"place": "Shashi Lodge", "reviews": 66, "lat": 24.75, "lng": 90.4},
        "china matir pahar": {"place": "China Matir Pahar", "reviews": 201, "lat": 25.1, "lng": 90.6},
    }
    check("names match whatever their case and hyphens", gz.core_name("t-badh") == gz.core_name("T-Badh"))
    check("a kind-of-place word does not stop a match",
          gz.core_name("Kolatoli Beach") == gz.core_name("Kolatoli"))

    hit = gz.match_place_list(["T-badh"], listed, {})
    check("an exact listed name matches", hit and hit["place"] == "T-Badh", str(hit))
    level, reason = gz.raise_with_place_list("V0", "not found in OpenStreetMap or Wikidata", hit)
    check("a listed place is never V0 (T-Badh, 7,902 Google reviews)", level == "V3", level)
    check("and the reason names the listing", "T-Badh" in reason and "7902" in reason, reason)
    check("100-999 Google reviews is V2", gz.maps_visibility(listed["china matir pahar"])[0] == "V2")
    check("under 100 is V1", gz.maps_visibility(listed["shashi lodge"])[0] == "V1")
    check("an unknown count is still on the map, so V1",
          gz.maps_visibility({"place": "X", "reviews": None})[0] == "V1")
    check("the place list never lowers a level",
          gz.raise_with_place_list("V3", "well documented", listed["shashi lodge"])[0] == "V3")
    check("no listing leaves the level alone",
          gz.raise_with_place_list("V0", "absent", None) == ("V0", "absent"))

    check("a misspelling is not matched on its own", gz.match_place_list(["Kantaji Temple"], listed, {}) is None)
    accepted = {gz.core_name("Kantaji Temple"): "Kantajew Temple"}
    check("an accepted misspelling matches",
          (gz.match_place_list(["Kantaji Temple"], listed, accepted) or {}).get("place") == "Kantajew Temple")

    existing = pd.DataFrame([{"variant": "Shoshi Lodge", "place": "Shashi Lodge", "similarity": 91.7,
                              "decision": "reject", "reason": "test"}])
    proposed = gz.propose_spellings(["Kantaji Temple", "Shoshi Lodge", "T-Badh", "Gangamati"], listed, existing)
    by_variant = proposed.set_index("variant")
    check("a near spelling is proposed as pending",
          by_variant.loc["Kantaji Temple", "decision"] == "pending"
          and by_variant.loc["Kantaji Temple", "place"] == "Kantajew Temple", str(proposed))
    check("a recorded decision is kept", by_variant.loc["Shoshi Lodge", "decision"] == "reject")
    check("an exact listed name is not proposed", "T-Badh" not in by_variant.index)
    check("an unrelated name is not proposed", "Gangamati" not in by_variant.index)

    gazetteer_path = REPO_ROOT / "data" / "phase4_gazetteer.csv"
    if gazetteer_path.exists():
        frame = pd.read_csv(gazetteer_path)
        listed_v0 = frame[(frame["visibility"] == "V0") & frame["maps_place"].notna()]
        check("in the real register, no place on our list is V0", listed_v0.empty,
              str(listed_v0["name"].tolist()))
        lowered = [r["name"] for _, r in frame.iterrows()
                   if r["osm_wikidata_visibility"] in gz.VISIBILITY_LEVELS
                   and gz.VISIBILITY_LEVELS.index(r["visibility"])
                   < gz.VISIBILITY_LEVELS.index(r["osm_wikidata_visibility"])]
        check("and no level was lowered", not lowered, str(lowered))
        no_source = frame[frame["lat"].notna() & frame["coord_source"].isna()]
        check("every coordinate says where it came from", no_source.empty, str(no_source["name"].tolist()))
    spellings = REPO_ROOT / "data" / "place_spellings.csv"
    if spellings.exists():
        frame = pd.read_csv(spellings)
        rejects = frame[frame["decision"] == "reject"]
        check("place_spellings.csv: every reject says why",
              rejects["reason"].fillna("").astype(str).str.strip().ne("").all())


def main() -> None:
    print("Gazetteer and visibility tests (BUILD_PLAN 5.4)\n")
    test_unknown_is_never_v0()
    test_thresholds()
    test_query_forms()
    test_osm_match_filtering()
    test_cache_hygiene()
    test_offline_never_touches_network()
    test_only_discovered_entities()
    test_place_list()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All gazetteer tests passed.")


if __name__ == "__main__":
    main()
