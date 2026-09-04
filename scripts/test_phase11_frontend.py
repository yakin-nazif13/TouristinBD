"""Phase 11 — tests that the frontend and the API cannot drift apart.

The interface is plain HTML/CSS/JS with no build step, so nothing would
otherwise catch a renamed endpoint or a mistyped element id until the page is
opened. These tests read `frontend/index.html`, pull out every API path and DOM
id it depends on, and check each one against the running app and the document
itself.

Run:
    .venv/bin/python scripts/test_phase11_frontend.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)
INDEX = REPO_ROOT / "frontend" / "index.html"
HTML = INDEX.read_text(encoding="utf-8")

PASSED: list[str] = []
FAILED: list[str] = []

# Sample query strings so every referenced endpoint is actually exercised, not
# just matched against the schema.
SAMPLE_PARAMS = {
    "/api/places": "?limit=5&sort=name&order=asc",
    "/api/search": "?q=beach&limit_per_kind=3",
    "/api/compare": "?places=Lalbagh Fort,Ahsan Manzil Museum&sample_reviews=2",
    "/api/itinerary": "?days=3&pace=standard&include_stays=true&preferences=P02",
}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def api_paths() -> tuple[set[str], set[str]]:
    """Literal and templated paths the page passes to its `api()` helper."""
    literal = set(re.findall(r"api\(\s*'(/[^']+)'", HTML))
    templated = set()
    for raw in re.findall(r"api\(\s*`(/[^`]+)`", HTML):
        templated.add(raw.split("${")[0].rstrip("/"))
    return literal, templated


def test_served() -> None:
    print("\nfrontend — served by the API")
    r = client.get("/app/")
    check("GET /app/ serves the page", r.status_code == 200, str(r.status_code))
    check("served page is the file on disk", r.text.strip() == HTML.strip(), "content differs")
    r = client.get("/", follow_redirects=False)
    check(
        "/ redirects to the interface",
        r.status_code in (302, 307) and r.headers.get("location") == "/app/",
        f"{r.status_code} {r.headers.get('location')}",
    )
    r = client.get("/docs")
    check("API docs still reachable", r.status_code == 200, str(r.status_code))


def test_endpoints_exist() -> None:
    print("\nfrontend — every endpoint it calls exists and answers")
    schema = client.get("/openapi.json").json()["paths"]
    literal, templated = api_paths()
    check("found the API calls in the page", len(literal) >= 8, str(sorted(literal)))

    for path in sorted(literal):
        base = path.split("?")[0]
        check(f"{base} is a documented route", base in schema, "not in the OpenAPI schema")
        if base == "/api/chat":
            r = client.post(base, json={"message": "hello"})
        else:
            r = client.get(base + SAMPLE_PARAMS.get(base, ""))
        check(f"{base} answers 200", r.status_code == 200, str(r.status_code))

    for prefix in sorted(templated):
        matches = [p for p in schema if p.startswith(prefix + "/")]
        check(f"{prefix}/<id> is a documented route", bool(matches), "no matching path template")

    # The chatbot drives two tabs, so its response contract matters here too.
    body = client.post("/api/chat", json={"message": "plan a 3 day trip in Dhaka"}).json()
    check(
        "chat replies carry the fields the page renders",
        {"intent", "reply", "results", "suggestions"} <= set(body),
        str(sorted(body)),
    )
    check(
        "itinerary replies embed a plan the page can outline",
        body["intent"] == "itinerary" and "days" in body["results"][0],
        body["intent"],
    )


def test_dom_ids() -> None:
    print("\nfrontend — every element the script touches exists")
    ids = set(re.findall(r"getElementById\(\s*'([^']+)'\s*\)", HTML))
    ids |= set(re.findall(r"querySelector(?:All)?\(\s*['\"]#([A-Za-z0-9_-]+)", HTML))
    check("found the element references", len(ids) >= 15, str(len(ids)))
    declared = set(re.findall(r'\bid="([^"]+)"', HTML))
    missing = sorted(ids - declared)
    check("no script reference points at a missing element", not missing, str(missing))

    for required in ("chatWindow", "itineraryOutput", "compareOutput", "exploreOutput", "statGrid"):
        check(f"#{required} is present", required in declared, "missing")

    # Skip the one in a template literal (`[data-tab="${name}"]`), which is a
    # selector built at runtime rather than a button in the markup.
    tabs = {t for t in re.findall(r'data-tab="([^"]+)"', HTML) if "${" not in t}
    panels = {i[4:] for i in declared if i.startswith("tab-")}
    check("every tab button has a panel", tabs == panels, f"{tabs} vs {panels}")
    listed = re.search(r"const TABS = \[([^\]]+)\]", HTML)
    check(
        "the TABS list matches the buttons",
        listed is not None and {t.strip().strip("'\"") for t in listed.group(1).split(",")} == tabs,
        listed.group(1) if listed else "TABS not found",
    )


def test_no_mock_data() -> None:
    print("\nfrontend — no mock data left behind")
    for marker in ("avgCostPerDay", "MOCK", "made up", "mock-data", "reviewSnippet:"):
        check(f"'{marker}' is gone from the page", marker not in HTML, "still present")
    check(
        "the demo banner is replaced by a live-data flag",
        'id="statusFlag"' in HTML and "DEMO MODE" not in HTML,
        "banner not updated",
    )
    check(
        "the page falls back to the local API when opened from disk",
        "http://127.0.0.1:8000" in HTML and "resolveApiBase" in HTML,
        "no fallback logic",
    )
    check(
        "an offline API is reported instead of being papered over",
        "apiBanner" in HTML and "API OFFLINE" in HTML,
        "no offline handling",
    )
    check(
        "user-visible values are HTML-escaped",
        HTML.count("escapeHtml(") > 30,
        f"only {HTML.count('escapeHtml(')} escape calls",
    )


def test_render_contracts() -> None:
    print("\nfrontend — payload fields the renderers read are really returned")
    plan = client.get("/api/itinerary?days=3&preferences=P02").json()
    for field in ("planned_days", "total_activities", "transfers", "avg_activity_rating",
                  "evidence_reviews", "preference_coverage", "cities", "divisions"):
        check(f"plan summary has {field}", field in plan["summary"], str(sorted(plan["summary"])))
    day = next(d for d in plan["days"] if d["activities"])
    for field in ("day", "base_city", "travel_note", "activities", "stay", "notes"):
        check(f"plan day has {field}", field in day, str(sorted(day)))
    activity = day["activities"][0]
    for field in ("place_name", "city", "district", "category", "avg_rating", "review_count",
                  "why", "matched_preferences", "review_snippet"):
        check(f"plan activity has {field}", field in activity, str(sorted(activity)))

    cmp_body = client.get(
        "/api/compare?places=Lalbagh Fort,Ahsan Manzil Museum&sample_reviews=2"
    ).json()
    for field in ("places", "comparison", "shared_preference_labels", "distinct_preferences"):
        check(f"comparison has {field}", field in cmp_body, str(sorted(cmp_body)))
    for field in ("metrics", "summary", "top_preference"):
        check(f"comparison block has {field}", field in cmp_body["comparison"], "missing")
    metric = cmp_body["comparison"]["metrics"][0]
    for field in ("label", "values", "leader", "unit", "higher_is_better"):
        check(f"metric row has {field}", field in metric, str(sorted(metric)))

    options = client.get("/api/itinerary/options").json()
    for field in ("preferences", "cities", "divisions", "max_days"):
        check(f"itinerary options have {field}", field in options, str(sorted(options)))

    overview = client.get("/api/overview").json()
    for field in ("total_reviews", "total_places", "total_cities", "total_topics",
                  "total_preferences", "avg_rating", "reviews_by_source", "reviews_by_language"):
        check(f"overview has {field}", field in overview, str(sorted(overview)))

    long_tail = client.get("/api/analytics/long-tail").json()
    check(
        "long-tail payload carries thresholds and a split",
        "thresholds" in long_tail and "split" in long_tail and "topics" in long_tail,
        str(sorted(long_tail)),
    )


def main() -> None:
    print("Phase 11 — frontend/API contract tests")
    health = client.get("/health").json()
    if health.get("database") != "ready":
        print(f"\nDatabase not ready: {health.get('detail')}")
        sys.exit(1)

    test_served()
    test_endpoints_exist()
    test_dom_ids()
    test_no_mock_data()
    test_render_contracts()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 11 frontend tests passed.")


if __name__ == "__main__":
    main()
