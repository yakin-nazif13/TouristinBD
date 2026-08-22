"""Places and cities."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db
from backend.models import City, Page, Place, PlaceDetail, PlacePreference, ReviewSummary
from backend.queries import review_summary_sql

router = APIRouter(prefix="/api", tags=["places"])


@router.get("/places", response_model=Page[Place])
def list_places(
    conn: sqlite3.Connection = Depends(db.get_conn),
    city: str | None = Query(None, description="Exact city name (case-insensitive)"),
    district: str | None = None,
    division: str | None = None,
    category: str | None = Query(None, description="Source category, e.g. 'hotel', 'Beach'"),
    place_kind: str | None = Query(None, description="attraction | accommodation"),
    source: str | None = Query(None, description="google_maps | booking.com"),
    min_rating: float | None = Query(None, ge=0, le=5),
    q: str | None = Query(None, description="Substring match on place name"),
    sort: str = Query("review_count", pattern="^(review_count|avg_rating|name|city)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[Place]:
    """Filterable place list with review counts and rating stats."""
    where: list[str] = []
    params: list = []

    def eq(col: str, value: str | None) -> None:
        if value:
            where.append(f"LOWER({col}) = LOWER(?)")
            params.append(value)

    eq("city", city)
    eq("district", district)
    eq("division", division)
    eq("category", category)
    eq("place_kind", place_kind)
    eq("source", source)
    if min_rating is not None:
        where.append("COALESCE(avg_review_rating, 0) >= ?")
        params.append(min_rating)
    if q:
        where.append("place_name LIKE ? ESCAPE '\\'")
        params.append(db.like_term(q))

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sort_col = {
        "review_count": "review_count",
        "avg_rating": "avg_review_rating",
        "name": "place_name",
        "city": "city",
    }[sort]
    order_sql = f"ORDER BY {sort_col} {order.upper()}, place_name ASC"

    return Page[Place](
        **db.paginate(
            conn,
            f"SELECT * FROM v_place_stats {clause}",
            f"SELECT COUNT(*) FROM v_place_stats {clause}",
            params,
            limit,
            offset,
            order_sql,
        )
    )


@router.get("/places/{place_ref}", response_model=PlaceDetail)
def get_place(
    place_ref: str,
    conn: sqlite3.Connection = Depends(db.get_conn),
    sample_reviews: int = Query(5, ge=0, le=50),
) -> PlaceDetail:
    """A single place by numeric id or by (case-insensitive) name."""
    if place_ref.isdigit():
        place = db.one(conn, "SELECT * FROM v_place_stats WHERE place_id = ?", (int(place_ref),))
    else:
        place = db.one(
            conn, "SELECT * FROM v_place_stats WHERE LOWER(place_name) = LOWER(?)", (place_ref,)
        )
    if place is None:
        raise HTTPException(status_code=404, detail=f"place not found: {place_ref}")

    pid = place["place_id"]

    ratings = db.rows(
        conn,
        "SELECT review_rating, COUNT(*) AS review_count FROM reviews "
        "WHERE place_id = ? GROUP BY review_rating ORDER BY review_rating",
        (pid,),
    )

    prefs = db.rows(
        conn,
        "SELECT preference_id, preference_label, preference_type, review_count, avg_rating "
        "FROM v_venue_preference_rollup WHERE place_id = ? "
        "ORDER BY review_count DESC",
        (pid,),
    )
    mapped_total = sum(p["review_count"] for p in prefs) or 1
    preferences = [
        PlacePreference(**p, review_share=round(p["review_count"] / mapped_total, 4))
        for p in prefs
    ]

    topics = db.rows(
        conn,
        """
        SELECT r.topic_id, t.interpreted_label, t.top_keywords,
               COUNT(*) AS review_count,
               ROUND(AVG(r.review_rating), 3) AS avg_rating
        FROM reviews r
        LEFT JOIN topics t ON t.topic_id = r.topic_id
        WHERE r.place_id = ?
        GROUP BY r.topic_id
        ORDER BY review_count DESC
        """,
        (pid,),
    )

    samples: list[ReviewSummary] = []
    if sample_reviews:
        samples = [
            ReviewSummary(**r)
            for r in db.rows(
                conn,
                review_summary_sql("WHERE v.place_id = ?") + " LIMIT ?",
                (pid, sample_reviews),
            )
        ]

    return PlaceDetail(
        place=Place(**place),
        rating_breakdown=ratings,
        preferences=preferences,
        topics=topics,
        sample_reviews=samples,
    )


@router.get("/cities", response_model=list[City])
def list_cities(
    conn: sqlite3.Connection = Depends(db.get_conn),
    division: str | None = None,
    min_reviews: int = Query(0, ge=0),
) -> list[City]:
    """Cities present in the corpus with place/review counts."""
    where = ["review_count >= ?"]
    params: list = [min_reviews]
    if division:
        where.append("LOWER(division) = LOWER(?)")
        params.append(division)
    return [
        City(**r)
        for r in db.rows(
            conn,
            f"SELECT * FROM v_city_stats WHERE {' AND '.join(where)} "
            "ORDER BY review_count DESC, city ASC",
            params,
        )
    ]
