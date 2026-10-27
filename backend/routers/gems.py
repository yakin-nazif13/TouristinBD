"""The gem register: hidden places, where they are, and what each place offers.

BUILD_PLAN sections 5.4-5.7. `/api/entities` serves everything resolution found;
these endpoints serve the part a visitor sees — scored places with a point on
the map, and the foods, activities and transport attached to the places they
were found in.

Two things are carried on every row rather than left to the frontend:

- **Where a point came from.** `coord_source` is `openstreetmap`,
  `google_maps_place_list`, or `near_host_place` — an undocumented place has no
  coordinates of its own, so it is shown at the place whose reviews mention it,
  and `near_place` says which.
- **How fresh the evidence is.** The reviews go back to 2011. A gem with no
  review inside the recency window is still listed, because the evidence is
  real, but it is marked `old` and `needs_recent_confirmation`, and a place's
  transport or prices with no recent review are marked `stale`.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db

router = APIRouter(prefix="/api", tags=["gems"])

VISIBILITY_HELP = {
    "V0": "not on any map or list",
    "V1": "on the map, few reviews",
    "V2": "on the map, moderately reviewed",
    "V3": "well known / official",
}

# Facts about a place that go out of date. A food or an activity mentioned in
# 2018 is probably still there; a 2018 bus fare or boat route may not be.
PERISHABLE_TYPES = {"ACCESS", "TIP"}

GEM_FIELDS = """
    entity_id, canonical_name, gem_rank, gem_score, n_reviews, n_mentions,
    visibility, visibility_reason, already_official, maps_place, maps_review_count,
    wikidata_qid, lat, lng, coord_source, near_place, divisions, state, publishable,
    term_mentions, term_sentiment, term_hidden, term_distinct, term_recency,
    first_evidence_date, last_evidence_date, last_evidence_year, n_recent_reviews,
    recent_since, freshness, needs_recent_confirmation
"""


def _recency(conn: sqlite3.Connection) -> dict:
    window = db.meta_value(conn, "recency_window_years")
    since = db.scalar(conn, "SELECT recent_since FROM v_entity_freshness LIMIT 1")
    return {"window_years": int(window) if window else None, "recent_since": since}


def _gem_filters(
    visibility: str | None, division: str | None, freshness: str | None,
    state: str | None, hidden_only: bool, min_score: float, mapped_only: bool,
) -> tuple[str, list]:
    where, params = ["COALESCE(gem_score, 0) >= ?"], [min_score]
    if visibility:
        levels = [v.strip().upper() for v in visibility.split(",") if v.strip()]
        where.append(f"visibility IN ({','.join('?' * len(levels))})")
        params += levels
    if division:
        where.append("LOWER(divisions) LIKE LOWER(?) ESCAPE '\\'")
        params.append(db.like_term(division))
    if freshness:
        where.append("freshness = ?")
        params.append(freshness.lower())
    if state:
        where.append("LOWER(state) = LOWER(?)")
        params.append(state)
    if hidden_only:
        where.append("COALESCE(already_official, 0) = 0")
    if mapped_only:
        where.append("lat IS NOT NULL AND lng IS NOT NULL")
    return " WHERE " + " AND ".join(where), params


@router.get("/gems")
def list_gems(
    conn: sqlite3.Connection = Depends(db.get_conn),
    visibility: str | None = Query(None, description="Comma-separated levels, e.g. V0,V1"),
    division: str | None = Query(None, description="Division of the reviews it was found in"),
    freshness: str | None = Query(None, pattern="^(recent|old)$"),
    state: str | None = Query(None, description="candidate, verified, rejected or sensitive"),
    hidden_only: bool = Query(False, description="Leave out places already well known (V3)"),
    mapped_only: bool = Query(False, description="Only gems with a point on the map"),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Scored gem candidates, best first, with visibility, coordinates and freshness."""
    clause, params = _gem_filters(visibility, division, freshness, state, hidden_only, min_score, mapped_only)
    total = db.scalar(conn, f"SELECT COUNT(*) FROM v_gems{clause}", params) or 0
    items = db.rows(
        conn, f"SELECT {GEM_FIELDS} FROM v_gems{clause} ORDER BY gem_rank ASC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "recency": _recency(conn),
        "visibility_levels": VISIBILITY_HELP,
        "gems": items,
    }


