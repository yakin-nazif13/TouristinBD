"""Response models for the Phase 8 API.

Kept deliberately permissive (every analytical field optional) so that adding a
column upstream in the pipeline does not break serialization — the point of the
project is a flexible data layer, not a rigid contract.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int = Field(description="Rows matching the filters, ignoring pagination")
    limit: int
    offset: int
    returned: int
    items: list[T]


class Health(BaseModel):
    status: str
    database: str
    schema_version: int | None = None
    built_at_utc: str | None = None
    detail: str | None = None


class Meta(BaseModel):
    schema_version: int
    built_at_utc: str | None = None
    row_counts: dict[str, int] = {}
    source_files: dict[str, str | None] = {}
    build_notes: list[str] = []
    pipeline_phases: dict[str, str] = {}


class DatasetOverview(BaseModel):
    total_reviews: int
    total_places: int
    total_cities: int
    total_topics: int
    total_preferences: int
    clustered_reviews: int
    outlier_reviews: int
    avg_rating: float | None = None
    first_review_date: str | None = None
    last_review_date: str | None = None
    reviews_by_source: dict[str, int] = {}
    reviews_by_language: dict[str, int] = {}
    reviews_by_place_kind: dict[str, int] = {}
    preferences_by_type: dict[str, int] = {}


class Place(BaseModel):
    place_id: int
    place_name: str
    city: str | None = None
    district: str | None = None
    division: str | None = None
    category: str | None = None
    place_kind: str | None = None
    source: str | None = None
    place_avg_rating: float | None = None
    source_url: str | None = None
    review_count: int = 0
    avg_review_rating: float | None = None
    positive_reviews: int | None = None
    negative_reviews: int | None = None
    first_review_date: str | None = None
    last_review_date: str | None = None


class PlacePreference(BaseModel):
    preference_id: str | None = None
    preference_label: str | None = None
    preference_type: str | None = None
    review_count: int
    avg_rating: float | None = None
    review_share: float | None = None


class ReviewSummary(BaseModel):
    review_id: str
    place_id: int | None = None
    place_name: str | None = None
    city: str | None = None
    source: str | None = None
    review_rating: float | None = None
    review_text_clean: str | None = None
    review_date: str | None = None
    detected_language: str | None = None
    topic_id: int | None = None
    interpreted_label: str | None = None
    preference_id: str | None = None
    preference_label: str | None = None
    preference_type: str | None = None


class PlaceDetail(BaseModel):
    place: Place
    rating_breakdown: list[dict[str, Any]] = []
    preferences: list[PlacePreference] = []
    topics: list[dict[str, Any]] = []
    sample_reviews: list[ReviewSummary] = []


class City(BaseModel):
    city: str
    district: str | None = None
    division: str | None = None
    place_count: int
    review_count: int
    avg_review_rating: float | None = None


class Topic(BaseModel):
    topic_id: int
    topic_name: str | None = None
    top_keywords: str | None = None
    review_count: int | None = None
    corpus_share: float | None = None
    interpreted_label: str | None = None
    interpretation: str | None = None
    dimension_hint: str | None = None
    preference_id: str | None = None
    preference_label: str | None = None
    preference_type: str | None = None
    similarity: float | None = None
    confidence: str | None = None
    needs_review: bool | None = None
    is_long_tail: bool | None = None
    sdd: float | None = None


class Preference(BaseModel):
    preference_id: str
    category: str | None = None
    subcategory: str | None = None
    preference_label: str | None = None
    preference_description: str | None = None
    preference_type: str | None = None
    topic_count: int = 0
    review_count: int = 0
    review_share: float | None = None
    avg_similarity: float | None = None
    coverage_status: str | None = None
    coverage_action: str | None = None


class PreferenceDetail(BaseModel):
    preference: Preference
    topics: list[Topic] = []
    top_cities: list[dict[str, Any]] = []
    top_places: list[dict[str, Any]] = []
    sample_reviews: list[ReviewSummary] = []


class Recommendation(BaseModel):
    place_id: int
    place_name: str
    city: str | None = None
    district: str | None = None
    category: str | None = None
    place_kind: str | None = None
    review_count: int
    avg_rating: float | None = None
    match_score: float = Field(description="0-1 blend of preference evidence and rating")
    matched_preferences: list[str] = []
    matched_review_count: int = 0
    evidence_share: float | None = None


class SearchHit(BaseModel):
    kind: str = Field(description="place | city | preference | topic | review")
    id: str
    label: str
    detail: str | None = None
    score: float | None = None
