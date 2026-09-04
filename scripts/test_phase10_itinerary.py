"""Phase 10 — smoke tests for the itinerary builder and the comparison tool.

Runs the API in-process against the real built database (no network, no LLM).
Checks that plans are internally consistent (day numbering, no repeated stop,
travel levels matching the geography), that every claim in a plan is backed by
rows in the database, and that the comparison block agrees with the raw stats
it is derived from.

Run:
    .venv/bin/python scripts/test_phase10_itinerary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

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


def plan(**params) -> dict:
    r = client.get("/api/itinerary", params=params)
    check(f"GET /api/itinerary {params} -> 200", r.status_code == 200, r.text[:200])
    return r.json() if r.status_code == 200 else {}


def activities(body: dict) -> list[dict]:
    return [a for d in body.get("days", []) for a in d.get("activities", [])]


# ---------------------------------------------------------------------------
# Itinerary structure
# ---------------------------------------------------------------------------
def test_structure() -> None:
    print("\nitinerary — structure")
    body = plan(days=5, preferences="P02,P03")
    days = body["days"]
    check("returns exactly the requested number of days", len(days) == 5, str(len(days)))
    check(
        "days are numbered 1..n in order",
        [d["day"] for d in days] == list(range(1, 6)),
        str([d["day"] for d in days]),
    )
    acts = activities(body)
    ids = [a["place_id"] for a in acts]
    check("no place is scheduled twice", len(ids) == len(set(ids)), str(ids))
    check(
        "summary counts match the days",
        body["summary"]["total_activities"] == len(acts)
        and body["summary"]["unique_places"] == len(set(ids)),
        str(body["summary"]),
    )
    check(
        "planned_days counts only days with activities",
        body["summary"]["planned_days"] == sum(1 for d in days if d["activities"]),
        str(body["summary"]["planned_days"]),
    )
    check("day 1 is the trip start", days[0]["travel_level"] == "start", days[0]["travel_level"])
    check(
        "every activity carries a reason",
        all(a["why"] for a in acts),
        str([a["place_name"] for a in acts if not a["why"]]),
    )
    check(
        "every activity is an attraction, not a hotel",
        all(a["category"] != "hotel" for a in acts),
        str([a["category"] for a in acts]),
    )


def test_travel_levels() -> None:
    print("\nitinerary — travel levels follow the geography")
    body = plan(days=7)
    days = body["days"]
    ok = True
    detail = ""
    for prev, cur in zip(days, days[1:]):
        if not cur["activities"]:
            continue
        if prev["base_city"] == cur["base_city"]:
            expected = "same_city"
        elif prev["district"] == cur["district"]:
            expected = "same_district"
        elif prev["division"] == cur["division"]:
            expected = "same_division"
        else:
            expected = "cross_division"
        if cur["travel_level"] != expected:
            ok = False
            detail = f"day {cur['day']}: {cur['travel_level']} != {expected}"
    check("travel_level matches city/district/division of consecutive days", ok, detail)
    check(
        "every day past the first explains its travel",
        all(d["travel_note"] for d in days[1:]),
        str([d["day"] for d in days[1:] if not d["travel_note"]]),
    )
    check(
        "transfers counted only for real moves",
        body["summary"]["transfers"]
        == sum(1 for d in days if d["travel_level"] in ("same_division", "cross_division")),
        str(body["summary"]["transfers"]),
    )


def test_pace() -> None:
    print("\nitinerary — pace controls activities per day")
    caps = {"relaxed": 1, "standard": 2, "packed": 3}
    for pace, cap in caps.items():
        body = plan(days=3, pace=pace)
        per_day = [len(d["activities"]) for d in body["days"]]
        check(
            f"pace={pace} never exceeds {cap} activities/day",
            all(n <= cap for n in per_day),
            str(per_day),
        )
    relaxed = plan(days=3, pace="relaxed")
    packed = plan(days=3, pace="packed")
    check(
        "packed schedules at least as much as relaxed",
        packed["summary"]["total_activities"] >= relaxed["summary"]["total_activities"],
        f"{packed['summary']['total_activities']} vs {relaxed['summary']['total_activities']}",
    )


def test_evidence() -> None:
    print("\nitinerary — evidence is real and matches the database")
    body = plan(days=4, preferences="P02")
    acts = activities(body)
    check("preference filter returns places", len(acts) > 0, str(len(acts)))
    check(
        "every activity has evidence for the requested preference",
        all(any(e["preference_id"] == "P02" for e in a["matched_preferences"]) for a in acts),
        str([(a["place_name"], a["matched_preferences"]) for a in acts]),
    )
    check(
        "evidence_review_count equals the sum of its preference rows",
        all(
            a["evidence_review_count"] == sum(e["review_count"] for e in a["matched_preferences"])
            for a in acts
        ),
        "mismatch",
    )
    check(
        "covered_preferences reports P02",
        body["summary"]["covered_preferences"] == ["P02"]
        and body["summary"]["preference_coverage"] == 1.0,
        str(body["summary"]),
    )

    # Cross-check one activity against the place endpoint it is derived from.
    first = acts[0]
    detail = client.get(f"/api/places/{first['place_id']}").json()
    check(
        "activity stats match /api/places",
        detail["place"]["review_count"] == first["review_count"]
        and detail["place"]["avg_review_rating"] == first["avg_rating"],
        f"{detail['place']['review_count']}/{first['review_count']}",
    )
    rollup = client.get(
        "/api/analytics/venue-preferences", params={"place_id": first["place_id"]}
    ).json()
    by_id = {r["preference_id"]: r["review_count"] for r in rollup}
    check(
        "matched preference counts match the venue rollup",
        all(by_id.get(e["preference_id"]) == e["review_count"] for e in first["matched_preferences"]),
        f"{by_id} vs {first['matched_preferences']}",
    )
    snippets = [a for a in acts if a["review_snippet"]]
    check("at least one activity quotes a real review", len(snippets) > 0, str(len(snippets)))


def test_filters() -> None:
    print("\nitinerary — filters")
    body = plan(days=3, division="Sylhet")
    divisions = {a["division"] for a in activities(body)}
    check("division filter is respected", divisions <= {"Sylhet"}, str(divisions))

    body = plan(days=4, exclude_city="Cox's Bazar")
    cities = {a["city"] for a in activities(body)}
    check("exclude_city is respected", "Cox's Bazar" not in cities, str(cities))

    body = plan(days=3, city="Dhaka", preferences="P03")
    check(
        "city anchor starts the trip there",
        body["days"][0]["base_city"] == "Dhaka",
        body["days"][0]["base_city"],
    )

    body = plan(days=4, max_regions=1)
    check(
        "max_regions=1 keeps the trip in one division",
        len({a["division"] for a in activities(body)}) <= 1,
        str({a["division"] for a in activities(body)}),
    )

    body = plan(days=2, include_stays=False)
    check(
        "include_stays=false suggests no hotel",
        all(d["stay"] is None for d in body["days"]),
        str([d["stay"] for d in body["days"]]),
    )

    body = plan(days=2, include_stays=True)
    stays = [d["stay"] for d in body["days"] if d["stay"]]
    check("include_stays suggests hotels", len(stays) > 0, str(len(stays)))
    if stays:
        hotel = client.get(f"/api/places/{stays[0]['place_id']}").json()
        check(
            "suggested stay really is an accommodation",
            hotel["place"]["place_kind"] == "accommodation",
            str(hotel["place"]["place_kind"]),
        )


def test_degradation() -> None:
    print("\nitinerary — honest degradation")
    body = plan(days=14, pace="packed")
    days = body["days"]
    check("still returns 14 days", len(days) == 14, str(len(days)))
    empty = [d["day"] for d in days if not d["activities"]]
    filled = [d["day"] for d in days if d["activities"]]
    check(
        "unfillable days are pushed to the end of the trip",
        not filled or not empty or min(empty) > max(filled),
        f"filled={filled} empty={empty}",
    )
    check(
        "warns when the corpus cannot fill the trip",
        any("could be filled" in w for w in body["warnings"]),
        str(body["warnings"]),
    )
    check(
        "free days explain themselves",
        all(d["travel_note"] and d["notes"] for d in days if not d["activities"]),
        str(empty),
    )

    body = plan(days=3, min_reviews=999)
    check(
        "impossible filters return an empty plan, not an error",
        body["summary"]["total_activities"] == 0 and body["days"] == [],
        str(body["summary"]),
    )
    check("empty plan explains why", len(body["warnings"]) > 0, str(body["warnings"]))

    body = plan(days=3, city="Sylhet")
    check(
        "a city with no reviewed attraction widens to its division",
        any("widened" in w for w in body["warnings"]) or body["summary"]["total_activities"] > 0,
        str(body["warnings"]),
    )

    r = client.get("/api/itinerary", params={"days": 3, "preferences": "P99"})
    check("unknown preference id -> 400", r.status_code == 400, str(r.status_code))
    r = client.get("/api/itinerary", params={"days": 0})
    check("days=0 -> 422", r.status_code == 422, str(r.status_code))
    r = client.get("/api/itinerary", params={"days": 99})
    check("days above the cap -> 422", r.status_code == 422, str(r.status_code))
    r = client.get("/api/itinerary", params={"pace": "sprint"})
    check("unknown pace -> 422", r.status_code == 422, str(r.status_code))


def test_post_and_options() -> None:
    print("\nitinerary — POST body and form options")
    payload = {"days": 3, "preferences": "P02", "pace": "relaxed", "include_stays": True}
    r = client.post("/api/itinerary", json=payload)
    check("POST /api/itinerary -> 200", r.status_code == 200, r.text[:200])
    posted = r.json()
    got = client.get("/api/itinerary", params=payload).json()
    check(
        "POST and GET produce the same plan",
        [a["place_id"] for a in activities(posted)] == [a["place_id"] for a in activities(got)],
        "differs",
    )
    check(
        "the plan echoes the request it was built from",
        posted["request"]["days"] == 3 and posted["request"]["pace"] == "relaxed",
        str(posted["request"]),
    )
    r = client.post("/api/itinerary", json={"days": 3, "pace": "sprint"})
    check("POST rejects an invalid pace", r.status_code == 422, str(r.status_code))

    r = client.get("/api/itinerary/options")
    check("GET /api/itinerary/options -> 200", r.status_code == 200, str(r.status_code))
    options = r.json()
    prefs = {p["preference_id"] for p in options["preferences"]}
    api_prefs = {p["preference_id"] for p in client.get("/api/preferences").json()}
    check("options list every preference in the taxonomy", prefs == api_prefs, str(prefs ^ api_prefs))
    check("options list cities and divisions", options["cities"] and options["divisions"], str(options))
    check(
        "options report the pace ladder",
        {p["value"] for p in options["pace"]} == {"relaxed", "standard", "packed"},
        str(options["pace"]),
    )
    check(
        "options count attractions and accommodations",
        options["attraction_count"] > 0 and options["accommodation_count"] > 0,
        str(options),
    )


# ---------------------------------------------------------------------------
# Comparison tool
# ---------------------------------------------------------------------------
def test_comparison() -> None:
    print("\ncompare — enriched comparison block")
    r = client.get("/api/compare", params={"places": "Lalbagh Fort,Ahsan Manzil Museum"})
    check("GET /api/compare -> 200", r.status_code == 200, str(r.status_code))
    body = r.json()
    check("keeps the Phase 8 keys", {"places", "shared_preferences"} <= set(body), str(body.keys()))
    comparison = body["comparison"]
    metrics = {m["metric"]: m for m in comparison["metrics"]}
    check(
        "reports the expected metric rows",
        {
            "avg_rating",
            "review_count",
            "positive_share",
            "negative_share",
            "preference_breadth",
            "evidence_share",
        }
        <= set(metrics),
        str(set(metrics)),
    )
    names = [p["place_name"] for p in body["places"]]
    check(
        "every metric has a value per place",
        all(set(m["values"]) == set(names) for m in comparison["metrics"]),
        str(names),
    )

    rating = metrics["avg_rating"]
    from_stats = {p["place_name"]: p["avg_review_rating"] for p in body["places"]}
    check("avg_rating values come from the place stats", rating["values"] == from_stats, str(rating))
    best = max(v for v in from_stats.values() if v is not None)
    winners = [k for k, v in from_stats.items() if v == best]
    check(
        "rating leader is the highest rated place (None on a tie)",
        rating["leader"] == (winners[0] if len(winners) == 1 else None),
        str(rating["leader"]),
    )
    negative = metrics["negative_share"]
    check("lower-is-better metrics are flagged", negative["higher_is_better"] is False, "flag")

    breadth = metrics["preference_breadth"]
    check(
        "preference breadth matches the rollup rows",
        breadth["values"] == {p["place_name"]: float(len(p["preferences"])) for p in body["places"]},
        str(breadth["values"]),
    )
    check("summary verdict is a sentence", comparison["summary"].endswith("."), comparison["summary"])
    check(
        "shared preference labels line up with the ids",
        len(body["shared_preference_labels"]) == len(body["shared_preferences"]),
        str(body["shared_preference_labels"]),
    )

    samples = body["places"][0]["sample_reviews"]
    check("supporting reviews are attached", "positive" in samples and "critical" in samples, str(samples.keys()))
    check(
        "positive samples really are positive",
        all(s["review_rating"] >= 4 for s in samples["positive"]),
        str([s["review_rating"] for s in samples["positive"]]),
    )
    check(
        "sample reviews belong to the place",
        all(s["place_id"] == body["places"][0]["place_id"] for s in samples["positive"]),
        "wrong place",
    )

    r = client.get("/api/compare", params={"places": "Lalbagh Fort,Ahsan Manzil Museum", "sample_reviews": 0})
    check(
        "sample_reviews=0 omits the quotes",
        r.status_code == 200 and "sample_reviews" not in r.json()["places"][0],
        str(r.status_code),
    )
    r = client.get("/api/compare", params={"places": "Lalbagh Fort,Lalbagh Fort"})
    check("comparing a place with itself -> 400", r.status_code == 400, str(r.status_code))
    r = client.get("/api/compare", params={"places": "Lalbagh Fort,Nowhere Fort"})
    check("unknown place -> 404", r.status_code == 404, str(r.status_code))


# ---------------------------------------------------------------------------
# Chatbot integration
# ---------------------------------------------------------------------------
def test_chat_itinerary() -> None:
    print("\nchat — itinerary intent")

    def ask(message: str) -> dict:
        r = client.post("/api/chat", json={"message": message})
        check(f"'{message}' -> 200", r.status_code == 200, str(r.status_code))
        return r.json()

    body = ask("plan a 4 day trip in Sylhet")
    check("plans a trip", body["intent"] == "itinerary", body["intent"])
    check("reads the day count", body["entities"]["days"] == 4, str(body["entities"]))
    check("reads the city", body["entities"]["city"] == "Sylhet", str(body["entities"]))
    check("returns a plan payload", body["results"] and "days" in body["results"][0], "no plan")

    body = ask("build me an itinerary for a relaxed week")
    check("'a week' means 7 days", body["entities"]["days"] == 7, str(body["entities"]))
    check("'relaxed' sets the pace", body["entities"]["pace"] == "relaxed", str(body["entities"]))

    body = ask("plan a relaxed week around Cox's Bazar")
    check(
        "'plan a ... week' still reads as a trip request",
        body["intent"] == "itinerary" and body["entities"]["days"] == 7,
        f"{body['intent']} {body['entities']}",
    )

    body = ask("plan a weekend in Sylhet")
    check(
        "'weekend' means 2 days",
        body["intent"] == "itinerary" and body["entities"]["days"] == 2,
        f"{body['intent']} {body['entities']}",
    )

    body = ask("tell me about Sundarbans")
    check("a plain place question is not hijacked into a plan", body["intent"] == "place_info", body["intent"])
    body = ask("hotels in Sylhet")
    check("a hotel question is not hijacked into a plan", body["intent"] != "itinerary", body["intent"])

    body = ask("3 days in Dhaka")
    check("a bare duration still plans a trip", body["intent"] == "itinerary", body["intent"])

    body = ask("compare Kaptai Lake and Ratargul Swamp Forest over 3 days")
    check(
        "an explicit compare still wins over a duration",
        body["intent"] == "compare",
        body["intent"],
    )

    body = ask("plan a trip for 99 days")
    check(
        "an absurd duration is clamped, not rejected",
        body["intent"] == "itinerary" and body["entities"]["days"] == 14,
        str(body["entities"]),
    )


def main() -> None:
    print("Phase 10 — itinerary builder & comparison tool tests")
    health = client.get("/health").json()
    if health.get("database") != "ready":
        print(f"\nDatabase not ready: {health.get('detail')}")
        sys.exit(1)

    test_structure()
    test_travel_levels()
    test_pace()
    test_evidence()
    test_filters()
    test_degradation()
    test_post_and_options()
    test_comparison()
    test_chat_itinerary()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 10 itinerary/comparison tests passed.")


if __name__ == "__main__":
    main()
