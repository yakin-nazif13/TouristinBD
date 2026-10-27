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
from backend.queries import review_summary_sql

router = APIRouter(prefix="/api", tags=["discovery"])

# Weights for the recommendation blend. Documented in the endpoint docstring so
# the ranking stays explainable in the write-up.
W_EVIDENCE = 0.45
W_PREF_COVERAGE = 0.30
W_RATING = 0.25


SEARCH_KINDS = "place,city,food,activity,transport,gem,preference,topic,review"

# The entity layer's types, under the names a visitor would search for.
THING_KINDS = {"food": "FOOD", "activity": "ACTIVITY", "transport": "ACCESS"}

def _like(column: str, text: str) -> tuple[str, list[str]]:
    """`column` contains `text`, whatever its case or Bangla spelling form."""
    return db.like_any(column, text)


def _like_all(column: str, words: list[str]) -> tuple[str, list[str]]:
    """`column` contains every one of `words`, in any order."""
    parts = [_like(column, w) for w in words]
    return "(" + " AND ".join(p[0] for p in parts) + ")", [x for p in parts for x in p[1]]


def _snippet(text: str, words: list[str], width: int = 220) -> str:
    """A window of `text` around the first matched word, rather than its start.

    A long review that mentions bamboo chicken in its fifth paragraph would
    otherwise be shown by its first sentence, and the match would be invisible.
    """
    text = " ".join(str(text or "").split())
    lowered = text.lower()
    found = [lowered.find(f.lower()) for w in words for f in db.spelling_forms(w)]
    at = min((i for i in found if i >= 0), default=0)
    start = max(0, at - width // 3)
    piece = text[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


def _search_impl(
    conn: sqlite3.Connection,
    q: str,
    kinds: str = SEARCH_KINDS,
    limit_per_kind: int = 5,
) -> list[SearchHit]:
    """One query across every kind of thing the site knows about.

    Case never matters, either Unicode spelling of a Bangla letter is found,
    and a several-word query matches its words in any order, so "chicken
    bamboo" finds "bamboo chicken".
    """
    wanted = {k.strip().lower() for k in kinds.split(",") if k.strip()}
    words = [w for w in q.split() if len(w) >= 2] or [q]
    hits: list[SearchHit] = []
    surface, surface_params = _like("v.surface", q)

    if "place" in wanted:
        # A place can also be found by a Bangla or variant spelling reviewers
        # used ("কুয়াকাটা" finds Kuakata Sea Beach): the spelling resolves to a
        # place entity, whose name is then looked for in the place names.
        aliases = [r["canonical_name"] for r in db.rows(
            conn,
            "SELECT DISTINCT e.canonical_name FROM entities e JOIN entity_variants v "
            f"ON v.entity_id = e.entity_id WHERE e.entity_type = 'PLACE' AND {surface} LIMIT 5",
            surface_params,
        )]
        name, name_params = _like_all("place_name", words)
        city, city_params = _like("city", q)
        alias_clause = "".join(" OR place_name LIKE ? ESCAPE '\\'" for _ in aliases)
        for r in db.rows(
            conn,
            "SELECT place_id, place_name, city, category, review_count, avg_review_rating "
            f"FROM v_place_stats WHERE {name} OR {city}{alias_clause} "
            "ORDER BY review_count DESC LIMIT ?",
            [*name_params, *city_params, *[db.like_term(a) for a in aliases], limit_per_kind],
        ):
            hits.append(
                SearchHit(
                    kind="place",
                    id=str(r["place_id"]),
                    label=r["place_name"],
                    detail=f"{r['city'] or 'unknown city'} · {r['category'] or '—'} · "
                    f"{r['review_count']} reviews · avg {r['avg_review_rating']}",
                    score=float(r["review_count"] or 0),
                    place=r["place_name"],
                )
            )

    if "city" in wanted:
        city, city_params = _like("city", q)
        district, district_params = _like("district", q)
        for r in db.rows(
            conn,
            "SELECT city, district, division, place_count, review_count, avg_review_rating "
            f"FROM v_city_stats WHERE {city} OR {district} "
            "ORDER BY review_count DESC LIMIT ?",
            [*city_params, *district_params, limit_per_kind],
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

    # Foods, activities and transport, by any spelling reviewers used
    # ("bamboo chicken", "ব্যাম্বু চিকেন"), each leading to the places that offer it.
    thing_name, thing_params = _like_all("e.canonical_name", words)
    for kind, entity_type in THING_KINDS.items():
        if kind not in wanted:
            continue
        for r in db.rows(
            conn,
            "SELECT e.entity_id, e.canonical_name, "
            "  (SELECT COUNT(DISTINCT pa.place_name) FROM place_attributes pa WHERE pa.entity_id = e.entity_id) AS n_places, "
            "  (SELECT COALESCE(SUM(pa.n_reviews), 0) FROM place_attributes pa WHERE pa.entity_id = e.entity_id) AS n_reviews "
            f"FROM entities e WHERE e.entity_type = ? AND ({thing_name} OR EXISTS ("
            f"  SELECT 1 FROM entity_variants v WHERE v.entity_id = e.entity_id AND {surface})) "
            "ORDER BY n_reviews DESC LIMIT ?",
            [entity_type, *thing_params, *surface_params, limit_per_kind],
        ):
            if not r["n_places"]:
                continue
            speciality = db.one(conn, "SELECT district FROM local_specialities WHERE entity_id = ?",
                                (r["entity_id"],))
            hits.append(SearchHit(
                kind=kind,
                id=r["entity_id"],
                label=r["canonical_name"],
                detail=f"mentioned in {r['n_reviews']} review(s) of {r['n_places']} place(s)"
                + (f" · a local speciality of {speciality['district']}" if speciality else ""),
                score=float(r["n_reviews"] or 0),
            ))

    if "gem" in wanted:
        gem_name, gem_params = _like_all("g.canonical_name", words)
        for r in db.rows(
            conn,
            "SELECT g.entity_id, g.canonical_name, g.gem_rank, g.gem_score, g.visibility, g.n_reviews "
            f"FROM gems g WHERE {gem_name} OR EXISTS ("
            f"  SELECT 1 FROM entity_variants v WHERE v.entity_id = g.entity_id AND {surface}) "
            "ORDER BY g.gem_rank LIMIT ?",
            [*gem_params, *surface_params, limit_per_kind],
        ):
            hits.append(SearchHit(
                kind="gem",
                id=r["entity_id"],
                label=r["canonical_name"],
                detail=f"gem #{r['gem_rank']} · score {r['gem_score']:.2f} · {r['visibility']} · "
                f"{r['n_reviews']} independent review(s)",
                score=float(r["gem_score"] or 0),
            ))

    if "preference" in wanted:
        label, label_params = _like("p.preference_label", q)
        description, description_params = _like("p.preference_description", q)
        subcategory, subcategory_params = _like("p.subcategory", q)
        for r in db.rows(
            conn,
            "SELECT p.preference_id, p.preference_label, p.preference_description, "
            "p.preference_type, f.review_count FROM preferences p "
            "JOIN v_preference_frequency f ON f.preference_id = p.preference_id "
            f"WHERE {label} OR {description} OR {subcategory} "
            "ORDER BY f.review_count DESC LIMIT ?",
            [*label_params, *description_params, *subcategory_params, limit_per_kind],
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
        label, label_params = _like("interpreted_label", q)
        keywords, keyword_params = _like("top_keywords", q)
        interpretation, interpretation_params = _like("interpretation", q)
        for r in db.rows(
            conn,
            "SELECT topic_id, interpreted_label, top_keywords, review_count FROM topics "
            f"WHERE {label} OR {keywords} OR {interpretation} "
            "ORDER BY review_count DESC LIMIT ?",
            [*label_params, *keyword_params, *interpretation_params, limit_per_kind],
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
        every_word, word_params = _like_all("r.review_text_clean", words)
        phrase, phrase_params = _like("r.review_text_clean", q)
        # The exact phrase first, then the shortest: a short review that names
        # the term is about it; a 3,000-character essay may mention it once.
        for r in db.rows(
            conn,
            "SELECT r.review_id, r.review_text_clean, r.review_rating, p.place_name "
            "FROM reviews r LEFT JOIN places p ON p.place_id = r.place_id "
            f"WHERE {every_word} "
            f"ORDER BY {phrase} DESC, r.review_rating DESC, r.text_length ASC LIMIT ?",
            [*word_params, *phrase_params, limit_per_kind],
        ):
            hits.append(
                SearchHit(
                    kind="review",
                    id=r["review_id"],
                    label=f"{r['place_name']} · {r['review_rating']}★",
                    detail=_snippet(r["review_text_clean"], words),
                    score=float(r["review_rating"] or 0),
                    place=r["place_name"],
                )
            )

    return hits


@router.get("/search", response_model=list[SearchHit])
def search(
    q: str = Query(..., min_length=2, description="Free-text query"),
    conn: sqlite3.Connection = Depends(db.get_conn),
    kinds: str = Query(
        SEARCH_KINDS,
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
        f"SELECT place_id, place_name, city, district, division, category, place_kind, "
        f"review_count, avg_review_rating FROM v_place_stats WHERE {' AND '.join(where)}",
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
                division=p["division"],
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


def _sample_reviews_for_place(
    conn: sqlite3.Connection, place_id: int, limit: int = 2
) -> dict[str, list[dict]]:
    """The most substantial positive and critical reviews backing a place.

    Phase 10's comparison view needs the *words* behind the numbers, not just
    the aggregate — a 3.2★ hotel and a 3.2★ hotel are not the same hotel.
    """

    def fetch(order: str, having: str) -> list[dict]:
        return db.rows(
            conn,
            review_summary_sql(
                f"WHERE v.place_id = ? AND {having} AND r.review_text_clean IS NOT NULL "
                "AND LENGTH(r.review_text_clean) > 40",
                f"ORDER BY {order}",
            )
            + " LIMIT ?",
            (place_id, limit),
        )

    return {
        "positive": fetch("v.review_rating DESC, v.text_length DESC", "v.review_rating >= 4"),
        "critical": fetch("v.review_rating ASC, v.text_length DESC", "v.review_rating <= 3"),
    }


def _comparison_metrics(resolved: list[dict]) -> list[dict]:
    """Side-by-side metric rows with a leader per row (None when tied)."""
    specs = [
        ("avg_rating", "Average rating", True, "/5"),
        ("review_count", "Reviews analysed", True, None),
        ("positive_share", "Share of 4-5★ reviews", True, "%"),
        ("negative_share", "Share of 1-2★ reviews", False, "%"),
        ("preference_breadth", "Distinct preferences evidenced", True, None),
        ("evidence_share", "Reviews mapped to a preference", True, "%"),
    ]

    def value_of(row: dict, metric: str) -> float | None:
        total = row.get("review_count") or 0
        if metric == "avg_rating":
            return row.get("avg_review_rating")
        if metric == "review_count":
            return float(total)
        if metric == "positive_share":
            return round((row.get("positive_reviews") or 0) / total, 4) if total else None
        if metric == "negative_share":
            return round((row.get("negative_reviews") or 0) / total, 4) if total else None
        if metric == "preference_breadth":
            return float(len(row.get("preferences") or []))
        if metric == "evidence_share":
            mapped = sum(p["review_count"] for p in row.get("preferences") or [])
            return round(mapped / total, 4) if total else None
        return None

    metrics: list[dict] = []
    for metric, label, higher_is_better, unit in specs:
        values = {r["place_name"]: value_of(r, metric) for r in resolved}
        present = {k: v for k, v in values.items() if v is not None}
        leader = None
        if present:
            best = (max if higher_is_better else min)(present.values())
            winners = [k for k, v in present.items() if v == best]
            leader = winners[0] if len(winners) == 1 else None
        metrics.append(
            {
                "metric": metric,
                "label": label,
                "higher_is_better": higher_is_better,
                "unit": unit,
                "values": values,
                "leader": leader,
            }
        )
    return metrics


def _comparison_summary(resolved: list[dict], metrics: list[dict], shared: list[str]) -> str:
    by_metric = {m["metric"]: m for m in metrics}
    parts: list[str] = []
    rating = by_metric["avg_rating"]
    if rating["leader"]:
        parts.append(
            f"{rating['leader']} rates highest at {rating['values'][rating['leader']]}/5"
        )
    breadth = by_metric["preference_breadth"]
    if breadth["leader"]:
        parts.append(
            f"{breadth['leader']} covers the most preferences "
            f"({int(breadth['values'][breadth['leader']])})"
        )
    parts.append(
        f"they share {len(shared)} preference(s)"
        if shared
        else "they share no preference evidence, so they suit different trips"
    )
    return "; ".join(parts) + "."


def _compare_impl(conn: sqlite3.Connection, places: str, sample_reviews: int = 2) -> dict:
    refs = [p.strip() for p in places.split(",") if p.strip()]
    if not 2 <= len(refs) <= 4:
        raise HTTPException(status_code=400, detail="pass between 2 and 4 places")
    if len({r.lower() for r in refs}) != len(refs):
        raise HTTPException(status_code=400, detail="pass distinct places")

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
        if sample_reviews:
            row["sample_reviews"] = _sample_reviews_for_place(
                conn, row["place_id"], sample_reviews
            )
        resolved.append(row)

    pref_sets = [{p["preference_id"] for p in r["preferences"]} for r in resolved]
    shared = sorted(set.intersection(*pref_sets)) if pref_sets else []
    labels = {
        p["preference_id"]: p["preference_label"] for r in resolved for p in r["preferences"]
    }
    metrics = _comparison_metrics(resolved)
    return {
        "places": resolved,
        "shared_preferences": shared,
        "shared_preference_labels": [labels.get(pid, pid) for pid in shared],
        "distinct_preferences": {
            r["place_name"]: sorted(s - set(shared)) for r, s in zip(resolved, pref_sets)
        },
        # Phase 10: the interpretation layer on top of the raw rows, so the
        # frontend renders a verdict instead of re-deriving one in JavaScript.
        "comparison": {
            "metrics": metrics,
            "summary": _comparison_summary(resolved, metrics, shared),
            "top_preference": {
                r["place_name"]: (
                    r["preferences"][0]["preference_label"] if r["preferences"] else None
                )
                for r in resolved
            },
        },
    }


@router.get("/compare", response_model=dict)
def compare(
    conn: sqlite3.Connection = Depends(db.get_conn),
    places: str = Query(..., description="Comma-separated place_ids or place names (2-4)"),
    sample_reviews: int = Query(2, ge=0, le=10, description="Supporting reviews per place"),
) -> dict:
    """Side-by-side comparison of 2-4 places on real review evidence.

    Returns the raw per-place rows (stats, preference rollup, rating breakdown,
    supporting positive/critical reviews) plus a `comparison` block holding the
    metric table, a leader per metric, and a one-line verdict.
    """
    return _compare_impl(conn, places, sample_reviews)
