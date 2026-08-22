"""Analytics endpoints — the SQL equivalents of the Phase 7 tables.

These read from views, so they always reflect whatever is currently in the DB
rather than a snapshot CSV.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from backend import db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/rating-distribution", response_model=list[dict])
def rating_distribution(conn: sqlite3.Connection = Depends(db.get_conn)) -> list[dict]:
    """Rating histogram per source, with each source's share."""
    result = db.rows(
        conn,
        "SELECT source, review_rating, review_count FROM v_rating_distribution "
        "ORDER BY source, review_rating",
    )
    totals: dict[str, int] = {}
    for r in result:
        totals[r["source"]] = totals.get(r["source"], 0) + r["review_count"]
    for r in result:
        total = totals.get(r["source"]) or 1
        r["pct_in_source"] = round(r["review_count"] / total, 4)
    return result


@router.get("/temporal", response_model=list[dict])
def temporal(
    conn: sqlite3.Connection = Depends(db.get_conn),
    granularity: str = Query("month", pattern="^(month|year)$"),
    source: str | None = None,
) -> list[dict]:
    """Review volume over time, monthly or yearly."""
    params: list = []
    clause = ""
    if source:
        clause = "WHERE LOWER(source) = LOWER(?)"
        params.append(source)
    if granularity == "month":
        return db.rows(
            conn,
            f"SELECT review_month AS period, source, review_count FROM v_temporal_volume "
            f"{clause} ORDER BY period, source",
            params,
        )
    return db.rows(
        conn,
        f"SELECT CAST(review_year AS TEXT) AS period, source, COUNT(*) AS review_count "
        f"FROM reviews {'WHERE LOWER(source) = LOWER(?)' if source else ''} "
        "GROUP BY review_year, source HAVING review_year IS NOT NULL "
        "ORDER BY period, source",
        params,
    )


@router.get("/preference-frequency", response_model=list[dict])
def preference_frequency(conn: sqlite3.Connection = Depends(db.get_conn)) -> list[dict]:
    """Reviews and topics per preference (Phase 7 preference_frequency table)."""
    result = db.rows(
        conn, "SELECT * FROM v_preference_frequency ORDER BY review_count DESC"
    )
    total = sum(r["review_count"] or 0 for r in result) or 1
    for r in result:
        r["review_share"] = round((r["review_count"] or 0) / total, 4)
    return result


@router.get("/city-preferences", response_model=list[dict])
def city_preferences(
    conn: sqlite3.Connection = Depends(db.get_conn),
    city: str | None = None,
    preference_id: str | None = None,
) -> list[dict]:
    """City × preference rollup — which cities evidence which preferences."""
    where: list[str] = []
    params: list = []
    if city:
        where.append("LOWER(city) = LOWER(?)")
        params.append(city)
    if preference_id:
        where.append("LOWER(preference_id) = LOWER(?)")
        params.append(preference_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return db.rows(
        conn,
        f"SELECT * FROM v_city_preference_rollup {clause} "
        "ORDER BY city ASC, review_count DESC",
        params,
    )


@router.get("/venue-preferences", response_model=list[dict])
def venue_preferences(
    conn: sqlite3.Connection = Depends(db.get_conn),
    city: str | None = None,
    preference_id: str | None = None,
    place_id: int | None = None,
) -> list[dict]:
    """Venue × preference rollup — the per-place evidence Phase 10 will rank on."""
    where: list[str] = []
    params: list = []
    if city:
        where.append("LOWER(city) = LOWER(?)")
        params.append(city)
    if preference_id:
        where.append("LOWER(preference_id) = LOWER(?)")
        params.append(preference_id)
    if place_id is not None:
        where.append("place_id = ?")
        params.append(place_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return db.rows(
        conn,
        f"SELECT * FROM v_venue_preference_rollup {clause} "
        "ORDER BY place_name ASC, review_count DESC",
        params,
    )


@router.get("/long-tail", response_model=dict)
def long_tail(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Phase 4 Stage 4 long-tail verdicts plus the mainstream/long-tail split."""
    flags = db.rows(
        conn,
        "SELECT lt.*, t.interpreted_label FROM long_tail_flags lt "
        "LEFT JOIN topics t ON t.topic_id = lt.topic_id "
        "ORDER BY lt.corpus_share DESC",
    )
    split = db.rows(
        conn,
        """
        SELECT COALESCE(p.preference_type, 'unmapped') AS preference_type,
               COUNT(DISTINCT m.topic_id)   AS topic_count,
               COUNT(DISTINCT p.preference_id) AS preference_count,
               SUM(t.review_count)          AS review_count,
               ROUND(AVG(m.similarity), 4)  AS avg_similarity,
               ROUND(AVG(lt.sdd), 4)        AS mean_sdd
        FROM topic_preference_map m
        LEFT JOIN topics t      ON t.topic_id = m.topic_id
        LEFT JOIN preferences p ON p.preference_id = m.preference_id
        LEFT JOIN long_tail_flags lt ON lt.topic_id = m.topic_id
        GROUP BY COALESCE(p.preference_type, 'unmapped')
        ORDER BY review_count DESC
        """,
    )
    total = sum(r["review_count"] or 0 for r in split) or 1
    for r in split:
        r["review_share"] = round((r["review_count"] or 0) / total, 4)
    thresholds = db.one(
        conn,
        "SELECT MAX(sdd_threshold) AS sdd_threshold, "
        "MAX(scarcity_threshold) AS scarcity_threshold FROM long_tail_flags",
    )
    return {
        "thresholds": thresholds or {},
        "split": split,
        "topics": flags,
        "note": (
            "A topic is long-tail when corpus_share < scarcity_threshold AND "
            "sdd > sdd_threshold (semantic distinctiveness from abundant topics)."
        ),
    }


@router.get("/language-mix", response_model=list[dict])
def language_mix(conn: sqlite3.Connection = Depends(db.get_conn)) -> list[dict]:
    """Detected language vs the platform's own language tag (Phase 2 finding)."""
    return db.rows(
        conn,
        "SELECT detected_language, platform_language_tag, source, COUNT(*) AS review_count "
        "FROM reviews GROUP BY detected_language, platform_language_tag, source "
        "ORDER BY review_count DESC",
    )
