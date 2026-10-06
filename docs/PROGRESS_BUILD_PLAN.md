# TouristinBD — Build Plan Progress Checklist (v2 plan, Phases 1–7)

Last updated: 2026-10-06 — **Plan Phase 3 and Plan Phase 4 are complete in code.**
The hidden-gem engine runs end to end on the existing 538-review corpus and produces
results: 182 grounded mentions → 78 resolved entities → 23 scored for official
visibility → **4 places absent from both OpenStreetMap and Wikidata** → 13 candidates
ranked by gem score → a verification queue where nothing auto-publishes. Plan Phase 5
(research rigour) is **deliberately not started**: three of its six sections cannot
produce meaningful numbers until data collection and human verification happen.

> How to use this file: this tracks `docs/BUILD_PLAN.txt`, which renumbers everything.
> **The plan's Phases 1–7 are not the old MVP's Phases 0–12.** `docs/PROGRESS.md`
> tracks the original twelve-phase MVP and is still accurate for that; this file picks
> up where the v2 plan begins. Keep both current.

## Scope of the v2 plan (from BUILD_PLAN.txt)
- Capstone MVP → publishable, government-usable platform
- Research claim: topic-level long-tail detection fails on small translated corpora
  (our own detector found 0); **entity-level extraction from original-language text**
  recovers what it misses, traceably
- Two faces on one evidence base: a district register for government officers, and the
  existing tourist chat/itinerary/compare tools
- Hard rule throughout: every published claim links back to the text supporting it

## Accounts / infrastructure
- [x] GitHub repo — `yakin-nazif13/TouristinBD`, CI green on every push
- [x] Apify account (free tier) — used for the existing 538 reviews
- [x] Gemini API key — present in `.env`, pinned to `gemini-3.5-flash`
- [x] GitHub Actions workflows for the phases that need torch (see "Environment note")
- [ ] YouTube Data API key — needed for Plan Phase 2's Bangla/Banglish collection
- [ ] Public deploy host — Render config written and tested, no service created yet
- [ ] Managed Postgres — needed for Plan Phase 6

## Environment note (why some phases run in CI, not locally)
Windows Smart App Control is in enforcement mode on one development machine, and torch
ships unsigned DLLs, so `import torch` fails with `WinError 4551`. Anything needing
torch / sentence-transformers / BERTopic therefore runs on a Linux runner instead:
- `.github/workflows/phase6.yml` — the sensitivity analysis
- `.github/workflows/phase3-embeddings.yml` — the embedding benchmark

Everything else runs locally with `.venv\Scripts\python.exe`. Note the project docs say
`.venv/bin/python`, which is the Unix path and does not exist on Windows.

---

## Plan Phase 1 — Fix the foundations
- [x] All five Phase 1 scripts landed (ingestion fix, Phase 6 reproducibility, human
      validation tooling, agreement computation, annotator protocol)
- [x] 50-pair human validation **labelled by one annotator** (unaiza, 2026-10-05):
      precision **1.000**, recall **0.769**, F1 **0.870**, 50/50 labelled in 17 minutes.
      All 10 mapped positives confirmed; zero false positives.
      Committed as `data/human_labels/labels_unaiza.csv`.
- [x] The three disagreements are all one shape — topics judged related where the
      pipeline said otherwise (topic 3/P05, 6/P04, 7/P04), each above τ_sim=0.4 but
      beaten by a competing preference. **Recall is bounded by the
      one-topic-one-preference assumption, not by the similarity threshold.**
- [ ] **Second annotator** — `compute_human_agreement.py` needs ≥2 label files and
      only one exists, so Cohen's kappa is not yet computable. ~17 minutes of work.
      Nobody may re-run Phase 4 or Phase 5 before this, or the sample regenerates and
      the existing labels are orphaned.
- [ ] **Phase 6 re-run** — the committed `phase6_*` artifacts predate the CRC32 and
      seeded-UMAP fixes. A first reproducible run does **not** support the earlier
      "taxonomy stabilises at ~400 reviews" claim, and `PROGRESS.md` marks it
      superseded. Trigger `.github/workflows/phase6.yml` and commit the real numbers.
      **Do not cite the ~400-review figure until this is done.**
