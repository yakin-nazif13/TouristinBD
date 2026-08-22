"""
Phase 5 — Bidirectional validation for topic-preference mappings.

Direction 1 (Topic -> Preference, precision):
  - Flag low-similarity mappings where Sim(topic, mapped_preference) < tau_sim.
  - Flag ambiguous mappings where (best - second_best) < ambiguity_margin.

Direction 2 (Preference -> Topic, coverage):
  - Under-coverage: mapped topic count < min_topics_per_preference
  - Over-coverage:  mapped topic count > max_topics_per_preference

Also creates a ~50-pair manual review sample and a compact report.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

MAPPING_PATH = DATA_DIR / "topic_preference_mapping.csv"
PREFERENCES_PATH = DATA_DIR / "preference_classification.csv"
TOPICS_JOINED_PATH = DATA_DIR / "topic_preferences.csv"
SIM_MATRIX_PATH = DATA_DIR / "topic_preference_sim_matrix.npy"

PRECISION_PATH = DATA_DIR / "phase5_direction1_precision_checks.csv"
COVERAGE_PATH = DATA_DIR / "phase5_direction2_coverage_checks.csv"
REVIEW_SAMPLE_PATH = DATA_DIR / "phase5_manual_review_sample.csv"
REPORT_JSON_PATH = DATA_DIR / "phase5_validation_report.json"
REPORT_MD_PATH = DATA_DIR / "phase5_validation_report.md"
RECOMMENDATIONS_PATH = DATA_DIR / "phase5_recommendations.csv"

TAU_SIM = 0.4
AMBIGUITY_MARGIN = 0.08
MIN_TOPICS_PER_PREFERENCE = 3
MAX_TOPICS_PER_PREFERENCE = 20
TARGET_REVIEW_SAMPLE_SIZE = 50
RANDOM_SEED = 42


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray]:
    mapping = pd.read_csv(MAPPING_PATH)
    preferences = pd.read_csv(PREFERENCES_PATH)
    topics_joined = pd.read_csv(TOPICS_JOINED_PATH)
    sim_matrix = np.load(SIM_MATRIX_PATH)
    return mapping, preferences, topics_joined, sim_matrix


def run_direction1_precision(mapping: pd.DataFrame) -> pd.DataFrame:
    out = mapping.copy()
    out["similarity"] = out["similarity"].astype(float)
    out["second_best_similarity"] = out["second_best_similarity"].astype(float)
    out["sim_gap"] = (out["similarity"] - out["second_best_similarity"]).round(4)
    out["low_similarity_flag"] = out["similarity"] < TAU_SIM
    out["ambiguous_flag"] = out["sim_gap"] < AMBIGUITY_MARGIN
    out["precision_status"] = np.where(
        out["low_similarity_flag"],
        "low_similarity",
        np.where(out["ambiguous_flag"], "ambiguous", "pass"),
    )
    return out


def run_direction2_coverage(
    mapping: pd.DataFrame, preferences: pd.DataFrame
) -> pd.DataFrame:
    counts = (
        mapping.groupby("preference_id", as_index=False)["topic_id"]
        .count()
        .rename(columns={"topic_id": "mapped_topic_count"})
    )
    coverage = preferences.merge(counts, on="preference_id", how="left")
    coverage["mapped_topic_count"] = coverage["mapped_topic_count"].fillna(0).astype(int)

    coverage["coverage_status"] = np.where(
        coverage["mapped_topic_count"] < MIN_TOPICS_PER_PREFERENCE,
        "under_coverage",
        np.where(
            coverage["mapped_topic_count"] > MAX_TOPICS_PER_PREFERENCE,
            "over_coverage",
            "adequate",
        ),
    )
    coverage["coverage_action"] = np.where(
        coverage["coverage_status"] == "under_coverage",
        "merge_or_expand",
        np.where(
            coverage["coverage_status"] == "over_coverage", "split", "no_action"
        ),
    )
    return coverage


def build_manual_review_sample(
    mapping: pd.DataFrame, sim_matrix: np.ndarray, target_size: int
) -> pd.DataFrame:
    """
    Build a practical review set with balance:
      - all mapped positives (topic, mapped_pref)
      - all second-best alternatives
      - random negatives to reach target size
    """
    topic_ids = mapping["topic_id"].astype(int).tolist()
    pref_ids = mapping["preference_id"].astype(str).tolist()
    pref_index = {pid: idx for idx, pid in enumerate(pref_ids)}
    mapped_pref_by_topic = {
        int(row.topic_id): str(row.preference_id) for row in mapping.itertuples(index=False)
    }
    second_pref_by_topic = {
        int(row.topic_id): str(row.second_best_preference_id)
        for row in mapping.itertuples(index=False)
    }

    rows: list[dict] = []

    # Positives
    for row in mapping.itertuples(index=False):
        t = int(row.topic_id)
        p = str(row.preference_id)
        rows.append(
            {
                "topic_id": t,
                "preference_id": p,
                "similarity": float(row.similarity),
                "pair_type": "mapped_positive",
                "expected_relation": 1,
            }
        )

    # Second-best challengers
    for row in mapping.itertuples(index=False):
        t = int(row.topic_id)
        p2 = str(row.second_best_preference_id)
        rows.append(
            {
                "topic_id": t,
                "preference_id": p2,
                "similarity": float(row.second_best_similarity),
                "pair_type": "second_best_challenger",
                "expected_relation": 0,
            }
        )

    used = {(int(r["topic_id"]), str(r["preference_id"])) for r in rows}
    rng = np.random.default_rng(RANDOM_SEED)

    # Candidate negatives are all non-mapped topic-pref pairs
    all_pairs = []
    for topic_id in topic_ids:
        for pid in pref_ids:
            if (topic_id, pid) in used:
                continue
            sim = float(sim_matrix[topic_id, pref_index[pid]])
            all_pairs.append((topic_id, pid, sim))

    # Prefer harder negatives (higher similarity), then random fill
    hard = sorted(all_pairs, key=lambda x: x[2], reverse=True)
    needed = max(0, target_size - len(rows))
    hard_take = min(len(hard), max(0, needed // 2))
    selected_hard = hard[:hard_take]
    for topic_id, pid, sim in selected_hard:
        rows.append(
            {
                "topic_id": topic_id,
                "preference_id": pid,
                "similarity": round(sim, 4),
                "pair_type": "hard_negative",
                "expected_relation": 0,
            }
        )
    used.update((t, p) for t, p, _ in selected_hard)

    remaining_pool = [p for p in all_pairs if (p[0], p[1]) not in used]
    remaining_needed = max(0, target_size - len(rows))
    if remaining_needed > 0 and remaining_pool:
        idxs = rng.choice(
            len(remaining_pool), size=min(remaining_needed, len(remaining_pool)), replace=False
        )
        for i in idxs:
            topic_id, pid, sim = remaining_pool[int(i)]
            rows.append(
                {
                    "topic_id": topic_id,
                    "preference_id": pid,
                    "similarity": round(sim, 4),
                    "pair_type": "random_negative",
                    "expected_relation": 0,
                }
            )

    sample = pd.DataFrame(rows).sort_values(
        by=["pair_type", "topic_id", "similarity"], ascending=[True, True, False]
    )
    sample["human_label"] = ""  # to fill manually: 1 correct mapping, 0 incorrect
    sample["review_note"] = ""  # free text
    return sample.reset_index(drop=True)


def build_recommendations(
    precision: pd.DataFrame, coverage: pd.DataFrame, topics_joined: pd.DataFrame
) -> pd.DataFrame:
    recs: list[dict] = []

    # Precision issues
    for row in precision[precision["precision_status"] != "pass"].itertuples(index=False):
        recs.append(
            {
                "type": "topic_precision_issue",
                "target_id": f"topic_{int(row.topic_id)}",
                "severity": "high" if row.low_similarity_flag else "medium",
                "details": (
                    f"mapped {row.preference_id} sim={row.similarity:.4f}, "
                    f"second={row.second_best_preference_id} sim={row.second_best_similarity:.4f}, "
                    f"gap={row.sim_gap:.4f}"
                ),
                "suggested_action": "manual_remap_review",
            }
        )

    # Coverage issues
    for row in coverage[coverage["coverage_status"] != "adequate"].itertuples(index=False):
        recs.append(
            {
                "type": "preference_coverage_issue",
                "target_id": str(row.preference_id),
                "severity": "medium",
                "details": f"mapped_topic_count={int(row.mapped_topic_count)}",
                "suggested_action": str(row.coverage_action),
            }
        )

    # Heuristic merge candidates: same subcategory + semantically close in stage3
    # Since topic 2 and 9 map to P03 already, we add known suggestion for P05 vs P03
    # if both are Heritage and P05 has very low coverage.
    coverage_lookup = {
        str(r.preference_id): int(r.mapped_topic_count) for r in coverage.itertuples(index=False)
    }
    p05_count = coverage_lookup.get("P05")
    p03_count = coverage_lookup.get("P03")
    if p05_count is not None and p03_count is not None and p05_count < MIN_TOPICS_PER_PREFERENCE:
        recs.append(
            {
                "type": "taxonomy_merge_candidate",
                "target_id": "P05->P03",
                "severity": "low",
                "details": "P05 (Panam heritage) is under-covered while P03 is broader Heritage.",
                "suggested_action": "consider_merge_after_human_review",
            }
        )

    # Spot-check topic 2 mixture as noted in progress
    if "topic_id" in topics_joined.columns:
        t2 = topics_joined[topics_joined["topic_id"] == 2]
        if not t2.empty:
            recs.append(
                {
                    "type": "topic_spot_check",
                    "target_id": "topic_2",
                    "severity": "low",
                    "details": "Mixed heritage/Jaflong signal historically observed; spot-check manually.",
                    "suggested_action": "manual_sample_review",
                }
            )

    if not recs:
        recs.append(
            {
                "type": "no_critical_issues",
                "target_id": "all",
                "severity": "info",
                "details": "No low-similarity or coverage violations detected under current thresholds.",
                "suggested_action": "proceed_to_phase6_or_expand_data",
            }
        )
    return pd.DataFrame(recs)


def write_reports(
    precision: pd.DataFrame,
    coverage: pd.DataFrame,
    sample: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> None:
    low_sim = int((precision["low_similarity_flag"]).sum())
    ambiguous = int((precision["ambiguous_flag"]).sum())
    under_cov = int((coverage["coverage_status"] == "under_coverage").sum())
    over_cov = int((coverage["coverage_status"] == "over_coverage").sum())
    adequate = int((coverage["coverage_status"] == "adequate").sum())

    summary = {
        "thresholds": {
            "tau_sim": TAU_SIM,
            "ambiguity_margin": AMBIGUITY_MARGIN,
            "min_topics_per_preference": MIN_TOPICS_PER_PREFERENCE,
            "max_topics_per_preference": MAX_TOPICS_PER_PREFERENCE,
        },
        "direction1_precision": {
            "total_topics": int(len(precision)),
            "low_similarity_flags": low_sim,
            "ambiguous_flags": ambiguous,
            "pass": int((precision["precision_status"] == "pass").sum()),
        },
        "direction2_coverage": {
            "total_preferences": int(len(coverage)),
            "under_coverage": under_cov,
            "over_coverage": over_cov,
            "adequate": adequate,
        },
        "manual_review_sample": {
            "rows": int(len(sample)),
            "mapped_positive": int((sample["pair_type"] == "mapped_positive").sum()),
            "second_best_challenger": int(
                (sample["pair_type"] == "second_best_challenger").sum()
            ),
            "hard_negative": int((sample["pair_type"] == "hard_negative").sum()),
            "random_negative": int((sample["pair_type"] == "random_negative").sum()),
        },
        "recommendation_count": int(len(recommendations)),
    }

    with open(REPORT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    md = f"""# Phase 5 Validation Report

