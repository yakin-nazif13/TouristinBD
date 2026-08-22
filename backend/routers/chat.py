"""Phase 9 — retrieval-based chatbot.

No LLM call and no API key: the message is classified into a small set of
intents by keyword regexes, entities (place / city / preference) are matched
against whatever is currently in the database, and the reply is composed from
the same read-only views `/api/search`, `/api/recommend`, `/api/compare` and
`/api/places` already serve (imported and called in-process, not duplicated).
Because nothing here is hardcoded to specific place or preference ids, new
places, cities or preferences added in a later rebuild are picked up with no
code change — the same forward-compatibility goal as the rest of Phase 8.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend import db
from backend.routers.discovery import _compare_impl, _recommend_impl, _search_impl
from backend.routers.places import _get_place_impl, _list_places_impl

router = APIRouter(prefix="/api", tags=["chat"])

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "have", "about", "near",
    "some", "good", "nice", "want", "looking", "places", "place", "things",
    "what", "whats", "where", "wheres", "tell", "know", "does", "any",
    "there", "you", "your", "are", "can", "could", "would", "like", "into",
    "from", "who", "how", "much", "many", "than", "then", "also", "very",
}

WORD_RE = re.compile(r"[a-z']+")

GREETING_RE = re.compile(r"\b(hi|hello|hey|salam|assalamualaikum|good morning|good afternoon|good evening)\b")
THANKS_RE = re.compile(r"\b(thanks|thank you|thx|cheers)\b")
COMPARE_RE = re.compile(r"\b(compare|versus)\b|\bvs\.?\b")
REVIEW_RE = re.compile(r"\b(reviews?|say about|feedback|opinions?|worth (it|visiting))\b")
RECOMMEND_RE = re.compile(
    r"\b(recommend|suggest|best|top|where (should|can) i|things to do|"
    r"good places?|looking for|want to (see|visit|go))\b"
)
ACCOMMODATION_RE = re.compile(r"\b(hotel|hotels|resort|stay|accommodation|room)\b")
ATTRACTION_RE = re.compile(r"\b(attraction|sightseeing|beach|tour|monument)\b")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(5, ge=1, le=20)


class ChatResponse(BaseModel):
    intent: str
    reply: str
    entities: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    suggestions: list[str] = []


def _tokenize(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if len(w) > 2 and w not in STOPWORDS}


STRONG_MATCH_SCORE = 100


def _match_places(conn: sqlite3.Connection, message_lower: str, tokens: set[str]) -> list[dict]:
    """Places mentioned in the message, ranked, each tagged with a match score.

    A score of `STRONG_MATCH_SCORE` means the full name (or its part before
    any parenthetical qualifier, e.g. "Sundarbans" out of "Sundarbans
    (Karamjal Wildlife Centre)") appears verbatim in the message — a
    confident match. Anything lower is a fuzzy single-word overlap (e.g.
    "lake" matching both "Kaptai Lake" and "Foy's Lake Resort") and should
    not by itself override a stronger signal elsewhere in the message.
    """
    ranked: list[tuple[int, dict]] = []
    for p in db.rows(conn, "SELECT place_id, place_name, city, review_count FROM v_place_stats"):
        name_lower = p["place_name"].lower()
        primary = name_lower.split(" (")[0].strip()
        if name_lower in message_lower or (primary and primary in message_lower):
            p["_match_score"] = STRONG_MATCH_SCORE
            ranked.append((STRONG_MATCH_SCORE, p))
            continue
        name_tokens = {w for w in WORD_RE.findall(name_lower) if len(w) > 3}
        overlap = name_tokens & tokens
        if overlap:
            p["_match_score"] = len(overlap)
            ranked.append((len(overlap), p))
    ranked.sort(key=lambda x: (x[0], x[1]["review_count"] or 0), reverse=True)
    return [p for _, p in ranked]


def _match_cities(conn: sqlite3.Connection, message_lower: str) -> list[dict]:
    return [
        c
        for c in db.rows(conn, "SELECT city, district, division FROM v_city_stats")
        if c["city"] and c["city"].lower() in message_lower
    ]


def _match_preferences(conn: sqlite3.Connection, tokens: set[str]) -> list[dict]:
    ranked: list[tuple[int, dict]] = []
    for p in db.rows(
        conn,
        "SELECT preference_id, preference_label, category, subcategory, "
        "preference_description FROM preferences",
    ):
        text = " ".join(
            filter(None, [p["preference_label"], p["category"], p["subcategory"], p["preference_description"]])
        )
        pref_tokens = {w for w in WORD_RE.findall(text.lower()) if len(w) > 3 and w not in STOPWORDS}
        overlap = pref_tokens & tokens
        if overlap:
            ranked.append((len(overlap), p))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in ranked]


SUGGESTIONS = [
    "best beaches in Cox's Bazar",
    "tell me about Sundarbans",
    "compare Kaptai Lake and Ratargul Swamp Forest",
    "hotels in Sylhet",
]


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, conn: sqlite3.Connection = Depends(db.get_conn)) -> ChatResponse:
    """A single retrieval turn: classify intent, fetch evidence, reply."""
    message = payload.message.strip()
    lower = message.lower()
    tokens = _tokenize(lower)

    if GREETING_RE.search(lower) and len(tokens) <= 3:
        return ChatResponse(
            intent="greeting",
            reply="Hi! Ask me about places, cities, or interests in Bangladesh — "
            "for example: \"" + SUGGESTIONS[0] + "\".",
            suggestions=SUGGESTIONS,
        )
    if THANKS_RE.search(lower) and len(tokens) <= 4:
        return ChatResponse(intent="thanks", reply="You're welcome! Anything else you'd like to explore?")

    matched_places = _match_places(conn, lower, tokens)
    matched_cities = _match_cities(conn, lower)
    matched_prefs = _match_preferences(conn, tokens)
    # A full place name found verbatim in the message is a confident match;
    # a match from a single overlapping word (e.g. "lake") is not — it should
    # not be enough to drag an unrelated place into a comparison, or to
    # override a place lookup with an unrelated preference recommendation.
    strong_places = [p for p in matched_places if p["_match_score"] >= STRONG_MATCH_SCORE]

    place_kind = None
    if ACCOMMODATION_RE.search(lower):
        place_kind = "accommodation"
    elif ATTRACTION_RE.search(lower):
        place_kind = "attraction"

    if COMPARE_RE.search(lower) and len(strong_places) >= 2:
        ids = [str(p["place_id"]) for p in strong_places[:4]]
        result = _compare_impl(conn, ",".join(ids))
        names = [p["place_name"] for p in result["places"]]
        shared = result["shared_preferences"]
        reply = f"Comparing {', '.join(names)}: " + (
            f"they share {len(shared)} preference(s) — {', '.join(shared)}."
            if shared
            else "no shared preference evidence between them yet."
        )
        return ChatResponse(
            intent="compare", reply=reply, entities={"places": names}, results=[result]
        )

    if REVIEW_RE.search(lower) and matched_places:
        top = matched_places[0]
        detail = _get_place_impl(conn, str(top["place_id"]), sample_reviews=payload.limit)
        texts = [r.review_text_clean for r in detail.sample_reviews if r.review_text_clean]
        rating = detail.place.avg_review_rating
        reply = (
            f"{detail.place.place_name} has {detail.place.review_count} review(s), "
            f"averaging {rating if rating is not None else 'n/a'}/5."
        )
        if texts:
            reply += " Sample: " + " | ".join(t[:160] for t in texts[:3])
        return ChatResponse(
            intent="reviews",
            reply=reply,
            entities={"place": detail.place.place_name},
            results=[r.model_dump() for r in detail.sample_reviews],
        )

    if matched_prefs and not (strong_places and not RECOMMEND_RE.search(lower)):
        pref_ids = [p["preference_id"] for p in matched_prefs[:3]]
        city_filter = matched_cities[0]["city"] if matched_cities else None
        recs = _recommend_impl(
            conn,
            preferences=",".join(pref_ids),
            city=city_filter,
            place_kind=place_kind,
            limit=payload.limit,
        )
        if recs:
            listing = ", ".join(f"{r.place_name} ({r.avg_rating}★)" for r in recs)
            basis = ", ".join(p["preference_label"] for p in matched_prefs[:3] if p["preference_label"])
            where = f" in {city_filter}" if city_filter else ""
            reply = f"For {basis}{where}, top matches: {listing}."
        else:
            reply = "I couldn't find review evidence for that combination yet — try a different city."
        return ChatResponse(
            intent="recommend",
            reply=reply,
            entities={"preferences": pref_ids, "city": city_filter, "place_kind": place_kind},
            results=[r.model_dump() for r in recs],
        )

    if matched_places:
        top = matched_places[0]
        detail = _get_place_impl(conn, str(top["place_id"]), sample_reviews=3)
        pref_labels = [p.preference_label for p in detail.preferences[:3] if p.preference_label]
        rating = detail.place.avg_review_rating
        reply = (
            f"{detail.place.place_name} in {detail.place.city or 'an unspecified city'} has "
            f"{detail.place.review_count} review(s) averaging {rating if rating is not None else 'n/a'}/5."
        )
        if pref_labels:
            reply += f" Known for: {', '.join(pref_labels)}."
        return ChatResponse(
            intent="place_info",
            reply=reply,
            entities={"place": detail.place.place_name},
            results=[detail.model_dump()],
        )

    if matched_cities:
        city = matched_cities[0]["city"]
        page = _list_places_impl(conn, city=city, sort="review_count", order="desc", limit=payload.limit)
        if page.items:
            names = ", ".join(p.place_name for p in page.items)
            reply = f"{city} has {page.total} reviewed place(s), including: {names}."
        else:
            reply = f"I don't have any reviewed places for {city} yet."
        return ChatResponse(
            intent="city_info",
            reply=reply,
            entities={"city": city},
            results=[p.model_dump() for p in page.items],
        )

    if RECOMMEND_RE.search(lower):
        recs = _recommend_impl(conn, place_kind=place_kind, limit=payload.limit)
        listing = ", ".join(f"{r.place_name} ({r.avg_rating}★)" for r in recs)
        reply = f"Overall top-rated picks: {listing}." if recs else "No places in the dataset yet."
        return ChatResponse(
            intent="recommend_general",
            reply=reply,
            entities={"place_kind": place_kind},
            results=[r.model_dump() for r in recs],
        )

    if len(message) >= 2:
        hits = _search_impl(conn, message, kinds="place,city,preference,topic,review", limit_per_kind=3)
        if hits:
            top = hits[: payload.limit]
            reply = "Here's what I found: " + "; ".join(f"{h.label} ({h.kind})" for h in top)
            return ChatResponse(intent="search_fallback", reply=reply, results=[h.model_dump() for h in top])

    return ChatResponse(
        intent="unknown",
        reply="I couldn't match that to anything in the dataset yet. Try asking about a place, "
        "a city, or an interest — for example: \"" + SUGGESTIONS[0] + "\".",
        suggestions=SUGGESTIONS,
    )
