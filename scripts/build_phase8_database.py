"""
Phase 8 (part 1) — Build the SQLite database from the Phase 2-7 artifacts.

Design goals:
- Non-destructive: only reads `data/*.csv|json`, only writes `data/touristinbd.db`
  and `data/phase8_build_report.{md,json}`.
- Idempotent: rebuilds the DB from scratch every run, so re-running the earlier
  phases with more reviews and then re-running this script is always safe.
- Forgiving about schema drift: every input file is optional, and missing columns
  are filled with NULL rather than crashing. New places, topics, preferences,
  languages, sources or cities need no code change — they flow straight through.
- Aggregates live in SQL *views*, not copied tables, so they can never go stale
  relative to the rows in the DB.

Run:
    .venv/bin/python scripts/build_phase8_database.py
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
# TOURISTINBD_DATA_DIR lets the build (and the API, via backend/db.py) point at a
# different artifact directory — used by the rebuild tests and by deployments.
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
DB_PATH = DATA_DIR / "touristinbd.db"

OUT_REPORT_MD = DATA_DIR / "phase8_build_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase8_build_report.json"

# Bumped when the DB schema changes so the API can refuse a stale database.
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Input files. Everything here is optional; a missing file is reported, not fatal.
# ---------------------------------------------------------------------------
INPUTS = {
    "processed_reviews": DATA_DIR / "processed_reviews.csv",
    "reviews_with_topics": DATA_DIR / "reviews_with_topics.csv",
    "topics_summary": DATA_DIR / "topics_summary.csv",
    "stage1_interpretations": DATA_DIR / "stage1_topic_interpretations.csv",
    "preference_classification": DATA_DIR / "preference_classification.csv",
    "topic_preference_mapping": DATA_DIR / "topic_preference_mapping.csv",
    "long_tail_flags": DATA_DIR / "long_tail_flags.csv",
    "topic_preferences": DATA_DIR / "topic_preferences.csv",
    "phase5_precision": DATA_DIR / "phase5_direction1_precision_checks.csv",
    "phase5_coverage": DATA_DIR / "phase5_direction2_coverage_checks.csv",
    "phase5_recommendations": DATA_DIR / "phase5_recommendations.csv",
    "phase5_manual_sample": DATA_DIR / "phase5_manual_review_sample.csv",
    "phase6_metrics": DATA_DIR / "phase6_sensitivity_metrics.csv",
    "phase6_mappings": DATA_DIR / "phase6_sensitivity_mappings.csv",
    "phase7_statistical_tests": DATA_DIR / "phase7_statistical_tests.json",
    "place_geography": DATA_DIR / "place_geography.csv",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def load_csv(key: str, notes: list[str]) -> pd.DataFrame | None:
    path = INPUTS[key]
    if not path.exists():
        notes.append(f"missing optional input: {path.name} (skipped)")
        return None
    df = pd.read_csv(path)
    return df


def load_json(key: str, notes: list[str]) -> dict | None:
    path = INPUTS[key]
    if not path.exists():
        notes.append(f"missing optional input: {path.name} (skipped)")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def project(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return df with exactly `columns`, filling absent ones with NA.

    This is what makes the loader tolerant of upstream schema drift: an extra
    column upstream is dropped, a renamed/absent one becomes NULL.
    """
    out = pd.DataFrame(index=df.index)
    for col in columns:
        out[col] = df[col] if col in df.columns else pd.NA
    return out


def to_bool(series: pd.Series) -> pd.Series:
    """Normalize the various truthy spellings pandas/CSV round-trips produce."""
    truthy = {"true", "1", "1.0", "yes", "t"}
    falsy = {"false", "0", "0.0", "no", "f", "", "nan", "none"}

    def conv(v):
        if pd.isna(v):
            return None
        s = str(v).strip().lower()
        if s in truthy:
            return 1
        if s in falsy:
            return 0
        return None

    return series.map(conv)


def write_table(conn: sqlite3.Connection, name: str, df: pd.DataFrame) -> int:
    df.to_sql(name, conn, if_exists="append", index=False)
    return len(df)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
DROP VIEW  IF EXISTS v_place_stats;
DROP VIEW  IF EXISTS v_city_stats;
DROP VIEW  IF EXISTS v_dataset_overview;
DROP VIEW  IF EXISTS v_rating_distribution;
DROP VIEW  IF EXISTS v_temporal_volume;
DROP VIEW  IF EXISTS v_preference_frequency;
DROP VIEW  IF EXISTS v_city_preference_rollup;
DROP VIEW  IF EXISTS v_venue_preference_rollup;
DROP VIEW  IF EXISTS v_review_preference;