@router.get("/gems/map")
def gem_map(
    conn: sqlite3.Connection = Depends(db.get_conn),
    visibility: str | None = Query(None, description="Comma-separated levels, e.g. V0,V1"),
    hidden_only: bool = Query(False),
    include_places: bool = Query(True, description="Also return the corpus's own places"),
) -> dict:
    """GeoJSON for the map: gems, and optionally the places reviews were written about.

    Coordinates are [lng, lat], as GeoJSON requires.
    """
    clause, params = _gem_filters(visibility, None, None, None, hidden_only, 0.0, True)
    features = []
    for gem in db.rows(conn, f"SELECT {GEM_FIELDS} FROM v_gems{clause} ORDER BY gem_rank ASC", params):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [gem["lng"], gem["lat"]]},
            "properties": {"layer": "gem", **{k: v for k, v in gem.items() if k not in ("lat", "lng")}},
        })
    if include_places:
        places = db.rows(
            conn,
            "SELECT place_id, place_name, city, district, division, place_kind, review_count, "
            "       avg_review_rating, last_review_date, lat, lng "
            "FROM v_place_stats WHERE lat IS NOT NULL AND lng IS NOT NULL ORDER BY place_name",
        )
        for place in places:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [place["lng"], place["lat"]]},
                "properties": {"layer": "place", **{k: v for k, v in place.items() if k not in ("lat", "lng")}},
            })
    unmapped = db.rows(conn, "SELECT entity_id, canonical_name FROM v_gems WHERE lat IS NULL OR lng IS NULL")
    return {
        "type": "FeatureCollection",
        "features": features,
        "recency": _recency(conn),
        "visibility_levels": VISIBILITY_HELP,
        "unmapped_gems": unmapped,
    }


