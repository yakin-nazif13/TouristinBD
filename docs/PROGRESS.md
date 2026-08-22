# TouristinBD — Progress Checklist

Last updated: 2026-08-20

> How to use this file: keep it up to date at the end of every session. Since Claude's
> workspace resets between sessions, **download the project zip after each session and
> re-upload it (or at least this file) at the start of the next one** so we pick up where
> we left off.

## Simplified MVP scope (agreed)
- ~300–800 real reviews (not 80k), from Google Maps + Booking.com only
- **Full 4-stage LLM preference pipeline** (topic interpretation → hierarchy →
  cosine topic–preference mapping → long-tail ID), localized to BD tourism
- Bidirectional validation on a sample (~50 pairs), not the full dataset
- SQLite instead of Postgres to start
- Bilingual chatbot is a stretch goal, not a requirement

## Accounts/tools set up so far
- [x] Apify account (free tier) — used for Google Maps review scraping via the Apify Console
      website UI (no API/network setup needed on Claude's side — CSV export/upload workflow).
- [x] Gemini API key — used for Phase 4 (`gemini-flash-lite-latest`); OpenAI key present but
      currently out of credits.
- [ ] GitHub account — code storage (not set up yet)
- [ ] Free database host (Supabase or Neon) — for real data, later
- [ ] Free deploy host (Vercel + Render/Railway) — for public URL, later

## Phase-by-phase status

- [x] **Phase 0 — Project setup**: folder structure created, fake-data demo built and running.
- [x] **Fake-data demo (chat / itinerary / compare)**: working, plain HTML/CSS/JS, no backend needed.
- [~] **Phase 1 — Data collection**: in progress.
  - [x] Apify account created (free tier), API token in hand (kept private, not committed to any public repo).
  - [x] First Google Maps reviews batch scraped via Apify Console UI (manual run, CSV export → upload to Claude workflow — avoids needing sandbox network access).
  - [x] 300 clean real reviews collected across **15/15 planned places** → `data/real_reviews_batch1.csv`.
    Places: Cox's Bazar Beach, Srimangal Tea Garden, Nilachal Tourist Center, Jaflong Zero Point,
    Ratargul Swamp Forest, Saint Martin's Island, Panam City, Sixty Dome Mosque, Lalbagh Fort,
    Ahsan Manzil Museum, Kuakata Beach, Kaptai Lake, Sompur Mahavihar (Paharpur), Guliakhali Sea Beach,
    Sundarbans (Karamjal Wildlife Centre).
  - [x] Sundarbans re-scraped correctly (search term "Karamjal" — Bangladesh side, countryCode=BD confirmed).
  - [x] Booking.com batch collected: 240 reviews across 12 hotels in 4 districts (Cox's Bazar,
        Sylhet, Chittagong, Dhaka) → `data/real_reviews_booking_batch1.csv`. Ratings normalized
        from Booking's 1–10 scale to the same 1–5 scale as Google Maps data.
  - [x] **MVP data target met: 540 total real reviews** (300 Google Maps + 240 Booking.com),
        comfortably inside the 300–800 range.
  - [x] Confirmed language tags aren't fully reliable — some Booking.com reviews tagged
        language='en' actually contain real Bengali-script text. Real work for Phase 2's
        language detection step, which is good — proves it's needed.
  - [ ] Optional: scale further later if BERTopic wants more data once we see Phase 3 results.
  - [ ] Note for Phase 2: scraped review text so far is all English (Google's auto-translate
        default) — may need an "original language" scraper setting so Bengali/code-mixed text
        actually exists for language detection later.
- [x] **Phase 2 — Preprocessing**: done.
  - [x] Merged Google Maps (300) + Booking.com (240) into one unified schema.
  - [x] Cleaned text: stripped HTML entities, normalized the "Liked:/Disliked:" labels into
        readable sentences, collapsed whitespace.
  - [x] Removed 1 unusably short review and 1 exact duplicate → 538 final rows.
  - [x] Real language detection (not just platform tags) using Bengali-script matching +
        `langdetect`, with a length-based fallback because `langdetect` is unreliable under
        ~20 characters (initially mislabeled things like "Exceptional. Best" as Romanian —
        fixed by defaulting short Latin-script text to English, then manually spot-checked
        the remaining flagged rows).
  - [x] **Result: 530 English, 5 Bengali-English code-mixed, 2 pure Bengali, 1 Dutch**, out of
        538 reviews → `data/processed_reviews.csv`.
  - [x] Confirmed real (if small) Bengali/code-mixed presence — useful for the write-up's
        multilingual angle, even though the dataset skews heavily English (expected, since
        Google/Booking reviews from international-facing listings trend English).
- [x] **Phase 3 — Multilingual BERTopic modeling**: done (MVP version).
  - [x] Installed BERTopic + clustering deps (scikit-learn, umap-learn, hdbscan) — all free,
        pip-installed, no accounts needed.
  - [x] **Network limitation found & worked around**: true BERTopic normally downloads a
        pretrained sentence-embedding model from HuggingFace — that site isn't reachable from
        Claude's sandboxed workspace (same restriction as Apify's API earlier). Built a custom,
        fully-offline embedding backend using TF-IDF + TruncatedSVD instead of sentence-transformers.
        This is a legitimate simplified-MVP substitute, but it clusters more on word overlap than
        deep semantic meaning — worth upgrading to real sentence-transformer embeddings later by
        running this on your own machine/a cloud notebook (no sandbox restriction there).
  - [x] Ran on all 538 cleaned reviews → **26 topics found + 1 outlier group** (48 reviews, ~9%,
        didn't cluster cleanly — normal for a dataset this size).
  - [x] Results are a healthy mix of **place-specific topics** (e.g. Ratargul Swamp Forest,
        Paharpur Buddhist Vihara, Jaflong Zero Point, Karamjal/Sundarbans) and **cross-cutting
        experience topics** that show up across multiple hotels (e.g. room complaints, staff
        hospitality, pool/swimming amenities, value-for-money, general complaint language) — the
        cross-cutting ones are exactly the kind of thing Phase 4's preference classification will
        want to work with.
  - [x] Found one real Bengali-heavy topic (negative hotel reviews, e.g. "গিজার কাজ করে না") —
        confirms the code-mixed content flagged in Phase 2 is showing up as its own signal.
  - [x] **Known artifact to fix in Phase 4**: the single Dutch review's words ("het", "de", "van")
        leaked into a topic's keyword list since they were rare enough in the corpus to look
        "distinctive" to TF-IDF. Minor, but worth excluding non-English/non-Bengali docs from
        keyword extraction going forward.
  - [x] Saved outputs: `data/reviews_with_topics.csv` (every review + its topic_id),
        `data/topics_summary.csv` (topic sizes + top keywords), `data/topic_sizes_chart.png`,
        and the fitted model itself in `data/bertopic_model_dir/` (so we don't have to retrain
        from scratch next session).
  - [x] **Phase 3 re-run**: the BERTopic workflow was upgraded to use a Hugging Face multilingual
        embedding model (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`) instead of
        the earlier TF-IDF/SVD fallback. The new run produces more semantically coherent topic
        assignments and writes the updated artifacts to the same data paths above.
- [x] **Phase 4 — LLM preference classification (4-stage)**: done (MVP run).
  - [x] Upgraded `scripts/run_phase4_preference_classification.py` from the old 2-stage
        single-prompt classifier to the Zhang et al. 2026 4-stage design:
        1. Topic interpretation (LLM) → `data/stage1_topic_interpretations.*`
        2. Preference hierarchy Category→Subcategory→Preference (LLM) →
           `data/preference_classification.*`
        3. Topic–preference cosine mapping with multilingual MiniLM embeddings,
           τ_sim=0.4 confidence flag → `data/topic_preference_mapping.*` (+ sim matrix npy)
        4. Long-tail rule: corpus share < 2% AND SDD > 0.6 → `data/long_tail_flags.*`
        Joined convenience table: `data/topic_preferences.*`
  - [x] Fixed empty `top_keywords` in `topics_summary.csv` (derived from BERTopic topic names).
  - [x] Fixed Stage 1 sample bias: place-diverse review sampling + place-mix grounding so
        mixed clusters (e.g. topic 2 = Dhaka heritage + some Jaflong) aren't mislabeled from
        the first N reviews of one venue.
  - [x] Ran successfully with Gemini `gemini-flash-lite-latest` (OpenAI key is out of credits;
        `gemini-flash-latest` / `gemini-2.0-flash` were truncating or 429ing).
  - [x] Results: **10 preferences**, **10/10 high-confidence mappings** (all sim ≥ 0.76),
        **0 long-tail topics** under the paper rule. Topic 9 is scarce (1.3%) but SDD=0.10
        because it is nearly identical to abundant heritage topic 2 — correctly stays mainstream.
        Topics 2 and 9 both map to P03 (Historic landmarks / archaeological sites).
  - [ ] Known MVP limits to revisit later: no Culinary dimension yet (dataset is hotels +
        attractions only); preference hierarchy is still ~1 preference per place-topic; with
        only 10 topics, long-tail recall is naturally near-zero until the corpus grows.
  - [ ] Phase 5 should spot-check topic 2 (mixed heritage/Jaflong cluster) and whether
        Panam (topic 4) should merge into P03 rather than stay as its own preference.
- [x] **Phase 5 — Bidirectional validation (sampled)**: done (automated pass; awaiting human labels).
  - [x] `scripts/run_phase5_bidirectional_validation.py` written and run.
  - [x] Direction 1 (topic → preference precision): **10/10 topics pass** — all similarity
        scores ≥ τ_sim=0.4 and all gaps ≥ ambiguity_margin=0.08. Zero remaps needed.
  - [x] Direction 2 (preference → topic coverage): **all 10 preferences under-coverage**
        (mapped_topic_count < 3). This is a structural MVP artefact — with only 10 topics
        the 1:1 topic-preference ratio means every preference inherits one topic, which is
        below the paper's threshold of 3 (calibrated for 1,071 topics). Not an error;
        coverage will improve as the corpus and topic count grow.
  - [x] P10 (General historical monuments) has 0 mapped topics — no corpus evidence at
        this scale. Recommend folding into P03 after human review.
  - [x] 50-pair manual review sample built: 10 mapped positives, 10 second-best challengers,
        15 hard negatives, 15 random negatives → `data/phase5_manual_review_sample.csv`.
        Fill `human_label` column (1=correct, 0=incorrect) to compute precision/recall.
  - [x] Outputs: `phase5_direction1_precision_checks.*`, `phase5_direction2_coverage_checks.*`,
        `phase5_manual_review_sample.csv`, `phase5_recommendations.csv`,
        `phase5_validation_report.{json,md}`.
  - [ ] Human labelling of the 50-pair sample not yet done — no expert rater available;
        can be completed by the researcher as a self-review step.
- [x] **Phase 6 — Sensitivity analysis**: done (MVP hybrid).
  - [x] `scripts/run_phase6_sensitivity_analysis.py` added and run.
  - [x] **Hybrid design (safe for later phases):** at each subsample size we re-train
        BERTopic, then map topics to the **fixed Phase 4 preference list** via embeddings
        (no LLM re-run). Outputs only under `data/phase6_*` — Phase 3–5 files untouched.
  - [x] MVP ladder (paper uses 20k/40k/60k/80k): **151 / 247 / 398 / 538** reviews.
  - [x] Results: preference coverage rises from **2/10 → 9/10** as sample size grows;
        mapped preference set stabilizes at full corpus (Jaccard vs prev = 1.0 at 538).
        Recommended minimum corpus size for stable mappings on current taxonomy: **538**
        (i.e. you need the full MVP corpus; more data will help further).
  - [x] Phase 4 locked reference row included for comparison (avg sim 0.88 vs ~0.53 on
        retrained subsamples — expected because Phase 4 used LLM interpretations, not just keywords).
  - [x] Outputs: `phase6_sensitivity_metrics.csv`, `phase6_sensitivity_mappings.csv`,
        `phase6_sensitivity_chart.png`, `phase6_sensitivity_report.{md,json}`.
- [x] **Phase 7 — Statistics & visualization layer**: done (MVP analytics layer).
  - [x] `scripts/run_phase7_statistics_visualization.py` added and run.
  - [x] Built reusable aggregate tables from Phases 2–6 outputs (all saved as `data/phase7_*`):
        dataset overview, temporal review volume, rating distributions, preference frequency,
        preference coverage, mapping quality, city rollups, and venue rollups.
  - [x] Built chart set for dashboard/report use:
        `phase7_chart_topic_counts.png`, `phase7_chart_rating_by_source.png`,
        `phase7_chart_preference_counts.png`, `phase7_chart_mainstream_vs_longtail.png`,
        `phase7_chart_sensitivity.png`.
  - [x] Added statistical-test payload (`phase7_statistical_tests.json`) with graceful handling
        when long-tail has zero reviews (tests skipped with explicit note, no crash).
  - [x] Added dashboard payload manifest (`phase7_dashboard_payload.json`) so Phase 8 API / Phase 11
        frontend can consume fixed paths without hardcoding.
  - [x] Safety: this phase is non-destructive; canonical Phase 3–6 files are unchanged.
- [x] **Phase 8 — Backend API + database (SQLite)**: done.
  - [x] `data/place_geography.csv` added: reviewable city/district/division mapping for
        the 6 places whose city was blank in `processed_reviews.csv` (Cox's Bazar Beach,
        Saint Martin's Island, Kaptai Lake, Sompur Mahavihar, Guliakhali Sea Beach,
        Sundarbans/Karamjal). Source CSVs untouched — edit this file directly if a
        city/district is wrong.
  - [x] `scripts/build_phase8_database.py`: rebuilds `data/touristinbd.db` from scratch
        every run (idempotent) from whichever Phase 2-7 CSV/JSON artifacts exist.
        Every input is optional — a missing Phase 3-6 file degrades gracefully (empty
        table) instead of crashing, so the DB can be rebuilt from Phase 2 output alone.
        Schema-drift tolerant: unknown extra columns are dropped, expected-but-missing
        columns become NULL. All aggregates (dataset overview, rating distribution,
        preference frequency, city/venue rollups) are SQL **views**, not copied tables,
        so they can't go stale. Writes `data/phase8_build_report.{md,json}`.
  - [x] `backend/` — FastAPI app (`main.py`, `db.py`, `models.py`, `queries.py`,
        `routers/{meta,places,reviews,taxonomy,analytics,research,discovery}.py`).
        Opens the DB read-only; refuses to serve (503 + rebuild hint) if the DB is
        missing or its schema_version doesn't match the code.
  - [x] Endpoint surface: health/meta/overview, places + cities, reviews (filter by
        place/city/source/language/topic/preference/rating/date/text), topics +
        preferences + full category→subcategory→preference taxonomy tree, Phase 7-style
        analytics (ratings, temporal, preference frequency, city/venue rollups,
        long-tail split, language mix), Phase 5/6 research endpoints (validation,
        manual-review sample, sensitivity), and discovery endpoints (cross-entity
        search, preference-based place recommendation, multi-place comparison) —
        these last two are the retrieval/ranking surface Phases 9-10 will call into.
        Auto docs at `/docs`.
  - [x] `scripts/test_phase8_api.py`: 68 in-process smoke tests over every route
        (filters, pagination, 404s, validation-error cases, cross-checks against the
        source CSVs). All passing.
  - [x] `scripts/test_phase8_rebuild.py`: 29 forward-compatibility tests — rebuilds the
        DB against mutated copies of `data/` (new place not in place_geography.csv,
        new preference id, Phase 2-only input, upstream schema drift + stale geography
        row, DB not built yet) and checks both the build and the API degrade correctly
        rather than crashing. This is the check that the "no compatibility issues when
        new data is added" goal actually holds. All passing.
  - [x] `TOURISTINBD_DATA_DIR` env var (read by both the build script and `backend/db.py`)
        lets the DB/API point at a different artifact directory — used by the rebuild
        tests and available for later deployment.
  - [x] Added `scipy`, `fastapi`, `uvicorn[standard]`, `httpx` to `requirements.txt`
        (scipy was already a runtime dependency of Phase 7 but had never been pinned).
- [ ] **Phase 9 — Chatbot (real, retrieval-based)**: not started (demo has mock rule-based version only).
- [ ] **Phase 10 — Itinerary builder + comparison tool (real data)**: not started (demo has mock version only).
- [ ] **Phase 11 — Frontend polish / Next.js migration**: optional, current plain HTML/JS demo works fine for now.
- [ ] **Phase 12 — Deployment**: not started.

## Notes for next session
- Demo file: `frontend/index.html` — open directly in any browser, no install needed. Still
  running on mock data; real data isn't wired into the website yet (that's a later step,
  Phase 10-11).
- Real data files:
  - `data/real_reviews_batch1.csv` — 300 raw Google Maps reviews (15 places).
  - `data/real_reviews_booking_batch1.csv` — 240 raw Booking.com reviews (12 hotels).
  - `data/processed_reviews.csv` — **538 cleaned, merged, language-tagged reviews.**
  - `data/reviews_with_topics.csv` / `topics_summary.csv` — Phase 3 topic assignments.
  - Phase 5 validation: `phase5_*` tables + `phase5_manual_review_sample.csv`.
  - Phase 6 sensitivity: `phase6_sensitivity_*` (does not replace Phase 3–5 files).
  - Phase 7 analytics layer: `phase7_*` tables/charts + `phase7_dashboard_payload.json`.
- Re-run Phase 4 with:
  `source /tmp/touristinbd-venv/bin/activate && python scripts/run_phase4_preference_classification.py`
  (needs network + a working Gemini/OpenAI key; default model is `gemini-flash-lite-latest`).
- Rebuild the database after re-running any earlier phase (Phase 1-7 output changed):
  `.venv/bin/python scripts/build_phase8_database.py`
- Run the API: `.venv/bin/python -m backend.main` (docs at http://127.0.0.1:8000/docs).
- Verify the backend after any change: `.venv/bin/python scripts/test_phase8_api.py` and
  `.venv/bin/python scripts/test_phase8_rebuild.py`.
- Next natural step: **Phase 9 — real retrieval-based chatbot**, built on top of the
  Phase 8 `/api/search` and `/api/reviews` endpoints. Then **Phase 10 — itinerary
  builder + comparison tool**, built on `/api/recommend` and `/api/compare` (both
  already implemented in Phase 8, unused by any frontend yet).
