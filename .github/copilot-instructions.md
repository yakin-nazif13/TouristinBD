# Copilot instructions for TouristinBD

- This is a capstone project: a review-mining pipeline plus a working site over
  its output. Phases 0–12 are complete. `docs/PROGRESS.md` is the source of truth
  for status, decisions and known limits — read it first, and update it whenever a
  phase changes or you discover a limitation that affects future work.
- **There is no mock data left.** `frontend/index.html` reads the live API; the old
  inline `destinations` array is gone. Don't reintroduce hardcoded sample data — if
  something can't be answered from the corpus, say so in the UI (the page already
  does this for unfillable itinerary days and an unreachable API).
- New data enters through `scripts/add_reviews.py` → `scripts/run_phase2_preprocessing.py`.
  Phase 2 must keep reproducing the committed `data/processed_reviews.csv` byte for byte —
  every later phase is keyed on the `review_id`s in it, so drifting cleaning silently
  detaches topics and preferences from their reviews. `test_phase2_preprocessing.py`
  asserts this; if you change a cleaning rule you must justify the diff, not re-baseline it.
- Architecture: `scripts/run_phase*.py` (research pipeline, writes `data/*.csv|json`)
  → `scripts/build_phase8_database.py` (rebuilds `data/touristinbd.db` from whichever
  artifacts exist) → `backend/` (read-only FastAPI over that DB) → `frontend/index.html`
  (plain HTML/CSS/JS, served by the backend at `/app/`).
- **Aggregates are SQL views, never copied tables.** Adding reviews and rebuilding must
  refresh every endpoint with no code change. Nothing may be hardcoded to a specific
  place, city, topic or preference id — that forward-compatibility is the point of the
  design and `scripts/test_phase8_rebuild.py` enforces it.
- Router endpoints that other Python code also calls are split into a plain
  `_*_impl` function plus a thin FastAPI wrapper (see `discovery.py`, `places.py`,
  `itinerary.py`). Call the `_impl`, never the route function — calling a route
  directly binds unpassed parameters to their raw `Query(...)` sentinels.
- Every change must keep the seven suites green:
  `scripts/test_phase{2_preprocessing,8_api,8_rebuild,9_chat,10_itinerary,11_frontend,12_deployment}.py`
  (449 tests, in-process, no server/network/LLM). They follow a shared style —
  a `check(name, condition, detail)` helper and a pass/fail count — so extend them
  in that style rather than adding pytest.
- Serving needs `requirements-api.txt` only. `requirements.txt` (torch, BERTopic,
  sentence-transformers) is for re-running Phases 3–7. Don't add a runtime import that
  isn't in the slim file — `test_phase12_deployment.py` checks this from the AST.
- The CSV schema is meaningful. `data/processed_reviews.csv` uses `review_id`,
  `review_text_clean`, `detected_language`, `platform_language_tag`, `place_name`,
  `review_rating`, `source`; `data/place_geography.csv` supplies city/district/division
  for places whose city was blank. Preserve these names and paths.
- Keep the frontend a single dependency-free file: no React/Vue/Next, no package
  manager, no bundler. Preserve the visual language (CSS custom properties
  `--bg-deep`, `--marigold`, `--pink`, `--leaf`; Fraunces/Work Sans/IBM Plex Mono via
  Google Fonts). Escape every interpolated value with `escapeHtml` — review text is
  user content.
- The chatbot is retrieval-based on purpose: keyword intents plus database lookups, no
  LLM call and no API key at runtime. Keep it that way unless the task explicitly asks
  for a generative bot.
- Prefer minimal, local edits that fit the existing pattern over new abstractions, and
  document any real limitation in `docs/PROGRESS.md` rather than papering over it.
