"""Phase 4 — gazetteer and official visibility. BUILD_PLAN section 5.4.

    "Sources: OpenStreetMap Bangladesh extract (Geofabrik, free), Wikidata, the
     BTB/district official attraction lists where published, and each
     candidate's Google Maps presence and review count.
     Visibility levels:
       V0 not on any map or list
       V1 on the map, few reviews
       V2 on the map, moderately reviewed
       V3 well known / official"

V0 is the level that matters. It is what makes something a discovery rather
than a site everyone already lists, and section 5.5 scores it highest.

Because V0 is a claim that something is *absent* from the record, this module
is careful about one distinction that is easy to lose:

    "we looked and it is not there"   ->  V0
    "we could not look"               ->  unknown, never V0

A failed lookup, a rate-limited request or a network error records `unknown`.
Treating those as V0 would manufacture discoveries out of our own outages,
which is the single most damaging error this phase could make.

Two sources are queried live, both free and both requiring no key:

  Nominatim (OpenStreetMap)  one request per second, as its usage policy
                             requires, with a descriptive User-Agent.
  Wikidata                   returns 429 after a short burst, so requests are
                             paced and retried with exponential backoff.

Everything is cached in data/gazetteer_cache.json, keyed by name. A re-run
costs nothing and needs no network, which is what makes the pipeline
reproducible and lets CI run `--offline`.

Why sitelinks and importance rather than review counts: the plan's V1/V2 wording
refers to Google Maps review counts, which an extracted entity with no Maps page
of its own does not have. Wikidata sitelink count and Nominatim's importance
score are the closest free, documented proxies, and the thresholds below were
chosen by probing known and unknown places rather than guessed:

    Lalbagh Fort           OSM importance 0.41, 30 sitelinks   -> V3
    Kuakata                OSM importance 0.16,  9 sitelinks   -> V2
    Saint Martin's Island  absent from OSM,     15 sitelinks   -> V2
    Fatrar Chor            absent from both                    -> V0

But many extracted places *do* have a Maps page: they are on our own place list
(data/place_names.csv), with the Google review count recorded at import. A place
there is on a map by definition, so it is never V0. Without this, T-Badh (7,902
Google reviews) ranked as an undocumented gem because OpenStreetMap spells it
differently. The place list can only raise a level, never lower one, so it can
remove a false discovery but never create one.

A misspelling of a listed place ("Kantaji Temple" for Kantajew Temple) is not
matched automatically. Near matches are proposed in data/place_spellings.csv and
only an `accept` row is used, as with the Bangla names.

Run:
    .venv/bin/python scripts/build_gazetteer.py            # queries + caches
    .venv/bin/python scripts/build_gazetteer.py --offline  # cache only
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_schema import in_bangladesh  # noqa: E402
from gem_schema import VISIBILITY_LEVELS, strip_article, strip_qualifier  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_ENTITIES = DATA_DIR / "phase4_entities.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"
IN_VARIANTS = DATA_DIR / "phase4_entity_variants.csv"
IN_PLACE_LIST = DATA_DIR / "place_names.csv"
SPELLINGS = DATA_DIR / "place_spellings.csv"
CACHE = DATA_DIR / "gazetteer_cache.json"
OUT_CSV = DATA_DIR / "phase4_gazetteer.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_gazetteer_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_gazetteer_report.json"

USER_AGENT = (
    "TouristinBD-research/1.0 (CSE499 capstone, North South University; "
    "github.com/yakin-nazif13/TouristinBD)"
)

NOMINATIM_DELAY = 1.1   # its usage policy allows one request per second
WIKIDATA_DELAY = 1.0    # it starts returning 429 after a short burst
MAX_RETRIES = 4

# Nominatim returns the best string match, which for a short name can be
# something unrelated: "Mongla" matched a railway station with importance 0.0.
# Only these OSM categories count as a place being on the map.
PLACE_CATEGORIES = {
    "place", "natural", "historic", "tourism", "leisure", "waterway",
    "boundary", "landuse", "amenity", "building",
}

# Thresholds, fixed here and reported, in the same spirit as section 5.5's
# gem-score weights.
V3_SITELINKS = 20
V3_IMPORTANCE = 0.35
V2_SITELINKS = 5
V2_IMPORTANCE = 0.10

# Google Maps review counts for places on our own list: round order-of-magnitude
# boundaries, stated rather than fitted.
MAPS_V3_REVIEWS = 1000
MAPS_V2_REVIEWS = 100

# How alike a name must be to a listed place's to be proposed as a spelling of
# it (rapidfuzz ratio, 0-100). A proposal only; a person accepts or rejects.
SPELLING_MIN_SIMILARITY = 80

# Words that say what kind of place it is, not which one: "Kolatoli Beach" and
# "Kolatoli" are the same place, "Nilachal Tourist Center" and "Nilachal" too.
GENERIC_WORDS = {"tourist", "spot", "sea", "beach", "center", "centre", "area"}

UNKNOWN = "unknown"


class LookupUnavailable(RuntimeError):
    """The source could not be reached, as distinct from finding nothing."""


def _get_json(url: str, timeout: int = 20) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_with_backoff(url: str) -> dict | list:
    """Fetch with exponential backoff, raising LookupUnavailable if it never works.

    429 is expected from Wikidata rather than exceptional, so it is retried
    rather than treated as an answer.
    """
    delay = 1.5
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return _get_json(url)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise LookupUnavailable(f"HTTP {exc.code}") from exc
        except Exception as exc:  # network, timeout, malformed JSON
            last = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(delay + random.uniform(0, 0.4))
            delay *= 2
    raise LookupUnavailable(str(last))


def query_nominatim(name: str) -> dict:
    """OSM presence for a name, or {} when it is genuinely not found."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": f"{name}, Bangladesh", "format": "jsonv2", "limit": 3, "addressdetails": 1,
    })
    rows = _get_with_backoff(url)
    if not isinstance(rows, list):
        raise LookupUnavailable("unexpected Nominatim payload")

    for row in rows:
        category = row.get("category") or row.get("class") or ""
        if category not in PLACE_CATEGORIES:
            continue
        latitude, longitude = row.get("lat"), row.get("lon")
        # A coordinate outside Bangladesh is a wrong match, not a find.
        if not in_bangladesh(latitude, longitude):
            continue
        return {
            "osm_found": True,
            "osm_display_name": row.get("display_name", ""),
            "osm_category": category,
            "osm_type": row.get("type", ""),
            "osm_importance": round(float(row.get("importance") or 0.0), 4),
            "lat": float(latitude),
            "lng": float(longitude),
        }
    return {"osm_found": False}