def _coordinates(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """Name (case-folded) -> (lat, lng), from reviewed places and placed gems."""
    points: dict[str, tuple[float, float]] = {}
    for row in db.rows(conn, "SELECT place_name AS name, lat, lng FROM places WHERE lat IS NOT NULL"):
        points[row["name"].casefold()] = (row["lat"], row["lng"])
    for row in db.rows(conn, "SELECT canonical_name AS name, lat, lng FROM gems WHERE lat IS NOT NULL"):
        points.setdefault(row["name"].casefold(), (row["lat"], row["lng"]))
    return points


# Declared before /gems/{entity_id}, which would otherwise take "connections"
# as an entity id.
@router.get("/gems/connections")
def gem_connections(
    conn: sqlite3.Connection = Depends(db.get_conn),
    place: str | None = Query(None, description="Only links touching this place (any case)"),
    lesser_known_only: bool = Query(False, description="Only links with a V0-V2 gem at one end"),
    min_reviews: int = Query(2, ge=1),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Places talked about together, strongest first, with map coordinates where
    both ends have them. Each link carries a sentence from a real review."""
    where, params = ["n_reviews >= ?"], [min_reviews]
    if place:
        where.append("(LOWER(place_a) = LOWER(?) OR LOWER(place_b) = LOWER(?))")
        params += [place, place]
    links = db.rows(
        conn,
        "SELECT place_a, place_b, n_reviews, n_found_in, n_together, example_review_id, example_sentence "
        f"FROM place_connections WHERE {' AND '.join(where)} ORDER BY n_reviews DESC, place_a, place_b",
        params,
    )
    lesser = {r["canonical_name"].casefold(): r["visibility"] for r in db.rows(
        conn, "SELECT canonical_name, visibility FROM gems WHERE visibility IN ('V0', 'V1', 'V2')")}
    points = _coordinates(conn)
    out = []
    for link in links:
        gem_end = next((e for e in (link["place_a"], link["place_b"]) if e.casefold() in lesser), None)
        if lesser_known_only and gem_end is None:
            continue
        a, b = points.get(link["place_a"].casefold()), points.get(link["place_b"].casefold())
        out.append({
            **link,
            "lesser_known_place": gem_end,
            "lesser_known_visibility": lesser.get(gem_end.casefold()) if gem_end else None,
            "a_lat": a[0] if a else None, "a_lng": a[1] if a else None,
            "b_lat": b[0] if b else None, "b_lng": b[1] if b else None,
        })
        if len(out) >= limit:
            break
    return {"total": len(out), "connections": out}


@router.get("/coverage")
def district_coverage(
    conn: sqlite3.Connection = Depends(db.get_conn),
    status: str | None = Query(None, pattern="^(no data|thin|covered)$"),
    division: str | None = None,
) -> dict:
    """All 64 districts with how much data each has: the engine's blind spots."""
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if division:
        where.append("LOWER(division) = LOWER(?)")
        params.append(division)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.rows(
        conn,
        "SELECT district, division, places, reviews, recent_reviews, bangla_share, mentions, "
        f"gem_candidates, status, place_names FROM district_coverage{clause} "
        "ORDER BY CASE status WHEN 'no data' THEN 0 WHEN 'thin' THEN 1 ELSE 2 END, reviews, division, district",
        params,
    )
    for row in rows:
        row["place_names"] = [p for p in str(row["place_names"] or "").split("|") if p]
    summary = {s: db.scalar(conn, "SELECT COUNT(*) FROM district_coverage WHERE status = ?", [s]) or 0
               for s in ("no data", "thin", "covered")}
    by_division = db.rows(
        conn,
        "SELECT division, COUNT(*) AS districts, "
        "SUM(status = 'no data') AS no_data, SUM(status = 'thin') AS thin, "
        "SUM(status = 'covered') AS covered, SUM(reviews) AS reviews "
        "FROM district_coverage GROUP BY division ORDER BY no_data DESC, division",
    )
    return {"total": len(rows), "summary": summary, "by_division": by_division, "districts": rows}


@router.get("/gems/{entity_id}")
def gem_detail(
    entity_id: str,
    conn: sqlite3.Connection = Depends(db.get_conn),
    evidence_limit: int = Query(20, ge=1, le=200),
) -> dict:
    """One gem with its spellings and its evidence, newest review first."""
    gem = db.one(conn, f"SELECT {GEM_FIELDS} FROM v_gems WHERE LOWER(entity_id) = LOWER(?)", [entity_id])
    if gem is None:
        raise HTTPException(status_code=404, detail=f"no gem {entity_id!r}")
    variants = db.rows(
        conn,
        "SELECT surface, mentions, is_canonical FROM entity_variants "
        "WHERE LOWER(entity_id) = LOWER(?) ORDER BY mentions DESC, surface ASC",
        [entity_id],
    )
    evidence = db.rows(
        conn,
        "SELECT mention_id, surface, sentence, language, review_id, found_in_place, "
        "       found_in_district, found_in_division, review_rating, review_date "
        "FROM v_mention_evidence WHERE LOWER(entity_id) = LOWER(?) "
        "ORDER BY review_date DESC, mention_id ASC LIMIT ?",
        [entity_id, evidence_limit],
    )
    found_in = db.rows(
        conn,
        "SELECT found_in_place AS place_name, COUNT(DISTINCT review_id) AS n_reviews "
        "FROM v_mention_evidence WHERE LOWER(entity_id) = LOWER(?) AND found_in_place IS NOT NULL "
        "GROUP BY found_in_place ORDER BY n_reviews DESC, place_name ASC",
        [entity_id],
    )
    return {
        "gem": gem,
        "recency": _recency(conn),
        "variants": variants,
        "found_in_places": found_in,
        "evidence": evidence,
    }


@router.get("/place-attributes")
def place_attributes(
    place: str = Query(..., description="Place name, as in /api/places"),
    conn: sqlite3.Connection = Depends(db.get_conn),
    entity_type: str | None = Query(None, description="FOOD, ACTIVITY, ACCESS or TIP"),
    recent_only: bool = Query(False, description="Only attributes with a review in the recency window"),
) -> dict:
    """What a place offers, grouped by type, each with a sentence from a real review.

    `stale` marks transport and tips with no recent review: still shown, since
    the review is real, but a card should say it may be out of date.
    """
    where, params = ["LOWER(place_name) = LOWER(?)"], [place]
    if entity_type:
        where.append("UPPER(entity_type) = UPPER(?)")
        params.append(entity_type)
    if recent_only:
        where.append("n_recent_reviews > 0")
    rows = db.rows(
        conn,
        "SELECT entity_type, entity_id, name, n_reviews, n_mentions, first_year, last_year, "
        "       n_recent_reviews, example_review_id, example_sentence, example_year "
        f"FROM place_attributes WHERE {' AND '.join(where)} "
        "ORDER BY entity_type ASC, n_reviews DESC, name ASC",
        params,
    )
    if not rows and db.scalar(conn, "SELECT 1 FROM places WHERE LOWER(place_name) = LOWER(?)", [place]) is None:
        raise HTTPException(status_code=404, detail=f"no place {place!r}")

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        row["stale"] = row["entity_type"] in PERISHABLE_TYPES and not row["n_recent_reviews"]
        grouped.setdefault(row["entity_type"], []).append(row)
    specialities = db.rows(
        conn,
        "SELECT entity_id, name, district, reviews_in_district, reviews_total, share "
        "FROM local_specialities WHERE '|' || places || '|' LIKE ? ORDER BY reviews_in_district DESC",
        [f"%|{place}|%"],
    )
    return {
        "place": place,
        "recency": _recency(conn),
        "attributes": grouped,
        "local_specialities": specialities,
    }


@router.get("/local-specialities")
def list_local_specialities(
    conn: sqlite3.Connection = Depends(db.get_conn),
    division: str | None = None,
) -> dict:
    """Foods whose reviews come mostly from one district, with a sentence from one."""
    where, params = "", []
    if division:
        where, params = " WHERE LOWER(division) = LOWER(?)", [division]
    rows = db.rows(
        conn,
        "SELECT entity_id, name, district, division, reviews_in_district, reviews_total, share, "
        f"       places, example_sentence FROM local_specialities{where} "
        "ORDER BY reviews_in_district DESC, name ASC",
        params,
    )
    for row in rows:
        row["places"] = [p for p in str(row["places"] or "").split("|") if p]
    return {"total": len(rows), "specialities": rows}


@router.get("/offers/{entity_id}")
def where_offered(
    entity_id: str,
    conn: sqlite3.Connection = Depends(db.get_conn),
) -> dict:
    """The places whose reviews mention a food, activity or transport mode, most
    reviewed first, each with a sentence from one of those reviews."""
    entity = db.one(conn, "SELECT entity_id, canonical_name, entity_type FROM entities "
                          "WHERE LOWER(entity_id) = LOWER(?)", [entity_id])
    if entity is None:
        raise HTTPException(status_code=404, detail=f"no entity {entity_id!r}")
    places = db.rows(
        conn,
        "SELECT place_name, district, division, n_reviews, last_year, n_recent_reviews, "
        "       example_sentence, example_year "
        "FROM place_attributes WHERE LOWER(entity_id) = LOWER(?) "
        "ORDER BY n_reviews DESC, place_name ASC",
        [entity_id],
    )
    speciality = db.one(conn, "SELECT district, reviews_in_district, reviews_total "
                              "FROM local_specialities WHERE LOWER(entity_id) = LOWER(?)", [entity_id])
    spellings = [r["surface"] for r in db.rows(
        conn, "SELECT surface FROM entity_variants WHERE LOWER(entity_id) = LOWER(?) "
              "ORDER BY mentions DESC", [entity_id])]
    return {**entity, "spellings": spellings, "local_speciality": speciality, "places": places}
