"""
Phase 7 — Statistics & visualization layer.

Builds reusable aggregates and charts from Phases 2–6 outputs.
Writes only `data/phase7_*` files (non-destructive).
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import mannwhitneyu, ranksums

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

# Inputs
PROCESSED = DATA_DIR / "processed_reviews.csv"
REVIEWS_WITH_TOPICS = DATA_DIR / "reviews_with_topics.csv"
TOPIC_PREFS = DATA_DIR / "topic_preferences.csv"
LONG_TAIL = DATA_DIR / "long_tail_flags.csv"
PHASE5_PRECISION = DATA_DIR / "phase5_direction1_precision_checks.csv"
PHASE5_COVERAGE = DATA_DIR / "phase5_direction2_coverage_checks.csv"
PHASE6_METRICS = DATA_DIR / "phase6_sensitivity_metrics.csv"

# Outputs
OUT_DATASET_OVERVIEW = DATA_DIR / "phase7_dataset_overview.csv"
OUT_TEMPORAL = DATA_DIR / "phase7_temporal_review_volume.csv"
OUT_RATING_DIST = DATA_DIR / "phase7_rating_distribution.csv"
OUT_PREF_FREQ = DATA_DIR / "phase7_preference_frequency.csv"
OUT_PREF_COVERAGE = DATA_DIR / "phase7_preference_coverage.csv"
OUT_MAINSTREAM_LONGTAIL = DATA_DIR / "phase7_mainstream_vs_longtail.csv"
OUT_MAPPING_QUALITY = DATA_DIR / "phase7_mapping_quality.csv"
OUT_CITY_PREF = DATA_DIR / "phase7_city_preference_rollup.csv"
OUT_VENUE_PREF = DATA_DIR / "phase7_venue_preference_rollup.csv"
OUT_STATS_TESTS = DATA_DIR / "phase7_statistical_tests.json"
OUT_DASHBOARD_JSON = DATA_DIR / "phase7_dashboard_payload.json"
OUT_REPORT_MD = DATA_DIR / "phase7_report.md"

CHART_TOPIC_COUNTS = DATA_DIR / "phase7_chart_topic_counts.png"
CHART_RATING_SOURCE = DATA_DIR / "phase7_chart_rating_by_source.png"
CHART_PREF_COUNTS = DATA_DIR / "phase7_chart_preference_counts.png"
CHART_MAINSTREAM_LONGTAIL = DATA_DIR / "phase7_chart_mainstream_vs_longtail.png"
CHART_SENSITIVITY = DATA_DIR / "phase7_chart_sensitivity.png"


def ensure_date_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([pd.NaT] * len(df))
    return pd.to_datetime(df[col], errors="coerce")


def save_plot(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def dataset_overview(processed: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "total_reviews", "value": int(len(processed))},
        {"metric": "unique_places", "value": int(processed["place_name"].nunique())},
        {"metric": "unique_cities", "value": int(processed["city"].nunique())},
        {"metric": "avg_rating", "value": round(float(processed["review_rating"].mean()), 3)},
    ]

    by_source = (
        processed.groupby("source", as_index=False)["review_id"]
        .count()
        .rename(columns={"review_id": "count"})
    )
    for r in by_source.itertuples(index=False):
        rows.append({"metric": f"reviews_source_{r.source}", "value": int(r.count)})

    by_lang = (
        processed.groupby("detected_language", as_index=False)["review_id"]
        .count()
        .rename(columns={"review_id": "count"})
    )
    for r in by_lang.itertuples(index=False):
        rows.append({"metric": f"reviews_language_{r.detected_language}", "value": int(r.count)})

    return pd.DataFrame(rows)


def temporal_volume(processed: pd.DataFrame) -> pd.DataFrame:
    dt = ensure_date_col(processed, "review_date")
    tmp = processed.copy()
    tmp["review_month"] = dt.dt.to_period("M").astype(str)
    tmp = tmp[tmp["review_month"] != "NaT"]
    if tmp.empty:
        return pd.DataFrame(columns=["review_month", "source", "review_count"])
    return (
        tmp.groupby(["review_month", "source"], as_index=False)["review_id"]
        .count()
        .rename(columns={"review_id": "review_count"})
        .sort_values(["review_month", "source"])
    )


def rating_distribution(processed: pd.DataFrame) -> pd.DataFrame:
    base = (
        processed.groupby(["source", "review_rating"], as_index=False)["review_id"]
        .count()
        .rename(columns={"review_id": "count"})
    )
    total = base.groupby("source", as_index=False)["count"].sum().rename(columns={"count": "source_total"})
    out = base.merge(total, on="source", how="left")
    out["pct_in_source"] = (out["count"] / out["source_total"]).round(4)
    return out.sort_values(["source", "review_rating"])


def preference_frequency(topic_prefs: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        topic_prefs.groupby(
            ["preference_id", "preference_label", "category", "subcategory", "preference_type"],
            as_index=False,
        )
        .agg(topic_count=("topic_id", "nunique"), review_count=("review_count", "sum"))
    )
    grouped["review_share"] = (grouped["review_count"] / grouped["review_count"].sum()).round(4)
    return grouped.sort_values("review_count", ascending=False)


def preference_coverage(topic_prefs: pd.DataFrame, phase5_cov: pd.DataFrame | None) -> pd.DataFrame:
    base = (
        topic_prefs.groupby("preference_id", as_index=False)
        .agg(
            mapped_topic_count=("topic_id", "nunique"),
            covered_reviews=("review_count", "sum"),
            avg_similarity=("similarity", "mean"),
        )
    )
    base["avg_similarity"] = base["avg_similarity"].round(4)
    if phase5_cov is not None and not phase5_cov.empty:
        keep = ["preference_id", "coverage_status", "coverage_action"]
        base = base.merge(phase5_cov[keep], on="preference_id", how="left")
    return base.sort_values(["mapped_topic_count", "covered_reviews"], ascending=[False, False])


def mainstream_longtail_table(topic_prefs: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        topic_prefs.groupby("preference_type", as_index=False)
        .agg(
            topic_count=("topic_id", "nunique"),
            preference_count=("preference_id", "nunique"),
            review_count=("review_count", "sum"),
            avg_similarity=("similarity", "mean"),
            mean_sdd=("sdd", "mean"),
        )
    )
    if grouped.empty:
        return pd.DataFrame(
            columns=["preference_type", "topic_count", "preference_count", "review_count", "avg_similarity", "mean_sdd", "review_share"]
        )
    grouped["avg_similarity"] = grouped["avg_similarity"].round(4)
    grouped["mean_sdd"] = grouped["mean_sdd"].round(4)
    grouped["review_share"] = (grouped["review_count"] / grouped["review_count"].sum()).round(4)
    return grouped.sort_values("review_count", ascending=False)


def mapping_quality(phase5_precision: pd.DataFrame | None, phase5_coverage: pd.DataFrame | None) -> pd.DataFrame:
    rows: list[dict] = []
    if phase5_precision is not None and not phase5_precision.empty:
        total = len(phase5_precision)
        rows.extend(
            [
                {"metric": "direction1_total_topics", "value": total},
                {
                    "metric": "direction1_low_similarity_flags",
                    "value": int((phase5_precision["low_similarity_flag"] == True).sum()),
                },
                {
                    "metric": "direction1_ambiguous_flags",
                    "value": int((phase5_precision["ambiguous_flag"] == True).sum()),
                },
                {
                    "metric": "direction1_pass_rate",
                    "value": round(float((phase5_precision["precision_status"] == "pass").mean()), 4),
                },
            ]
        )
    if phase5_coverage is not None and not phase5_coverage.empty:
        total_pref = len(phase5_coverage)
        rows.extend(
            [
                {"metric": "direction2_total_preferences", "value": total_pref},
                {
                    "metric": "direction2_under_coverage",
                    "value": int((phase5_coverage["coverage_status"] == "under_coverage").sum()),
                },
                {
                    "metric": "direction2_adequate",
                    "value": int((phase5_coverage["coverage_status"] == "adequate").sum()),
                },
                {
                    "metric": "direction2_adequate_rate",
                    "value": round(float((phase5_coverage["coverage_status"] == "adequate").mean()), 4),
                },
            ]
        )
    return pd.DataFrame(rows)


def city_and_venue_rollups(reviews_topics: pd.DataFrame, topic_prefs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = reviews_topics.merge(
        topic_prefs[["topic_id", "preference_id", "preference_label", "preference_type"]],
        on="topic_id",
        how="left",
    )
    city_roll = (
        merged.groupby(["city", "preference_id", "preference_label", "preference_type"], as_index=False)
        .agg(
            review_count=("review_id", "count"),
            avg_rating=("review_rating", "mean"),
        )
        .sort_values(["city", "review_count"], ascending=[True, False])
    )
    city_roll["avg_rating"] = city_roll["avg_rating"].round(3)

    venue_roll = (
        merged.groupby(["city", "place_name", "preference_id", "preference_label", "preference_type"], as_index=False)
        .agg(
            review_count=("review_id", "count"),
            avg_rating=("review_rating", "mean"),
        )
        .sort_values(["city", "place_name", "review_count"], ascending=[True, True, False])
    )
    venue_roll["avg_rating"] = venue_roll["avg_rating"].round(3)
    return city_roll, venue_roll


def statistical_tests(reviews_topics: pd.DataFrame, topic_prefs: pd.DataFrame) -> dict:
    merged = reviews_topics.merge(
        topic_prefs[["topic_id", "preference_type"]],
        on="topic_id",
        how="left",
    )
    merged["text_len"] = merged["review_text_clean"].fillna("").astype(str).str.len()
    mainstream = merged[merged["preference_type"] == "mainstream"]
    longtail = merged[merged["preference_type"] == "long_tail"]

    result: dict = {
        "group_sizes": {
            "mainstream_reviews": int(len(mainstream)),
            "longtail_reviews": int(len(longtail)),
        },
        "tests": {},
        "note": "",
    }

    if len(mainstream) == 0 or len(longtail) == 0:
        result["note"] = (
            "Long-tail group has zero reviews in current MVP run; "
            "Wilcoxon rank-sum and Mann-Whitney U tests are skipped."
        )
        return result

    # Rating comparison
    rs_stat, rs_p = ranksums(mainstream["review_rating"], longtail["review_rating"])
    mw_stat, mw_p = mannwhitneyu(
        mainstream["review_rating"], longtail["review_rating"], alternative="two-sided"
    )
    # Behavior proxy: review text length
    len_rs_stat, len_rs_p = ranksums(mainstream["text_len"], longtail["text_len"])
    len_mw_stat, len_mw_p = mannwhitneyu(
        mainstream["text_len"], longtail["text_len"], alternative="two-sided"
    )

    result["tests"] = {
        "rating_ranksums": {"statistic": float(rs_stat), "p_value": float(rs_p)},
        "rating_mannwhitneyu": {"statistic": float(mw_stat), "p_value": float(mw_p)},
        "length_ranksums": {"statistic": float(len_rs_stat), "p_value": float(len_rs_p)},
        "length_mannwhitneyu": {"statistic": float(len_mw_stat), "p_value": float(len_mw_p)},
    }
    result["note"] = "Both groups present; nonparametric tests computed."
    return result


def make_charts(
    topic_prefs: pd.DataFrame,
    rating_dist: pd.DataFrame,
    pref_freq: pd.DataFrame,
    main_long: pd.DataFrame,
    phase6_metrics: pd.DataFrame | None,
) -> None:
    # Topic counts by interpreted label
    sorted_tp = topic_prefs.sort_values("review_count", ascending=False)
    fig1, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(sorted_tp["interpreted_label"], sorted_tp["review_count"], color="#F2A93B")
    ax1.set_title("Reviews per topic (Phase 4 mapped topics)")
    ax1.set_ylabel("Review count")
    ax1.tick_params(axis="x", rotation=50)
    save_plot(fig1, CHART_TOPIC_COUNTS)

    # Rating by source
    if not rating_dist.empty:
        pivot = rating_dist.pivot(index="review_rating", columns="source", values="count").fillna(0)
        fig2, ax2 = plt.subplots(figsize=(8, 4.5))
        pivot.plot(kind="bar", ax=ax2)
        ax2.set_title("Rating distribution by source")
        ax2.set_xlabel("Review rating")
        ax2.set_ylabel("Count")
        save_plot(fig2, CHART_RATING_SOURCE)

    # Preference review counts
    fig3, ax3 = plt.subplots(figsize=(10, 5))
    pf = pref_freq.sort_values("review_count", ascending=False)
    ax3.bar(pf["preference_label"], pf["review_count"], color="#2F6F4E")
    ax3.set_title("Preference frequency (reviews mapped)")
    ax3.set_ylabel("Review count")
    ax3.tick_params(axis="x", rotation=50)
    save_plot(fig3, CHART_PREF_COUNTS)

    # Mainstream vs long-tail shares
    fig4, ax4 = plt.subplots(figsize=(6.5, 4))
    if main_long.empty:
        ax4.text(0.5, 0.5, "No data", ha="center", va="center")
    else:
        ax4.bar(main_long["preference_type"], main_long["review_count"], color=["#3A7D44", "#8E44AD"][: len(main_long)])
        ax4.set_ylabel("Review count")
    ax4.set_title("Mainstream vs long-tail coverage")
    save_plot(fig4, CHART_MAINSTREAM_LONGTAIL)

    # Sensitivity trend from Phase 6
    if phase6_metrics is not None and not phase6_metrics.empty:
        sub = phase6_metrics[phase6_metrics["run_type"] == "bertopic_retrain_hybrid"].copy()
        if not sub.empty:
            fig5, ax5 = plt.subplots(figsize=(8, 4.5))
            ax5.plot(sub["sample_size"], sub["n_preferences_covered"], marker="o", label="Preferences covered")
            ax5.plot(sub["sample_size"], sub["n_topics"], marker="o", label="Topics")
            ax5.set_title("Phase 6 sensitivity summary")
            ax5.set_xlabel("Sample size")
            ax5.set_ylabel("Count")
            ax5.legend()
            save_plot(fig5, CHART_SENSITIVITY)


def load_optional(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def main() -> None:
    print("Phase 7 — building statistics and visualization layer")
    processed = pd.read_csv(PROCESSED)
    reviews_topics = pd.read_csv(REVIEWS_WITH_TOPICS)
    topic_prefs = pd.read_csv(TOPIC_PREFS)

    phase5_precision = load_optional(PHASE5_PRECISION)
    phase5_coverage = load_optional(PHASE5_COVERAGE)
    phase6_metrics = load_optional(PHASE6_METRICS)

    # Tables
    overview = dataset_overview(processed)
    temporal = temporal_volume(processed)
    ratings = rating_distribution(processed)
    pref_freq = preference_frequency(topic_prefs)
    pref_cov = preference_coverage(topic_prefs, phase5_coverage)
    main_long = mainstream_longtail_table(topic_prefs)
    map_quality = mapping_quality(phase5_precision, phase5_coverage)
    city_roll, venue_roll = city_and_venue_rollups(reviews_topics, topic_prefs)
    tests = statistical_tests(reviews_topics, topic_prefs)

    overview.to_csv(OUT_DATASET_OVERVIEW, index=False)
    temporal.to_csv(OUT_TEMPORAL, index=False)
    ratings.to_csv(OUT_RATING_DIST, index=False)
    pref_freq.to_csv(OUT_PREF_FREQ, index=False)
    pref_cov.to_csv(OUT_PREF_COVERAGE, index=False)
    main_long.to_csv(OUT_MAINSTREAM_LONGTAIL, index=False)
    map_quality.to_csv(OUT_MAPPING_QUALITY, index=False)
    city_roll.to_csv(OUT_CITY_PREF, index=False)
    venue_roll.to_csv(OUT_VENUE_PREF, index=False)

    with open(OUT_STATS_TESTS, "w", encoding="utf-8") as f:
        json.dump(tests, f, ensure_ascii=False, indent=2)

    # Charts
    make_charts(topic_prefs, ratings, pref_freq, main_long, phase6_metrics)

    payload = {
        "tables": {
            "dataset_overview": OUT_DATASET_OVERVIEW.name,
            "temporal_review_volume": OUT_TEMPORAL.name,
            "rating_distribution": OUT_RATING_DIST.name,
            "preference_frequency": OUT_PREF_FREQ.name,
            "preference_coverage": OUT_PREF_COVERAGE.name,
            "mainstream_vs_longtail": OUT_MAINSTREAM_LONGTAIL.name,
            "mapping_quality": OUT_MAPPING_QUALITY.name,
            "city_preference_rollup": OUT_CITY_PREF.name,
            "venue_preference_rollup": OUT_VENUE_PREF.name,
        },
        "charts": [
            CHART_TOPIC_COUNTS.name,
            CHART_RATING_SOURCE.name,
            CHART_PREF_COUNTS.name,
            CHART_MAINSTREAM_LONGTAIL.name,
            CHART_SENSITIVITY.name,
        ],
        "statistical_tests": OUT_STATS_TESTS.name,
        "notes": [
            "All outputs are phase7_* files.",
            "If long-tail group is empty, significance tests are skipped gracefully.",
        ],
    }
    with open(OUT_DASHBOARD_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    report = f"""# Phase 7 Report

## What Was Built
- Dataset overview, temporal volume, and rating distribution tables.
- Preference frequency/coverage tables plus city and venue rollups.
- Mapping quality summary from Phase 5 and sensitivity summary integration from Phase 6.
- Chart set saved as `phase7_chart_*.png`.

## Key Counts
- Total processed reviews: {len(processed)}
- Topic-preference rows: {len(topic_prefs)}
- Preferences covered: {topic_prefs['preference_id'].nunique()}
- Mainstream/long-tail topics: {topic_prefs['preference_type'].value_counts().to_dict()}

## Statistical Tests
- Details saved in `{OUT_STATS_TESTS.name}`.
- Note: {tests.get('note', '')}

## Safety
- This phase is non-destructive. Canonical Phase 3–6 files are unchanged.
"""
    OUT_REPORT_MD.write_text(report, encoding="utf-8")

    print("Phase 7 complete.")
    print(f"  wrote: {OUT_DASHBOARD_JSON.name}, {OUT_REPORT_MD.name}")
    print("  tables + charts saved under data/phase7_*")


if __name__ == "__main__":
    main()