def query_wikidata(name: str) -> dict:
    """Wikidata presence and sitelink count, or {} when not found."""
    search_url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "limit": 1,
    })
    payload = _get_with_backoff(search_url)
    hits = payload.get("search", []) if isinstance(payload, dict) else []
    if not hits:
        return {"wikidata_found": False}

    hit = hits[0]
    time.sleep(WIKIDATA_DELAY)
    detail_url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": hit["id"], "props": "sitelinks", "format": "json",
    })
    sitelinks = 0
    try:
        detail = _get_with_backoff(detail_url)
        sitelinks = len(detail["entities"][hit["id"]].get("sitelinks", {}))
    except (LookupUnavailable, KeyError, TypeError):
        # The entity exists; only its sitelink count is unknown. Recorded as
        # found with 0 sitelinks would understate it, so flag the gap.
        return {
            "wikidata_found": True, "wikidata_qid": hit["id"],
            "wikidata_label": hit.get("label", ""),
            "wikidata_description": hit.get("description", ""),
            "wikidata_sitelinks": None,
        }
    return {
        "wikidata_found": True, "wikidata_qid": hit["id"],
        "wikidata_label": hit.get("label", ""),
        "wikidata_description": hit.get("description", ""),
        "wikidata_sitelinks": sitelinks,
    }


def assign_visibility(record: dict) -> tuple[str, str]:
    """(level, reason) for one gazetteer record.

    Returns `unknown` when neither source could be consulted — never V0, which
    is a positive claim that the thing is absent from the record.
    """
    osm_ok = record.get("osm_status") == "ok"
    wd_ok = record.get("wikidata_status") == "ok"
    if not osm_ok and not wd_ok:
        return UNKNOWN, "neither source could be reached"

    importance = record.get("osm_importance") or 0.0
    sitelinks = record.get("wikidata_sitelinks")
    sitelinks = -1 if sitelinks is None else sitelinks
    on_osm = bool(record.get("osm_found"))
    on_wikidata = bool(record.get("wikidata_found"))

    if sitelinks >= V3_SITELINKS or importance >= V3_IMPORTANCE:
        return "V3", (
            f"well documented: {sitelinks} Wikidata sitelink(s), "
            f"OSM importance {importance}"
        )
    if sitelinks >= V2_SITELINKS or importance >= V2_IMPORTANCE:
        return "V2", (
            f"moderately documented: {sitelinks} sitelink(s), "
            f"OSM importance {importance}"
        )
    if on_osm or on_wikidata:
        where = "OpenStreetMap" if on_osm else "Wikidata"
        return "V1", f"present in {where} but barely documented"

    # Absent from both, and both were actually consulted.
    if osm_ok and wd_ok:
        return "V0", "not found in OpenStreetMap or Wikidata"
    consulted = "OpenStreetMap" if osm_ok else "Wikidata"
    return UNKNOWN, f"absent from {consulted}, but the other source was unreachable"


