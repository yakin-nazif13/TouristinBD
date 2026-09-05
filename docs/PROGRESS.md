# TouristinBD — Progress Checklist

Last updated: 2026-09-05 — all 12 phases complete; Phase 4 taxonomy regenerated with
`gemini-3.5-flash` and Phases 5-8 refreshed on it. Phase 12 is configured and tested
but not yet pushed to a public host.

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
- [x] Gemini API key — working as of 2026-09-05, stored in `.env` (gitignored, mode 600).
      Phase 4 now pinned to `gemini-3.5-flash`. OpenAI key present but out of credits.
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
  - [x] **Phase 2 reconstructed as a script (2026-09-04).** The original preprocessing was
        done in an earlier session's workspace and only its *output* was ever saved — so
        `processed_reviews.csv` existed but nothing in the repo could produce it, which
        meant new scrapes had no way into the project. `scripts/run_phase2_preprocessing.py`
        now rebuilds it and **reproduces the committed file byte for byte**, which is what
        made the reconstruction verifiable:
        - merges every `data/real_reviews_*.csv` in filename order (so a new batch is
          picked up by dropping the file in — nothing to edit);
        - cleaning: HTML unescape → Booking's `| Liked:`/`| Disliked:` labels become
          sentences (and a *leading* `Liked:` is stripped, which one row needs) →
          whitespace collapse;
        - drops reviews under 10 characters after cleaning ("Bad. No") and exact duplicates
          of an earlier cleaned text — which is precisely the 1 + 1 rows the original run
          removed (the duplicate was `Good. Good. Good`, shared by Foy's Lake Resort and
          Civic Inn, so dedup is on text alone, not place+text);
        - language: Bengali script matched directly (`bn` vs `bn-en-mixed` by whether Latin
          letters are also present), otherwise `langdetect` with a length fallback.
        - **The one judgement call**: the original run spot-checked short reviews by hand
          after langdetect misfired on them. That is encoded as `SHORT_TEXT_MAX = 50` —
          below 50 characters, Latin-script text is taken as English. 50 is the point where
          the current corpus stops producing false hits (at 20 it labels
          "Exceptional. Beautyful" Romanian and "Very poor. Dirty property" Afrikaans); the
          Dutch review is 480 chars, so it is unaffected. For future batches,
          `data/language_overrides.csv` (review_id, detected_language) lets a human correct
          any row without touching code.
        - `langdetect` is seeded (`DetectorFactory.seed = 0`) at module import, not in
          `main()` — it is probabilistic, and an unseeded import made the same review come
          out `it` on one run and `en` on the next. Caught by the test suite.
        - Booking ratings were **already** normalized to 1-5 in
          `real_reviews_booking_batch1.csv`, so Phase 2 does not re-scale; that conversion
          now lives in `add_reviews.py --rating-scale 10` for future imports.
  - [x] **`scripts/add_reviews.py`** — the front door for new data:
        maps Apify/Booking column names to the project schema (with `--map OLD=NEW` for
        anything unusual), generates content-derived `review_id`s when the export has none
        (so re-importing the same file is a no-op rather than a doubling), converts rating
        scales, refuses rows already in the corpus, writes
        `data/real_reviews_<name>.csv`, re-runs Phase 2, then prints exactly which phases
        still need re-running. `--dry-run` previews the whole thing.
  - [x] `scripts/test_phase2_preprocessing.py` — 65 tests: byte-for-byte reproduction of
        the committed corpus, cleaning/idempotency/language unit cases, the drop rules,
        and the full ingestion path on throwaway copies of `data/` (including a check that
        the real data directory is never touched).
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
        attractions only); with only 10 topics, long-tail recall is naturally near-zero
        until the corpus grows.
  - [x] **Phase 4 re-run on a working key (2026-09-05) — taxonomy replaced.** The
        "~1 preference per place-topic" weakness above turned out to be a *model* limit,
        not a data limit. Three runs on the same Phase 3 topics, compared on Phase 5's own
        metrics:

        | Run | Model | Prefs | D1 precision | D2 adequate | Orphans | Mean sim |
        |---|---|---|---|---|---|---|
        | committed (earlier session) | `gemini-flash-lite-latest` | 10 | 10/10 | 0/10 | 1 (P10) | 0.88 |
        | re-run | `gemini-flash-lite-latest` | 9 | 10/10 | 0/9 | 0 | 0.87 |
        | **adopted** | **`gemini-3.5-flash`** | **5** | **10/10** | **2/5** | **0** | **0.70** |

        flash-lite names *venues* ("Historic Panam City heritage exploration", "Ratargul
        freshwater swamp forest exploration") — that is a renamed place list, not a
        preference taxonomy, and it is why every preference failed Phase 5's coverage
        threshold: a preference that means one venue can only ever inherit one topic.
        `gemini-3.5-flash` generalises instead (P03 "Historical landmark and ancient city
        tours" absorbs topics 2, 4 and 9; P05 "Ecotourism and forest boat safaris" absorbs
        5, 6 and 7), which is what the Stage 2 prompt asked for all along.
        Mean similarity drops (0.88 → 0.70) — expected and not a regression: a general
        preference sits further from any single topic than a venue-specific one does. All
        10 mappings stay far above τ_sim=0.4 and the precision check still passes 10/10.
  - [x] Adopted taxonomy: **P01** hotel quality/service · **P02** coastal beach and coral
        island · **P03** historical landmark and ancient city · **P04** hill tracts and
        scenic lake · **P05** ecotourism and forest boat safaris.
  - [x] `GEMINI_MODEL=gemini-3.5-flash` pinned in `.env`. Pin a concrete version rather
        than a `-latest` alias for anything being written up — aliases move.
  - [x] **Two Phase 4 robustness fixes**, both from failures hit during these runs:
        - *Truncation.* The "newer models truncate" note above was wrong about the cause:
          `max_tokens=500` was being consumed by reasoning tokens before the JSON was
          emitted, so the answer arrived cut off mid-object and surfaced as a JSON parse
          error. `call_llm` now detects `finish_reason == "length"` and raises
          `TruncatedResponse`; `call_llm_json` retries with a tripled budget instead of
          resampling at the same doomed size. Starting budgets raised to 1500 (Stage 1)
          and 8000 (Stage 2).
        - *Transient 503s.* `gemini-3.8-flash` answered "high demand" and the run died
          after 3 retries in ~4s, losing every call already paid for. Retries now run
          6 attempts with exponential backoff and jitter (2→32s), and only for genuinely
          transient statuses — a bad key or unknown model still fails immediately with a
          clear message rather than being retried six times.
        - `--model` flag added, so comparing models needs no file edits.
  - [x] Resolved: the two spot-checks Phase 5 asked for. Panam (topic 4) **did** merge into
        P03 rather than staying its own preference, and topic 2's mixed heritage/Jaflong
        cluster maps to P03 at sim=0.668 with no ambiguity flag.
- [x] **Phase 5 — Bidirectional validation (sampled)**: done (automated pass; awaiting human labels).
  - [x] `scripts/run_phase5_bidirectional_validation.py` written and run.
  - [x] Direction 1 (topic → preference precision): **10/10 topics pass** — all similarity
        scores ≥ τ_sim=0.4 and all gaps ≥ ambiguity_margin=0.08. Zero remaps needed.
  - [x] Direction 2 (preference → topic coverage): originally **all 10 preferences
        under-coverage** (mapped_topic_count < 3), which was read as a structural MVP
        artefact of having only 10 topics. The Phase 4 re-run above shows that was only
        half the story: with a taxonomy that generalises, **2 of 5 preferences now reach
        adequate coverage** (P03 and P05, 3 topics each) on the very same 10 topics. The
        remaining 3 are genuinely thin — P01 (hotels), P02 (coastal) and P04 (hills/lakes)
        each hold 1-2 topics, and those will need more reviews, not a better prompt.
  - [x] P10 (General historical monuments) had 0 mapped topics and was slated to be folded
        into P03 after human review. **Resolved by the re-run** — the regenerated taxonomy
        has no orphan preference at all.
  - [x] **Indexing bug found and fixed (2026-09-05).** `build_manual_review_sample` built
        its preference→column index from the *mapping* table (one row per topic) instead of
        the preference file that defines the similarity matrix's columns. With a 1:1
        mapping in matching order the two happen to agree, so it went unnoticed; but the
        committed run already had topics 2 and 9 both mapping to P03, so that duplicate
        made `pref_index["P03"]` point at column 9 instead of column 2 — every hard-negative
        similarity read from that column in the committed `phase5_manual_review_sample.csv`
        was wrong. Once the taxonomy shrank to 5 preferences the same bug went out of range
        and crashed, which is how it surfaced. Both indices now come from the files that
        define the matrix axes, and negatives are drawn from *all* preferences rather than
        only the mapped ones — so an unmapped preference can actually appear in the sample,
        which is exactly the pair a coverage review should be looking at.
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
  - [x] Original results (10-preference taxonomy): coverage rose **2/10 → 9/10** with
        sample size, stabilizing only at the full corpus; recommended minimum: **538**.
  - [x] **Re-run on the 5-preference taxonomy (2026-09-05): a strictly better result.**
        All **5/5 preferences are covered from 247 reviews onward**, and the mapped set
        stops changing at 398 (Jaccard vs previous = 1.000 at 398 and 538). Recommended
        minimum corpus size therefore drops **538 → 398**. That is the sensitivity story
        worth writing up: a taxonomy of general preferences is not just more useful, it is
        *more stable under subsampling* — it needs ~26% less data to settle, because a
        preference that spans several venues keeps its evidence when any one venue is
        sampled out.
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
- [x] **Phase 9 — Chatbot (real, retrieval-based)**: done.
  - [x] `backend/routers/chat.py` — `POST /api/chat`. No LLM call and no API key
        needed: the message is classified into an intent (greeting, thanks,
        compare, reviews-about, preference-based recommend, place info, city
        info, generic recommend, full-text-search fallback, unknown) by a
        small set of English keyword regexes, then entities (place / city /
        preference) are matched against whatever rows currently exist in the
        database — nothing is hardcoded to a specific place, city, or
        preference id, so a rebuild with new data is picked up automatically.
  - [x] Reuses the tested Phase 8 logic in-process rather than duplicating
        SQL: `discovery.py` and `places.py` were each split into a plain-Python
        `_*_impl` function (ordinary defaults) called by both the FastAPI route
        and `chat.py` directly — calling a route function straight from Python
        would otherwise bind unpassed parameters to their raw `Query(...)`
        sentinel instead of the value FastAPI resolves at request time, a bug
        caught by the Phase 9 test run (recommend crashed on `exclude_city`
        until the split was made).
  - [x] Match-confidence guard: a place name found verbatim in the message
        (or its part before a parenthetical qualifier, e.g. "Sundarbans" out
        of "Sundarbans (Karamjal Wildlife Centre)") is a *strong* match; a
        match from one overlapping word (e.g. "lake" matching both "Kaptai
        Lake" and "Foy's Lake Resort") is not, and cannot by itself pull an
        unrelated place into a comparison or override a direct place lookup
        with an unrelated preference recommendation. Both failure modes were
        caught live by the test run and fixed.
  - [x] `scripts/test_phase9_chat.py` — 31 in-process smoke tests over every
        intent branch, plus request-validation edge cases (empty/missing
        message). All passing. Also re-ran `test_phase8_api.py` (68) and
        `test_phase8_rebuild.py` (29) after the `discovery.py`/`places.py`
        refactor — no regressions.
  - [x] CORS `allow_methods` widened from `["GET"]` to `["GET", "POST"]` for
        the new endpoint; API version bumped to 0.9.0.
  - [ ] Not wired into `frontend/index.html` yet — API-only, matching the
        Phase 8 "backend only" scope decision. Bilingual support is still a
        stretch goal per the MVP scope, not implemented (English keyword
        regexes only).
- [x] **Phase 10 — Itinerary builder + comparison tool (real data)**: done.
  - [x] `backend/routers/itinerary.py` — `GET /api/itinerary`, `POST /api/itinerary`
        (same planner, JSON body) and `GET /api/itinerary/options` (everything a
        form needs: preferences with review counts, cities, divisions, the pace
        ladder — all read from the DB, so a rebuild with new data changes the
        form with no code change).
  - [x] How a plan is built, in four steps that are all defensible from the data:
        1. **Candidates** come from the Phase 8 `/api/recommend` scorer
           (`_recommend_impl`), so the itinerary inherits the documented ranking
           — evidence share × preference coverage × rating — instead of
           inventing a second one.
        2. **Proximity** has to be derived, because the corpus has no
           coordinates: a *region* is a division, and a day is kept inside one
           district where possible. Moving between regions is reported as a
           transfer with an honest travel note (`same_city` → `same_district` →
           `same_division` → `cross_division`) rather than pretending travel is
           free. This is the main MVP compromise in the phase — see limits below.
        3. **Days** are allocated to regions best-first (or from the requested
           city), each region holding consecutive days, so a trip doesn't bounce
           between divisions.
        4. **Evidence**: every stop carries the preferences it matched, how many
           reviews back each one, a plain-English `why`, and a real review
           snippet — preferring one attached to the matched preference.
  - [x] Honest degradation instead of padding: if the corpus can't fill the
        requested days, the unfillable days are kept but marked as free days
        **at the end** of the trip (never in the middle, which would split the
        plan in two), and a warning says how many days were filled. Asking for a
        city with no reviewed attraction (e.g. Sylhet city) widens to that city's
        division and says so. Impossible filters return an empty plan with a
        reason, not a 500.
  - [x] Hotels: each day suggests the best-rated reviewed accommodation in its
        base city, falling back to the division with a note saying so; togglable
        with `include_stays`.
  - [x] Comparison tool upgraded from raw rows to an actual verdict:
        `/api/compare` still returns everything Phase 8 returned (so nothing
        broke) plus a `comparison` block — six metrics with a leader each
        (`None` on a tie), a one-line summary, each place's strongest
        preference — and supporting **positive and critical review quotes** per
        place, because a 3.2★ hotel and a 3.2★ hotel are not the same hotel.
        Comparing a place with itself is now a 400 instead of a meaningless row.
  - [x] Chatbot gained an `itinerary` intent: "plan a 4 day trip in Sylhet",
        "a relaxed week", "3 days in Dhaka". Reads the duration (clamped to 14),
        the pace and the city; an explicit "compare A and B" still wins over a
        mentioned duration.
  - [x] `Recommendation` model gained `division` (needed for regional grouping).
  - [x] `scripts/test_phase10_itinerary.py` — 96 tests: plan structure, travel
        levels cross-checked against the geography, pace caps, evidence
        cross-checked against `/api/places` and the venue rollup, filters,
        degradation, POST/GET parity, the comparison block against the raw
        stats it is derived from, and the chatbot intent.
- [x] **Phase 11 — Frontend on real data**: done (kept as plain HTML/JS — no Next.js).
  - [x] `frontend/index.html` rewritten against the live API. The mock
        `destinations` array is gone; five tabs now read from the backend:
        **Overview** (corpus stats, most-evidenced preferences, source/language
        mix, mainstream vs long-tail), **Chat** (`POST /api/chat`, rendering
        each intent's evidence — itinerary outlines, recommendation cards,
        review quotes), **Itinerary Builder** (form built from
        `/api/itinerary/options`, day timeline with travel notes, evidence
        chips and review snippets), **Compare** (metric table with the leader
        highlighted, plus quotes), **Explore** (`/api/search` across every
        entity kind, click a place for its detail).
  - [x] The rickshaw-board ticker now scrolls **real preferences** with their
        review counts, long-tail ones in pink.
  - [x] Same visual language as the Phase 0 demo (Fraunces/Work Sans/IBM Plex
        Mono, deep teal + marigold + pink), now responsive.
  - [x] API base resolution: same origin when served by the backend, else
        `http://127.0.0.1:8000`, overridable with `?api=<url>` and remembered in
        `localStorage`. If the API is unreachable the page says so and shows the
        exact commands to start it — it never falls back to fake data.
  - [x] All interpolated values pass through `escapeHtml`, so review text can't
        inject markup.
  - [x] The backend now serves the page at `/app/` (`StaticFiles`, html=True)
        and `/` redirects there, so the whole project is one process and one URL.
  - [x] `scripts/test_phase11_frontend.py` — 96 tests that stop the page and the
        API drifting apart: every path the page passes to `api()` must exist in
        the OpenAPI schema and answer 200, every `getElementById`/`querySelector`
        id must exist in the markup, tab buttons must match panels and the
        `TABS` list, no mock-data markers may return, and the payload fields each
        renderer reads must actually be present in the live responses.
- [x] **Phase 12 — Deployment**: done (configuration + CI; not yet pushed to a host).
  - [x] `requirements-api.txt` — the service needs fastapi, uvicorn, pandas
        (for the DB build) and httpx only. `requirements.txt` keeps torch,
        BERTopic and sentence-transformers for re-running Phases 3-7; installing
        those on a free tier would blow the build limit for no benefit.
  - [x] `Dockerfile` — python:3.12-slim, builds the SQLite DB **and runs the
        Phase 8-11 suites during the image build**, so a broken artifact fails
        the build instead of shipping. No volume, no external DB, no runtime
        network. `HEALTHCHECK` hits `/health`.
  - [x] `render.yaml` — Render blueprint (free tier): build = install + build DB,
        start = `python -m backend.main`, health check = `/health`.
  - [x] `backend/main.py` reads `HOST`/`PORT` from the environment (managed hosts
        assign the port and require 0.0.0.0); local default stays loopback:8000.
  - [x] `.github/workflows/ci.yml` — builds the DB and runs all six suites on
        every push, plus a second job that builds the container, boots it and
        checks `/health` and `/app/`.
  - [x] `docs/DEPLOYMENT.md` — local, Render, Docker, split hosting (static page
        elsewhere + `?api=`), config reference and a troubleshooting table.
  - [x] `scripts/test_phase12_deployment.py` — 55 tests for the failure modes
        that only appear on a host: every runtime import is covered by
        `requirements-api.txt` (parsed from the AST of `backend/` and the build
        script), no pipeline-only package leaks into it, the container binds
        0.0.0.0 and builds the DB, `HOST`/`PORT` really reach uvicorn (checked by
        stubbing it), every data file the build needs is committed rather than
        gitignored, no API key is committed, and CORS lets a browser POST.
  - [x] API version bumped to **1.0.0**; `/api/meta` documents all 12 phases.
  - [ ] Not yet actually deployed: needs a GitHub repo and a Render (or other
        host) account — both listed as not-set-up at the top of this file. The
        configuration is written and tested; deploying is a dashboard step.

## Notes for next session
- The site: `.venv/bin/python -m backend.main`, then open <http://127.0.0.1:8000/app/>.
  It runs entirely on the real corpus now — no mock data anywhere in the project.
  `frontend/index.html` can still be opened straight from disk; it falls back to
  `http://127.0.0.1:8000` and shows a banner if the API isn't running.
- Real data files:
  - `data/real_reviews_batch1.csv` — 300 raw Google Maps reviews (15 places).
  - `data/real_reviews_booking_batch1.csv` — 240 raw Booking.com reviews (12 hotels).
  - `data/processed_reviews.csv` — **538 cleaned, merged, language-tagged reviews.**
  - `data/reviews_with_topics.csv` / `topics_summary.csv` — Phase 3 topic assignments.
  - Phase 5 validation: `phase5_*` tables + `phase5_manual_review_sample.csv`.
  - Phase 6 sensitivity: `phase6_sensitivity_*` (does not replace Phase 3–5 files).
  - Phase 7 analytics layer: `phase7_*` tables/charts + `phase7_dashboard_payload.json`.
- Re-run Phase 4 with:
  `.venv/bin/python scripts/run_phase4_preference_classification.py`
  (needs network + a working Gemini/OpenAI key in `.env`; model pinned there, override per
  run with `--model <name>`). Re-running it regenerates the taxonomy, so follow it with
  Phase 5 → 6 → 7 → `build_phase8_database.py` and the full test suite; the tests are
  written against the artifacts rather than against frozen preference ids, so a new
  taxonomy does not break them.
- The full pipeline stack (`pip install -r requirements.txt` — torch, BERTopic,
  sentence-transformers, langdetect) is needed for Phases 2-7. Serving needs only
  `requirements-api.txt`.
- Rebuild the database after re-running any earlier phase (Phase 1-7 output changed):
  `.venv/bin/python scripts/build_phase8_database.py`
- Run the API: `.venv/bin/python -m backend.main` (site at /app/, docs at /docs).
- Verify everything after any change — seven suites, 449 tests, ~1 min total:
  `test_phase2_preprocessing.py`, `test_phase8_api.py`, `test_phase8_rebuild.py`,
  `test_phase9_chat.py`, `test_phase10_itinerary.py`, `test_phase11_frontend.py`,
  `test_phase12_deployment.py` (all under `scripts/`, all in-process, no network).
- **Adding a new scrape** (the loop to use from now on):
  `.venv/bin/python scripts/add_reviews.py <export.csv> --source google_maps --name batch2`
  (add `--rating-scale 10` for Booking.com exports, `--dry-run` to preview). That merges
  and re-runs Phase 2; then re-run Phase 3 → Phase 4 → `build_phase8_database.py` to give
  the new reviews topics and preference evidence. Until Phase 3/4 are re-run they appear
  in listings, ratings and search but influence no recommendation or itinerary — the
  scripts say so rather than leaving it silent.
- Serving only needs `requirements-api.txt`. `requirements.txt` (torch, BERTopic,
  sentence-transformers) is only for re-running Phases 3-7.
- Try the chatbot: `POST /api/chat` with `{"message": "plan a 4 day trip in Sylhet"}`
  (see `/docs` for the schema). No API key needed — it's retrieval-based, not an LLM call.

## Known limits worth naming in the write-up
- **Itinerary proximity is hierarchical, not metric.** With no coordinates in the
  corpus, "near" means same district, then same division. Real distances would order
  days better — Sitakunda and Rangamati are the same division but ~120 km apart, so
  they can land on one day (the plan does flag "this day spans two districts").
  Adding a lat/lng column to `data/place_geography.csv` and switching
  `_travel_level`/`_day_buckets` to haversine is the natural upgrade, and nothing
  else in the planner would have to change.
- **Coverage is corpus-bound.** 27 places over 6 divisions means a 14-day trip can
  only be filled to ~7 days, and some cities (e.g. Sylhet city itself) have hotels but
  no reviewed attraction. The planner reports this rather than inventing stops.
- **No cost, season or opening-hours data**, so the old mock demo's "cost per day" and
  "best season" columns are gone rather than faked. They'd need a new data source.
- **Chatbot is English keyword regexes.** Bilingual support is still the stretch goal
  it was at MVP scope; the Bengali/code-mixed reviews are in the corpus and searchable,
  but a Bengali *question* won't route to the right intent.
- **Phase 5's 50-pair sample still has no human labels**, so precision/recall for the
  topic→preference mapping is unmeasured. This is now the single biggest open item: it is
  the one number in the project that needs a person, and the sample was regenerated for
  the new taxonomy, so fill `human_label` in `data/phase5_manual_review_sample.csv`
  (1 = the topic really does belong to that preference, 0 = it does not). Do **not** have
  an LLM fill that column — the whole point of the check is that it is independent of the
  model that produced the mapping.
- **Only 3 preferences hold hotel/coastal/hill evidence at 1-2 topics each.** More reviews,
  not a better prompt, is what closes that gap now.
- **Not yet deployed to a public URL** — the config is written and tested, but it needs
  a GitHub repo and a host account (see the unchecked boxes at the top of this file).
