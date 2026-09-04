"""Phase 10 — itinerary builder on real review evidence.

The plan is assembled from the same tables everything else in the API reads, so
a rebuild with more reviews changes the itineraries with no code change:

1. **Candidates** — places are ranked by the Phase 8 `/api/recommend` scorer
   (`_recommend_impl`), i.e. the share of a place's reviews that map to the
   requested preferences, how many of those preferences it covers, and its
   average rating. Nothing is hardcoded per place.
2. **Regions** — the corpus has no coordinates, so proximity is taken from the
   geography hierarchy the pipeline already resolves (city → district →
   division, see `data/place_geography.csv`). A *region* is a division; a day
   is kept inside one district where possible; changing region costs a
   transfer, which the plan reports rather than pretending travel is free.
3. **Days** — regions are visited best-first (or starting from the requested
   city), each holding enough consecutive days for its candidates at the chosen
   pace, so a trip does not bounce between divisions.
4. **Evidence** — every activity carries the preferences it matched, how many
   reviews back each one, and a real review snippet, so a plan can be defended
   from the data instead of asserted.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from backend import db
from backend.models import (
    ItineraryActivity,
    ItineraryDay,
    ItineraryPlan,
    ItineraryStay,
    ItinerarySummary,
    PreferenceEvidence,
)
from backend.queries import review_summary_sql
from backend.routers.discovery import _recommend_impl

router = APIRouter(prefix="/api", tags=["itinerary"])

# Attractions per day. "relaxed" suits long-haul spots (Sundarbans, Saint
# Martin's) where one visit fills a day; "packed" suits city clusters.
PACE_ACTIVITIES = {"relaxed": 1, "standard": 2, "packed": 3}

TRAVEL_NOTES = {
    "start": "Start in {to_city}.",
    "same_city": "Stay in {to_city} — no transfer needed.",
    "same_district": "Short hop within {to_district} district from {from_city} to {to_city}.",
    "same_division": (
        "Move from {from_city} to {to_city} inside {to_division} division — "
        "budget a few hours on the road."
    ),
    "cross_division": (
        "Transfer from {from_city} ({from_division}) to {to_city} ({to_division}) — "
        "a cross-division move, so allow up to half a day of travel."
    ),
}

# How many candidates to pull before planning; the ranking, not this cap,
# decides what actually lands in the plan.
CANDIDATE_LIMIT = 200


class ItineraryRequest(BaseModel):
    """JSON body accepted by `POST /api/itinerary` (mirrors the GET params)."""

    days: int = Field(3, ge=1, le=14)
    preferences: str | None = Field(
        None, description="Comma-separated preference_ids, e.g. P02,P03"
    )
    city: str | None = Field(None, description="City to start from, if any")
    division: str | None = Field(None, description="Restrict the trip to one division")
    exclude_city: str | None = Field(None, description="Comma-separated cities to skip")
    pace: str = Field("standard", pattern="^(relaxed|standard|packed)$")
    include_stays: bool = Field(True, description="Suggest a hotel for each base city")
    min_reviews: int = Field(1, ge=0)
    max_regions: int | None = Field(
        None, ge=1, le=8, description="Cap on divisions visited (default: days // 2 + 1)"
    )


def _region_key(place: Any) -> str:
    return place.division or place.district or place.city or "Unknown region"


def _travel_level(prev: dict | None, cur: dict) -> str:
    if prev is None:
        return "start"
    if prev.get("city") and prev["city"] == cur.get("city"):
        return "same_city"
    if prev.get("district") and prev["district"] == cur.get("district"):
        return "same_district"
    if prev.get("division") and prev["division"] == cur.get("division"):
        return "same_division"
    return "cross_division"


def _preference_evidence(
    conn: sqlite3.Connection, place_id: int, wanted: list[str]
) -> list[PreferenceEvidence]:
    sql = (
        "SELECT preference_id, preference_label, preference_type, review_count, avg_rating "
        "FROM v_venue_preference_rollup WHERE place_id = ?"
    )
    params: list = [place_id]
    if wanted:
        sql += f" AND UPPER(preference_id) IN ({','.join('?' for _ in wanted)})"
        params.extend(wanted)
    sql += " ORDER BY review_count DESC"
    return [PreferenceEvidence(**r) for r in db.rows(conn, sql, params)]


def _snippet(
    conn: sqlite3.Connection, place_id: int, preference_id: str | None, max_len: int = 220
) -> str | None:
    """A real review backing this stop, preferring one tied to the preference."""
    where = (
        "WHERE v.place_id = ? AND r.review_text_clean IS NOT NULL "
        "AND LENGTH(r.review_text_clean) > 40"
    )
    params: list = [place_id]
    if preference_id:
        where += " AND v.preference_id = ?"
        params.append(preference_id)
    row = db.one(
        conn,
        review_summary_sql(where, "ORDER BY v.review_rating DESC, v.text_length DESC") + " LIMIT 1",
        params,
    )
    if row is None and preference_id:
        return _snippet(conn, place_id, None, max_len)
    if row is None:
        return None
    text = (row["review_text_clean"] or "").strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _why(place: Any, evidence: list[PreferenceEvidence]) -> str:
    """One sentence a traveller can check against the data themselves."""
    if place.avg_rating:
        rated = f"rated {place.avg_rating}/5 across {place.review_count} reviews"
    else:
        rated = f"{place.review_count} reviews collected"
    if not evidence:
        return f"No preference evidence yet, but it is {rated}."

    backed = sum(e.review_count for e in evidence)
    labels = ", ".join(e.preference_label or e.preference_id for e in evidence[:2])
    strongest = ""
    if len(evidence) > 1:
        top = evidence[0]
        strongest = f" (strongest: {top.preference_label or top.preference_id})"
    return f"{backed} of its reviews discuss {labels}{strongest}; {rated}."


def _pick_stay(
    conn: sqlite3.Connection, city: str | None, division: str | None, min_reviews: int
) -> ItineraryStay | None:
    """Best-rated accommodation in the day's base city, else in its division."""
    for scope_city, scope_division, note in (
        (city, None, None),
        (None, division, "No reviewed hotel in {city} yet — nearest option in {division}."),
    ):
        if not (scope_city or scope_division):
            continue
        hotels = _recommend_impl(
            conn,
            city=scope_city,
            division=scope_division,
            place_kind="accommodation",
            min_reviews=min_reviews,
            limit=1,
        )
        if hotels:
            h = hotels[0]
            return ItineraryStay(
                place_id=h.place_id,
                place_name=h.place_name,
                city=h.city,
                review_count=h.review_count,
                avg_rating=h.avg_rating,
                note=note.format(city=city or "this city", division=division or "the region")
                if note
                else None,
            )
    return None