DROP TABLE IF EXISTS metadata;
DROP TABLE IF EXISTS sensitivity_mappings;
DROP TABLE IF EXISTS sensitivity_metrics;
DROP TABLE IF EXISTS validation_manual_sample;
DROP TABLE IF EXISTS validation_recommendations;
DROP TABLE IF EXISTS validation_coverage;
DROP TABLE IF EXISTS validation_precision;
DROP TABLE IF EXISTS long_tail_flags;
DROP TABLE IF EXISTS topic_preference_map;
DROP TABLE IF EXISTS preferences;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS places;

CREATE TABLE places (
    place_id         INTEGER PRIMARY KEY,
    place_name       TEXT NOT NULL UNIQUE,
    city             TEXT,
    district         TEXT,
    division         TEXT,
    category         TEXT,
    place_kind       TEXT,           -- attraction | accommodation
    source           TEXT,
    place_avg_rating REAL,
    source_url       TEXT,
    geo_resolved     INTEGER         -- 1 = matched place_geography.csv
);

CREATE TABLE topics (
    topic_id         INTEGER PRIMARY KEY,
    topic_name       TEXT,
    top_keywords     TEXT,
    review_count     INTEGER,
    corpus_share     REAL,
    interpreted_label TEXT,
    interpretation   TEXT,
    dimension_hint   TEXT
);

CREATE TABLE reviews (
    review_id        TEXT PRIMARY KEY,
    place_id         INTEGER REFERENCES places(place_id),
    topic_id         INTEGER REFERENCES topics(topic_id),
    source           TEXT,
    review_rating    REAL,
    review_text_clean TEXT,
    review_date      TEXT,
    review_month     TEXT,
    review_year      INTEGER,
    text_length      INTEGER,
    detected_language TEXT,
    platform_language_tag TEXT,
    traveler_type    TEXT,
    user_location    TEXT,
    nights_stayed    REAL,
    reviewer_num_reviews REAL,
    reviewer_is_local_guide INTEGER,
    review_likes     REAL,
    source_url       TEXT
);
CREATE INDEX idx_reviews_place    ON reviews(place_id);
CREATE INDEX idx_reviews_topic    ON reviews(topic_id);
CREATE INDEX idx_reviews_source   ON reviews(source);
CREATE INDEX idx_reviews_lang     ON reviews(detected_language);
CREATE INDEX idx_reviews_rating   ON reviews(review_rating);
CREATE INDEX idx_reviews_month    ON reviews(review_month);

CREATE TABLE preferences (
    preference_id    TEXT PRIMARY KEY,
    category         TEXT,
    subcategory      TEXT,
    preference_label TEXT,
    preference_description TEXT,
    preference_type  TEXT              -- mainstream | long_tail
);

CREATE TABLE topic_preference_map (
    topic_id         INTEGER PRIMARY KEY REFERENCES topics(topic_id),
    preference_id    TEXT REFERENCES preferences(preference_id),
    similarity       REAL,
    second_best_preference_id TEXT,
    second_best_similarity REAL,
    sim_gap          REAL,
    confidence       TEXT,
    needs_review     INTEGER,
    tau_sim          REAL
);
CREATE INDEX idx_tpm_pref ON topic_preference_map(preference_id);

CREATE TABLE long_tail_flags (
    topic_id         INTEGER PRIMARY KEY REFERENCES topics(topic_id),
    preference_id    TEXT,
    review_count     INTEGER,
    corpus_share     REAL,
    scarce           INTEGER,
    max_sim_to_abundant REAL,
    sdd              REAL,
    sdd_threshold    REAL,
    scarcity_threshold REAL,
    preference_type  TEXT,
    is_long_tail     INTEGER
);

CREATE TABLE validation_precision (
    topic_id         INTEGER PRIMARY KEY,
    interpreted_label TEXT,
    preference_id    TEXT,
    similarity       REAL,
    second_best_preference_id TEXT,
    second_best_similarity REAL,
    sim_gap          REAL,
    low_similarity_flag INTEGER,
    ambiguous_flag   INTEGER,
    precision_status TEXT
);

CREATE TABLE validation_coverage (
    preference_id    TEXT PRIMARY KEY,
    mapped_topic_count INTEGER,
    coverage_status  TEXT,
    coverage_action  TEXT
);

