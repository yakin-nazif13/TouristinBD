"""Topics (Phase 3) and the preference taxonomy (Phase 4)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db
from backend.models import Preference, PreferenceDetail, ReviewSummary, Topic
from backend.queries import review_summary_sql

router = APIRouter(prefix="/api", tags=["taxonomy"])

TOPIC_SELECT = """
SELECT t.topic_id, t.topic_name, t.top_keywords, t.review_count, t.corpus_share,
       t.interpreted_label, t.interpretation, t.dimension_hint,
       m.preference_id, p.preference_label, p.preference_type,
       m.similarity, m.confidence, m.needs_review,
       lt.is_long_tail, lt.sdd
FROM topics t
LEFT JOIN topic_preference_map m ON m.topic_id = t.topic_id
LEFT JOIN preferences p ON p.preference_id = m.preference_id
LEFT JOIN long_tail_flags lt ON lt.topic_id = t.topic_id
"""


@router.get("/topics", response_model=list[Topic])
def list_topics(
    conn: sqlite3.Connection = Depends(db.get_conn),
    include_outliers: bool = Query(False, description="Include the BERTopic -1 bucket"),
    preference_id: str | None = None,
    needs_review: bool | None = Query(None, description="Only topics flagged for human review"),
) -> list[Topic]:
    """Topic list with its mapped preference and long-tail verdict."""
    where: list[str] = []
    params: list = []
    if not include_outliers:
        where.append("t.topic_id >= 0")
    if preference_id:
        where.append("LOWER(m.preference_id) = LOWER(?)")
        params.append(preference_id)
    if needs_review is not None:
        where.append("COALESCE(m.needs_review, 0) = ?")
        params.append(1 if needs_review else 0)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return [
        Topic(**r)
        for r in db.rows(
            conn, f"{TOPIC_SELECT} {clause} ORDER BY t.review_count DESC", params
        )
    ]


@router.get("/topics/{topic_id}", response_model=dict)
def get_topic(
    topic_id: int,
    conn: sqlite3.Connection = Depends(db.get_conn),
    sample_reviews: int = Query(5, ge=0, le=50),
) -> dict:
    """One topic plus where it shows up and how Phase 5 judged its mapping."""
    topic = db.one(conn, f"{TOPIC_SELECT} WHERE t.topic_id = ?", (topic_id,))
    if topic is None:
        raise HTTPException(status_code=404, detail=f"topic not found: {topic_id}")

    places = db.rows(
        conn,
        "SELECT p.place_id, p.place_name, p.city, COUNT(*) AS review_count, "
        "ROUND(AVG(r.review_rating), 3) AS avg_rating "
        "FROM reviews r JOIN places p ON p.place_id = r.place_id "
        "WHERE r.topic_id = ? GROUP BY p.place_id ORDER BY review_count DESC",
        (topic_id,),
    )
    validation = db.one(
        conn, "SELECT * FROM validation_precision WHERE topic_id = ?", (topic_id,)
    )
    long_tail = db.one(conn, "SELECT * FROM long_tail_flags WHERE topic_id = ?", (topic_id,))
    samples = db.rows(
        conn,
        review_summary_sql("WHERE v.topic_id = ?") + " LIMIT ?",
        (topic_id, sample_reviews),
    )
    return {
        "topic": topic,
        "places": places,
        "validation": validation,
        "long_tail": long_tail,
        "sample_reviews": samples,
    }


PREFERENCE_SELECT = """
SELECT f.preference_id, f.category, f.subcategory, f.preference_label,
       p.preference_description, f.preference_type,
       f.topic_count, f.review_count, f.avg_similarity,
       c.coverage_status, c.coverage_action