def core_name(name: str) -> str:
    """The form names are matched against the place list in: "T-Badh" = "t-badh"."""
    text = strip_article(str(name or "")).lower().replace("'", "").replace("’", "")
    words = re.sub(r"[^\w\s]", " ", text).split()
    return " ".join(w for w in words if w not in GENERIC_WORDS)


def load_place_list(path: Path = IN_PLACE_LIST) -> dict[str, dict]:
    """core name -> the listed place, its Google review count and coordinates.

    A place's own names (final, list and alias) are entered first, then the
    shorter forms query_forms derives from them, so a derived "Sundarbans" from
    "Sundarbans (Karamjal Wildlife Centre)" can never displace the list's own
    "The Sundarbans".
    """
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    out: dict[str, dict] = {}
    derived: list[tuple[str, dict]] = []
    for _, row in frame.iterrows():
        reviews = pd.to_numeric(row.get("google_review_count"), errors="coerce")
        record = {
            "place": str(row["canonical_name"]),
            "reviews": None if pd.isna(reviews) else int(reviews),
            "lat": row.get("lat"), "lng": row.get("lng"),
        }
        own = [row.get("canonical_name"), row.get("list_name")]
        if pd.notna(row.get("aliases")):
            own += str(row["aliases"]).split("|")
        own = [str(n) for n in own if pd.notna(n) and str(n).strip()]
        for name in own:
            out.setdefault(core_name(name), record)
            derived += [(core_name(form), record) for form in query_forms(name)]
    for key, record in derived:
        out.setdefault(key, record)
    out.pop("", None)
    return out


def load_spellings(path: Path = SPELLINGS) -> dict[str, str]:
    """Accepted misspelling -> listed place it names."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    frame = frame[frame["decision"].astype(str).str.strip().str.lower() == "accept"]
    return {core_name(v): str(p) for v, p in zip(frame["variant"], frame["place"])}


def match_place_list(names: list[str], place_list: dict[str, dict],
                     spellings: dict[str, str]) -> dict | None:
    """The listed place these names refer to, or None. Names in priority order."""
    for name in names:
        key = core_name(name)
        if key in spellings:
            hit = place_list.get(core_name(spellings[key]))
            if hit:
                return hit
        if key in place_list:
            return place_list[key]
    return None


def maps_visibility(hit: dict) -> tuple[str, str]:
    """(level, reason) from a listed place's Google review count."""
    reviews = hit.get("reviews")
    where = f"on our Google Maps place list as {hit['place']!r}"
    if reviews is None:
        return "V1", f"{where} (review count not recorded)"
    level = ("V3" if reviews >= MAPS_V3_REVIEWS
             else "V2" if reviews >= MAPS_V2_REVIEWS else "V1")
    return level, f"{where} with {reviews} Google review(s)"


def raise_with_place_list(level: str, reason: str, hit: dict | None) -> tuple[str, str]:
    """The higher of the OSM/Wikidata level and the place-list level."""
    if hit is None:
        return level, reason
    maps_level, maps_reason = maps_visibility(hit)
    if level == UNKNOWN or VISIBILITY_LEVELS.index(maps_level) > VISIBILITY_LEVELS.index(level):
        return maps_level, maps_reason
    return level, reason