- [ ] Proposal corrections (task 1.5) — the "281 Google Maps + 235 Yelp" error (the data
      is Google Maps 300 + Booking.com 238), the duplicated citation in §1.6 and §2.4,
      the two different studies both cited as "Chang et al. (2024)", the mis-numbered
      lists in §5.4 and §11.1. **The proposal document is not in the repo**, so this
      cannot be done from here.
- [ ] Deploy to a non-sleeping instance (task 1.6)

## Plan Phase 2 — Data collection at national scale
- [x] **Section 3.5 provenance schema** — `source_type`, `collected_at`, `anchor_place`,
      `discovery_round`, `lat`, `lng`, carried from import through Phase 2 to the
      database. `scripts/corpus_schema.py` holds the single definition, including
      `source` → `source_type` mapping (`booking.com` → `booking`) and a Bangladesh
      bounding box that rejects a swapped lat/lng pair.
- [x] `add_reviews.py` gained `--source-type`, `--anchor-place`, `--discovery-round`,
      `--collected-at`, plus coordinate aliases for Apify's flattened `location/lat`
      shape. An explicit flag wins; a value already in the export is kept.
- [x] The two pre-3.5 batches are **not** back-filled. A fabricated coordinate or
      scrape date could not later be told apart from a real one, so those rows keep
      empty values and only `discovery_round` defaults (to 0, which is true by
      definition — snowballing did not exist when they were collected).
- [x] Byte-for-byte reproduction of the committed corpus still holds (80 tests)
- [x] `scrape_targets.csv`, `report_corpus_health.py`, `docs/DATA_COLLECTION.md`,
      and `test_scaling.py` with a synthetic 10,000-review import (Yakin, 2026-10-06)
- [ ] **YouTube Data API collector** — section 3.3a. This is where Banglish actually
      lives, it is free within quota, and the plan prefers official APIs over scraping
      for the ethics review. Not built.
- [ ] Blog fetcher (trafilatura, robots.txt respected) — section 3.3b
- [ ] Snowball round automation — section 3.2
- [ ] **The collection itself**: target ~10,000 texts across all 8 divisions, 20%+
      Bangla/Banglish. Currently 538 reviews, 27 places, 6 of 8 divisions.
      **Rangpur and Mymensingh still have zero places.**
- [ ] **Re-scrape retaining original-language text.** This is the single most
      load-bearing outstanding item: the research claim is entity extraction *from the
      original language*, and the corpus has no `review_text_original` column at all.
      Weakness W2 was fixed in Phase 1 but only for new batches.
- [ ] Coordinates for every place (16 recovered so far as a side effect of 5.4)

## Plan Phase 3 — The language pipeline — **COMPLETE in code**
- [x] **Four-way language label** (section 4.1): `bn` / `bn-latn` / `en` / `mixed`.
      The previous detector called "Khub sundor jayga" English, so Banglish was
      invisible (weakness W8).
- [x] A fifth label, `other`, with the ISO code recorded. A deliberate addition: the
      corpus contains one Dutch review, and calling it `en` would put a false value in
      the exact column the paper's language-mix table reads.
- [x] **Bangla normalisation** (section 4.2) — composes the vowel-sign and nukta
      sequences that render identically and compare unequal. NFC alone does not do
      this; they are not canonical equivalents.
- [x] **Phonetic matching key** — reduces either script to one consonant skeleton, so
      `Guliakhali / Guliyakhali / Gulyakhali` (plan line 67), `Chor Bijoy / Char Bijoy`
      (line 318) and `কুয়াকাটা / Kuakata` all collide. On the 27 corpus places it
      yields 27 distinct keys.
- [x] **Banglish classifier** (section 4.1) — character 1-4-gram TF-IDF + logistic
      regression with an out-of-fold F1, plus `label_banglish_sample.py`: blinded,
      resumable, shuffled per annotator, and a 500-text pool spanning all 27 places.
- [x] The classifier **refuses to train** on a single-class dataset or any class with
      one example. scikit-learn would train happily on the 530 English-only texts and
      report an F1, and that number reaching the paper would be worse than having no
      classifier. Five tests cover the refusals.
- [x] **Embedding benchmark** (section 4.3) — all four candidates (MiniLM, LaBSE,
      multilingual-e5-base, bge-m3), accuracy@1 and @5 both directions, CPU throughput.
      e5 and bge get their `query:`/`passage:` prefixes, without which the comparison
      looks decisive while being misconfigured.