FROM v_preference_frequency f
JOIN preferences p ON p.preference_id = f.preference_id
LEFT JOIN validation_coverage c ON c.preference_id = f.preference_id
"""


@router.get("/preferences", response_model=list[Preference])
def list_preferences(
    conn: sqlite3.Connection = Depends(db.get_conn),
    preference_type: str | None = Query(None, description="mainstream | long_tail"),
    category: str | None = None,
    min_reviews: int = Query(0, ge=0),
    include_unmapped: bool = Query(
        True, description="Keep preferences with no mapped topics (e.g. P10)"
    ),
) -> list[Preference]:
    """The Phase 4 preference taxonomy with corpus evidence attached."""
    where: list[str] = ["f.review_count >= ?"]
    params: list = [min_reviews]
    if preference_type:
        where.append("LOWER(f.preference_type) = LOWER(?)")
        params.append(preference_type)
    if category:
        where.append("LOWER(f.category) = LOWER(?)")
        params.append(category)
    if not include_unmapped:
        where.append("f.topic_count > 0")

    result = db.rows(
        conn,
        f"{PREFERENCE_SELECT} WHERE {' AND '.join(where)} "
        "ORDER BY f.review_count DESC, f.preference_id ASC",
        params,
    )
    total = sum(r["review_count"] or 0 for r in result) or 1
    return [
        Preference(**r, review_share=round((r["review_count"] or 0) / total, 4))
        for r in result
    ]


@router.get("/preferences/{preference_id}", response_model=PreferenceDetail)
def get_preference(
    preference_id: str,
    conn: sqlite3.Connection = Depends(db.get_conn)  ,
    sample_reviews: int = Query(5, ge=0, le=50),
) -> PreferenceDetail:
    """One preference: its topics, where it is strongest, and example reviews."""
    row = db.one(
        conn,
        f"{PREFERENCE_SELECT} WHERE LOWER(f.preference_id) = LOWER(?)",
        (preference_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"preference not found: {preference_id}")
    pid = row["preference_id"]

    topics = [
        Topic(**t)
        for t in db.rows(
            conn,
            f"{TOPIC_SELECT} WHERE m.preference_id = ? ORDER BY t.review_count DESC",
            (pid,),
        )
    ]
    cities = db.rows(
        conn,
        "SELECT city, district, division, review_count, avg_rating "
        "FROM v_city_preference_rollup WHERE preference_id = ? "
        "ORDER BY review_count DESC",
        (pid,),
    )
    places = db.rows(
        conn,
        "SELECT place_id, place_name, city, category, place_kind, review_count, avg_rating "
        "FROM v_venue_preference_rollup WHERE preference_id = ? "
        "ORDER BY review_count DESC",
        (pid,),
    )
    samples = [
        ReviewSummary(**r)
        for r in db.rows(
            conn,
            review_summary_sql("WHERE v.preference_id = ?") + " LIMIT ?",
            (pid, sample_reviews),
        )
    ]
    return PreferenceDetail(
        preference=Preference(**row),
        topics=topics,
        top_cities=cities,
        top_places=places,
        sample_reviews=samples,
    )


@router.get("/taxonomy", response_model=list[dict])
def preference_tree(conn: sqlite3.Connection = Depends(db.get_conn)) -> list[dict]:
    """Category → Subcategory → Preference hierarchy, as Phase 4 Stage 2 produced it."""
    flat = db.rows(
        conn,
        f"{PREFERENCE_SELECT} ORDER BY f.category, f.subcategory, f.preference_id",
    )
    tree: dict[str, dict] = {}
    for row in flat:
        cat = row["category"] or "Uncategorized"
        sub = row["subcategory"] or "General"
        node = tree.setdefault(cat, {"category": cat, "review_count": 0, "subcategories": {}})
        sub_node = node["subcategories"].setdefault(
            sub, {"subcategory": sub, "review_count": 0, "preferences": []}
        )
        sub_node["preferences"].append(
            {
                "preference_id": row["preference_id"],
                "preference_label": row["preference_label"],
                "preference_type": row["preference_type"],
                "topic_count": row["topic_count"],
                "review_count": row["review_count"],
            }
        )
        sub_node["review_count"] += row["review_count"] or 0
        node["review_count"] += row["review_count"] or 0

    return [
        {**cat_node, "subcategories": list(cat_node["subcategories"].values())}
        for cat_node in tree.values()
    ]
