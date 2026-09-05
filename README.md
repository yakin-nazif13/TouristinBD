# TouristinBD

A capstone project that mines Bangladeshi tourism reviews for what travellers
actually care about — including niche, "long-tail" preferences — and turns that
into a working site: a chatbot, an evidence-backed itinerary builder, and a
destination comparison tool.

Everything the site shows is derived from **538 real reviews** (Google Maps +
Booking.com) across 27 places, run through topic modelling and a 4-stage LLM
preference pipeline that distils them into **5 validated travel preferences**.
No mock data anywhere.

## Quick start

```bash
python3 -m venv .venv                                  # Python 3.10+
.venv/bin/pip install -r requirements-api.txt          # API only (~30 MB)
.venv/bin/python scripts/build_phase8_database.py      # data/*.csv -> SQLite
.venv/bin/python -m backend.main
```

- **Interface** — <http://127.0.0.1:8000/app/>
- **API docs** — <http://127.0.0.1:8000/docs>
- **Health** — <http://127.0.0.1:8000/health>

`frontend/index.html` can also be opened straight from disk; it falls back to
`http://127.0.0.1:8000` and tells you if the API isn't running.

To re-run the research pipeline itself (Phases 3–7) you need the full stack —
`pip install -r requirements.txt` — plus a Gemini or OpenAI key for Phase 4.

## What's here

| Path | What it is |
| --- | --- |
| `frontend/index.html` | The site: overview, chat, itinerary builder, compare, explore. Plain HTML/CSS/JS, no build step. |
| `backend/` | FastAPI service (read-only over SQLite), one router per surface. |
| `scripts/add_reviews.py` | Import a new scrape into the corpus (see below). |
| `scripts/run_phase*.py` | The research pipeline: preprocessing → topic modelling → preference classification → validation → sensitivity → analytics. |
| `scripts/build_phase8_database.py` | Rebuilds `data/touristinbd.db` from whichever pipeline artifacts exist. Idempotent and schema-drift tolerant. |
| `scripts/test_phase*.py` | 450 in-process tests across preprocessing, ingestion, the API, chatbot, planner, frontend contract and deployment config. |
| `data/` | Every artifact the pipeline produced, including the raw and cleaned review sets. |
| `docs/PROGRESS.md` | Phase-by-phase status, decisions and known limits. |
| `docs/DEPLOYMENT.md` | Local, Render, Docker and split-hosting instructions. |

## Adding new reviews

Point the importer at a fresh export. It maps the column names, generates ids,
converts Booking.com's 1–10 ratings, skips anything already in the corpus, and
re-runs preprocessing:

```bash
.venv/bin/python scripts/add_reviews.py ~/Downloads/export.csv \
    --source google_maps --name batch2          # add --dry-run to preview
```

Then re-run the phases that give the new reviews meaning, and rebuild:

```bash
.venv/bin/python scripts/run_phase3_huggingface_bertopic.py       # cluster them
.venv/bin/python scripts/run_phase4_preference_classification.py  # needs an LLM key
.venv/bin/python scripts/build_phase8_database.py                 # refresh the app
```

New places, cities and reviews reach every endpoint, the chatbot, compare and
the itinerary planner with **no code change**. Two things to know: until Phase 3
and 4 are re-run the new reviews have no topic, so they count in totals and
ratings but carry no preference evidence; and a place whose export had a blank
city needs a row in `data/place_geography.csv` or its district/division stay
empty. Both are reported by the scripts rather than left silent.

## The pipeline

```
Apify scrapes (Phase 1)
  → clean + merge + language detection (Phase 2)      → data/processed_reviews.csv
  → multilingual BERTopic (Phase 3)                   → data/reviews_with_topics.csv
  → 4-stage LLM preference classification (Phase 4)   → data/topic_preference_mapping.csv
  → bidirectional validation (Phase 5)                → data/phase5_*
  → sensitivity analysis (Phase 6)                    → data/phase6_*
  → aggregate tables + charts (Phase 7)               → data/phase7_*
  → SQLite + FastAPI (Phase 8)                        → data/touristinbd.db
  → chatbot (9), itinerary + compare (10), site (11), deployment (12)
```

Every aggregate the API serves is a **SQL view**, so re-running an earlier phase
with more reviews and rebuilding the database refreshes the whole site — no code
change, nothing hardcoded to a specific place, city or preference id.

## Tests

```bash
for t in 2_preprocessing 8_api 8_rebuild 9_chat 10_itinerary 11_frontend 12_deployment; do
  .venv/bin/python scripts/test_phase$t.py || break
done
```

They run the app in-process (no server, no network, no LLM) against the real
built database. CI runs all seven plus a container build on every push.

## Deploying

`docs/DEPLOYMENT.md` covers it. Short version: push to GitHub and point Render at
`render.yaml`, or `docker build -t touristinbd . && docker run -p 8000:8000
touristinbd`. The service is stateless — the database is rebuilt from the
committed artifacts at deploy time, so refreshing the data is a `git push`.

## Current status

Phases 0–12 complete. Known limits are listed at the end of `docs/PROGRESS.md`.
