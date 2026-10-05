# Collecting data at scale (target: 10,000+ reviews)

Short version: **adding data will not break the project**, but where you collect matters
more than how much. `scripts/test_scaling.py` imports a synthetic 10,000-review batch
across 120 places, builds the database and checks the API, so that claim is tested.

## What matters for finding the long tail

The current corpus is 538 reviews of 27 places, almost all the famous ones. Collecting
more reviews of the *same* places will add volume, not long tail: every extra review of
Cox's Bazar Beach lands in the same "coastal" topic. Long-tail material is places,
foods and tips that are mentioned **inside** reviews of other places or at lesser-known
sites. So:

- **Go wide, not deep.** 50+ places across all 8 divisions, 150-400 reviews each, beats
  10 places at 1,000 each. Today Rangpur and Mymensingh have **no places**, Barishal and
  Rajshahi one each (`scripts/report_corpus_health.py` prints this table).
- **Keep the reviewer's original text.** Most of the local knowledge is in Bangla and
  Banglish, and Google's English translation mangles place names.
- **Topic-level long-tail detection will still say "0" or "everything".** The rule in
  Phase 4 (topic share < 2% and semantically distinct) is a topic-level test. The
  entity-level extractor in `docs/BUILD_PLAN.txt` section 5 is what actually finds
  hidden places. More data is the prerequisite for that, not a substitute.

## 1. Plan the places

Copy rows into `data/scrape_targets.csv` (template provided) before scraping, so you
know what is done and what is missing.

- ~50 anchors, 5-8 per division (starting list: `docs/BUILD_PLAN.txt` section 3.1).
- Prefer places with 200+ Google reviews.
- Use the **Google Maps place URL**, not a search phrase. Search phrases are how
  "Sundarbans" once returned the Indian side.
- `place_name` in the export is Google's `title`. Use that exact string in
  `place_geography.csv` later; the two must match.

## 2. Scrape: `compass/google-maps-reviews-scraper` settings

Actor input names occasionally change; check the actor's input page if one is missing.

| Setting | Value | Why |
|---|---|---|
| Start URLs | the place URLs from `scrape_targets.csv` | exact places |
| Max reviews | 300-1000 per place | breadth over depth |
| Sort | `newest`, then a second run with `most relevant` | different slices; overlap is de-duplicated by `reviewId` |
| Language | `en` for one run, **`bn` for another** | Google shows a review's original text reliably only when browsing in its language |
| Reviews origin | all | |
| Personal data | **off** | no reviewer names or profile URLs are stored (see ethics in the build plan) |
| Proxy | residential if you get zero results | datacenter IPs get blocked |

Export as **CSV**. Check the header before importing: you want both `text` and one of
`textTranslated` / `originalText` (and `originalLanguage`). If only `text` is present,
`add_reviews.py` prints "cannot be separated" and the originals are lost; change the
actor settings and scrape again instead of importing that file.

**Booking.com:** same idea, one run per hotel across all districts. Booking rates out
of 10, so import with `--rating-scale 10`.

**Cost:** pay-per-result actors cost roughly USD 0.5 per 1,000 reviews, so 10,000
reviews is a few dollars. Free-tier credit usually covers a first round.

**Beyond Maps** (where most Bangla/Banglish text is): YouTube comments on Bangla travel
vlogs via the official YouTube Data API, public travel blogs (respect robots.txt),
TripAdvisor forum threads. Not Facebook groups: it breaks their terms and involves
private individuals' posts.

## 3. Import (one batch at a time)

```bash
# preview first; nothing is written
.venv/bin/python scripts/add_reviews.py ~/Downloads/gm_rajshahi_r1.csv \
    --source google_maps --name gm_rajshahi_r1 --dry-run

# then for real (re-runs Phase 2 and prints the corpus health report)
.venv/bin/python scripts/add_reviews.py ~/Downloads/gm_rajshahi_r1.csv \
    --source google_maps --name gm_rajshahi_r1
```

Re-importing a file is safe: rows already in the corpus are skipped.

## 4. Add geography for every new place

`add_reviews.py` ends by running `scripts/report_corpus_health.py`. If it lists
**places missing from place_geography.csv**, add a row for each to
`data/place_geography.csv` (`place_name,city,district,division,place_kind,notes`).
Without a division a place cannot be placed in an itinerary, and the health report
exits with an error until it is fixed.

## 5. Re-run the pipeline

```bash
.venv/bin/python scripts/report_corpus_health.py                    # check first
.venv/bin/python scripts/run_phase3_huggingface_bertopic.py         # ~2.5 min at 10k reviews, CPU
.venv/bin/python scripts/run_phase4_preference_classification.py    # needs Gemini key; one LLM call per topic
.venv/bin/python scripts/run_phase5_bidirectional_validation.py
.venv/bin/python scripts/run_phase6_sensitivity_analysis.py
.venv/bin/python scripts/run_phase7_statistics_visualization.py
.venv/bin/python scripts/build_phase8_database.py                   # required: rebuilds the app's DB
for t in scripts/test_*.py; do .venv/bin/python $t | tail -3; done
```

What changes automatically as the corpus grows (`scripts/corpus_scaling.py`):

| Setting | At ~540 reviews | At 10,000 reviews |
|---|---|---|
| BERTopic `min_topic_size` | 6 | 42 (0.4% of the corpus) |
| Topic count | `auto` | capped at 40 (Phase 4 puts all topics into one LLM prompt) |
| UMAP seed | 42 | 42 (same topics on every run; override with `--seed`) |
| Long-tail "scarce" cut | 2% | 2% down to 0.5/N for many topics (override with `--scarcity-threshold`) |
| Phase 5 manual-review sample | 10/10/15/15 pairs | 10/10/15/15 pairs (a seeded subset of topics) |

Phase 4 refuses to run with more than 60 topics, telling you to re-run Phase 3 with a
lower `--max-topics`.

## 6. After the new taxonomy exists

- **The 50-pair human labels must be redone.** The sample is regenerated for the new
  taxonomy. Do not have an LLM fill them.
- Phase 3's saved model (`data/bertopic_model_dir/`) is gitignored. It is ~100 MB at
  10k reviews; keep it as a release artifact or on the server.
- Expect a large outlier share (topic `-1`) from BERTopic on diverse text. It is not
  an error; those reviews simply do not belong to a topic.

## What is still open

- Language detection is `langdetect` + a Bangla-script check. Romanised Bangla
  (Banglish) will be labelled English. The fastText + Banglish classifier is Phase 3 of
  `docs/BUILD_PLAN.txt`.
- No coordinates in the corpus, so itineraries group by district/division, not distance.