CREATE TABLE validation_recommendations (
    rec_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type             TEXT,
    target_id        TEXT,
    severity         TEXT,
    details          TEXT,
    suggested_action TEXT
);

CREATE TABLE validation_manual_sample (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_type        TEXT,
    topic_id         INTEGER,
    interpreted_label TEXT,
    preference_id    TEXT,
    preference       TEXT,
    similarity       REAL,
    human_label      TEXT
);

CREATE TABLE sensitivity_metrics (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_size      INTEGER,
    sample_fraction  REAL,
    min_topic_size   INTEGER,
    n_topics         INTEGER,
    n_preferences_covered INTEGER,
    n_preferences_total   INTEGER,
    coverage_rate    REAL,
    avg_similarity   REAL,
    high_confidence_rate REAL,
    mapped_preference_ids TEXT,
    jaccard_vs_previous REAL,
    run_type         TEXT
);

CREATE TABLE sensitivity_mappings (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_size      INTEGER,
    topic_id         INTEGER,
    topic_name       TEXT,
    review_count     INTEGER,
    preference_id    TEXT,
    preference       TEXT,
    category         TEXT,
    similarity       REAL,
    high_confidence  INTEGER
);

CREATE TABLE metadata (
    key              TEXT PRIMARY KEY,
    value            TEXT
);

-- ---------------------------------------------------------------------------
-- Views: every aggregate the API serves is derived here, so adding reviews and
-- rebuilding is enough to refresh all analytics.
-- ---------------------------------------------------------------------------

-- One row per review, carrying its topic and (if mapped) its preference.
CREATE VIEW v_review_preference AS
SELECT
    r.review_id,
    r.place_id,
    p.place_name,
    p.city,
    p.district,
    p.division,
    p.category,
    p.place_kind,
    r.source,
    r.review_rating,
    r.review_date,
    r.review_month,
    r.review_year,
    r.detected_language,
    r.text_length,
    r.topic_id,
    t.interpreted_label,
    m.preference_id,
    pr.preference_label,
    pr.category      AS preference_category,
    pr.subcategory   AS preference_subcategory,
    pr.preference_type,
    m.similarity     AS mapping_similarity,
    m.confidence     AS mapping_confidence
FROM reviews r
LEFT JOIN places  p  ON p.place_id = r.place_id
LEFT JOIN topics  t  ON t.topic_id = r.topic_id
LEFT JOIN topic_preference_map m ON m.topic_id = r.topic_id
LEFT JOIN preferences pr ON pr.preference_id = m.preference_id;

CREATE VIEW v_place_stats AS
SELECT
    p.place_id,
    p.place_name,
    p.city,
    p.district,
    p.division,
    p.category,
    p.place_kind,
    p.source,
    p.place_avg_rating,
    p.source_url,
    COUNT(r.review_id)                       AS review_count,
    ROUND(AVG(r.review_rating), 3)           AS avg_review_rating,
    SUM(CASE WHEN r.review_rating >= 4 THEN 1 ELSE 0 END) AS positive_reviews,
    SUM(CASE WHEN r.review_rating <= 2 THEN 1 ELSE 0 END) AS negative_reviews,
    MIN(r.review_date)                       AS first_review_date,
    MAX(r.review_date)                       AS last_review_date
FROM places p
LEFT JOIN reviews r ON r.place_id = p.place_id
GROUP BY p.place_id;

CREATE VIEW v_city_stats AS
SELECT
    p.city,
    p.district,
    p.division,
    COUNT(DISTINCT p.place_id)     AS place_count,
    COUNT(r.review_id)             AS review_count,
    ROUND(AVG(r.review_rating), 3) AS avg_review_rating
FROM places p
LEFT JOIN reviews r ON r.place_id = p.place_id
WHERE p.city IS NOT NULL AND p.city <> ''
GROUP BY p.city, p.district, p.division;

CREATE VIEW v_dataset_overview AS
SELECT
    (SELECT COUNT(*) FROM reviews)                          AS total_reviews,
    (SELECT COUNT(*) FROM places)                           AS total_places,
    (SELECT COUNT(DISTINCT city) FROM places
        WHERE city IS NOT NULL AND city <> '')              AS total_cities,
    (SELECT COUNT(*) FROM topics WHERE topic_id >= 0)        AS total_topics,
    (SELECT COUNT(*) FROM preferences)                      AS total_preferences,
    (SELECT COUNT(*) FROM reviews WHERE topic_id >= 0)       AS clustered_reviews,
    (SELECT COUNT(*) FROM reviews WHERE topic_id < 0
        OR topic_id IS NULL)                                AS outlier_reviews,
    (SELECT ROUND(AVG(review_rating), 3) FROM reviews)      AS avg_rating,
    (SELECT MIN(review_date) FROM reviews)                  AS first_review_date,
    (SELECT MAX(review_date) FROM reviews)                  AS last_review_date;