def propose_spellings(names: list[str], place_list: dict[str, dict],
                      existing: pd.DataFrame | None) -> pd.DataFrame:
    """Near matches to listed places, for a person to accept or reject.

    A recorded decision is never overwritten; a new proposal starts pending.
    """
    from rapidfuzz import fuzz, process

    columns = ["variant", "place", "similarity", "decision", "reason"]
    rows = [] if existing is None else existing[columns].to_dict("records")
    known = {core_name(r["variant"]) for r in rows}
    keys = list(place_list)
    for name in names:
        key = core_name(name)
        if not name.isascii() or not key or key in place_list or key in known:
            continue
        best = process.extractOne(key, keys, scorer=fuzz.ratio)
        if best and best[1] >= SPELLING_MIN_SIMILARITY:
            rows.append({"variant": name, "place": place_list[best[0]]["place"],
                         "similarity": round(best[1], 1), "decision": "pending", "reason": ""})
            known.add(key)
    return pd.DataFrame(rows, columns=columns).sort_values(["place", "variant"]).reset_index(drop=True)


def load_cache() -> dict:
    """The cache, with incomplete records dropped so they are retried.

    Self-healing on load as well as on write: a cache written before the
    no-caching-failures rule existed still holds rate-limited entries, and
    without this they would stay `unknown` permanently.
    """
    if not CACHE.exists():
        return {}
    try:
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    complete = {
        name: record for name, record in raw.items()
        if isinstance(record, dict)
        and record.get("osm_status") == "ok"
        and record.get("wikidata_status") == "ok"
    }
    dropped = len(raw) - len(complete)
    if dropped:
        print(f"  dropped {dropped} incomplete cache entr(ies); they will be retried")
    return complete


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def query_forms(name: str) -> list[str]:
    """The name forms worth trying, most specific first.

    A parenthetical qualifier has to be stripped and the inner text tried on
    its own, or two UNESCO World Heritage sites in this corpus come out as
    undocumented: "Sompur Mahavihar (Paharpur)" is found as "Paharpur", and
    "Sundarbans (Karamjal Wildlife Centre)" as "Sundarbans". Scoring either V0
    would be an obvious error in the register.
    """
    forms = [name]
    base = strip_qualifier(name)
    if base and base != name:
        forms.append(base)
    # The text inside the parentheses is often the better-known name.
    inner = ""
    if "(" in name and ")" in name:
        inner = name[name.index("(") + 1:name.rindex(")")].strip()
    if inner and inner not in forms:
        forms.append(inner)
    # "the Sundarbans" is searched as "Sundarbans" too: the article only makes a match worse.
    for form in list(forms):
        plain = strip_article(form)
        if plain and plain not in forms:
            forms.append(plain)
    return forms


def lookup(name: str, cache: dict, offline: bool) -> dict:
    """One name's gazetteer record, from cache when present.

    Each name form is tried in turn and the first find wins, so a place is only
    called absent after every form has been checked.
    """
    if name in cache:
        return cache[name]
    if offline:
        return {
            "name": name, "osm_status": "not-cached", "wikidata_status": "not-cached",
            "osm_found": False, "wikidata_found": False,
        }

    record: dict = {"name": name}
    forms = query_forms(name)

    osm_status = None
    for form in forms:
        try:
            result = query_nominatim(form)
            osm_status = "ok"
            if result.get("osm_found"):
                record.update(result)
                record["osm_matched_form"] = form
                break
            record.setdefault("osm_found", False)
        except LookupUnavailable as exc:
            osm_status = osm_status or f"unavailable: {exc}"
        time.sleep(NOMINATIM_DELAY)
    record["osm_status"] = osm_status or "unavailable: no attempt"
    record.setdefault("osm_found", False)

    wd_status = None
    for form in forms:
        try:
            result = query_wikidata(form)
            wd_status = "ok"
            if result.get("wikidata_found"):
                record.update(result)
                record["wikidata_matched_form"] = form
                break
            record.setdefault("wikidata_found", False)
        except LookupUnavailable as exc:
            wd_status = wd_status or f"unavailable: {exc}"
        time.sleep(WIKIDATA_DELAY)
    record["wikidata_status"] = wd_status or "unavailable: no attempt"
    record.setdefault("wikidata_found", False)

    # Only a complete lookup is cached. Caching a rate-limited failure would
    # freeze it as `unknown` forever, so the name would never be checked again
    # and a real V0 or V3 could never be established for it.
    if record["osm_status"] == "ok" and record["wikidata_status"] == "ok":
        cache[name] = record
    return record


