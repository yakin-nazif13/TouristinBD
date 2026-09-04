# Deployment (Phase 12)

The whole project ships as **one stateless service**: FastAPI serves the API at
`/api/...` and the interface at `/app/`, reading a SQLite file that is rebuilt
from the committed pipeline artifacts at deploy time. There is no external
database, no API key and no network call at runtime — the LLM work happened
back in Phase 4 and its output is already in `data/`.

That means a data refresh is just:

```bash
.venv/bin/python scripts/add_reviews.py <new_export.csv> --source google_maps --name batch2
.venv/bin/python scripts/run_phase3_huggingface_bertopic.py        # cluster the new rows
.venv/bin/python scripts/run_phase4_preference_classification.py   # needs an LLM key
git add data/ && git commit -m "refresh corpus" && git push
```

The host rebuilds `data/touristinbd.db` on the next deploy and every endpoint,
chart and itinerary follows automatically — the aggregates are SQL views, so
nothing is cached or hardcoded.

---

## 1. Run it locally

```bash
python3 -m venv .venv                                  # Python 3.10+
.venv/bin/pip install -r requirements-api.txt          # API only, ~30 MB
.venv/bin/python scripts/build_phase8_database.py      # data/*.csv -> SQLite
.venv/bin/python -m backend.main
```

- Interface: <http://127.0.0.1:8000/app/>
- API docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

`requirements.txt` (torch, BERTopic, sentence-transformers, …) is only needed to
**re-run** the research pipeline, Phases 3–7. Serving needs `requirements-api.txt`.

`frontend/index.html` still works when opened straight from disk — it falls back
to `http://127.0.0.1:8000` and shows a banner if the API is not up.

## 2. Deploy to Render (free tier)

`render.yaml` is a blueprint, so there is nothing to configure by hand:

1. Push this repository to GitHub.
2. Render dashboard → **New → Blueprint** → pick the repo.
3. Render runs the build (`pip install -r requirements-api.txt && python
   scripts/build_phase8_database.py`), then `python -m backend.main`.
4. Open `https://<service>.onrender.com/app/`.

`HOST=0.0.0.0` is set in the blueprint and `PORT` is injected by Render;
`backend/main.py` reads both. `/health` is the health check, and it reports
`database: ready` only when the schema version matches the code — a half-built
deploy fails the check instead of serving broken data.

**Free-tier caveat:** the instance sleeps after ~15 minutes idle and takes ~30 s
to wake. Fine for a demo or a viva; use a paid instance or a keep-alive ping if
it needs to be always-on.

## 3. Deploy with Docker (any host)

```bash
docker build -t touristinbd .
docker run -p 8000:8000 touristinbd
```

The image builds the database **and runs the Phase 8–11 test suites during the
build**, so a broken artifact fails `docker build` rather than shipping. It ends
up around 250 MB, needs no volume and no runtime network access.

Works as-is on Fly.io (`fly launch --dockerfile`), Railway, Google Cloud Run and
any container host — they all set `$PORT`, which the app already honours.

## 4. Split deployment (static frontend elsewhere)

To host the page on Netlify / Vercel / GitHub Pages and the API somewhere else,
publish `frontend/` as the static site and point it at the API:

```
https://your-site.example/?api=https://your-api.example
```

The URL is remembered in `localStorage`, so it only has to be given once. CORS
already allows any origin (`GET` and `POST`), because the API is read-only apart
from `/api/chat`, which writes nothing.

## 5. After deploying

```bash
curl https://<host>/health          # database ready + build stamp
curl https://<host>/api/meta        # which artifacts the DB was built from
```

Against a running deployment you can also run the suites locally by pointing the
tests at the same data directory:

```bash
.venv/bin/python scripts/test_phase2_preprocessing.py   # needs `pip install langdetect`
.venv/bin/python scripts/test_phase8_api.py
.venv/bin/python scripts/test_phase8_rebuild.py
.venv/bin/python scripts/test_phase9_chat.py
.venv/bin/python scripts/test_phase10_itinerary.py
.venv/bin/python scripts/test_phase11_frontend.py
.venv/bin/python scripts/test_phase12_deployment.py
```

GitHub Actions (`.github/workflows/ci.yml`) runs all seven on every push, plus a
container build that boots the image and checks `/health` and `/app/`.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Bind address. Managed hosts need `0.0.0.0`. |
| `PORT` | `8000` | Injected by most hosts. |
| `TOURISTINBD_DATA_DIR` | `<repo>/data` | Where the artifacts and the SQLite file live. Read by both the build script and the API. |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every endpoint returns 503 with a rebuild hint | `data/touristinbd.db` missing or built by an older schema | Re-run `scripts/build_phase8_database.py` (the build step does this automatically) |
| Page shows "API OFFLINE" | The page cannot reach the API origin | Start the backend, or append `?api=<url>` to the page URL |
| Deploy succeeds but tables look empty | A `data/*.csv` artifact is gitignored, so the build degraded gracefully | Check `git ls-files data/`; `scripts/test_phase12_deployment.py` asserts the required files are committed |
| Build times out on a free tier | `requirements.txt` was installed instead of `requirements-api.txt` | Use the slim file — torch alone is ~800 MB |
