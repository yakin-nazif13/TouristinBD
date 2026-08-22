"""Phase 8 — TouristinBD backend API.

Read-only FastAPI service over `data/touristinbd.db`, which is built from the
Phase 2-7 pipeline artifacts by `scripts/build_phase8_database.py`.

Run:
    .venv/bin/python -m backend.main            # or
    .venv/bin/uvicorn backend.main:app --reload --port 8000

Interactive docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from backend import db
from backend.routers import (
    analytics,
    chat,
    discovery,
    meta,
    places,
    research,
    reviews,
    taxonomy,
)

DESCRIPTION = """
Read-only API over the TouristinBD review corpus and its preference taxonomy.

**Pipeline lineage**: raw scrapes → cleaned reviews (Phase 2) → BERTopic topics
(Phase 3) → 4-stage LLM preference classification (Phase 4) → bidirectional
validation (Phase 5) → sensitivity analysis (Phase 6) → aggregates (Phase 7) →
this API (Phase 8).

Every aggregate is a SQL view, so re-running the pipeline with more reviews and
rebuilding the database refreshes all endpoints with no code change.
"""

app = FastAPI(
    title="TouristinBD API",
    version="0.9.0",
    description=DESCRIPTION,
    openapi_tags=[
        {"name": "meta", "description": "Health, build provenance, dataset overview."},
        {"name": "places", "description": "Places and cities with review statistics."},
        {"name": "reviews", "description": "Review-level retrieval and filtering."},
        {"name": "taxonomy", "description": "Topics and the preference hierarchy."},
        {"name": "analytics", "description": "Aggregates equivalent to the Phase 7 tables."},
        {"name": "research", "description": "Phase 5 validation and Phase 6 sensitivity."},
        {"name": "discovery", "description": "Search, preference ranking, place comparison."},
        {"name": "chat", "description": "Retrieval-based chatbot built on the discovery endpoints."},
    ],
)

# The frontend demo is opened straight from disk (file://) and later served from
# a different host, so allow any origin — the API is read-only except for /api/chat.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(db.DatabaseUnavailable)
async def db_unavailable_handler(_: Request, exc: db.DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


app.include_router(meta.router)
app.include_router(places.router)
app.include_router(reviews.router)
app.include_router(taxonomy.router)
app.include_router(analytics.router)
app.include_router(research.router)
app.include_router(discovery.router)
app.include_router(chat.router)


def run() -> None:
    import uvicorn

    try:
        info = db.check_schema()
        print(
            f"database ready — schema v{info['schema_version']}, "
            f"built {info['built_at_utc']}"
        )
    except db.DatabaseUnavailable as exc:
        print(f"WARNING: {exc}")

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
