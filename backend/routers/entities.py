"""The entity layer: discovered mentions, resolved entities and their evidence.

BUILD_PLAN section 5. These are the endpoints that make the project's central
claim inspectable rather than only asserted:

    "A platform that mines tourist reviews ... for mentions of lesser-known
     places, foods, activities, routes and tips. ... Every claim links back to
     the texts that support it."

So every entity here can be opened to the mentions behind it, and every mention
carries the sentence it came from, the review it came from, and the character
offsets it was found at. Nothing is asserted without its evidence.

`found_in_place` is the important field: a mention of Fatrar Chor inside a
review *of Kuakata* is what section 3.2 snowballs on. Extraction excludes a
review's own place, including short forms of it, so everything served here is a
secondary mention by construction.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import db

router = APIRouter(prefix="/api", tags=["entities"])

ENTITY_SELECT = """
SELECT e.entity_id, e.canonical_name, e.entity_type, e.n_variants,
       e.districts, e.divisions, e.languages,
       v.n_mentions, v.n_reviews, v.n_found_in_places, v.n_divisions,
       v.avg_rating_of_host_reviews
FROM entities e
LEFT JOIN v_entity_evidence v ON v.entity_id = e.entity_id
"""


@router.get("/entities")
def list_entities(
    conn: sqlite3.Connection = Depends(db.get_conn),
    entity_type: str | None = Query(None, description="PLACE, FOOD, ACTIVITY, ACCESS or TIP"),
    min_reviews: int = Query(
        1, ge=0,
        description="Minimum distinct reviews mentioning it. Section 5.5 wants 2-3 "
                    "independent mentions before anything is a candidate.",
    ),
    division: str | None = Query(None, description="Division of the reviews it was found in"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Resolved entities, ranked by how much independent evidence backs them."""
    where = ["COALESCE(v.n_reviews, 0) >= ?"]
    params: list = [min_reviews]
    if entity_type:
        where.append("UPPER(e.entity_type) = UPPER(?)")
        params.append(entity_type)
    if division:
        where.append("e.divisions LIKE ?")
        params.append(f"%{division}%")

    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM entities e LEFT JOIN v_entity_evidence v "
        f"ON v.entity_id = e.entity_id{clause}", params
    ).fetchone()[0]

    rows = conn.execute(
        ENTITY_SELECT + clause
        + " ORDER BY COALESCE(v.n_reviews, 0) DESC, COALESCE(v.n_mentions, 0) DESC,"
          " e.canonical_name ASC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entities": [dict(row) for row in rows],
    }


@router.get("/entities/{entity_id}")
def entity_detail(
    entity_id: str,
    conn: sqlite3.Connection = Depends(db.get_conn),
    evidence_limit: int = Query(25, ge=1, le=200),
) -> dict:
    """One entity with its spelling variants and the evidence behind it."""
    row = conn.execute(
        ENTITY_SELECT + " WHERE LOWER(e.entity_id) = LOWER(?)", [entity_id]
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no entity {entity_id!r}")

    variants = conn.execute(
        "SELECT surface, mentions, phonetic_key, is_canonical FROM entity_variants "
        "WHERE LOWER(entity_id) = LOWER(?) ORDER BY mentions DESC, surface ASC",
        [entity_id],
    ).fetchall()

    evidence = conn.execute(
        "SELECT mention_id, surface, sentence, match_kind, language, extractor, "
        "       review_id, found_in_place, found_in_district, found_in_division, "
        "       review_rating, review_date "
        "FROM v_mention_evidence WHERE LOWER(entity_id) = LOWER(?) "
        "ORDER BY found_in_place ASC, mention_id ASC LIMIT ?",
        [entity_id, evidence_limit],
    ).fetchall()

    return {
        "entity": dict(row),
        "variants": [dict(v) for v in variants],
        "evidence": [dict(e) for e in evidence],
    }


@router.get("/mentions")
def list_mentions(
    conn: sqlite3.Connection = Depends(db.get_conn),
    entity_id: str | None = None,
    entity_type: str | None = None,
    review_id: str | None = None,
    found_in_place: str | None = Query(None, description="Place whose review the mention sits in"),
    language: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Grounded mentions, each with the sentence and review it came from."""
    where: list[str] = []
    params: list = []
    for column, value, exact in (
        ("entity_id", entity_id, True),
        ("entity_type", entity_type, True),
        ("review_id", review_id, True),
        ("language", language, True),
    ):
        if value:
            where.append(f"LOWER({column}) = LOWER(?)")
            params.append(value)
    if found_in_place:
        where.append("LOWER(found_in_place) LIKE LOWER(?)")
        params.append(f"%{found_in_place}%")

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM v_mention_evidence{clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT mention_id, entity_id, canonical_name, entity_type, surface, sentence, "
        "       match_kind, language, extractor, review_id, found_in_place, "
        "       found_in_district, found_in_division, review_rating, review_date "
        f"FROM v_mention_evidence{clause} ORDER BY mention_id ASC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "mentions": [dict(row) for row in rows],
    }


@router.get("/analytics/language-labels")
def language_labels(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Phase 3's four-way language label (BUILD_PLAN 4.1).

    Separate from /api/analytics/language-mix, which serves Phase 2's coarser
    `detected_language`. Both are kept: the older column is what the committed
    corpus and the earlier phases were built on, and silently replacing it
    would change numbers already written up.

    `language_method` is carried deliberately. A `heuristic` row is not a
    trained classifier's decision and a `short-text` row is a rule, so a mix
    table that hid the difference would overstate what has been established.
    `avg_confidence` is null for rule-based rows rather than filled with a
    stand-in.
    """
    rows = conn.execute(
        "SELECT language_label, language_method, text_basis, review_count, "
        "       avg_confidence, avg_rating "
        "FROM v_language_mix ORDER BY review_count DESC"
    ).fetchall()

    totals: dict[str, int] = {}
    for row in rows:
        label = row["language_label"] or "(none)"
        totals[label] = totals.get(label, 0) + (row["review_count"] or 0)
    overall = sum(totals.values())
    bangla_share = sum(
        count for label, count in totals.items() if label in {"bn", "bn-latn", "mixed"}
    ) / overall if overall else 0.0

    return {
        "by_label": totals,
        "bangla_or_banglish_share": round(bangla_share, 4),
        "target_share": 0.20,
        "meets_target": bangla_share >= 0.20,
        "rows": [dict(row) for row in rows],
    }
