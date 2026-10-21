# Visitor review uploads

Visitors can write a review on the website ("Share a review" tab). It is **not** published
or added to the dataset until you approve it.

```
Visitor fills in the form  ->  saved as a small file in   data/visitor_uploads/pending/
You read it                ->  moved to   approved/   or   rejected/
You run --ingest           ->  approved reviews join the dataset and go through the pipeline
```

## What a visitor can do
- Pick one of the places already in the dataset, **or** choose "A place not listed" and type
  its name and district. New places are the interesting ones: they are the hidden gems the
  project is looking for.
- Give 1-5 stars and write 30-3000 characters in Bangla, Banglish or English. The text is
  kept exactly as typed.
- They are told: "received, will appear once it has been checked". They never see anyone
  else's pending review.

No name, email or IP address is asked for or stored. (The spam limiter remembers a visitor's
address in memory only, for an hour, and never writes it down.)

## What you do

**Easiest: the admin panel.** Set the owners' shared password and add their emails with `scripts/manage_admins.py`,
open `/admin`, sign in with your email, and approve or reject from the page. It can also add the approved reviews to
the dataset. See [ADMIN_PANEL.md](ADMIN_PANEL.md).

**Or from the command line** (same result; both use the same code and the same safeguards):

```bash
.venv/bin/python scripts/process_submissions.py --list                 # what is waiting
.venv/bin/python scripts/process_submissions.py --show V20261006T101500-ab12cd

# a review of a place that is already in the dataset
.venv/bin/python scripts/process_submissions.py --approve V2026...-ab12cd \
    --by Yakin --reason "genuine review"

# a review of a NEW place also needs its division (district and city are optional)
.venv/bin/python scripts/process_submissions.py --approve V2026...-ef34ab \
    --by Yakin --reason "real place, checked on the map" --division Khulna

.venv/bin/python scripts/process_submissions.py --reject V2026...-99aa11 \
    --by Yakin --reason "advertising"

.venv/bin/python scripts/process_submissions.py --ingest --dry-run     # preview
.venv/bin/python scripts/process_submissions.py --ingest               # do it
```

A name (`--by`) and a reason (`--reason`) are required for every decision, the same rule the
hidden-gem verification queue uses. Changing your mind is allowed until a review is ingested;
both decisions are kept in the file.

### What `--ingest` does
1. Adds new places to `data/place_geography.csv` (using the division you gave).
2. Adds the approved reviews to the dataset as a batch `data/real_reviews_visitor_<date>.csv`
   (through `add_reviews.py`, so duplicates are skipped). They are labelled
   `source_type = visitor`.
3. Runs the same chain every new batch goes through: clean the text -> label the language ->
   find mentions of other places -> merge spelling variants -> check against OpenStreetMap and
   Wikidata -> gem score -> verification queue -> rebuild the database.
4. Moves the files to `ingested/`.

Add `--offline` to skip the live OpenStreetMap/Wikidata lookups (new names are then recorded
as "unknown", never as hidden). Add `--skip-funnel` to only add and clean.

If a step fails, the approved files stay where they are. Fix the problem and run `--ingest`
again: reviews that were already added are skipped.

**Restart the server afterwards** (`python -m backend.main`) so it serves the rebuilt database.

### What is *not* run per review
Topic modelling (BERTopic) and the paid preference step need torch and API quota. A visitor
review shows up straight away in place listings, ratings, search and the Discoveries tab, but
it only joins topic/preference-based recommendations and itineraries at the next full refresh
(`run_phase3_huggingface_bertopic.py` then `run_phase4_preference_classification.py`).

## Safeguards built in
| Risk | Protection |
|---|---|
| Spam bots | hidden form field (bots fill it in; they are told "thanks" and nothing is saved) |
| Flooding | 5 reviews per hour per visitor, and at most 500 pending (`TOURISTINBD_MAX_PENDING`) |
| Same review sent twice | detected by a fingerprint of the text, across all folders |
| Link spam | more than one link is refused |
| Broken pages / CSVs | HTML tags and control characters stripped |
| Fake ratings | nothing counts until you approve it |
| Wrong place for an approval | new places need a division before they can be approved |
| Auto-publishing a hidden gem | new entities start as `candidate`; only a human decision in the verification queue publishes |

The public site cannot approve anything. Only signed-in owners can, through the admin panel
([ADMIN_PANEL.md](ADMIN_PANEL.md)); every admin route refuses a request without an owner's token.

## Settings
| Environment variable | Meaning | Default |
|---|---|---|
| `TOURISTINBD_UPLOADS_DIR` | where the upload folders live | `data/visitor_uploads` |
| `TOURISTINBD_SUBMIT_LIMIT` | submissions per visitor per hour | `5` |
| `TOURISTINBD_MAX_PENDING` | pending reviews before the inbox closes | `500` |

## Before putting this on a public website
- **The free Render plan wipes files on every restart or deploy**, so pending reviews would
  disappear. Use a persistent disk (set `TOURISTINBD_UPLOADS_DIR` to it) or move storage to a
  database.
- The CORS setting allows any origin to post. Restrict it to your own site's address.
- Add a CAPTCHA or stronger rate limiting. The in-memory limiter resets on restart and is per
  server process.
- Say in the privacy notice that reviews are read by a person before they are used.
- Moderate with the login-protected admin panel ([ADMIN_PANEL.md](ADMIN_PANEL.md)), over HTTPS only,
  with `admin_users.json` on the same saved disk as the pending reviews.

## Tests
`scripts/test_submissions.py` (87 checks) covers the storage rules, the web API, and the whole
journey on a throwaway copy of the data: submit -> approve -> ingest -> database -> API. It also
checks that no existing entity changes its ID when the new reviews arrive and that the real
`data/` folder is never touched.
