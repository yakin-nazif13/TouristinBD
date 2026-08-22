"""Research-facing endpoints: Phase 5 validation and Phase 6 sensitivity.

These exist so the dissertation figures can be regenerated from the API instead
of by re-reading CSVs by hand.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from backend import db

router = APIRouter(prefix="/api/research", tags=["research"])

# Matches the stability rule stated in data/phase6_sensitivity_report.md.
STABILITY_THRESHOLD = 0.95


@router.get("/validation", response_model=dict)
def validation(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Phase 5 bidirectional validation: precision, coverage, and recommendations."""
    precision = db.rows(
        conn,
        "SELECT vp.*, t.interpreted_label AS topic_label FROM validation_precision vp "
        "LEFT JOIN topics t ON t.topic_id = vp.topic_id ORDER BY vp.topic_id",
    )
    coverage = db.rows(
        conn,
        "SELECT vc.*, p.preference_label, p.preference_type FROM validation_coverage vc "
        "LEFT JOIN preferences p ON p.preference_id = vc.preference_id "
        "ORDER BY vc.mapped_topic_count DESC, vc.preference_id",
    )
    recommendations = db.rows(
        conn,
        "SELECT type, target_id, severity, details, suggested_action "
        "FROM validation_recommendations ORDER BY severity, target_id",
    )
    sample = db.one(
        conn,
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN human_label IS NOT NULL AND human_label <> '' THEN 1 ELSE 0 END) "
        "AS labelled FROM validation_manual_sample",
    ) or {"total": 0, "labelled": 0}

    def rate(items: list[dict], col: str, value: str) -> float | None:
        if not items:
            return None
        return round(sum(1 for i in items if i.get(col) == value) / len(items), 4)

    return {
        "direction1_precision": {
            "topics_checked": len(precision),
            "pass_rate": rate(precision, "precision_status", "pass"),
            "low_similarity_flags": sum(1 for r in precision if r.get("low_similarity_flag")),
            "ambiguous_flags": sum(1 for r in precision if r.get("ambiguous_flag")),
            "rows": precision,
        },
        "direction2_coverage": {
            "preferences_checked": len(coverage),
            "adequate_rate": rate(coverage, "coverage_status", "adequate"),
            "under_coverage": sum(
                1 for r in coverage if r.get("coverage_status") == "under_coverage"
            ),
            "rows": coverage,
        },
        "recommendations": recommendations,
        "manual_review_sample": {
            "total_pairs": int(sample.get("total") or 0),
            "labelled_pairs": int(sample.get("labelled") or 0),
            "note": (
                "Human labels are entered in data/phase5_manual_review_sample.csv "
                "(human_label column) and picked up on the next database rebuild."
            ),
        },
    }


@router.get("/validation/sample", response_model=list[dict])
def validation_sample(
    conn: sqlite3.Connection = Depends(db.get_conn),
    pair_type: str | None = Query(None, description="e.g. mapped_positive, hard_negative"),
    labelled: bool | None = Query(None, description="Filter by whether human_label is filled"),
) -> list[dict]:
    """The 50-pair manual review sample, for building a labelling UI later."""
    where: list[str] = []
    params: list = []
    if pair_type:
        where.append("LOWER(pair_type) = LOWER(?)")
        params.append(pair_type)
    if labelled is True:
        where.append("human_label IS NOT NULL AND human_label <> ''")
    elif labelled is False:
        where.append("(human_label IS NULL OR human_label = '')")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return db.rows(
        conn,
        f"SELECT * FROM validation_manual_sample {clause} "
        "ORDER BY pair_type, similarity DESC",
        params,
    )


@router.get("/sensitivity", response_model=dict)
def sensitivity(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Phase 6 sensitivity ladder: how coverage stabilizes with corpus size."""
    metrics = db.rows(
        conn, "SELECT * FROM sensitivity_metrics ORDER BY run_type, sample_size"
    )
    retrained = sorted(
        (m for m in metrics if m.get("run_type") == "bertopic_retrain_hybrid"),
        key=lambda m: m["sample_size"],
    )

    # Phase 6's stability rule: the mapped preference set is stable from the
    # smallest rung whose Jaccard-vs-previous, and every rung after it, clears
    # the threshold. The first rung is skipped — it has no predecessor, so its
    # Jaccard is 1.0 by convention rather than by evidence.
    stable_from = None
    for i in range(1, len(retrained)):
        if all(
            (m.get("jaccard_vs_previous") or 0) >= STABILITY_THRESHOLD
            for m in retrained[i:]
        ):
            stable_from = retrained[i]["sample_size"]
            break

    return {
        "metrics": metrics,
        "stability_threshold": STABILITY_THRESHOLD,
        "recommended_min_corpus_size": stable_from
        or (retrained[-1]["sample_size"] if retrained else None),
        "note": (
            "recommended_min_corpus_size is the smallest sample size from which the "
            f"mapped preference set stays stable (Jaccard vs previous rung >= "
            f"{STABILITY_THRESHOLD} for that rung and all larger ones). The first "
            "rung is excluded because it has no predecessor to compare against."
        ),
    }


@router.get("/sensitivity/mappings", response_model=list[dict])
def sensitivity_mappings(
    conn: sqlite3.Connection = Depends(db.get_conn),
    sample_size: int | None = None,
) -> list[dict]:
    """Per-rung topic→preference mappings from the sensitivity re-runs."""
    clause, params = "", []
    if sample_size is not None:
        clause, params = "WHERE sample_size = ?", [sample_size]
    return db.rows(
        conn,
        f"SELECT * FROM sensitivity_mappings {clause} "
        "ORDER BY sample_size, review_count DESC",
        params,
    )


@router.get("/statistical-tests", response_model=dict)
def statistical_tests(conn: sqlite3.Connection = Depends(db.get_conn)) -> dict:
    """Phase 7 nonparametric tests, carried through the build as-is."""
    payload = db.meta_json(conn, "phase7_statistical_tests")
    if not payload:
        return {
            "available": False,
            "note": "data/phase7_statistical_tests.json was absent at build time.",
        }
    return {"available": True, **payload}
