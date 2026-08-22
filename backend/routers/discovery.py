"""Discovery endpoints — cross-entity search and preference-based ranking.

These are the two API surfaces Phases 9 (chatbot retrieval) and 10 (itinerary /
comparison on real data) will build on, so they live in the backend rather than
being reimplemented in the frontend.

Each endpoint is a thin FastAPI wrapper around a plain-Python `_*_impl`
function with ordinary defaults (no `Query`/`Depends` sentinels). That split
lets `backend/routers/chat.py` call the same logic in-process without going
through HTTP or FastAPI's parameter resolution — calling a route function
directly would otherwise bind any unpassed parameter to its raw `Query(...)`
object instead of the default it resolves to at request time.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db
from backend.models import Recommendation, SearchHit

router = APIRouter(prefix="/api", tags=["discovery"])

# Weights for the recommendation blend. Documented in the endpoint docstring so
# the ranking stays explainable in the write-up.
W_EVIDENCE = 0.45
W_PREF_COVERAGE = 0.30
W_RATING = 0.25


def _search_impl(
    conn: sqlite3.Connection,
    q: str,
    kinds: str = "place,city,preference,topic,review",
    limit_per_kind: int = 5,
) -> list[SearchHit]:
    wanted = {k.strip().lower() for k in kinds.split(",") if k.strip()}
    term = db.like_term(q)
    hits: list[SearchHit] = []

    if "place" in wanted:
        for r in db.rows(
            conn,
            "SELECT place_id, place_name, city, category, review_count, avg_review_rating "
            "FROM v_place_stats WHERE place_name LIKE ? ESCAPE '\\' OR city LIKE ? ESCAPE '\\' "
            "ORDER BY review_count DESC LIMIT ?",
            (term, term, limit_per_kind),
        ):
            hits.append(
                SearchHit(
                    kind="place",
                    id=str(r["place_id"]),
                    label=r["place_name"],
                    detail=f"{r['city'] or 'unknown city'} · {r['category'] or '—'} · "
                    f"{r['review_count']} reviews · avg {r['avg_review_rating']}",
                    score=float(r["review_count"] or 0),
                )
            )

    if "city" in wanted:
        for r in db.rows(
            conn,
            "SELECT city, district, division, place_count, review_count, avg_review_rating "
            "FROM v_city_stats WHERE city LIKE ? ESCAPE '\\' OR district LIKE ? ESCAPE '\\' "
            "ORDER BY review_count DESC LIMIT ?",
            (term, term, limit_per_kind),
        ):
            hits.append(
                SearchHit(
                    kind="city",
                    id=r["city"],
                    label=r["city"],
                    detail=f"{r['division'] or '—'} division · {r['place_count']} places · "
                    f"{r['review_count']} reviews",
                    score=float(r["review_count"] or 0),
                )
            )

    if "preference" in wanted:
        for r in db.rows(
            conn,
            "SELECT p.preference_id, p.preference_label, p.preference_description, "
            "p.preference_type, f.review_count FROM preferences p "
            "JOIN v_preference_frequency f ON f.preference_id = p.preference_id "
            "WHERE p.preference_label LIKE ? ESCAPE '\\' "
            "OR p.preference_description LIKE ? ESCAPE '\\' "
            "OR p.subcategory LIKE ? ESCAPE '\\' "
            "ORDER BY f.review_count DESC LIMIT ?",
            (term, term, term, limit_per_kind),
        ):
            hits.append(
                SearchHit(
                    kind="preference",
                    id=r["preference_id"],
                    label=r["preference_label"],
                    detail=f"{r['preference_type']} · {r['review_count']} reviews",
                    score=float(r["review_count"] or 0),
                )
            )

    if "topic" in wanted:
        for r in db.rows(
            conn,
            "SELECT topic_id, interpreted_label, top_keywords, review_count FROM topics "
            "WHERE interpreted_label LIKE ? ESCAPE '\\' OR top_keywords LIKE ? ESCAPE '\\' "
            "OR interpretation LIKE ? ESCAPE '\\' "
            "ORDER BY review_count DESC LIMIT ?",
            (term, term, term, limit_per_kind),
        ):
            hits.append(
                SearchHit(
                    kind="topic",
                    id=str(r["topic_id"]),
                    label=r["interpreted_label"] or f"Topic {r['topic_id']}",
                    detail=f"keywords: {r['top_keywords']} · {r['review_count']} reviews",
                    score=float(r["review_count"] or 0),
                )
            )

    if "review" in wanted:
        for r in db.rows(
            conn,
            "SELECT r.review_id, r.review_text_clean, r.review_rating, p.place_name "
            "FROM reviews r LEFT JOIN places p ON p.place_id = r.place_id "
            "WHERE r.review_text_clean LIKE ? ESCAPE '\\' "
            "ORDER BY r.review_rating DESC, r.text_length DESC LIMIT ?",
            (term, limit_per_kind),
        ):
            text = (r["review_text_clean"] or "").strip()
            hits.append(
                SearchHit(
                    kind="review",
                    id=r["review_id"],
                    label=f"{r['place_name']} · {r['review_rating']}★",
                    detail=text[:220] + ("…" if len(text) > 220 else ""),
                    score=float(r["review_rating"] or 0),
                )
            )

    return hits


@router.get("/search", response_model=list[SearchHit])
def search(
    q: str = Query(..., min_length=2, description="Free-text query"),
    conn: sqlite3.Connection = Depends(db.get_conn),
    kinds: str = Query(
        "place,city,preference,topic,review",
        description="Comma-separated entity kinds to search",
    ),
    limit_per_kind: int = Query(5, ge=1, le=50),
) -> list[SearchHit]:
    """One query across places, cities, preferences, topics and review text."""
    return _search_impl(conn, q, kinds, limit_per_kind)


def _recommend_impl(
    conn: sqlite3.Connection,
    preferences: str | None = None,
    city: str | None = None,
    division: str | None = None,
    place_kind: str | None = None,
    exclude_city: str | None = None,
    min_reviews: int = 1,
    limit: int = 10,
) -> list[Recommendation]:
    wanted: list[str] = []
    if preferences:
        wanted = [p.strip().upper() for p in preferences.split(",") if p.strip()]
        known = {
            r["preference_id"].upper()
            for r in db.rows(conn, "SELECT preference_id FROM preferences")
        }
        unknown = [p for p in wanted if p not in known]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown preference_id(s): {', '.join(unknown)}. "
                "See GET /api/preferences for valid ids.",
            )

    where = ["review_count >= ?"]
    params: list = [min_reviews]
    if city:
        where.append("LOWER(city) = LOWER(?)")
        params.append(city)
    if division:
        where.append("LOWER(division) = LOWER(?)")
        params.append(division)
    if place_kind:
        where.append("LOWER(place_kind) = LOWER(?)")
        params.append(place_kind)
    if exclude_city:
        skip = [c.strip() for c in exclude_city.split(",") if c.strip()]
        if skip:
            placeholders = ",".join("?" for _ in skip)
            where.append(f"LOWER(city) NOT IN ({placeholders})")
            params.extend(c.lower() for c in skip)

    places = db.rows(
        conn,
        f"SELECT place_id, place_name, city, district, category, place_kind, review_count, "
        f"avg_review_rating FROM v_place_stats WHERE {' AND '.join(where)}",
        params,
    )
    if not places:
        return []

    evidence: dict[int, dict[str, int]] = {}
    if wanted:
        placeholders = ",".join("?" for _ in wanted)
        for r in db.rows(
            conn,
            f"SELECT place_id, preference_id, review_count FROM v_venue_preference_rollup "
            f"WHERE UPPER(preference_id) IN ({placeholders})",
            wanted,
        ):
            evidence.setdefault(r["place_id"], {})[r["preference_id"]] = r["review_count"]

    results: list[Recommendation] = []
    for p in places:
        matched = evidence.get(p["place_id"], {})
        matched_count = sum(matched.values())
        total_reviews = p["review_count"] or 0
        rating_norm = (p["avg_review_rating"] or 0) / 5.0

        if wanted:
            if not matched:
                continue
            evidence_share = matched_count / total_reviews if total_reviews else 0.0
            pref_coverage = len(matched) / len(wanted)
            score = (
                W_EVIDENCE * evidence_share
                + W_PREF_COVERAGE * pref_coverage
                + W_RATING * rating_norm
            )
        else:
            evidence_share = None
            # No preferences requested: rating first, volume as a mild tiebreaker.
            volume_norm = min(total_reviews / 50.0, 1.0)
            score = 0.75 * rating_norm + 0.25 * volume_norm

        results.append(
            Recommendation(
                place_id=p["place_id"],
                place_name=p["place_name"],
                city=p["city"],
                district=p["district"],
                category=p["category"],
                place_kind=p["place_kind"],
                review_count=total_reviews,
                avg_rating=p["avg_review_rating"],
                match_score=round(score, 4),
                matched_preferences=sorted(matched.keys()),
                matched_review_count=matched_count,
                evidence_share=round(evidence_share, 4) if evidence_share is not None else None,
            )
        )

    results.sort(key=lambda r: (r.match_score, r.review_count), reverse=True)
    return results[:limit]


@router.get("/recommend", response_model=list[Recommendation])
def recommend(
    conn: sqlite3.Connection = Depends(db.get_conn),
    preferences: str | None = Query(
        None, description="Comma-separated preference_ids, e.g. P02,P03"
    ),
    city: str | None = None,
    division: str | None = None,
    place_kind: str | None = Query(None, description="attraction | accommodation"),
    exclude_city: str | None = Query(None, description="Comma-separated cities to skip"),
    min_reviews: int = Query(1, ge=0, description="Minimum reviews for a place to qualify"),
    limit: int = Query(10, ge=1, le=100),
) -> list[Recommendation]:
    """Rank places against a set of preferences, using review evidence.

    `match_score` = 0.45 × evidence_share + 0.30 × preference_coverage +
    0.25 × (avg_rating / 5), where *evidence_share* is the fraction of the
    place's reviews that map to a requested preference and *preference_coverage*
    is the fraction of the requested preferences the place has any evidence for.
    With no `preferences` given it degrades to a rating-and-volume ranking.
    """
    return _recommend_impl(
        conn, preferences, city, division, place_kind, exclude_city, min_reviews, limit
    )


def _compare_impl(conn: sqlite3.Connection, places: str) -> dict:
    refs = [p.strip() for p in places.split(",") if p.strip()]
    if not 2 <= len(refs) <= 4:
        raise HTTPException(status_code=400, detail="pass between 2 and 4 places")

    resolved: list[dict] = []
    for ref in refs:
        if ref.isdigit():
            row = db.one(conn, "SELECT * FROM v_place_stats WHERE place_id = ?", (int(ref),))
        else:
            row = db.one(
                conn,
                "SELECT * FROM v_place_stats WHERE LOWER(place_name) = LOWER(?)",
                (ref,),
            )
        if row is None:
            raise HTTPException(status_code=404, detail=f"place not found: {ref}")
        row["preferences"] = db.rows(
            conn,
            "SELECT preference_id, preference_label, preference_type, review_count, avg_rating "
            "FROM v_venue_preference_rollup WHERE place_id = ? ORDER BY review_count DESC",
            (row["place_id"],),
        )
        row["rating_breakdown"] = db.rows(
            conn,
            "SELECT review_rating, COUNT(*) AS review_count FROM reviews "
            "WHERE place_id = ? GROUP BY review_rating ORDER BY review_rating",
            (row["place_id"],),
        )
        resolved.append(row)

    pref_sets = [{p["preference_id"] for p in r["preferences"]} for r in resolved]
    shared = set.intersection(*pref_sets) if pref_sets else set()
    return {
        "places": resolved,
        "shared_preferences": sorted(shared),
        "distinct_preferences": {
            r["place_name"]: sorted(s - shared) for r, s in zip(resolved, pref_sets)
        },
    }


@router.get("/compare", response_model=dict)
def compare(
    conn: sqlite3.Connection = Depends(db.get_conn),
    places: str = Query(..., description="Comma-separated place_ids or place names (2-4)"),
) -> dict:
    """Side-by-side comparison of 2-4 places on real review evidence."""
    return _compare_impl(conn, places)