- [x] Language labels served from the database (`review_language`, `v_language_mix`)
      and the API (`/api/analytics/language-labels`)
- [x] **Result on the 538**: `en` 532, `bn` 4, `mixed` 1, `other` 1.
      Bangla/Banglish/mixed share **0.9%** against the plan's 20% target, and
      **zero `bn-latn` rows** — the true state of a corpus collected through Google's
      translation, not a classifier failure.
- [ ] **500 hand-labelled Latin-script texts** to train the classifier. Tool and pool
      exist; the corpus contains no Banglish to label, so this follows collection.
- [ ] **Hand-written Banglish** for the `bn_latn` column of `embedding_triples.csv`.
      The benchmark refuses under 30 triples and the corpus yields **zero**, because a
      triple needs the reviewer's own words beside the translation.

## Plan Phase 4 — The hidden-gem engine — **COMPLETE in code**
- [x] **5.1 Entity model** — five types (PLACE, FOOD, ACTIVITY, ACCESS, TIP), four
      visibility levels (V0–V3), four queue states (candidate/verified/rejected/
      sensitive), with only `verified` publishable.
- [x] **5.2 Extraction with the hard grounding rule** — a surface form that cannot be
      located in the review is dropped and counted; every survivor carries the
      character offsets it was found at, stored in the database, so a claim in the
      register traces to a span of a real review. One function, applied to every
      extractor's output, so none can bypass it. 71 tests.
- [x] Three extractors sharing that rule: `gazetteer` (offline, free, deterministic),
      `gemini` (the plan's main method — **implemented and tested but NOT YET RUN**,
      since it costs API quota and refuses to start without `--yes`), and `ner`
      (the baseline; needs torch).
- [x] **Result**: 182 grounded mentions, 0% drop rate, 54 distinct surface forms,
      across 169 reviews. Recovers the access knowledge the plan quotes —
      *"get off at Fokirhat Bazar and take a CNG"*, *"engine boat from kaptai boat
      station"*, *"bargain for the boat price"*.
- [x] **5.3 Entity resolution** — four signals with weights fixed in advance (phonetic
      key, rapidfuzz, category-word containment, geography), single-link clustering,
      evaluated against 34 hand-made variant groups in
      `data/entity_resolution_gold.csv`, each row citing the plan line or corpus
      observation it rests on. **B-cubed F1 0.902**, precision 0.952, purity 0.952.
      96 surfaces → 78 entities.
- [x] Refuses to merge `Karamjal` into `Sundarbans` — containment is not equivalence,
      and merging them would hide Karamjal from the register.
- [x] **5.4 Gazetteer and V0–V3 visibility** — OpenStreetMap (Nominatim) and Wikidata,
      both free, rate-limited per their policies, cached so a re-run needs no network.
      **V0 4 · V1 6 · V2 5 · V3 8**, and **16 coordinates recovered**.
- [x] **The V0 list: Gangamati, Guliyakhali, Fatrar Chor, Chor Bijoy** — four places
      mentioned inside reviews of *other* places and absent from both sources. Plan
      line 63 predicts exactly these from Kuakata reviews.
- [x] **The invariant**: "we could not look" records `unknown`, never V0. Treating an
      outage as absence would manufacture discoveries out of our own downtime. 7 tests.
- [x] **5.5 Gem score** — five terms, fixed weights, each stored per entity so a
      ranking can be explained term by term: `mentions` 0.30 (saturating at 10),
      `hidden` 0.30, `distinct` 0.15, `sentiment` 0.15, `recency` 0.10. 13 of 78
      entities clear the 2-independent-review gate. Top: **Gangamati (V0) 0.69**.
- [x] **The ablation result** — removing `hidden` collapses the score into a popularity
      ranking (the three V3s take the top three); removing `mentions` orders candidates
      almost exactly by hiddenness. So `hidden` is what makes this a gem score rather
      than a list of famous places, and that is now demonstrable.
- [x] **5.6 Locals versus visitors** — built, and the honest answer is that the
      question **cannot be answered on this corpus**. See "Findings" below.
- [x] **5.7 Verification queue** — nothing auto-publishes; a high score decides what an
      officer sees first, never what the public sees. `sensitive` stays in the district
      register with its evidence and never reaches the tourist side. The decision log is
      append-only (who / when / state / why), a changed mind leaves both entries, and a
      decision missing an author or a reason is refused. 42 tests.