OUTPUT_COLUMNS = [
    "entity_id", "name", "visibility", "visibility_reason",
    "osm_found", "osm_category", "osm_type", "osm_importance", "osm_display_name",
    "wikidata_found", "wikidata_qid", "wikidata_label", "wikidata_sitelinks",
    "lat", "lng", "osm_status", "wikidata_status",
    "osm_wikidata_visibility", "maps_place", "maps_review_count", "coord_source",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true",
                        help="use only the cache; never touch the network")
    parser.add_argument("--limit", type=int, help="only the first N entities")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and re-query everything")
    args = parser.parse_args()

    if not IN_ENTITIES.exists():
        print(f"error: {IN_ENTITIES} does not exist; run scripts/resolve_entities.py first")
        return 1

    entities = pd.read_csv(IN_ENTITIES)
    # Only PLACE entities have a map presence to check. A TIP ("bargain for the
    # boat price") is not a thing OpenStreetMap could contain, and asking would
    # produce a meaningless V0.
    places = entities[entities["entity_type"].astype(str).str.upper() == "PLACE"]

    # And only entities actually found in review text. Resolution adds the
    # corpus's own place names to its pool so that a short form has an official
    # name to resolve against; those carry zero mentions and were never
    # discovered by anything. Scoring them produced the corpus's hotels as V0
    # "undocumented places" — a hotel missing from OpenStreetMap is not a
    # hidden gem, and publishing that list would discredit the whole register.
    mention_counts = pd.to_numeric(places.get("n_mentions"), errors="coerce").fillna(0)
    discovered = places[mention_counts > 0]
    skipped = len(places) - len(discovered)
    places = discovered
    if skipped:
        print(f"  skipping {skipped} entit(ies) with no mentions "
              "(corpus place names added for resolution, not discoveries)")
    if args.limit:
        places = places.head(args.limit)

    cache = {} if args.refresh else load_cache()
    print(f"Phase 4 — gazetteer over {len(places)} PLACE entit(ies)"
          + (" [offline]" if args.offline else ""))
    print(f"  cache: {len(cache)} name(s) already known")
    if not args.offline:
        estimate = sum(1 for n in places["canonical_name"].astype(str) if n not in cache)
        print(f"  {estimate} to look up, about {estimate * 3.2:.0f}s at the rate limits")

    # Every spelling resolution put in an entity is a name it may be listed under.
    names_of: dict[str, list[str]] = {}
    if IN_VARIANTS.exists():
        variants = pd.read_csv(IN_VARIANTS).sort_values("mentions", ascending=False)
        for entity_id, surface in zip(variants["entity_id"].astype(str), variants["surface"].astype(str)):
            names_of.setdefault(entity_id, []).append(surface)
    place_list = load_place_list()
    spellings = load_spellings()
    print(f"  place list: {len(place_list)} name form(s); {len(spellings)} accepted spelling(s)")

    rows = []
    for _, entity in places.iterrows():
        name = str(entity["canonical_name"])
        # Query the fuller official form when resolution found one: "Kuakata
        # Beach" is likelier to be on a map than a bare "Kuakata".
        record = lookup(name, cache, args.offline)
        base_level, base_reason = assign_visibility(record)
        hit = match_place_list([name, *names_of.get(str(entity["entity_id"]), [])], place_list, spellings)
        level, reason = raise_with_place_list(base_level, base_reason, hit)
        row = {
            "entity_id": entity["entity_id"],
            "name": name,
            "visibility": level,
            "visibility_reason": reason,
            **{k: record.get(k) for k in OUTPUT_COLUMNS if k not in
               ("entity_id", "name", "visibility", "visibility_reason")},
            "osm_wikidata_visibility": base_level,
            "maps_place": hit["place"] if hit else None,
            "maps_review_count": hit["reviews"] if hit else None,
            "coord_source": "openstreetmap" if pd.notna(record.get("lat")) else None,
        }
        # The map needs a point. OSM's is kept when there is one; otherwise the
        # listed place's own Google Maps coordinates.
        if row["coord_source"] is None and hit and pd.notna(hit["lat"]):
            row.update(lat=float(hit["lat"]), lng=float(hit["lng"]), coord_source="google_maps_place_list")
        rows.append(row)
        print(f"    {level:<7} {name}" + (f"  (was {base_level})" if level != base_level else ""))

    if not args.offline:
        save_cache(cache)

    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_CSV, index=False)

    existing = pd.read_csv(SPELLINGS) if SPELLINGS.exists() else None
    all_names = [n for _, e in places.iterrows()
                 for n in [str(e["canonical_name"]), *names_of.get(str(e["entity_id"]), [])]]
    proposals = propose_spellings(all_names, place_list, existing)
    proposals.to_csv(SPELLINGS, index=False, encoding="utf-8")
    pending = int((proposals["decision"] == "pending").sum())
    print(f"  {SPELLINGS.name}: {len(proposals)} spelling(s), {pending} awaiting a decision")

    counts = frame["visibility"].value_counts().to_dict()
    with_coords = int(frame["lat"].notna().sum())
    raised = frame[frame["visibility"] != frame["osm_wikidata_visibility"]]
    payload = {
        "n_entities": int(len(frame)),
        "by_visibility": {k: int(v) for k, v in counts.items()},
        "with_coordinates": with_coords,
        "coordinates_by_source": {k: int(v) for k, v in frame["coord_source"].value_counts().items()},
        "raised_by_place_list": int(len(raised)),
        "spellings_pending": pending,
        "thresholds": {
            "V3_sitelinks": V3_SITELINKS, "V3_importance": V3_IMPORTANCE,
            "V2_sitelinks": V2_SITELINKS, "V2_importance": V2_IMPORTANCE,
            "maps_V3_reviews": MAPS_V3_REVIEWS, "maps_V2_reviews": MAPS_V2_REVIEWS,
        },
        "sources": ["nominatim.openstreetmap.org", "wikidata.org", "data/place_names.csv (Google Maps)"],
        "offline": args.offline,
    }
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    v0 = frame[frame["visibility"] == "V0"]
    lines = [
        "# Phase 4 — Gazetteer and official visibility",
        "",
        "How documented each discovered place already is (BUILD_PLAN 5.4), from",
        "OpenStreetMap and Wikidata. **V0 — absent from both — is what makes",
        "something a discovery rather than a site everyone already lists.**",
        "",
        "A lookup that could not be performed is recorded as `unknown`, never V0.",
        "Treating an outage as absence would manufacture discoveries.",
        "",
        f"- PLACE entities checked: **{len(frame)}**",
        f"- Coordinates recovered: **{with_coords}** (these also serve section 3.6)",
        "",
        "| level | meaning | entities |",
        "| --- | --- | --- |",
    ]
    meanings = {
        "V0": "not on any map or list", "V1": "on the map, barely documented",
        "V2": "moderately documented", "V3": "well known / official",
        UNKNOWN: "could not be checked",
    }
    for level in [*VISIBILITY_LEVELS, UNKNOWN]:
        if level in counts:
            lines.append(f"| {level} | {meanings[level]} | {counts[level]} |")
    if not v0.empty:
        lines += [
            "", "## V0 — undocumented places found in review text", "",
            "Each of these was mentioned in a review of somewhere else and appears in",
            "neither OpenStreetMap nor Wikidata.", "",
        ]
        lines += [f"- **{row['name']}**" for _, row in v0.iterrows()]
    if not raised.empty:
        lines += [
            "", "## Raised by our own place list", "",
            "Found on our Google Maps place list, so on a map whatever OpenStreetMap",
            "and Wikidata say. Only ever raised, never lowered.", "",
            "| entity | OSM / Wikidata | now | listed as | Google reviews |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {r['name']} | {r['osm_wikidata_visibility']} | {r['visibility']} | "
            f"{r['maps_place']} | {'' if pd.isna(r['maps_review_count']) else int(r['maps_review_count'])} |"
            for _, r in raised.iterrows()
        ]
    if pending:
        lines += ["", f"**{pending} spelling(s) in `{SPELLINGS.name}` await a decision.** "
                  "Until accepted they are not used."]
    lines += [
        "", "## Thresholds", "",
        f"- V3: {V3_SITELINKS}+ Wikidata sitelinks, or OSM importance >= {V3_IMPORTANCE}",
        f"- V2: {V2_SITELINKS}+ sitelinks, or OSM importance >= {V2_IMPORTANCE}",
        "- V1: present in either source, below those",
        "- V0: absent from both, both having been successfully consulted",
        f"- On our place list: V3 at {MAPS_V3_REVIEWS}+ Google reviews, V2 at "
        f"{MAPS_V2_REVIEWS}+, otherwise V1 — never V0",
        "",
        "Chosen by probing known and unknown places, not assumed. The plan's V1/V2",
        "wording refers to Google Maps review counts, which an extracted entity",
        "with no Maps page of its own does not have; sitelinks and importance are",
        "the closest free documented proxies and are named here so the substitution",
        "is visible.",
    ]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  by visibility: {counts}")
    print(f"  coordinates recovered: {with_coords}")
    print(f"  wrote {OUT_CSV.name}, {OUT_REPORT_MD.name}, {OUT_REPORT_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
