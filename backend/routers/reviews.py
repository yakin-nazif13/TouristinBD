"""Review-level access — the retrieval surface Phase 9's chatbot will read from."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db
from backend.models import Page, ReviewSummary
from backend.queries import REVIEW_SUMMARY_FROM, REVIEW_SUMMARY_SELECT

router = APIRouter(prefix="/api", tags=["reviews"])

FULL_COLS = """
    review_id, place_id, place_name, city, district, division, category, place_kind,
    source, review_rating, review_date, review_month, review_year, detected_language,
    text_length, topic_id, interpreted_label, preference_id, preference_label,
    preference_category, preference_subcategory, preference_type,
    mapping_similarity, mapping_confidence
"""

SORT_COLUMNS = {"date": "v.review_date", "rating": "v.review_rating", "length": "v.text_length"}


@router.get("/reviews", response_model=Page[ReviewSummary])
def list_reviews(
    conn: sqlite3.Connection = Depends(db.get_conn),
    place: str | None = Query(None, description="Place name (substring match)"),
    place_id: int | None = None,
    city: str | None = None,
    source: str | None = None,
    language: str | None = Query(None, description="detected_language, e.g. en, bn, bn-en"),
    topic_id: int | None = Query(None, description="Use -1 for BERTopic outliers"),
    preference_id: str | None = None,
    preference_type: str | None = Query(None, description="mainstream | long_tail"),
    min_rating: float | None = Query(None, ge=0, le=5),
    max_rating: float | None = Query(None, ge=0, le=5),
    date_from: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    date_to: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    q: str | None = Query(None, description="Substring search in review text"),
    sort: str = Query("date", pattern="^(date|rating|length)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ReviewSummary]:
    """Paginated, filterable reviews joined to their topic and preference."""
    where: list[str] = []
    params: list = []

    def eq(col: str, value) -> None:
        if value is not None and value != "":
            where.append(f"LOWER({col}) = LOWER(?)")
            params.append(value)

    def cmp(col: str, op: str, value) -> None:
        if value is not None and value != "":
            where.append(f"{col} {op} ?")
            params.append(value)

    cmp("v.place_id", "=", place_id)
    if place:
        where.append("v.place_name LIKE ? ESCAPE '\\'")
        params.append(db.like_term(place))
    eq("v.city", city)
    eq("v.source", source)
    eq("v.detected_language", language)
    eq("v.preference_id", preference_id)
    eq("v.preference_type", preference_type)
    cmp("v.topic_id", "=", topic_id)
    cmp("v.review_rating", ">=", min_rating)
    cmp("v.review_rating", "<=", max_rating)
    cmp("v.review_date", ">=", date_from)
    cmp("v.review_date", "<=", date_to)
    if q:
        where.append("r.review_text_clean LIKE ? ESCAPE '\\'")
        params.append(db.like_term(q))

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = f"ORDER BY {SORT_COLUMNS[sort]} {order.upper()}, v.review_id ASC"

    return Page[ReviewSummary](
        **db.paginate(
            conn,
            f"SELECT {REVIEW_SUMMARY_SELECT} {REVIEW_SUMMARY_FROM} {clause}",
            f"SELECT COUNT(*) {REVIEW_SUMMARY_FROM} {clause}",
            params,
            limit,
            offset,
            order_sql,
        )
    )


@router.get("/reviews/{review_id}", response_model=dict)
def get_review(review_id: str, conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """One review with every stored field, including full pipeline lineage."""
    row = db.one(
        conn,
        f"SELECT {FULL_COLS} FROM v_review_preference WHERE review_id = ?",
        (review_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"review not found: {review_id}")
    extra = db.one(
        conn,
        "SELECT review_text_clean, platform_language_tag, traveler_type, user_location, "
        "nights_stayed, reviewer_num_reviews, reviewer_is_local_guide, review_likes, source_url "
        "FROM reviews WHERE review_id = ?",
        (review_id,),
    )
    return {**row, **(extra or {})}


@router.get("/languages", response_model=list[dict])
def list_languages(conn: sqlite3.Connection = Depends(db.get_conn)) -> list[dict]:
    """Detected-language mix — the multilingual angle of the write-up."""
    return db.rows(
        conn,
        "SELECT detected_language, platform_language_tag, COUNT(*) AS review_count "
        "FROM reviews GROUP BY detected_language, platform_language_tag "
        "ORDER BY review_count DESC",
    )