## Thresholds
- tau_sim: `{TAU_SIM}`
- ambiguity_margin: `{AMBIGUITY_MARGIN}`
- min_topics_per_preference: `{MIN_TOPICS_PER_PREFERENCE}`
- max_topics_per_preference: `{MAX_TOPICS_PER_PREFERENCE}`

## Direction 1 (Topic -> Preference)
- total topics: `{summary["direction1_precision"]["total_topics"]}`
- low-similarity flags: `{summary["direction1_precision"]["low_similarity_flags"]}`
- ambiguous flags: `{summary["direction1_precision"]["ambiguous_flags"]}`
- pass: `{summary["direction1_precision"]["pass"]}`

## Direction 2 (Preference -> Topic)
- total preferences: `{summary["direction2_coverage"]["total_preferences"]}`
- under-coverage: `{summary["direction2_coverage"]["under_coverage"]}`
- over-coverage: `{summary["direction2_coverage"]["over_coverage"]}`
- adequate: `{summary["direction2_coverage"]["adequate"]}`

## Manual Review Sample
- rows: `{summary["manual_review_sample"]["rows"]}`
- mapped positives: `{summary["manual_review_sample"]["mapped_positive"]}`
- second-best challengers: `{summary["manual_review_sample"]["second_best_challenger"]}`
- hard negatives: `{summary["manual_review_sample"]["hard_negative"]}`
- random negatives: `{summary["manual_review_sample"]["random_negative"]}`