- [ ] **800-text double-annotated gold set** (section 5.1) — the extraction F1 table
      depends on it, and it needs two annotators. Scope down from 800 given capacity.
- [ ] **One LLM extraction run** to compare against the gazetteer baseline. Costs
      Gemini quota; not run without explicit approval.
- [ ] **Verify the 13 candidates.** The queue is empty — nobody has reviewed anything,
      which is the correct state but blocks precision@k in Plan Phase 5. ~30 minutes.

## Plan Phase 5 — Research rigour — **NOT STARTED, deliberately**
Three distinct blockers, not "more data" in general:

| Section | Blocked by | Status |
|---|---|---|
| 6.1 baselines (popularity, LDA, BERTopic-only, LLM-only) | precision@k needs **human-verified gems**; the queue is empty. k=10,20 over 13 candidates has no power | blocked |
| 6.2 original-vs-translated ablation | **original-language text** — the corpus has none. The plan calls this "likely the most-cited table" | blocked |
| 6.2 gem-score term ablations | nothing | **already produced** (see 5.5) |
| 6.2 embedding model choice | ≥30 triples → original text | blocked |
| 6.3 multiple seeds (5–10) | nothing; needs torch → Actions | **doable now** |
| 6.4 saturation curves | thousands of texts **and** verified gems | blocked |
| 6.5 large-corpus pipeline re-run | a large corpus, by definition | blocked |
| 6.6 bootstrap CIs | on precision@k no; on resolution F1 and extraction rates yes | **partly doable** |

Running the blocked sections now would produce a full set of tables with no
statistical power — precision@k over 13 candidates, a saturation curve from one data
point. Those are worse than absent, because they look like results and do not survive
a question.

## Plan Phase 6 — Government-grade product
- [x] Existing SQLite + FastAPI + web interface, now carrying the entity layer
- [x] Database schema v2 — `mentions`, `entities`, `entity_variants`, plus
      `v_mention_evidence` (each mention with the place whose review it sits in) and
      `v_entity_evidence` (independent-review counts)
- [x] `/api/entities`, `/api/entities/{id}`, `/api/mentions`,
      `/api/analytics/language-labels`
- [x] A sixth **Discoveries** tab — entities ranked by independent reviews, filterable
      by type and threshold, every row opening to the reviewer's own sentences with the
      place the mention was found in
- [ ] **Government dashboard** (section 7.4) — district register view, verification
      workflow UI, visitor-issue aspects, trends, one-click bilingual PDF brief, data
      quality panel. **This is the demo centrepiece and needs no new data.**
- [ ] PostgreSQL + PostGIS + Alembic (section 7.1)
- [ ] **Incremental pipeline** (section 7.2) — `transform()` on the saved BERTopic
      model instead of a full refit, plus a taxonomy diff an analyst approves. Without
      it every new batch forces a full refit *and* a paid Phase 4 re-run.
- [ ] Accounts, roles, audit log (section 7.3)
- [ ] Bangla/English UI toggle and Bangla chatbot lexicons (section 7.6)
- [ ] Paid hosting (section 7.7)

## Plan Phase 7 — Papers and innovation challenges
- [ ] Not started; depends on Plan Phase 5 results.

---

## Findings worth naming in the write-up

1. **51% of our first "discoveries" were self-mentions.** The first extraction run
   reported 440 mentions and 40 secondary places, matching the plan's estimate. 224 of
   those 440 were the review's own place in short form — a review of "Kuakata Beach"
   saying "Kuakata". Extraction excluded the exact place name but not a prefix of it.
   Corrected to 182 mentions across 52 entities, and a test now asserts that no mention
   is ever the review's own place.
2. **Resolution F1 fell from 0.969 to 0.902 as a direct result, and that is the honest
   number.** The evaluation set shrank from 32 to 21 gold surfaces because names like
   `Guliakhali`, `Kuakata` and `Ratargul` appeared *only* in their own place's reviews.
   Substantive variant merges fell from 7 to 1. In a corpus this size, most apparent
   variant evidence was a self-mention artifact — an argument for scaling the corpus,
   not for tuning the resolver.
3. **A fabricated confidence was being reported for 532 of 538 reviews.** The language
   pipeline recorded confidence 1.0 because `langdetect.detect()` returns no score and
   the gap was filled with the Latin-script proportion, which for English is exactly
   1.0. Now a real probability is recorded (0.998 average), and rule-based labels carry
   **NULL** rather than a stand-in.
