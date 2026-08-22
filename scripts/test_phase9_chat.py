"""Phase 9 — smoke tests for the retrieval-based chatbot (`POST /api/chat`).

No network/LLM involved, so these just exercise intent routing against the
real built database. Run after `scripts/build_phase8_database.py`.

Run:
    .venv/bin/python scripts/test_phase9_chat.py
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


def ask(message: str, limit: int = 5) -> dict:
    r = client.post("/api/chat", json={"message": message, "limit": limit})
    check(f"'{message}' -> 200", r.status_code == 200, str(r.status_code))
    return r.json()


def main() -> None:
    print("Phase 9 — chatbot smoke tests\n")

    body = ask("hello there")
    check("greeting: intent", body["intent"] == "greeting", body["intent"])
    check("greeting: has suggestions", len(body["suggestions"]) > 0, str(body))

    body = ask("thanks a lot")
    check("thanks: intent", body["intent"] == "thanks", body["intent"])

    body = ask("tell me about Sundarbans")
    check("place_info: intent", body["intent"] == "place_info", body["intent"])
    check(
        "place_info: resolves to a Sundarbans place",
        "Sundarbans" in body["entities"].get("place", ""),
        str(body["entities"]),
    )
    check("place_info: results non-empty", len(body["results"]) == 1, str(body["results"]))

    body = ask("what do people say about Ratargul Swamp Forest")
    check("reviews: intent", body["intent"] == "reviews", body["intent"])
    check(
        "reviews: entity is Ratargul",
        "Ratargul" in body["entities"].get("place", ""),
        str(body["entities"]),
    )

    body = ask("compare Kaptai Lake and Ratargul Swamp Forest")
    check("compare: intent", body["intent"] == "compare", body["intent"])
    check("compare: two places in entities", len(body["entities"].get("places", [])) == 2, str(body["entities"]))
    check("compare: result has shared_preferences key", "shared_preferences" in body["results"][0], str(body["results"]))

    body = ask("hotels in Sylhet")
    check(
        "recommend/city: intent is recommend or city_info",
        body["intent"] in ("recommend", "recommend_general", "city_info"),
        body["intent"],
    )

    body = ask("Cox's Bazar")
    check(
        "city_info or place_info for a bare city/place mention",
        body["intent"] in ("city_info", "place_info"),
        body["intent"],
    )
    check("bare mention: results non-empty", len(body["results"]) > 0, str(body))

    body = ask("best places to visit")
    check(
        "generic recommend: intent",
        body["intent"] in ("recommend_general", "recommend"),
        body["intent"],
    )
    check("generic recommend: results non-empty", len(body["results"]) > 0, str(body))

    body = ask("asdkjhasdkjh nonsense query xyz")
    check(
        "unknown/fallback: sensible intent for gibberish",
        body["intent"] in ("unknown", "search_fallback"),
        body["intent"],
    )

    body = ask("Lalbagh Fort")
    check("single place mention resolves", body["intent"] == "place_info", body["intent"])

    r = client.post("/api/chat", json={"message": "hi"})
    check("minimal payload accepted", r.status_code == 200, str(r.status_code))

    r = client.post("/api/chat", json={"message": ""})
    check("empty message rejected by validation", r.status_code == 422, str(r.status_code))

    r = client.post("/api/chat", json={})
    check("missing message field rejected", r.status_code == 422, str(r.status_code))

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All Phase 9 chatbot tests passed.")


if __name__ == "__main__":
    main()
