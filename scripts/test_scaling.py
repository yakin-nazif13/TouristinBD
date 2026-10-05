"""Scaling tests — does the project still work when the corpus is 20x bigger?

The MVP corpus is 538 reviews. The plan is 10,000+. This suite checks, without
needing torch, a network or an API key, that:

  1. the size-dependent settings (min topic size, topic cap, scarcity cut) give
     the MVP values at MVP size and sensible ones at 10k;
  2. Phase 5's manual-review sample keeps its mix of positives/negatives with
     40 topics instead of 10, and never offers a true mapping as a "negative";
  3. Phase 4 refuses to build a Stage-2 prompt for more topics than fit, and a
     realistic 40-topic prompt is a sane size;
  4. a synthetic 10,000-review batch imports (add_reviews -> Phase 2), the corpus
     health report flags places with no geography and goes green once they are
     added, the database builds, and the API still answers with correct counts.

Everything heavy runs on a throwaway copy of `data/` (TOURISTINBD_DATA_DIR); the
real corpus is never touched.

Run:
    .venv/bin/python scripts/test_scaling.py
"""

from __future__ import annotations

import importlib
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import corpus_scaling as scaling  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
PASSED: list[str] = []
FAILED: list[str] = []

SYNTH_REVIEWS = 10_000
SYNTH_PLACES = 120
DIVISIONS = ["Barishal", "Chattogram", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def run_script(script: str, *args: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# 1. settings
# ---------------------------------------------------------------------------
def test_scaling_rules() -> None:
    print("\nsize-dependent settings")
    check("MVP size keeps min_topic_size = 6", scaling.choose_min_topic_size(538) == 6,
          str(scaling.choose_min_topic_size(538)))
    check("10k reviews -> min_topic_size 40", scaling.choose_min_topic_size(10_000) == 40,
          str(scaling.choose_min_topic_size(10_000)))
    check("tiny corpus never goes below the floor", scaling.choose_min_topic_size(20) == 6, "")
    check("MVP size keeps nr_topics='auto'", scaling.choose_nr_topics(538) == "auto", "")
    check("10k reviews cap the topic count",
          scaling.choose_nr_topics(10_000) == scaling.LARGE_CORPUS_MAX_TOPICS, "")
    check("an explicit --max-topics always wins", scaling.choose_nr_topics(10_000, 25) == 25
          and scaling.choose_nr_topics(538, 12) == 12, "")
    check("scarcity cut is the paper's 2% at MVP topic counts", scaling.scarcity_threshold(10) == 0.02,
          str(scaling.scarcity_threshold(10)))
    check("scarcity cut shrinks with many topics", scaling.scarcity_threshold(40) < 0.02
          and scaling.scarcity_threshold(100) < scaling.scarcity_threshold(40), "")
    check("scarcity cut tolerates zero topics", scaling.scarcity_threshold(0) == 0.02, "")


# ---------------------------------------------------------------------------
# 2. Phase 5 sampler
# ---------------------------------------------------------------------------
def test_phase5_sampler() -> None:
    print("\nPhase 5 manual-review sample at 40 topics")
    import run_phase5_bidirectional_validation as p5

    rng = np.random.default_rng(1)
    n_topics, n_prefs = 40, 8
    pref_ids = [f"P{i + 1:02d}" for i in range(n_prefs)]
    mapping = pd.DataFrame({
        "topic_id": range(n_topics),
        "preference_id": [pref_ids[i % n_prefs] for i in range(n_topics)],
        "similarity": 0.7,
        "second_best_preference_id": [pref_ids[(i + 1) % n_prefs] for i in range(n_topics)],
        "second_best_similarity": 0.5,
    })
    prefs = pd.DataFrame({"preference_id": pref_ids})
    sim = rng.random((n_topics, n_prefs))
    sample = p5.build_manual_review_sample(mapping, prefs, sim, 50)

    kinds = sample["pair_type"].value_counts().to_dict()
    check("sample is still 50 pairs", len(sample) == 50, str(len(sample)))
    check("it keeps positives, challengers and both kinds of negative",
          {"mapped_positive", "second_best_challenger", "hard_negative", "random_negative"} <= set(kinds), str(kinds))
    check("positives are capped at the quota, not one per topic", kinds.get("mapped_positive") == 10, str(kinds))
    true_map = dict(zip(mapping.topic_id, mapping.preference_id))
    negatives = sample[sample["expected_relation"] == 0]
    leaked = [(t, p) for t, p in zip(negatives.topic_id, negatives.preference_id) if true_map[t] == p]
    check("a true mapping is never offered as a negative", not leaked, str(leaked))
    check("no pair appears twice", not sample.duplicated(["topic_id", "preference_id"]).any(), "")

    # At MVP size nothing changes: every topic is used.
    small_map = mapping.head(10).reset_index(drop=True)
    small = p5.build_manual_review_sample(small_map, prefs, sim[:10], 50)
    check("at 10 topics every topic still gets a positive",
          (small["pair_type"] == "mapped_positive").sum() == 10, str(small["pair_type"].value_counts().to_dict()))


# ---------------------------------------------------------------------------
# 3. Phase 4 prompt size
# ---------------------------------------------------------------------------
def load_phase4():
    """Import the Phase 4 script, stubbing the API/embedding libraries if they are missing."""
    for name, attrs in (("openai", {"OpenAI": object}), ("dotenv", {"load_dotenv": lambda *a, **k: None}),
                        ("sentence_transformers", {"SentenceTransformer": object}),
                        ("sklearn", {}), ("sklearn.metrics", {}),
                        ("sklearn.metrics.pairwise", {"cosine_similarity": lambda *a, **k: None})):
        try:
            importlib.import_module(name)
        except Exception:
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[name] = mod
    return importlib.import_module("run_phase4_preference_classification")


def fake_topics(n: int) -> list[dict]:
    return [{
        "topic_id": i, "interpreted_label": f"Experience theme number {i} around a destination",
        "top_keywords": "beach, sunset, boat, fish, market, guide, ticket, crowd",
        "corpus_share": 0.02, "review_count": 200, "dimension_hint": "Attractions & Activities",
        "interpretation": "Visitors describe this theme in two or three sentences of plain prose. " * 2,
    } for i in range(n)]


def test_phase4_prompt() -> None:
    print("\nPhase 4 Stage-2 prompt")
    p4 = load_phase4()
    prompt = p4.build_stage2_prompt(fake_topics(40))
    check("a 40-topic prompt builds", "Topic 39:" in prompt, "")
    check("a 40-topic prompt is a sane size (< 40k characters)", len(prompt) < 40_000, str(len(prompt)))
    try:
        p4.build_stage2_prompt(fake_topics(p4.MAX_STAGE2_TOPICS + 1))
        refused, message = False, ""
    except RuntimeError as exc:
        refused, message = True, str(exc)
    check("more topics than fit is refused up front, not by a truncated LLM answer", refused, "")
    check("the refusal says how to fix it", "--max-topics" in message, message)


# ---------------------------------------------------------------------------
# 4. synthetic 10k import
# ---------------------------------------------------------------------------
PHRASES = [
    "The road to the site was rough but the view at the end was worth every minute",
    "We hired a local boatman who knew the quiet channels away from the main ghat",
    "Entry tickets were cheap and the staff at the gate were helpful and polite",
    "Best visited early in the morning before the tour buses arrive from the city",
    "The tea stall near the entrance serves excellent milk tea and fresh pitha",
    "Toilets were dirty and there was litter along the path, the place needs care",
    "A hidden temple a short walk behind the main building that few visitors find",
    "Bargain hard with the rickshaw pullers, the fare they quote first is double",
    "The sunset from the embankment was one of the best I have seen in Bangladesh",
    "Parking is limited so come by CNG, and carry cash because there is no ATM nearby",
    "Our family enjoyed the market where women sell handmade baskets and local sweets",
    "The museum was small but well kept and the caretaker explained the history",
]
BANGLA = [
    "জায়গাটা খুবই সুন্দর, পরিবার নিয়ে যাওয়ার জন্য একদম উপযুক্ত এবং শান্ত পরিবেশ",
    "নৌকায় করে ঘুরতে অনেক ভালো লেগেছে, মাঝিরা খুব আন্তরিক ছিলেন আমাদের সাথে",
]


def synthetic_export(path: Path, seed: int = 7) -> list[str]:
    rnd = random.Random(seed)
    places = [f"Synthetic Place {i:03d}" for i in range(SYNTH_PLACES)]
    rows = []
    for i in range(SYNTH_REVIEWS):
        place = places[i % SYNTH_PLACES]
        if rnd.random() < 0.08:
            text = f"{rnd.choice(BANGLA)} নম্বর {i}"
        else:
            text = ". ".join(rnd.sample(PHRASES, 3)) + f". Visit number {i} at {place}."
        rows.append({
            "title": place, "city": f"City {i % SYNTH_PLACES}", "stars": rnd.randint(1, 5),
            "text": text, "publishedAtDate": f"2026-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}",
        })
    pd.DataFrame(rows).to_csv(path, index=False)
    return places


def test_synthetic_import() -> None:
    print(f"\nsynthetic import of {SYNTH_REVIEWS:,} reviews across {SYNTH_PLACES} places")
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        data = tmp / "data"
        data.mkdir()
        for pattern in ("*.csv", "*.json"):
            for src in DATA_DIR.glob(pattern):
                shutil.copy2(src, data / src.name)
        before = len(pd.read_csv(data / "processed_reviews.csv"))
        export = tmp / "export.csv"
        places = synthetic_export(export)

        real_before = (DATA_DIR / "processed_reviews.csv").stat().st_mtime_ns
        result = run_script("add_reviews.py", str(export), "--source", "google_maps", "--name", "synthetic",
                            data_dir=data)
        check("the batch imports", result.returncode == 0, (result.stderr or result.stdout)[-400:])
        if result.returncode != 0:
            return
        processed = pd.read_csv(data / "processed_reviews.csv")
        added = len(processed) - before
        check("nearly every synthetic review survives cleaning and de-duplication",
              added >= SYNTH_REVIEWS * 0.99, f"{added} of {SYNTH_REVIEWS}")
        check("all synthetic places are in the corpus",
              set(places) <= set(processed["place_name"]), "")
        check("review_id stays unique across the 10k batch", processed["review_id"].is_unique, "")
        langs = processed["detected_language"].value_counts()
        check("Bangla text is detected at scale", langs.get("bn", 0) + langs.get("bn-en-mixed", 0) > 500,
              str(langs.to_dict()))

        # re-importing the same export must be a no-op
        again = run_script("add_reviews.py", str(export), "--source", "google_maps", "--name", "synthetic",
                           "--no-preprocess", data_dir=data)
        check("re-importing the same 10k export adds nothing",
              f"skipped {SYNTH_REVIEWS} row(s) already in the corpus" in again.stdout
              and len(pd.read_csv(data / "processed_reviews.csv")) == len(processed),
              again.stdout[-300:])

        # health report: no geography yet -> hard failure that names the places
        health = run_script("report_corpus_health.py", "--no-write", data_dir=data)
        check("health report fails when places have no division", health.returncode == 2, str(health.returncode))
        check("…and names the offending places", "Synthetic Place 000" in health.stdout, health.stdout[-300:])

        geo = pd.read_csv(data / "place_geography.csv")
        new_geo = pd.DataFrame({
            "place_name": places, "city": [f"City {i}" for i in range(len(places))],
            "district": [f"District {i % 64}" for i in range(len(places))],
            "division": [DIVISIONS[i % 8] for i in range(len(places))],
            "place_kind": "attraction", "notes": "synthetic",
        })
        pd.concat([geo, new_geo], ignore_index=True).to_csv(data / "place_geography.csv", index=False)
        health = run_script("report_corpus_health.py", "--no-write", data_dir=data)
        check("health report is green once geography is added", health.returncode == 0,
              health.stdout[-300:])
        check("every division now has places", "| Rangpur | 15" in health.stdout, health.stdout[-900:])

        # database + API
        build = run_script("build_phase8_database.py", data_dir=data)
        check("the database builds at 10k", build.returncode == 0, (build.stderr or build.stdout)[-400:])
        if build.returncode != 0:
            return
        conn = sqlite3.connect(data / "touristinbd.db")
        n_db = conn.execute("select count(*) from reviews").fetchone()[0]
        n_places = conn.execute("select count(*) from places").fetchone()[0]
        conn.close()
        check("every review reached the database", n_db == len(processed), f"{n_db} vs {len(processed)}")
        check("every place reached the database", n_places == processed["place_name"].nunique(),
              f"{n_places} vs {processed['place_name'].nunique()}")

        os.environ["TOURISTINBD_DATA_DIR"] = str(data)
        for mod in [m for m in list(sys.modules) if m.startswith("backend")]:
            del sys.modules[mod]
        from fastapi.testclient import TestClient
        client = TestClient(importlib.import_module("backend.main").app)

        overview = client.get("/api/overview").json()
        check("API overview reports the grown corpus", overview["total_reviews"] == len(processed), str(overview))
        page = client.get("/api/places", params={"limit": 500}).json()
        check("API lists every place in one page of 500", page["total"] == len(page["items"]) == n_places,
              f"{page.get('total')} / {len(page['items'])}")
        first = client.get("/api/places", params={"limit": 50, "offset": 0}).json()
        second = client.get("/api/places", params={"limit": 50, "offset": 50}).json()
        check("place pagination walks through the list without overlap",
              not ({p["place_id"] for p in first["items"]} & {p["place_id"] for p in second["items"]}), "")
        reviews = client.get("/api/reviews", params={"place": "Synthetic Place 007", "limit": 5}).json()
        check("review filter works on the grown corpus", reviews["total"] > 50, str(reviews.get("total")))
        chat = client.post("/api/chat", json={"message": "tell me about Synthetic Place 007"})
        check("chat answers about a new place", chat.status_code == 200 and chat.json()["intent"] != "unknown",
              chat.text[:200])
        plan = client.get("/api/itinerary", params={"days": 3})
        check("the itinerary planner still answers", plan.status_code == 200, plan.text[:200])
        search = client.get("/api/search", params={"q": "ghat"})
        check("full-text search answers on 10k reviews", search.status_code == 200, search.text[:200])

        check("the real data directory was not touched",
              (DATA_DIR / "processed_reviews.csv").stat().st_mtime_ns == real_before, "")
    # restore the default so anything run after this uses the real data
    os.environ.pop("TOURISTINBD_DATA_DIR", None)


def main() -> None:
    print("Scaling tests\n")
    test_scaling_rules()
    test_phase5_sampler()
    test_phase4_prompt()
    test_synthetic_import()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All scaling tests passed.")


if __name__ == "__main__":
    main()