4. **Section 5.6 conflicts with section 10.** Answering locals-versus-visitors through
   reviewer location needs Google Maps reviewer location, which is exactly the
   personal-data output the ethics stance keeps switched off. The route that does not
   conflict is **language** — Bangla or Banglish implies a domestic reviewer and needs
   no personal data — which becomes usable after the YouTube pass. This is a decision
   for the team, not a coding choice.
5. **`reviewer_is_local_guide` is not a residency signal.** The plan lists it as a
   proxy, but it is Google's badge for contribution volume, and 274 of the 300 reviews
   carrying it are `True`. A proxy that says yes to nine in ten reviewers cannot
   separate two audiences, so it is excluded.
6. **The source that identifies the reviewer is not the source that carries the
   evidence.** 181 of 182 mentions sit in reviews that cannot be labelled:
   `user_location` comes from Booking.com (hotel reviews, which rarely name another
   place), while the mentions are almost all in Google Maps reviews.
7. **Two UNESCO World Heritage sites scored V0 before a fix.** `Sompur Mahavihar
   (Paharpur)` and `Sundarbans (Karamjal Wildlife Centre)` — a parenthetical qualifier
   broke the gazetteer lookup. Names are now tried in three forms.
8. **The corpus's hotels were scored as undocumented places.** Resolution adds corpus
   place names to its pool so short forms have something to match; those carry zero
   mentions and were never discovered. Only entities with ≥1 mention are scored now.

## Known limits
- The corpus is **538 reviews of 27 places, 98% English**, covering 6 of 8 divisions.
  Every result above is bounded by that.
- **The LLM extractor has not been run.** All current results come from the gazetteer
  baseline, which can only find names already in a known-name list — it cannot discover
  a place nobody has listed, which is precisely what the LLM extractor is for.
- Entity resolution has one known error: it merges `Cox's Bazar` with `Cox's Bazar
  Beach`, while the gold set says `Kuakata` and `Kuakata Beach` are the same. Whether a
  town and a feature within it are one register entity is a judgement that defines
  correctness, so it is documented rather than silently resolved. It is the only thing
  between F1 0.902 and higher.
- **Cohen's kappa is not computable** (one annotator).
- **The Phase 6 sensitivity numbers predate the reproducibility fix** and should not be
  cited.
- `recency` is 1.0 for 10 of 13 candidates, so its 0.10 weight does little work on this
  corpus.
- Two V3 (already-famous) entities outrank every V2 and V1, because `mentions` saturates
  for a much-reviewed place. The weights were **not** retuned after seeing this; section
  6.2 settles the weighting against human-verified gems. An `already_official` flag lets
  the register filter them.

## How to run everything
```
.venv\Scripts\python.exe scripts\run_phase2_preprocessing.py
.venv\Scripts\python.exe scripts\run_phase3_language_pipeline.py
.venv\Scripts\python.exe scripts\extract_mentions.py --extractor gazetteer
.venv\Scripts\python.exe scripts\resolve_entities.py --evaluate
.venv\Scripts\python.exe scripts\build_gazetteer.py
.venv\Scripts\python.exe scripts\score_gems.py
.venv\Scripts\python.exe scripts\analyze_audience.py
.venv\Scripts\python.exe scripts\verification_queue.py --export-register
.venv\Scripts\python.exe scripts\build_phase8_database.py
.venv\Scripts\python.exe -m backend.main      # then open /app/ and the Discoveries tab
```
Tests: **974 across 20 suites**, all passing, about two minutes.

## Next session, in priority order
1. **Plan Phase 6's government dashboard** — the demo centrepiece, needs no new data,
   and `BUILD_PLAN.txt` line 573 is explicit: *"Phase 4 + dashboard are the demo;
   everything else is secondary."*
2. The unblocked Plan Phase 5 pieces — multiple seeds (6.3), the gem-score ablation
   table formalised, bootstrap CIs on the metrics that already exist.
3. Two cheap human unlocks: a second annotator for the 50 pairs (kappa), and verifying
   the 13 candidates (partially unblocks precision@k).
4. Trigger the Phase 6 sensitivity workflow and commit the real reproducible numbers.
5. Then data collection: YouTube collector, re-scrape with original-language text on.
