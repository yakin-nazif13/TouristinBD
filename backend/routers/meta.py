"""Health, build metadata, and the headline dataset overview."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from backend import db
from backend.models import DatasetOverview, Health, Meta

router = APIRouter()

PIPELINE_PHASES = {
    "phase1": "Data collection (Google Maps + Booking.com scrapes)",
    "phase2": "Preprocessing, merge, language detection",
    "phase3": "Multilingual BERTopic topic modeling",
    "phase4": "4-stage LLM preference classification",
    "phase5": "Bidirectional validation (sampled)",
    "phase6": "Sensitivity analysis",
    "phase7": "Statistics & visualization layer",
    "phase8": "Backend API + SQLite database (this service)",
}


@router.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    """Liveness plus a database readiness check."""
    try:
        info = db.check_schema()
    except db.DatabaseUnavailable as exc:
        return Health(status="degraded", database="unavailable", detail=str(exc))
    return Health(
        status="ok",
        database="ready",
        schema_version=info["schema_version"],
        built_at_utc=info["built_at_utc"],
    )


@router.get("/api/meta", response_model=Meta, tags=["meta"])
def meta(conn: sqlite3.Connection = Depends(db.get_conn)) -> Meta:
    """Which artifacts the database was built from, and when."""
    return Meta(
        schema_version=int(db.meta_value(conn, "schema_version") or 0),
        built_at_utc=db.meta_value(conn, "built_at_utc"),
        row_counts=db.meta_json(conn, "row_counts") or {},
        source_files=db.meta_json(conn, "source_files") or {},
        build_notes=db.meta_json(conn, "build_notes") or [],
        pipeline_phases=PIPELINE_PHASES,
    )


@router.get("/api/overview", response_model=DatasetOverview, tags=["meta"])
def overview(conn: sqlite3.Connection = Depends(db.get_conn)) -> DatasetOverview:
    """Headline counts for a dashboard hero section."""
    base = db.one(conn, "SELECT * FROM v_dataset_overview") or {}

    def counts(sql: str) -> dict[str, int]:
        return {
            str(r["k"]): int(r["n"])
            for r in db.rows(conn, sql)
            if r["k"] is not None
        }

    return DatasetOverview(
        **base,
        reviews_by_source=counts(
            "SELECT source AS k, COUNT(*) AS n FROM reviews GROUP BY source ORDER BY n DESC"
        ),
        reviews_by_language=counts(
            "SELECT detected_language AS k, COUNT(*) AS n FROM reviews "
            "GROUP BY detected_language ORDER BY n DESC"
        ),
        reviews_by_place_kind=counts(
            "SELECT p.place_kind AS k, COUNT(*) AS n FROM reviews r "
            "JOIN places p ON p.place_id = r.place_id GROUP BY p.place_kind ORDER BY n DESC"
        ),
        preferences_by_type=counts(
            "SELECT preference_type AS k, COUNT(*) AS n FROM preferences "
            "GROUP BY preference_type ORDER BY n DESC"
        ),
    )
