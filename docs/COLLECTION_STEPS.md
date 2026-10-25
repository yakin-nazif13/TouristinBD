# How to collect the 9,500 reviews — step by step

Plain-language guide. The plan, the place list and the Apify settings are already prepared by
`scripts/import_place_list.py` (see `docs/DATA_COLLECTION.md` for how that works).

**What you have ready:** 100 places in all 8 divisions, and a folder of ready-to-paste Apify settings:

```
data/scrape_batches/
    pilot.json            3 places, English      <- start here
    pilot_bangla.json     the same 3 places, Bangla
    relevant/   23 files  the main collection (longest, most useful reviews)
    bangla/     12 files  Bangla-language pass
    newest/     12 files  recent reviews (optional)
```

## Before you start (one time)
1. Make an Apify account at apify.com. Check how much free credit it gives (Billing / Usage).
2. Set a **spending limit** in Billing so a mistake cannot cost more than you expect.
3. Rough cost: pay-per-result actors charge about USD 0.3–0.6 per 1,000 reviews. The `relevant/` folder is up to about
   11,400 reviews (roughly USD 5–7). Check the price shown on the actor's page.
4. Keep every export you download **outside the project folder** (for example in Downloads). They hold more than
   the project needs.

## Part 1 — Google Maps reviews with Apify

### Step 1: open the tool
apify.com → **Store** → search **Google Maps Reviews Scraper** (made by *compass*) → open it in the Console.

### Step 2: run the pilot (about 15 minutes, costs cents)
1. Open the **Input** tab. Switch to **JSON** view.
2. Open `data/scrape_batches/pilot.json`, copy everything, paste it in, press **Start**.
3. When it says **Succeeded**: open the **Output / Storage → Dataset** tab → **Export** → **CSV** → include all fields → download.
4. Do the same with `pilot_bangla.json`.

If Apify says a field is not valid, switch to the normal form and fill it in by hand using the same numbers:
Place IDs = the ids in the file, Max reviews = 200, Sort = Most relevant, Language = English (or Bangla for the second
file), Personal data = **off**. If the actor wants links instead of ids, re-make the files with
`.venv/bin/python scripts/import_place_list.py YOUR_LIST.csv --format urls --no-refresh`.

### Step 3: check the pilot export (the most important step)
Open the CSV in Excel / Numbers and look at the column names. You need:

| Column | Why |
|---|---|
| `text` **and** `textTranslated` (or `originalText`) | the reviewer's own words kept next to the translation |
| `originalLanguage` (or `language`) | tells Bangla from English |
| `reviewId`, `placeId`, `title`, `stars`, `publishedAtDate` | identity, place, rating, date |

In the Bangla pilot, find a Bangla review. Its `text` should be in Bangla letters. **If the original words are missing,
stop and fix the settings before spending more money.** The whole research idea depends on keeping them.

### Step 4: import the pilot (try it first, then for real)
```bash
.venv/bin/python scripts/add_reviews.py ~/Downloads/pilot.csv --source google_maps --name pilot --dry-run
```
Read what it prints:
- Good: `kept original-language text for N row(s)`.
- Bad: `cannot be separated` — go back to Step 2 and change the actor settings.
- Good: lines like `place renamed to its final name: ...` and `filled coordinates from the place list`.
- Look at: `N place name(s) are not in data/place_names.csv` — a place under a different title. Add it to
  `data/place_aliases.csv` (columns `alias,place_id,note`) and run the import command again.

Happy? Run the same command **without** `--dry-run`. Do the same for the Bangla pilot (`--name pilot_bangla`).
It cleans the text automatically and prints a health report.

### Step 5: the main collection
Work through `data/scrape_batches/relevant/` one file at a time, biggest value first:
`chattogram_*`, `dhaka_*`, `sylhet_*`, then the rest.
For each file:
1. Paste it into the actor's Input (JSON view), **Start**, wait (5 to 40 minutes).
2. Export the CSV. Name it after the file, e.g. `relevant_chattogram_100.csv`.
3. Import it:
```bash
.venv/bin/python scripts/add_reviews.py ~/Downloads/relevant_chattogram_100.csv --source google_maps --name relevant_chattogram_100
```
Run **one Apify run at a time** at first. Importing the same file twice is harmless (repeats are skipped).

