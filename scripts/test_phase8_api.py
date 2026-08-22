"""Phase 8 (part 2) — smoke tests for the backend API.

Runs the whole API in-process with FastAPI's TestClient, so no server needs to
be started and nothing touches the network. Checks that every route answers,
that the row counts line up with the pipeline artifacts, and that the filters
and pagination actually filter and paginate.

Run:
    .venv/bin/python scripts/test_phase8_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def get(path: str, **params) -> tuple[int, object]:
    r = client.get(path, params=params or None)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def main() -> None:
    print("Phase 8 — API smoke tests\n")

    # ---- meta ------------------------------------------------------------
    print("meta")
    code, health = get("/health")
    check("GET /health returns ok", code == 200 and health["status"] == "ok", str(health))

    code, meta = get("/api/meta")
    check("GET /api/meta has row counts", code == 200 and bool(meta["row_counts"]), str(code))
    check(
        "meta lists all 8 pipeline phases",
        len(meta.get("pipeline_phases", {})) == 8,
        str(meta.get("pipeline_phases")),
    )

    code, overview = get("/api/overview")
    processed = pd.read_csv(REPO_ROOT / "data" / "processed_reviews.csv")
    check(
        "overview total_reviews matches processed_reviews.csv",
        code == 200 and overview["total_reviews"] == len(processed),
        f"{overview.get('total_reviews')} vs {len(processed)}",
    )
    check(
        "overview clustered + outliers == total",
        overview["clustered_reviews"] + overview["outlier_reviews"] == overview["total_reviews"],
        str(overview),
    )
    check(
        "overview breaks reviews down by source",
        sum(overview["reviews_by_source"].values()) == overview["total_reviews"],
        str(overview["reviews_by_source"]),
    )

    # ---- places ----------------------------------------------------------
    print("\nplaces")
    code, page = get("/api/places", limit=100)
    check("GET /api/places lists every place", code == 200 and page["total"] == 27, str(page.get("total")))
    check(
        "every place has a city (geography enrichment worked)",
        all(p["city"] for p in page["items"]),
        str([p["place_name"] for p in page["items"] if not p["city"]]),
    )
    check(
        "place review counts sum to the corpus",
        sum(p["review_count"] for p in page["items"]) == overview["total_reviews"],
        str(sum(p["review_count"] for p in page["items"])),
    )

    code, hotels = get("/api/places", place_kind="accommodation", limit=100)
    check("place_kind filter works", code == 200 and hotels["total"] == 12, str(hotels.get("total")))

    code, dhaka = get("/api/places", city="dhaka")
    check(
        "city filter is case-insensitive",
        code == 200 and dhaka["total"] == 5,
        str(dhaka.get("total")),
    )

    code, page2 = get("/api/places", limit=5, offset=5)
    check("pagination returns a distinct window", code == 200 and page2["returned"] == 5, str(code))
    first_ids = {p["place_id"] for p in page["items"][:5]}
    check(
        "offset actually skips rows",
        not first_ids & {p["place_id"] for p in page2["items"]},
        "windows overlap",
    )

    code, detail = get("/api/places/Lalbagh Fort")
    check(
        "GET /api/places/{name} resolves by name",
        code == 200 and detail["place"]["place_name"] == "Lalbagh Fort",
        str(code),
    )
    check(
        "place detail carries preferences and samples",
        bool(detail["preferences"]) and bool(detail["sample_reviews"]),
        f"prefs={len(detail['preferences'])} samples={len(detail['sample_reviews'])}",
    )
    code, _ = get("/api/places/does-not-exist")
    check("unknown place returns 404", code == 404, str(code))

    code, cities = get("/api/cities")
    check("GET /api/cities returns all 16 cities", code == 200 and len(cities) == 16, str(len(cities)))
    check(
        "city review counts sum to the corpus",
        sum(c["review_count"] for c in cities) == overview["total_reviews"],
        str(sum(c["review_count"] for c in cities)),
    )

    # ---- reviews ---------------------------------------------------------
    print("\nreviews")
    code, rpage = get("/api/reviews", limit=10)
    check("GET /api/reviews paginates", code == 200 and rpage["total"] == len(processed), str(rpage.get("total")))
    check("review rows carry text", all(r["review_text_clean"] for r in rpage["items"]), "empty text")

    code, filtered = get("/api/reviews", min_rating=5, limit=5)
    check(
        "min_rating filter holds",
        code == 200 and all(r["review_rating"] >= 5 for r in filtered["items"]),
        str([r["review_rating"] for r in filtered["items"]]),
    )

    code, textq = get("/api/reviews", q="sunset", limit=5)
    check(
        "text search matches review text",
        code == 200 and textq["total"] > 0
        and all("sunset" in (r["review_text_clean"] or "").lower() for r in textq["items"]),
        str(textq.get("total")),
    )

    code, escaped = get("/api/reviews", q="100%_", limit=5)
    check("LIKE wildcards in q are escaped", code == 200 and escaped["total"] == 0, str(escaped.get("total")))

    code, outliers = get("/api/reviews", topic_id=-1, limit=5)
    check(
        "topic_id=-1 returns the BERTopic outliers",
        code == 200 and outliers["total"] == overview["outlier_reviews"],
        f"{outliers.get('total')} vs {overview['outlier_reviews']}",
    )

    code, bypref = get("/api/reviews", preference_id="P01", limit=5)
    check("preference_id filter works", code == 200 and bypref["total"] == 239, str(bypref.get("total")))

    code, dated = get("/api/reviews", date_from="2026-01-01", limit=5)
    check(
        "date_from filter holds",
        code == 200 and all(r["review_date"] >= "2026-01-01" for r in dated["items"]),
        str([r["review_date"] for r in dated["items"]]),
    )

    sample_id = rpage["items"][0]["review_id"]
    code, single = get(f"/api/reviews/{sample_id}")
    check("GET /api/reviews/{id} returns lineage", code == 200 and "topic_id" in single, str(code))

    code, langs = get("/api/languages")
    check(
        "GET /api/languages sums to the corpus",
        code == 200 and sum(l["review_count"] for l in langs) == overview["total_reviews"],
        str(code),
    )

    # ---- taxonomy --------------------------------------------------------
    print("\ntaxonomy")
    code, topics = get("/api/topics")
    check("GET /api/topics excludes outliers by default", code == 200 and len(topics) == 10, str(len(topics)))
    check(
        "every topic has a mapped preference",
        all(t["preference_id"] for t in topics),
        str([t["topic_id"] for t in topics if not t["preference_id"]]),
    )
    code, with_out = get("/api/topics", include_outliers=True)
    check("include_outliers adds the -1 bucket", len(with_out) == 11, str(len(with_out)))

    code, topic = get("/api/topics/0")
    check(
        "topic detail includes places and validation",
        code == 200 and bool(topic["places"]) and topic["validation"] is not None,
        str(code),
    )

    code, prefs = get("/api/preferences")
    check("GET /api/preferences returns 10", code == 200 and len(prefs) == 10, str(len(prefs)))
    check(
        "P10 is present with zero evidence",
        any(p["preference_id"] == "P10" and p["review_count"] == 0 for p in prefs),
        str([(p["preference_id"], p["review_count"]) for p in prefs]),
    )
    code, mapped_only = get("/api/preferences", include_unmapped=False)
    check("include_unmapped=false drops P10", len(mapped_only) == 9, str(len(mapped_only)))

    code, pref = get("/api/preferences/p03")
    check(
        "preference lookup is case-insensitive and joins topics",
        code == 200 and pref["preference"]["preference_id"] == "P03" and len(pref["topics"]) == 2,
        str(code),
    )
    check(
        "preference detail lists cities and places",
        bool(pref["top_cities"]) and bool(pref["top_places"]),
        str(len(pref["top_cities"])),
    )
    code, _ = get("/api/preferences/P99")
    check("unknown preference returns 404", code == 404, str(code))

    code, tree = get("/api/taxonomy")
    check(
        "GET /api/taxonomy nests category -> subcategory -> preference",
        code == 200 and all("subcategories" in c for c in tree),
        str(code),
    )
    leaf_count = sum(
        len(s["preferences"]) for c in tree for s in c["subcategories"]
    )
    check("taxonomy tree holds all 10 preferences", leaf_count == 10, str(leaf_count))

    # ---- analytics -------------------------------------------------------
    print("\nanalytics")
    code, ratings = get("/api/analytics/rating-distribution")
    check(
        "rating distribution sums to the corpus",
        code == 200 and sum(r["review_count"] for r in ratings) == overview["total_reviews"],
        str(code),
    )
    code, temporal = get("/api/analytics/temporal")
    check("temporal (month) returns periods", code == 200 and len(temporal) > 0, str(code))
    code, yearly = get("/api/analytics/temporal", granularity="year")
    check("temporal (year) returns periods", code == 200 and len(yearly) > 0, str(code))

    code, freq = get("/api/analytics/preference-frequency")
    check(
        "preference frequency shares sum to ~1",
        code == 200 and abs(sum(f["review_share"] for f in freq) - 1.0) < 0.01,
        str(sum(f["review_share"] for f in freq) if code == 200 else code),
    )

    code, cityprefs = get("/api/analytics/city-preferences")
    check("city-preference rollup non-empty", code == 200 and len(cityprefs) > 0, str(code))
    code, venueprefs = get("/api/analytics/venue-preferences", city="Dhaka")
    check(
        "venue-preference rollup filters by city",
        code == 200 and all(v["city"] == "Dhaka" for v in venueprefs),
        str(code),
    )

    code, lt = get("/api/analytics/long-tail")
    check("long-tail endpoint returns thresholds and split", code == 200 and "split" in lt, str(code))
    code, mix = get("/api/analytics/language-mix")
    check("language-mix non-empty", code == 200 and len(mix) > 0, str(code))

    # ---- research --------------------------------------------------------
    print("\nresearch")
    code, val = get("/api/research/validation")
    check(
        "validation reports direction-1 pass rate 1.0",
        code == 200 and val["direction1_precision"]["pass_rate"] == 1.0,
        str(val["direction1_precision"].get("pass_rate") if code == 200 else code),
    )
    check(
        "validation reports 10 under-coverage preferences",
        val["direction2_coverage"]["under_coverage"] == 10,
        str(val["direction2_coverage"].get("under_coverage")),
    )
    check(
        "manual sample is tracked (50 pairs)",
        val["manual_review_sample"]["total_pairs"] == 50,
        str(val["manual_review_sample"]),
    )

    code, unlabelled = get("/api/research/validation/sample", labelled=False)
    check("unlabelled sample filter returns 50", code == 200 and len(unlabelled) == 50, str(len(unlabelled)))

    code, sens = get("/api/research/sensitivity")
    check(
        "sensitivity recommends a minimum corpus size",
        code == 200 and sens["recommended_min_corpus_size"] == 538,
        str(sens.get("recommended_min_corpus_size")),
    )
    code, sensmap = get("/api/research/sensitivity/mappings", sample_size=538)
    check("sensitivity mappings filter by rung", code == 200 and len(sensmap) > 0, str(code))

    code, tests = get("/api/research/statistical-tests")
    check("statistical tests carried through", code == 200 and tests["available"] is True, str(code))

    # ---- discovery -------------------------------------------------------
    print("\ndiscovery")
    code, hits = get("/api/search", q="beach")
    check("search returns multi-kind hits", code == 200 and len({h["kind"] for h in hits}) > 1, str(code))
    code, _ = get("/api/search", q="a")
    check("search rejects a 1-char query", code == 422, str(code))

    code, recs = get("/api/recommend", preferences="P02", limit=5)
    check(
        "recommend ranks places with evidence for P02",
        code == 200 and len(recs) > 0 and all("P02" in r["matched_preferences"] for r in recs),
        str(code),
    )
    check(
        "recommend scores are sorted descending",
        all(recs[i]["match_score"] >= recs[i + 1]["match_score"] for i in range(len(recs) - 1)),
        str([r["match_score"] for r in recs]),
    )
    code, multi = get("/api/recommend", preferences="P02,P03", limit=10)
    check("multi-preference recommend works", code == 200 and len(multi) > 0, str(code))
    code, norec = get("/api/recommend", limit=3)
    check("recommend without preferences falls back to rating", code == 200 and len(norec) == 3, str(code))
    code, err = get("/api/recommend", preferences="P99")
    check("recommend rejects unknown preference ids", code == 400, str(code))
    code, hotels_only = get("/api/recommend", place_kind="accommodation", limit=5)
    check(
        "recommend respects place_kind",
        code == 200 and all(r["place_kind"] == "accommodation" for r in hotels_only),
        str(code),
    )

    code, cmp = get("/api/compare", places="Lalbagh Fort,Ahsan Manzil Museum")
    check(
        "compare returns both places and shared preferences",
        code == 200 and len(cmp["places"]) == 2 and "P03" in cmp["shared_preferences"],
        str(cmp.get("shared_preferences") if code == 200 else code),
    )
    code, _ = get("/api/compare", places="Lalbagh Fort")
    check("compare rejects a single place", code == 400, str(code))

    # ---- docs ------------------------------------------------------------
    print("\ndocs")
    r = client.get("/openapi.json")
    check("OpenAPI schema builds", r.status_code == 200, str(r.status_code))
    route_count = len(r.json().get("paths", {}))
    check("OpenAPI documents every route", route_count >= 25, f"{route_count} paths")
    r = client.get("/", follow_redirects=False)
    check("/ redirects to /docs", r.status_code in (302, 307), str(r.status_code))

    # ---- summary ---------------------------------------------------------
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All Phase 8 API smoke tests passed.")


if __name__ == "__main__":
    main()