## Output Files
- `data/phase5_direction1_precision_checks.csv`
- `data/phase5_direction2_coverage_checks.csv`
- `data/phase5_manual_review_sample.csv`
- `data/phase5_recommendations.csv`
- `data/phase5_validation_report.json`
"""
    REPORT_MD_PATH.write_text(md, encoding="utf-8")


def main() -> None:
    print("Loading Phase 4 artifacts for Phase 5 validation")
    mapping, preferences, topics_joined, sim_matrix = load_inputs()

    n_topics = len(mapping)
    n_prefs = len(preferences)
    if sim_matrix.shape != (n_topics, n_prefs):
        raise RuntimeError(
            f"Similarity matrix shape {sim_matrix.shape} does not match "
            f"(topics={n_topics}, preferences={n_prefs})."
        )

    print("Running direction 1 precision checks")
    precision = run_direction1_precision(mapping)
    precision.to_csv(PRECISION_PATH, index=False)

    print("Running direction 2 coverage checks")
    coverage = run_direction2_coverage(mapping, preferences)
    coverage.to_csv(COVERAGE_PATH, index=False)

    print(f"Building manual review sample (target {TARGET_REVIEW_SAMPLE_SIZE})")
    sample = build_manual_review_sample(mapping, sim_matrix, TARGET_REVIEW_SAMPLE_SIZE)
    sample.to_csv(REVIEW_SAMPLE_PATH, index=False)

    print("Building recommendations")
    recommendations = build_recommendations(precision, coverage, topics_joined)
    recommendations.to_csv(RECOMMENDATIONS_PATH, index=False)

    print("Writing reports")
    write_reports(precision, coverage, sample, recommendations)

    print("Phase 5 complete.")
    print(f"  precision rows: {len(precision)}")
    print(f"  coverage rows: {len(coverage)}")
    print(f"  manual review sample rows: {len(sample)}")
    print(f"  recommendations: {len(recommendations)}")


if __name__ == "__main__":
    main()