def _allocate_days(
    regions: list[tuple[str, list]], days: int, per_day: int, max_regions: int
) -> tuple[list[tuple[str, list, int]], int]:
    """Split the trip into (region, day_count) blocks, best region first.

    A region gets at most as many days as it has candidates to fill at the
    chosen pace, so days are never padded with repeats while another region
    still has unvisited places. Any days left over once every region is spent
    are returned as a count and become free days at the *end* of the trip —
    padding them in the middle would break the plan into disconnected halves.
    """
    blocks: list[tuple[str, list, int]] = []
    remaining = days
    for key, places in regions[:max_regions]:
        if remaining <= 0:
            break
        want = min(remaining, math.ceil(len(places) / per_day))
        if want <= 0:
            continue
        blocks.append((key, places, want))
        remaining -= want
    return blocks, remaining


def _day_buckets(places: list, day_count: int, per_day: int) -> list[list]:
    """Group a region's ranked places into days, keeping each day local.

    The highest-scoring unused place seeds the day; the rest of the day is
    filled from the same district when possible so a day is not spent driving
    across a division.
    """
    remaining = list(places)
    buckets: list[list] = []
    for _ in range(day_count):
        if not remaining:
            buckets.append([])
            continue
        seed = remaining.pop(0)
        bucket = [seed]
        while len(bucket) < per_day and remaining:
            idx = next(
                (i for i, p in enumerate(remaining) if p.district and p.district == seed.district),
                None,
            )
            if idx is None:
                idx = next(
                    (i for i, p in enumerate(remaining) if p.city and p.city == seed.city), 0
                )
            bucket.append(remaining.pop(idx))
        buckets.append(bucket)
    return buckets