### Step 6: check progress and know when to stop
```bash
.venv/bin/python scripts/report_corpus_health.py --min-division-places 5
```
It shows reviews per division, the language mix and any place missing a location. The `relevant/` folder alone should
get you close to **9,500 usable reviews** (short and repeated ones are dropped automatically). Stop when you reach it.
Then run `bangla/` to lift the Bangla share (aim for 20% Bangla/Banglish). `newest/` is optional; it mostly adds short reviews.

### If something goes wrong
| Problem | What to do |
|---|---|
| The run returns almost nothing | Turn on the actor's proxy option (residential). A blocked connection gives empty results. |
| "Input invalid" | Use the form view (Step 2). |
| `cannot be separated` on import | The export lacks original text. Change the settings and scrape again. Do not import it. |
| Unknown place names on import | Add a line to `data/place_aliases.csv` and import again. |
| A place came back with far fewer reviews than planned | Normal for small places; the plan never asks for more than a place has. |

## Part 2 — Other sources (why, and what is ready)

**Why bother:** Google reviews are short. Hidden places are named in **long** texts, and Banglish (Bangla in English
letters) lives mostly in YouTube comments and blogs. In your data, reviews that name another place had a median length of
about 1,000 characters.

| Source | What it gives | Status |
|---|---|---|
| **YouTube comments** on Bangla travel vlogs (official API, free quota) | Banglish and Bangla, many place names | **Not built yet** — I can build it |
| **Travel blog posts** (Bangla and English) | The most place names per text | **Not built yet** — I can build it |
| **TripAdvisor** (an Apify actor works the same way as Part 1) | Longer English reviews | Ready to try, same steps. Check its terms. |
| **Visitor reviews** from the website | Trickle of new, local reviews | Ready (Share a review tab and the admin panel) |
| Booking.com hotels near the spots | Few mentions of other places | Low value for hidden places |
| Facebook groups | — | **Do not use** (breaks their rules; private people's posts) |

**To get ready for YouTube** (free): Google Cloud Console → new project → *APIs & Services → Library* → enable
**YouTube Data API v3** → *Credentials → Create credentials → API key* → restrict it to that one API. The free allowance is
10,000 units a day, and 100 comments cost about 1 unit, so 1,500 comments is trivial. Keep the key in `.env` as
`YOUTUBE_API_KEY`. Never put it in git. Pick 20–30 Bangla vlogs about your places and list their links; the collector will
read the comments.

**Counting:** a blog post is one text but names many places, so do not count one post as one review. If you add YouTube
and blogs, lower the Google target to match, e.g. `import_place_list.py LIST.csv --total 7000 --online`
(it is safe to re-run; it rewrites the batch files).

## After you finish collecting
1. **Finish the human labelling first** (the second person labels the 50 pairs). Re-running the topic and preference
   steps replaces those 50 pairs, and the existing labels would no longer match.
2. Then run, in this order (all offline except step 3 and Phase 4):
```bash
.venv/bin/python scripts/run_phase3_language_pipeline.py
.venv/bin/python scripts/extract_mentions.py --extractor gazetteer
.venv/bin/python scripts/resolve_entities.py
SSL_CERT_FILE=$(.venv/bin/python -c "import certifi;print(certifi.where())") .venv/bin/python scripts/build_gazetteer.py
.venv/bin/python scripts/score_gems.py
.venv/bin/python scripts/verification_queue.py --export-register
.venv/bin/python scripts/build_phase8_database.py
```
3. For topics and preferences (needs the Gemini key): `run_phase3_huggingface_bertopic.py` (about 3 minutes at this size),
   then `run_phase4_preference_classification.py`, then Phases 5, 6, 7 and the database build.
4. Run all the tests: `for t in scripts/test_*.py; do .venv/bin/python $t | tail -2; done`.

## A decision before you import thousands of reviews
Your GitHub repository is **public**, and the review text files in `data/` are committed to it. Your own plan
(`docs/BUILD_PLAN.txt`, section 10) says to publish derived data, not raw platform text, and Google's terms limit
republishing reviews. Roughly 9,500 more reviews would go into a public repo. Options: make the repository private
(simplest), or stop committing the raw review files and share only the derived results. The deployment and tests currently
expect those files to be committed, so decide this before the big import.