CREATE VIEW v_rating_distribution AS
SELECT
    source,
    review_rating,
    COUNT(*) AS review_count
FROM reviews
GROUP BY source, review_rating;

CREATE VIEW v_temporal_volume AS
SELECT
    review_month,
    source,
    COUNT(*) AS review_count
FROM reviews
WHERE review_month IS NOT NULL AND review_month <> ''
GROUP BY review_month, source;

CREATE VIEW v_preference_frequency AS
SELECT
    pr.preference_id,
    pr.preference_label,
    pr.category,
    pr.subcategory,
    pr.preference_type,
    COUNT(DISTINCT m.topic_id)              AS topic_count,
    COALESCE(SUM(t.review_count), 0)        AS review_count,
    ROUND(AVG(m.similarity), 4)             AS avg_similarity,
    MIN(m.confidence)                       AS min_confidence
FROM preferences pr
LEFT JOIN topic_preference_map m ON m.preference_id = pr.preference_id
LEFT JOIN topics t ON t.topic_id = m.topic_id
GROUP BY pr.preference_id;

CREATE VIEW v_city_preference_rollup AS
SELECT
    city,
    district,
    division,
    preference_id,
    preference_label,
    preference_type,
    COUNT(*)                        AS review_count,
    ROUND(AVG(review_rating), 3)    AS avg_rating
FROM v_review_preference
WHERE preference_id IS NOT NULL AND city IS NOT NULL AND city <> ''
GROUP BY city, preference_id;

CREATE VIEW v_venue_preference_rollup AS
SELECT
    place_id,
    place_name,
    city,
    category,
    place_kind,
    preference_id,
    preference_label,
    preference_type,
    COUNT(*)                        AS review_count,
    ROUND(AVG(review_rating), 3)    AS avg_rating