def _build_itinerary_impl(conn: sqlite3.Connection, req: ItineraryRequest) -> ItineraryPlan:
    per_day = PACE_ACTIVITIES[req.pace]
    wanted = [p.strip().upper() for p in (req.preferences or "").split(",") if p.strip()]
    warnings: list[str] = []

    # _recommend_impl validates the preference ids (400 on unknown ones) and
    # applies the same scoring the /api/recommend endpoint documents.
    candidates = _recommend_impl(
        conn,
        preferences=req.preferences,
        city=req.city,
        division=req.division,
        place_kind="attraction",
        exclude_city=req.exclude_city,
        min_reviews=req.min_reviews,
        limit=CANDIDATE_LIMIT,
    )
    # Anchoring on one city usually leaves too little to fill a trip, so widen
    # to that city's division and keep the requested city's places in front.
    anchor_city = req.city
    if anchor_city and len(candidates) < req.days * per_day:
        anchor = db.one(
            conn,
            "SELECT division FROM v_place_stats WHERE LOWER(city) = LOWER(?) AND division IS NOT NULL",
            (anchor_city,),
        )
        if anchor and anchor["division"] and not req.division:
            widened = _recommend_impl(
                conn,
                preferences=req.preferences,
                division=anchor["division"],
                place_kind="attraction",
                exclude_city=req.exclude_city,
                min_reviews=req.min_reviews,
                limit=CANDIDATE_LIMIT,
            )
            if len(widened) > len(candidates):
                warnings.append(
                    f"Only {len(candidates)} reviewed attraction(s) in {anchor_city}; "
                    f"widened the search to {anchor['division']} division."
                )
                candidates = widened

    if not candidates:
        return ItineraryPlan(
            request=req.model_dump(),
            summary=ItinerarySummary(
                days=req.days,
                planned_days=0,
                total_activities=0,
                unique_places=0,
                requested_preferences=wanted,
                uncovered_preferences=wanted,
                preference_coverage=0.0 if wanted else None,
            ),
            days=[],
            warnings=warnings
            + [
                "No reviewed attraction matches those filters yet. "
                "Try fewer preferences, another city, or min_reviews=0."
            ],
        )

    # Group into regions, ranked by the evidence they carry. If the traveller
    # named a city, its region leads regardless of score.
    grouped: dict[str, list] = {}
    for c in candidates:
        grouped.setdefault(_region_key(c), []).append(c)
    for places in grouped.values():
        places.sort(key=lambda p: (p.match_score, p.review_count), reverse=True)

    anchor_region = None
    if anchor_city:
        anchor_region = next(
            (
                _region_key(c)
                for c in candidates
                if c.city and c.city.lower() == anchor_city.lower()
            ),
            None,
        )
        if anchor_region:
            grouped[anchor_region].sort(
                key=lambda p: (
                    bool(p.city and anchor_city and p.city.lower() == anchor_city.lower()),
                    p.match_score,
                ),
                reverse=True,
            )

    regions = sorted(
        grouped.items(),
        key=lambda kv: (
            kv[0] == anchor_region,
            sum(p.match_score for p in kv[1][: req.days * per_day]),
        ),
        reverse=True,
    )

    max_regions = req.max_regions or max(1, min(len(regions), req.days // 2 + 1))
    blocks, spare_days = _allocate_days(regions, req.days, per_day, max_regions)

    days: list[ItineraryDay] = []
    prev_base: dict | None = None
    day_no = 0
    for _region, places, day_count in blocks:
        for bucket in _day_buckets(places, day_count, per_day):
            if not bucket:
                continue
            day_no += 1
            notes: list[str] = []
            seed = bucket[0]
            base = {"city": seed.city, "district": seed.district, "division": seed.division}
            level = _travel_level(prev_base, base)
            note = TRAVEL_NOTES[level].format(
                from_city=(prev_base or {}).get("city") or "your start point",
                from_division=(prev_base or {}).get("division") or "—",
                to_city=base["city"] or "the area",
                to_district=base["district"] or "the district",
                to_division=base["division"] or "the region",
            )
            if len({p.district for p in bucket}) > 1:
                notes.append("This day spans two districts — start early.")

            activities: list[ItineraryActivity] = []
            for rec in bucket:
                evidence = _preference_evidence(conn, rec.place_id, wanted)
                activities.append(
                    ItineraryActivity(
                        place_id=rec.place_id,
                        place_name=rec.place_name,
                        city=rec.city,
                        district=rec.district,
                        division=rec.division,
                        category=rec.category,
                        review_count=rec.review_count,
                        avg_rating=rec.avg_rating,
                        match_score=rec.match_score,
                        matched_preferences=evidence,
                        evidence_review_count=sum(e.review_count for e in evidence),
                        why=_why(rec, evidence),
                        review_snippet=_snippet(
                            conn, rec.place_id, evidence[0].preference_id if evidence else None
                        ),
                    )
                )

            stay = (
                _pick_stay(conn, base["city"], base["division"], req.min_reviews)
                if req.include_stays
                else None
            )
            if req.include_stays and stay is None:
                notes.append(f"No reviewed accommodation near {base['city'] or 'this stop'} yet.")

            days.append(
                ItineraryDay(
                    day=day_no,
                    base_city=base["city"],
                    district=base["district"],
                    division=base["division"],
                    travel_level=level,
                    travel_note=note,
                    activities=activities,
                    stay=stay,
                    notes=notes,
                )
            )
            prev_base = base

    # Days the corpus cannot fill are kept — the traveller asked for them — but
    # labelled honestly instead of being padded with repeat stops.
    for _ in range(spare_days):
        day_no += 1
        base = prev_base or {}
        days.append(
            ItineraryDay(
                day=day_no,
                base_city=base.get("city"),
                district=base.get("district"),
                division=base.get("division"),
                travel_level="same_city" if prev_base else "start",
                travel_note="Free day — the corpus has no further reviewed attraction to add.",
                notes=[
                    "Every reviewed attraction matching your filters is already in the plan; "
                    "use this day to rest, explore locally, or extend an earlier stop."
                ],
            )
        )

    planned = [d for d in days if d.activities]
    all_activities = [a for d in days for a in d.activities]
    ratings = [a.avg_rating for a in all_activities if a.avg_rating is not None]
    evidenced = {e.preference_id for a in all_activities for e in a.matched_preferences}
    # With preferences requested, "covered" means those of them the plan can
    # back; without, it is simply everything the plan happens to demonstrate.
    covered = sorted(evidenced & set(wanted)) if wanted else sorted(evidenced)
    uncovered = sorted(set(wanted) - set(covered))

    if uncovered:
        warnings.append(
            "No place in this plan has review evidence for: " + ", ".join(uncovered) + "."
        )
    if len(planned) < req.days:
        warnings.append(
            f"Only {len(planned)} of {req.days} day(s) could be filled from the current corpus."
        )

    summary = ItinerarySummary(
        days=req.days,
        planned_days=len(planned),
        total_activities=len(all_activities),
        unique_places=len({a.place_id for a in all_activities}),
        cities=sorted({a.city for a in all_activities if a.city}),
        divisions=sorted({a.division for a in all_activities if a.division}),
        avg_activity_rating=round(sum(ratings) / len(ratings), 3) if ratings else None,
        evidence_reviews=sum(a.evidence_review_count for a in all_activities),
        requested_preferences=wanted,
        covered_preferences=covered,
        uncovered_preferences=uncovered,
        preference_coverage=round(len(covered) / len(wanted), 4) if wanted else None,
        transfers=sum(1 for d in days if d.travel_level in ("same_division", "cross_division")),
    )
    return ItineraryPlan(
        request=req.model_dump(), summary=summary, days=days, warnings=warnings
    )


@router.get("/itinerary", response_model=ItineraryPlan)
def get_itinerary(
    conn: sqlite3.Connection = Depends(db.get_conn),
    days: int = Query(3, ge=1, le=14),
    preferences: str | None = Query(None, description="Comma-separated preference_ids"),
    city: str | None = Query(None, description="City to start from"),
    division: str | None = Query(None, description="Restrict the trip to one division"),
    exclude_city: str | None = Query(None, description="Comma-separated cities to skip"),
    pace: str = Query("standard", pattern="^(relaxed|standard|packed)$"),
    include_stays: bool = Query(True),
    min_reviews: int = Query(1, ge=0),
    max_regions: int | None = Query(None, ge=1, le=8),
) -> ItineraryPlan:
    """Build a day-by-day plan from the review corpus.

    Places are ranked with the `/api/recommend` scorer, grouped by the
    geography hierarchy so consecutive days stay near each other, and returned
    with the preference evidence and review snippets that justify each stop.
    """
    return _build_itinerary_impl(
        conn,
        ItineraryRequest(
            days=days,
            preferences=preferences,
            city=city,
            division=division,
            exclude_city=exclude_city,
            pace=pace,
            include_stays=include_stays,
            min_reviews=min_reviews,
            max_regions=max_regions,
        ),
    )


@router.post("/itinerary", response_model=ItineraryPlan)
def post_itinerary(
    payload: ItineraryRequest = Body(...),
    conn: sqlite3.Connection = Depends(db.get_conn),
) -> ItineraryPlan:
    """Same planner as `GET /api/itinerary`, taking a JSON body."""
    return _build_itinerary_impl(conn, payload)


@router.get("/itinerary/options", response_model=dict)
def itinerary_options(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Everything a form needs to build a valid request — read from the DB.

    The frontend renders its controls from this, so new preferences, cities or
    divisions appear after a rebuild without touching the page.
    """
    prefs = db.rows(
        conn,
        "SELECT p.preference_id, p.preference_label, p.category, p.subcategory, "
        "p.preference_type, f.review_count, f.topic_count "
        "FROM preferences p LEFT JOIN v_preference_frequency f "
        "ON f.preference_id = p.preference_id ORDER BY f.review_count DESC, p.preference_id",
    )
    return {
        "preferences": prefs,
        "cities": [
            r["city"]
            for r in db.rows(
                conn,
                "SELECT city FROM v_city_stats WHERE review_count > 0 ORDER BY review_count DESC",
            )
        ],
        "divisions": [
            r["division"]
            for r in db.rows(
                conn,
                "SELECT division, COUNT(*) AS n FROM places WHERE division IS NOT NULL "
                "AND division <> '' GROUP BY division ORDER BY n DESC",
            )
        ],
        "pace": [{"value": k, "activities_per_day": v} for k, v in PACE_ACTIVITIES.items()],
        "max_days": 14,
        "attraction_count": db.scalar(
            conn, "SELECT COUNT(*) FROM places WHERE place_kind = 'attraction'"
        ),
        "accommodation_count": db.scalar(
            conn, "SELECT COUNT(*) FROM places WHERE place_kind = 'accommodation'"
        ),
    }


__all__ = ["router", "ItineraryRequest", "_build_itinerary_impl"]
