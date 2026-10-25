"""Tests for how every review gets a topic and how near-tied topics map to two preferences.

Run:
    .venv/bin/python scripts/test_topic_assignment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def test_reassign_outliers() -> None:
    print("\nreassigning BERTopic outliers")
    import run_phase3_huggingface_bertopic as p3

    # Two tight clusters on the x and y axes, plus outliers leaning towards each.
    emb = np.array([[1, 0.0], [1, 0.1], [0.9, 0.0], [0.0, 1], [0.1, 1], [0.0, 0.9],
                    [1, 0.3], [0.2, 1], [0.7, 0.7]], dtype=float)
    topics = np.array([0, 0, 0, 1, 1, 1, -1, -1, -1])
    final, sim, moved = p3.reassign_outliers(emb, topics)
    check("no outlier is left", not (final == -1).any(), str(final))
    check("an outlier near cluster 0 joins cluster 0", final[6] == 0, str(final))
    check("an outlier near cluster 1 joins cluster 1", final[7] == 1, str(final))
    check("only the outliers are marked reassigned", moved.tolist() == [False] * 6 + [True] * 3, str(moved))
    check("clustered reviews keep their topic", final[:6].tolist() == topics[:6].tolist(), str(final))
    check("similarity is a cosine in [-1, 1]", bool(((sim >= -1) & (sim <= 1.0000001)).all()), str(sim))
    check("the input array is not modified", topics[6] == -1, str(topics))

    only_outliers, s2, m2 = p3.reassign_outliers(emb[:3], np.array([-1, -1, -1]))
    check("with no real topic there is nothing to join (stays -1)", (only_outliers == -1).all(), str(only_outliers))


def test_bangla_tokens() -> None:
    print("\nBangla topic keywords")
    from sklearn.feature_extraction.text import CountVectorizer

    import topic_embedding as te

    vec = CountVectorizer(token_pattern=te.TOKEN_PATTERN, stop_words=te.STOP_WORDS)
    vec.fit(["লালবাগ কেল্লা খুব সুন্দর জায়গা", "Lalbagh fort is a very nice place"])
    vocab = set(vec.get_feature_names_out())
    check("Bangla words with vowel signs stay whole", {"লালবাগ", "কেল্লা", "সুন্দর"} <= vocab, str(sorted(vocab)))
    check("a Bangla function word is dropped", "খুব" not in vocab, str(sorted(vocab)))
    check("English keywords still work", "lalbagh" in vocab and "fort" in vocab, str(sorted(vocab)))
    check("an English stop word is dropped", "is" not in vocab, str(sorted(vocab)))


def test_secondary_mapping() -> None:
    print("\nnear-tied topics map to two preferences")
    import run_phase5_bidirectional_validation as p5

    mapping = pd.DataFrame(
        {
            "topic_id": [0, 1, 2, 3],
            "preference_id": ["P01", "P02", "P03", "P01"],
            "similarity": [0.80, 0.70, 0.30, 0.75],
            "second_best_preference_id": ["P02", "P01", "P04", "P03"],
            "second_best_similarity": [0.50, 0.68, 0.28, 0.45],
        }
    )
    precision = p5.run_direction1_precision(mapping)
    sec = p5.build_secondary_mapping(precision)
    check("a clear winner gets no second preference", 0 not in sec["topic_id"].tolist(), str(sec))
    check("a near tie gets its runner-up", sec.loc[sec["topic_id"] == 1, "preference_id"].tolist() == ["P01"], str(sec))
    check(
        "a low-similarity topic is not widened",
        2 not in sec["topic_id"].tolist(),
        "a topic that barely matches anything should be reviewed, not spread over two preferences",
    )
    check("the runner-up must clear tau_sim", 3 not in sec["topic_id"].tolist(), str(sec))
    check("rank is recorded", set(sec["mapping_rank"]) == {2}, str(sec))

    prefs = pd.DataFrame({"preference_id": ["P01", "P02", "P03", "P04"]})
    base = p5.run_direction2_coverage(mapping, prefs)
    widened = p5.run_direction2_coverage(mapping, prefs, sec)
    count = lambda df, p: int(df.loc[df["preference_id"] == p, "mapped_topic_count"].iloc[0])  # noqa: E731
    check("coverage counts the runner-up mapping", count(widened, "P01") == count(base, "P01") + 1,
          f"{count(base, 'P01')} -> {count(widened, 'P01')}")
    check("the primary count is kept separately",
          int(widened.loc[widened["preference_id"] == "P01", "primary_topic_count"].iloc[0]) == count(base, "P01"))


def test_database_and_api() -> None:
    print("\nthe database and API use both mappings")
    import sqlite3

    from fastapi.testclient import TestClient

    from backend.main import app

    data = REPO_ROOT / "data"
    secondary_path = data / "topic_preference_secondary.csv"
    if not secondary_path.exists() or not (data / "touristinbd.db").exists():
        check("built artifacts present", False, "run Phase 5 and build_phase8_database.py first")
        return
    secondary = pd.read_csv(secondary_path)
    conn = sqlite3.connect(data / "touristinbd.db")
    ranks = dict(conn.execute("SELECT mapping_rank, COUNT(*) FROM topic_preference_map GROUP BY mapping_rank"))
    topics = conn.execute("SELECT COUNT(*) FROM topics WHERE topic_id >= 0").fetchone()[0]
    check("every topic has exactly one primary mapping", ranks.get(1) == topics, f"{ranks} vs {topics} topics")
    check("every near-tied topic has a second mapping", ranks.get(2, 0) == len(secondary), f"{ranks} vs {len(secondary)}")

    total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    listed = conn.execute("SELECT COUNT(*) FROM v_review_preference").fetchone()[0]
    check("the review list view has one row per review (no duplicates)", listed == total, f"{listed} vs {total}")
    wide = conn.execute("SELECT COUNT(*) FROM v_review_preference_all").fetchone()[0]
    expected_wide = conn.execute(
        "SELECT COUNT(*) FROM reviews r JOIN topic_preference_map m ON m.topic_id = r.topic_id"
    ).fetchone()[0]
    check("the evidence view repeats a review under each preference it expresses",
          wide >= total and wide == expected_wide + conn.execute("SELECT COUNT(*) FROM reviews WHERE topic_id IS NULL OR topic_id NOT IN (SELECT topic_id FROM topic_preference_map)").fetchone()[0],
          f"{wide}")
    unclassified = conn.execute("SELECT COUNT(*) FROM reviews WHERE topic_id IS NULL OR topic_id = -1").fetchone()[0]
    check("no review is left without a topic", unclassified == 0, f"{unclassified} review(s) unclassified")
    no_pref = conn.execute("SELECT COUNT(*) FROM preferences WHERE preference_id NOT IN (SELECT preference_id FROM topic_preference_map)").fetchone()[0]
    check("every preference has at least one topic behind it", no_pref == 0, f"{no_pref} preference(s) have no evidence")

    client = TestClient(app)
    row = secondary.iloc[0]
    body = client.get("/api/reviews", params={"preference_id": row["preference_id"], "topic_id": int(row["topic_id"]), "limit": 1}).json()
    check("filtering reviews by a preference includes its runner-up topics", body["total"] > 0, str(body.get("total")))
    topic_ids = {t["topic_id"] for t in client.get("/api/preferences/" + row["preference_id"]).json()["topics"]}
    check("a preference lists the topics that reach it as runner-up", int(row["topic_id"]) in topic_ids, str(topic_ids))
    listing = client.get("/api/topics").json()
    check("the topic list has one row per topic", len(listing) == len({t["topic_id"] for t in listing}), str(len(listing)))
    page = client.get("/api/reviews", params={"limit": 50}).json()
    ids = [r["review_id"] for r in page["items"]]
    check("a review never appears twice in a list", len(ids) == len(set(ids)))
    check("review totals equal the corpus", page["total"] == total, f"{page['total']} vs {total}")


def main() -> None:
    test_reassign_outliers()
    test_bangla_tokens()
    test_secondary_mapping()
    test_database_and_api()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for line in FAILED:
            print("  -", line)
        sys.exit(1)
    print("All topic assignment tests passed.")


if __name__ == "__main__":
    main()