FROM v_review_preference
WHERE preference_id IS NOT NULL
GROUP BY place_id, preference_id;
"""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def build_places(
    reviews: pd.DataFrame, geo: pd.DataFrame | None, notes: list[str]
) -> pd.DataFrame:
    """One row per place_name, geography enriched from place_geography.csv."""
    agg = (
        reviews.groupby("place_name", as_index=False)
        .agg(
            csv_city=("city", lambda s: next((v for v in s if pd.notna(v) and str(v).strip()), None)),
            category=("category", lambda s: s.mode().iat[0] if not s.mode().empty else None),
            source=("source", lambda s: s.mode().iat[0] if not s.mode().empty else None),
            place_avg_rating=("place_avg_rating", "max"),
            source_url=("source_url", lambda s: next((v for v in s if pd.notna(v)), None)),
        )
        .sort_values("place_name")
        .reset_index(drop=True)
    )

    if geo is not None and not geo.empty:
        geo_cols = project(geo, ["place_name", "city", "district", "division", "place_kind"])
        geo_cols["place_name"] = geo_cols["place_name"].astype(str).str.strip()
        merged = agg.merge(geo_cols, on="place_name", how="left", indicator=True)
        unmapped = merged.loc[merged["_merge"] == "left_only", "place_name"].tolist()
        if unmapped:
            notes.append(
                "places not found in place_geography.csv (city taken from review CSV, "
                f"district/division left NULL): {', '.join(unmapped)}"
            )
        extra = sorted(set(geo_cols["place_name"]) - set(agg["place_name"]))
        if extra:
            notes.append(
                f"place_geography.csv rows with no reviews yet (ignored): {', '.join(extra)}"
            )
        merged["geo_resolved"] = (merged["_merge"] == "both").astype(int)
        merged = merged.drop(columns=["_merge"])
    else:
        merged = agg.copy()
        merged["city"] = pd.NA
        merged["district"] = pd.NA
        merged["division"] = pd.NA
        merged["place_kind"] = pd.NA
        merged["geo_resolved"] = 0

    # Geography file wins; fall back to whatever the review CSV had.
    merged["city"] = merged["city"].fillna(merged["csv_city"])
    # Derive place_kind from category when the geography file does not say.
    derived_kind = merged["category"].fillna("").str.lower().map(
        lambda c: "accommodation" if any(k in c for k in ("hotel", "resort", "inn", "guest")) else "attraction"
    )
    merged["place_kind"] = merged["place_kind"].fillna(derived_kind)

    blank_city = merged.loc[merged["city"].isna() | (merged["city"].astype(str).str.strip() == ""), "place_name"]
    if len(blank_city):
        notes.append(f"places still missing a city after enrichment: {', '.join(blank_city)}")

    merged = merged.drop(columns=["csv_city"])
    merged.insert(0, "place_id", range(1, len(merged) + 1))
    return merged[
        [
            "place_id",
            "place_name",
            "city",
            "district",
            "division",
            "category",
            "place_kind",
            "source",
            "place_avg_rating",
            "source_url",
            "geo_resolved",
        ]
    ]


def build_topics(
    topics_summary: pd.DataFrame | None,
    interpretations: pd.DataFrame | None,
    topic_prefs: pd.DataFrame | None,
    reviews: pd.DataFrame,
    notes: list[str],
) -> pd.DataFrame:
    """Topic dimension, assembled from whichever Phase 3/4 artifacts exist."""
    counts = (
        reviews.groupby("topic_id", as_index=False)["review_id"]
        .count()
        .rename(columns={"review_id": "actual_review_count"})
    )
    total = max(len(reviews), 1)

    if topics_summary is not None and not topics_summary.empty:
        ts = topics_summary.rename(columns={"Topic": "topic_id", "Count": "review_count"})
        base = project(ts, ["topic_id", "topic_name", "top_keywords", "review_count"])
    else:
        notes.append("topics_summary.csv absent; topic dimension derived from review assignments")
        base = counts.rename(columns={"actual_review_count": "review_count"}).copy()
        base["topic_name"] = pd.NA
        base["top_keywords"] = pd.NA

    base = base.merge(counts, on="topic_id", how="outer")
    base["review_count"] = base["review_count"].fillna(base["actual_review_count"])
    base = base.drop(columns=["actual_review_count"])

    # Interpreted labels: prefer the joined Phase 4 table, fall back to Stage 1.
    label_src = None
    for candidate in (topic_prefs, interpretations):
        if candidate is not None and not candidate.empty and "interpreted_label" in candidate.columns:
            label_src = candidate
            break
    if label_src is not None:
        labels = project(
            label_src, ["topic_id", "interpreted_label", "interpretation", "dimension_hint"]
        ).drop_duplicates(subset=["topic_id"])
        base = base.merge(labels, on="topic_id", how="left")
    else:
        notes.append("no interpreted topic labels found (Phase 4 Stage 1 output missing)")
        base["interpreted_label"] = pd.NA
        base["interpretation"] = pd.NA
        base["dimension_hint"] = pd.NA

    base["corpus_share"] = (base["review_count"].astype(float) / total).round(4)

    # Give the BERTopic outlier bucket a readable name so the API can show it.
    outlier = base["topic_id"] == -1
    base.loc[outlier, "interpreted_label"] = base.loc[outlier, "interpreted_label"].fillna(
        "Unclustered (BERTopic outliers)"
    )
    base.loc[outlier, "topic_name"] = base.loc[outlier, "topic_name"].fillna("-1_outliers")

    return base[
        [
            "topic_id",
            "topic_name",
            "top_keywords",
            "review_count",
            "corpus_share",
            "interpreted_label",
            "interpretation",
            "dimension_hint",
        ]
    ].sort_values("topic_id")


def build_reviews(
    processed: pd.DataFrame,
    with_topics: pd.DataFrame | None,
    places: pd.DataFrame,
    notes: list[str],
) -> pd.DataFrame:
    if with_topics is not None and not with_topics.empty and "topic_id" in with_topics.columns:
        base = with_topics.copy()
        missing = set(processed["review_id"]) - set(base["review_id"])
        if missing:
            notes.append(
                f"{len(missing)} review(s) present in processed_reviews.csv but not in "
                "reviews_with_topics.csv; loaded with topic_id NULL "
                "(re-run Phase 3 to cluster them)"
            )
            extra = processed[processed["review_id"].isin(missing)].copy()
            extra["topic_id"] = pd.NA
            base = pd.concat([base, extra], ignore_index=True)
    else:
        notes.append("reviews_with_topics.csv absent; reviews loaded without topic assignments")
        base = processed.copy()
        base["topic_id"] = pd.NA

    cols = [
        "review_id",
        "place_name",
        "topic_id",
        "source",
        "review_rating",
        "review_text_clean",
        "review_date",
        "detected_language",
        "platform_language_tag",
        "traveler_type",
        "user_location",
        "nights_stayed",
        "reviewer_num_reviews",
        "reviewer_is_local_guide",
        "review_likes",
        "source_url",
    ]
    out = project(base, cols)

    dt = pd.to_datetime(out["review_date"], errors="coerce", format="mixed", utc=True)
    out["review_month"] = dt.dt.strftime("%Y-%m")
    out["review_year"] = dt.dt.year
    out["review_date"] = dt.dt.strftime("%Y-%m-%d")
    out["text_length"] = out["review_text_clean"].fillna("").astype(str).str.len()
    out["reviewer_is_local_guide"] = to_bool(out["reviewer_is_local_guide"])

    out = out.merge(places[["place_id", "place_name"]], on="place_name", how="left")
    orphans = out["place_id"].isna().sum()
    if orphans:
        notes.append(f"{orphans} review(s) could not be linked to a place row")

    before = len(out)
    out = out.drop_duplicates(subset=["review_id"], keep="first")
    if len(out) != before:
        notes.append(f"dropped {before - len(out)} duplicate review_id row(s)")

    return out[
        [
            "review_id",
            "place_id",
            "topic_id",
            "source",
            "review_rating",
            "review_text_clean",
            "review_date",
            "review_month",
            "review_year",
            "text_length",
            "detected_language",
            "platform_language_tag",
            "traveler_type",
            "user_location",
            "nights_stayed",
            "reviewer_num_reviews",
            "reviewer_is_local_guide",
            "review_likes",
            "source_url",
        ]
    ]


def build_preferences(
    pref_class: pd.DataFrame | None,
    long_tail: pd.DataFrame | None,
    notes: list[str],
) -> pd.DataFrame:
    if pref_class is None or pref_class.empty:
        notes.append("preference_classification.csv absent; preferences table left empty")
        return pd.DataFrame(
            columns=[
                "preference_id",
                "category",
                "subcategory",
                "preference_label",
                "preference_description",
                "preference_type",
            ]
        )

    src = pref_class.rename(
        columns={"preference": "preference_label", "description": "preference_description"}
    )
    out = project(
        src,
        [
            "preference_id",
            "category",
            "subcategory",
            "preference_label",
            "preference_description",
            "preference_type",
        ],
    ).drop_duplicates(subset=["preference_id"])

    # Phase 4 Stage 4 is the authority on mainstream vs long_tail.
    if long_tail is not None and not long_tail.empty and "is_long_tail" in long_tail.columns:
        lt = long_tail.copy()
        lt["is_long_tail"] = to_bool(lt["is_long_tail"])
        lt_prefs = set(lt.loc[lt["is_long_tail"] == 1, "preference_id"].dropna())
        if lt_prefs:
            out.loc[out["preference_id"].isin(lt_prefs), "preference_type"] = "long_tail"
    out["preference_type"] = out["preference_type"].fillna("mainstream")
    return out


def build_topic_preference_map(
    mapping: pd.DataFrame | None, precision: pd.DataFrame | None, notes: list[str]
) -> pd.DataFrame:
    cols = [
        "topic_id",
        "preference_id",
        "similarity",
        "second_best_preference_id",
        "second_best_similarity",
        "sim_gap",
        "confidence",
        "needs_review",
        "tau_sim",
    ]
    if mapping is None or mapping.empty:
        notes.append("topic_preference_mapping.csv absent; topic_preference_map left empty")
        return pd.DataFrame(columns=cols)

    out = project(mapping, cols)
    if out["sim_gap"].isna().all():
        out["sim_gap"] = (
            out["similarity"].astype(float) - out["second_best_similarity"].astype(float)
        ).round(4)
    out["needs_review"] = to_bool(out["needs_review"])
    return out.drop_duplicates(subset=["topic_id"])


def build_long_tail(long_tail: pd.DataFrame | None, notes: list[str]) -> pd.DataFrame:
    cols = [
        "topic_id",
        "preference_id",
        "review_count",
        "corpus_share",
        "scarce",
        "max_sim_to_abundant",
        "sdd",
        "sdd_threshold",
        "scarcity_threshold",
        "preference_type",
        "is_long_tail",
    ]
    if long_tail is None or long_tail.empty:
        notes.append("long_tail_flags.csv absent; long_tail_flags left empty")
        return pd.DataFrame(columns=cols)
    out = project(long_tail, cols)
    out["scarce"] = to_bool(out["scarce"])
    out["is_long_tail"] = to_bool(out["is_long_tail"])
    return out.drop_duplicates(subset=["topic_id"])


def build_validation_precision(df: pd.DataFrame | None, notes: list[str]) -> pd.DataFrame:
    cols = [
        "topic_id",
        "interpreted_label",
        "preference_id",
        "similarity",
        "second_best_preference_id",
        "second_best_similarity",
        "sim_gap",
        "low_similarity_flag",
        "ambiguous_flag",
        "precision_status",
    ]
    if df is None or df.empty:
        notes.append("phase5_direction1_precision_checks.csv absent")
        return pd.DataFrame(columns=cols)
    out = project(df, cols)
    out["low_similarity_flag"] = to_bool(out["low_similarity_flag"])
    out["ambiguous_flag"] = to_bool(out["ambiguous_flag"])
    return out.drop_duplicates(subset=["topic_id"])


def build_validation_coverage(df: pd.DataFrame | None, notes: list[str]) -> pd.DataFrame:
    cols = ["preference_id", "mapped_topic_count", "coverage_status", "coverage_action"]
    if df is None or df.empty:
        notes.append("phase5_direction2_coverage_checks.csv absent")
        return pd.DataFrame(columns=cols)
    return project(df, cols).drop_duplicates(subset=["preference_id"])


def build_manual_sample(df: pd.DataFrame | None, notes: list[str]) -> pd.DataFrame:
    cols = [
        "pair_type",
        "topic_id",
        "interpreted_label",
        "preference_id",
        "preference",
        "similarity",
        "human_label",
    ]
    if df is None or df.empty:
        notes.append("phase5_manual_review_sample.csv absent")
        return pd.DataFrame(columns=cols)
    out = project(df, cols)
    labelled = out["human_label"].notna().sum()
    notes.append(
        f"phase5 manual review sample: {labelled}/{len(out)} pairs carry a human_label"
    )
    return out


def build_simple(df: pd.DataFrame | None, cols: list[str], name: str, notes: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        notes.append(f"{name} absent or empty")
        return pd.DataFrame(columns=cols)
    return project(df, cols)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("Phase 8 — building SQLite database from pipeline artifacts")
    notes: list[str] = []

    processed = load_csv("processed_reviews", notes)
    if processed is None or processed.empty:
        raise SystemExit(
            "data/processed_reviews.csv is required — run Phase 2 first."
        )

    with_topics = load_csv("reviews_with_topics", notes)
    topics_summary = load_csv("topics_summary", notes)
    interpretations = load_csv("stage1_interpretations", notes)
    topic_prefs = load_csv("topic_preferences", notes)
    pref_class = load_csv("preference_classification", notes)
    mapping = load_csv("topic_preference_mapping", notes)
    long_tail = load_csv("long_tail_flags", notes)
    p5_precision = load_csv("phase5_precision", notes)
    p5_coverage = load_csv("phase5_coverage", notes)
    p5_recs = load_csv("phase5_recommendations", notes)
    p5_sample = load_csv("phase5_manual_sample", notes)
    p6_metrics = load_csv("phase6_metrics", notes)
    p6_mappings = load_csv("phase6_mappings", notes)
    p7_tests = load_json("phase7_statistical_tests", notes)
    geo = load_csv("place_geography", notes)

    places = build_places(processed, geo, notes)
    topics = build_topics(topics_summary, interpretations, topic_prefs, with_topics if with_topics is not None else processed.assign(topic_id=pd.NA), notes)
    reviews = build_reviews(processed, with_topics, places, notes)
    preferences = build_preferences(pref_class, long_tail, notes)
    tpm = build_topic_preference_map(mapping, p5_precision, notes)
    lt = build_long_tail(long_tail, notes)

    # Referential integrity: never write a mapping that points at a missing row.
    known_topics = set(topics["topic_id"].dropna().astype(int))
    known_prefs = set(preferences["preference_id"].dropna())
    for name, frame in (("topic_preference_map", tpm), ("long_tail_flags", lt)):
        if frame.empty:
            continue
        bad_topic = ~frame["topic_id"].astype("Int64").isin(known_topics)
        if bad_topic.any():
            notes.append(f"{name}: dropped {int(bad_topic.sum())} row(s) with unknown topic_id")
            frame.drop(frame.index[bad_topic], inplace=True)
    if not tpm.empty and known_prefs:
        bad_pref = ~tpm["preference_id"].isin(known_prefs) & tpm["preference_id"].notna()
        if bad_pref.any():
            notes.append(
                f"topic_preference_map: {int(bad_pref.sum())} row(s) point at an unknown "
                "preference_id; preference_id set to NULL"
            )
            tpm.loc[bad_pref, "preference_id"] = pd.NA

    val_precision = build_validation_precision(p5_precision, notes)
    val_coverage = build_validation_coverage(p5_coverage, notes)
    val_recs = build_simple(
        p5_recs, ["type", "target_id", "severity", "details", "suggested_action"],
        "phase5_recommendations.csv", notes,
    )
    val_sample = build_manual_sample(p5_sample, notes)
    sens_metrics = build_simple(
        p6_metrics,
        [
            "sample_size", "sample_fraction", "min_topic_size", "n_topics",
            "n_preferences_covered", "n_preferences_total", "coverage_rate",
            "avg_similarity", "high_confidence_rate", "mapped_preference_ids",
            "jaccard_vs_previous", "run_type",
        ],
        "phase6_sensitivity_metrics.csv", notes,
    )
    sens_mappings = build_simple(
        p6_mappings,
        [
            "sample_size", "topic_id", "topic_name", "review_count", "preference_id",
            "preference", "category", "similarity", "high_confidence",
        ],
        "phase6_sensitivity_mappings.csv", notes,
    )
    if not sens_mappings.empty:
        sens_mappings["high_confidence"] = to_bool(sens_mappings["high_confidence"])

    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        row_counts = {
            "places": write_table(conn, "places", places),
            "topics": write_table(conn, "topics", topics),
            "reviews": write_table(conn, "reviews", reviews),
            "preferences": write_table(conn, "preferences", preferences),
            "topic_preference_map": write_table(conn, "topic_preference_map", tpm),
            "long_tail_flags": write_table(conn, "long_tail_flags", lt),
            "validation_precision": write_table(conn, "validation_precision", val_precision),
            "validation_coverage": write_table(conn, "validation_coverage", val_coverage),
            "validation_recommendations": write_table(conn, "validation_recommendations", val_recs),
            "validation_manual_sample": write_table(conn, "validation_manual_sample", val_sample),
            "sensitivity_metrics": write_table(conn, "sensitivity_metrics", sens_metrics),
            "sensitivity_mappings": write_table(conn, "sensitivity_mappings", sens_mappings),
        }

        meta_rows = [
            ("schema_version", str(SCHEMA_VERSION)),
            ("built_at_utc", built_at),
            ("source_files", json.dumps(
                {k: (v.name if v.exists() else None) for k, v in INPUTS.items()}
            )),
            ("row_counts", json.dumps(row_counts)),
            ("phase7_statistical_tests", json.dumps(p7_tests) if p7_tests else ""),
            ("build_notes", json.dumps(notes)),
        ]
        conn.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", meta_rows)
        conn.commit()

        # Smoke-check every view so a broken view fails the build, not the API.
        views = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        )]
        for view in views:
            conn.execute(f"SELECT * FROM {view} LIMIT 1").fetchall()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    report = {
        "schema_version": SCHEMA_VERSION,
        "built_at_utc": built_at,
        "database": DB_PATH.name,
        "row_counts": row_counts,
        "views": views,
        "notes": notes,
    }
    with open(OUT_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = [
        "# Phase 8 — Database Build Report",
        "",
        f"- Built (UTC): {built_at}",
        f"- Database: `data/{DB_PATH.name}` (schema version {SCHEMA_VERSION})",
        "",
        "## Row counts",
        "",
        "| table | rows |",
        "| --- | --- |",
    ]
    lines += [f"| {t} | {n} |" for t, n in row_counts.items()]
    lines += ["", "## Views", ""] + [f"- `{v}`" for v in views]
    lines += ["", "## Build notes", ""]
    lines += [f"- {n}" for n in notes] or ["- none"]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        shown = DB_PATH.relative_to(REPO_ROOT)
    except ValueError:  # TOURISTINBD_DATA_DIR points outside the repo
        shown = DB_PATH
    print(f"  wrote {shown}")
    for table, n in row_counts.items():
        print(f"    {table:<28} {n:>6}")
    if notes:
        print("  notes:")
        for n in notes:
            print(f"    - {n}")
    print(f"  report: data/{OUT_REPORT_MD.name}")


if __name__ == "__main__":
    main()
