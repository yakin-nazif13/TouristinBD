"""
Phase 6 — Sensitivity analysis (MVP hybrid).

Paper target: re-run the full pipeline at 20k / 40k / 60k / 80k reviews.
MVP adaptation: stratified subsamples of the 538-review corpus at
~150 / 250 / 400 / 538 reviews (same step pattern, scaled down).

Hybrid design (safe for later phases):
  - Re-train BERTopic on each subsample (tests topic stability vs data size).
  - Map new topics onto the FIXED Phase 4 preference taxonomy via embeddings
    (no LLM re-run → preference IDs stay stable for Phase 7+).
  - Writes ONLY to data/phase6_* — never overwrites Phase 3–5 artifacts.

Tracks:
  - topic count, preferences covered, avg mapping similarity
  - high-confidence share (sim >= tau_sim)
  - Jaccard similarity of mapped preference-ID sets between consecutive sizes
  - recommended minimum corpus size where consecutive Jaccard change < 5%
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from bertopic import BERTopic
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

REVIEWS_PATH = DATA_DIR / "processed_reviews.csv"
PREFERENCES_PATH = DATA_DIR / "preference_classification.csv"
REFERENCE_MAPPING_PATH = DATA_DIR / "topic_preference_mapping.csv"

OUT_METRICS_CSV = DATA_DIR / "phase6_sensitivity_metrics.csv"
OUT_MAPPINGS_CSV = DATA_DIR / "phase6_sensitivity_mappings.csv"
OUT_REPORT_JSON = DATA_DIR / "phase6_sensitivity_report.json"
OUT_REPORT_MD = DATA_DIR / "phase6_sensitivity_report.md"
OUT_CHART = DATA_DIR / "phase6_sensitivity_chart.png"

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TAU_SIM = 0.4
STABILITY_DELTA = 0.05  # <5% change between consecutive sizes
RANDOM_SEED = 42

# Paper used 20k/40k/60k/80k. MVP scales the same 4-step ladder to |corpus|.
SAMPLE_FRACTIONS = (0.28, 0.46, 0.74, 1.00)  # ≈150 / 250 / 400 / 538 on n=538


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Prefer stratification by source, then place_name when available."""
    if n >= len(df):
        return df.copy()
    rng = np.random.default_rng(seed)
    strata_col = "source" if "source" in df.columns else None
    if strata_col is None:
        idx = rng.choice(len(df), size=n, replace=False)
        return df.iloc[sorted(idx)].reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    groups = list(df.groupby(strata_col, sort=False))
    # proportional allocation, then top-up to exact n
    sizes = []
    for _, g in groups:
        sizes.append(max(1, int(round(n * len(g) / len(df)))))
    # fix rounding drift
    while sum(sizes) > n:
        i = int(np.argmax(sizes))
        if sizes[i] > 1:
            sizes[i] -= 1
        else:
            break
    while sum(sizes) < n:
        deficits = [len(g) - sizes[i] for i, (_, g) in enumerate(groups)]
        i = int(np.argmax(deficits))
        if deficits[i] <= 0:
            break
        sizes[i] += 1

    for (name, g), k in zip(groups, sizes):
        k = min(k, len(g))
        take = g.sample(n=k, random_state=seed + abs(hash(str(name))) % 10_000)
        parts.append(take)
    out = pd.concat(parts, ignore_index=True)
    if len(out) > n:
        out = out.sample(n=n, random_state=seed).reset_index(drop=True)
    return out.reset_index(drop=True)


def adaptive_min_topic_size(n: int) -> int:
    # Keep clusters formable on small subsamples without inventing tiny noise topics.
    return max(3, min(6, n // 40))


def build_texts(df: pd.DataFrame) -> list[str]:
    return [str(t or "").strip() for t in df["review_text_clean"].tolist()]


def keywords_from_name(name: str) -> str:
    parts = str(name or "").split("_")
    if parts and parts[0].lstrip("~").lstrip("-").isdigit():
        parts = parts[1:]
    return ", ".join(p for p in parts if p)


def fit_topics(
    texts: list[str],
    embedder: SentenceTransformer,
    min_topic_size: int,
) -> pd.DataFrame:
    model = BERTopic(
        embedding_model=embedder,
        min_topic_size=min_topic_size,
        nr_topics="auto",
        vectorizer_model=CountVectorizer(ngram_range=(1, 2), stop_words="english"),
        top_n_words=10,
        verbose=False,
        calculate_probabilities=False,
    )
    topics, _ = model.fit_transform(texts)
    info = model.get_topic_info().copy()
    info = info[info["Topic"] != -1].copy()
    rows = []
    for _, row in info.iterrows():
        tid = int(row["Topic"])
        name = str(row.get("Name", f"topic_{tid}"))
        # Prefer c-TF-IDF words when available
        words = model.get_topic(tid) or []
        if isinstance(words, list) and words and isinstance(words[0], tuple):
            kw = ", ".join(w for w, _ in words[:10])
        else:
            kw = keywords_from_name(name)
        rows.append(
            {
                "topic_id": tid,
                "topic_name": name,
                "top_keywords": kw,
                "review_count": int(row["Count"]),
            }
        )
    # attach a short representative label text for embedding
    for r in rows:
        r["topic_text"] = (
            f"{r['topic_name']}. Keywords: {r['top_keywords']}. "
            f"Reviews: {r['review_count']}"
        )
    return pd.DataFrame(rows)


def map_topics_to_preferences(
    topics: pd.DataFrame,
    pref_texts: list[str],
    pref_ids: list[str],
    pref_meta: pd.DataFrame,
    embedder: SentenceTransformer,
) -> pd.DataFrame:
    if topics.empty:
        return pd.DataFrame(
            columns=[
                "topic_id",
                "topic_name",
                "preference_id",
                "preference",
                "similarity",
                "high_confidence",
            ]
        )
    topic_emb = embedder.encode(topics["topic_text"].tolist(), normalize_embeddings=True)
    pref_emb = embedder.encode(pref_texts, normalize_embeddings=True)
    sims = cosine_similarity(topic_emb, pref_emb)
    meta_by_id = {str(r.preference_id): r for r in pref_meta.itertuples(index=False)}
    rows = []
    for i, topic in topics.iterrows():
        best = int(np.argmax(sims[i]))
        sim = float(sims[i, best])
        pid = pref_ids[best]
        meta = meta_by_id[pid]
        rows.append(
            {
                "topic_id": int(topic["topic_id"]),
                "topic_name": topic["topic_name"],
                "review_count": int(topic["review_count"]),
                "preference_id": pid,
                "preference": meta.preference,
                "category": meta.category,
                "similarity": round(sim, 4),
                "high_confidence": sim >= TAU_SIM,
            }
        )
    return pd.DataFrame(rows)


def run_size(
    sample: pd.DataFrame,
    sample_size: int,
    embedder: SentenceTransformer,
    pref_texts: list[str],
    pref_ids: list[str],
    preferences: pd.DataFrame,
) -> tuple[dict, pd.DataFrame]:
    texts = build_texts(sample)
    min_size = adaptive_min_topic_size(sample_size)
    print(f"  fitting BERTopic (n={sample_size}, min_topic_size={min_size})")
    topics = fit_topics(texts, embedder, min_size)
    mappings = map_topics_to_preferences(
        topics, pref_texts, pref_ids, preferences, embedder
    )
    mapped_prefs = set(mappings["preference_id"].astype(str)) if not mappings.empty else set()
    avg_sim = float(mappings["similarity"].mean()) if not mappings.empty else 0.0
    high_conf = (
        float(mappings["high_confidence"].mean()) if not mappings.empty else 0.0
    )
    metrics = {
        "sample_size": sample_size,
        "sample_fraction": None,  # filled by main()
        "min_topic_size": min_size,
        "n_topics": int(len(topics)),
        "n_preferences_covered": int(len(mapped_prefs)),
        "n_preferences_total": int(len(preferences)),
        "coverage_rate": round(len(mapped_prefs) / max(1, len(preferences)), 4),
        "avg_similarity": round(avg_sim, 4),
        "high_confidence_rate": round(high_conf, 4),
        "mapped_preference_ids": sorted(mapped_prefs),
    }
    mappings = mappings.copy()
    mappings.insert(0, "sample_size", sample_size)
    return metrics, mappings


def write_chart(metrics_df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    x = metrics_df["sample_size"]

    axes[0].plot(x, metrics_df["n_topics"], marker="o", color="#F2A93B")
    axes[0].set_title("Topics found")
    axes[0].set_xlabel("Sample size")
    axes[0].set_ylabel("Count")

    axes[1].plot(x, metrics_df["coverage_rate"], marker="o", color="#2F6F4E")
    axes[1].set_title("Preference coverage rate")
    axes[1].set_xlabel("Sample size")
    axes[1].set_ylim(0, 1.05)

    axes[2].plot(x, metrics_df["jaccard_vs_previous"], marker="o", color="#C45C26")
    axes[2].axhline(1 - STABILITY_DELTA, color="gray", linestyle="--", linewidth=1)
    axes[2].set_title("Jaccard vs previous size")
    axes[2].set_xlabel("Sample size")
    axes[2].set_ylim(0, 1.05)

    fig.suptitle("Phase 6 sensitivity (MVP hybrid)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_CHART, dpi=150)
    plt.close(fig)


def recommend_min_size(metrics_df: pd.DataFrame) -> dict:
    """
    Find the smallest sample size where consecutive Jaccard is already
    within (1 - STABILITY_DELTA) of the next larger size — i.e. adding more
    data changes the mapped preference set by <5%.
    """
    rows = metrics_df.sort_values("sample_size").to_dict(orient="records")
    stable_from = None
    for i in range(1, len(rows)):
        j = float(rows[i]["jaccard_vs_previous"])
        if j >= (1.0 - STABILITY_DELTA):
            stable_from = int(rows[i]["sample_size"])
            break
    return {
        "stability_delta": STABILITY_DELTA,
        "recommended_min_corpus_size": stable_from,
        "note": (
            "Smallest subsample where mapped preference-ID set changes <5% "
            "vs the previous size (Jaccard >= 0.95). None means the MVP corpus "
            "never fully stabilized — keep collecting toward the paper's 20k+ ladder."
            if stable_from is None
            else "Mapped preference set is stable at/above this size for the current taxonomy."
        ),
    }


def main() -> None:
    print("Phase 6 — sensitivity analysis (hybrid, non-destructive)")
    reviews = pd.read_csv(REVIEWS_PATH)
    preferences = pd.read_csv(PREFERENCES_PATH)
    if "review_text_clean" not in reviews.columns:
        raise RuntimeError("processed_reviews.csv missing review_text_clean")

    corpus_n = len(reviews)
    sample_sizes = sorted(
        {max(50, int(round(corpus_n * f))) for f in SAMPLE_FRACTIONS}
    )
    sample_sizes = [min(s, corpus_n) for s in sample_sizes]
    # ensure full corpus is included once
    if corpus_n not in sample_sizes:
        sample_sizes.append(corpus_n)
    sample_sizes = sorted(set(sample_sizes))
    print(f"Corpus size: {corpus_n}")
    print(f"Sample ladder: {sample_sizes}")

    pref_ids = preferences["preference_id"].astype(str).tolist()
    pref_texts = [
        f"{r.category} > {r.subcategory} > {r.preference}. {r.description}"
        for r in preferences.itertuples(index=False)
    ]

    print(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
    embedder = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")

    all_metrics: list[dict] = []
    all_mappings: list[pd.DataFrame] = []
    prev_prefs: set[str] | None = None

    for size in sample_sizes:
        print(f"\n=== sample_size={size} ===")
        sample = stratified_sample(reviews, size, seed=RANDOM_SEED + size)
        metrics, mappings = run_size(
            sample, size, embedder, pref_texts, pref_ids, preferences
        )
        metrics["sample_fraction"] = round(size / corpus_n, 4)
        mapped = set(metrics["mapped_preference_ids"])
        if prev_prefs is None:
            metrics["jaccard_vs_previous"] = 1.0
        else:
            metrics["jaccard_vs_previous"] = round(jaccard(prev_prefs, mapped), 4)
        prev_prefs = mapped
        all_metrics.append(metrics)
        all_mappings.append(mappings)
        print(
            f"  topics={metrics['n_topics']}, "
            f"prefs_covered={metrics['n_preferences_covered']}/{metrics['n_preferences_total']}, "
            f"avg_sim={metrics['avg_similarity']:.3f}, "
            f"jaccard_vs_prev={metrics['jaccard_vs_previous']:.3f}"
        )

    # Optional reference row from locked Phase 4 mapping (does not retrain)
    if REFERENCE_MAPPING_PATH.exists():
        ref = pd.read_csv(REFERENCE_MAPPING_PATH)
        ref_prefs = set(ref["preference_id"].astype(str))
        last = all_metrics[-1]["mapped_preference_ids"]
        all_metrics.append(
            {
                "sample_size": corpus_n,
                "sample_fraction": 1.0,
                "min_topic_size": "phase4_reference",
                "n_topics": int(ref["topic_id"].nunique()),
                "n_preferences_covered": int(len(ref_prefs)),
                "n_preferences_total": int(len(preferences)),
                "coverage_rate": round(len(ref_prefs) / max(1, len(preferences)), 4),
                "avg_similarity": round(float(ref["similarity"].mean()), 4),
                "high_confidence_rate": round(
                    float((ref["similarity"] >= TAU_SIM).mean()), 4
                ),
                "mapped_preference_ids": sorted(ref_prefs),
                "jaccard_vs_previous": round(jaccard(set(last), ref_prefs), 4),
                "run_type": "phase4_locked_reference",
            }
        )
        print(
            f"\nReference Phase 4 mapping: prefs={len(ref_prefs)}, "
            f"jaccard_vs_full_retrain={all_metrics[-1]['jaccard_vs_previous']:.3f}"
        )

    for m in all_metrics:
        m.setdefault("run_type", "bertopic_retrain_hybrid")

    metrics_df = pd.DataFrame(all_metrics)
    # store preference id lists as JSON strings for CSV readability
    metrics_df["mapped_preference_ids"] = metrics_df["mapped_preference_ids"].apply(
        lambda xs: json.dumps(xs)
    )
    metrics_df.to_csv(OUT_METRICS_CSV, index=False)

    mappings_df = pd.concat(all_mappings, ignore_index=True) if all_mappings else pd.DataFrame()
    mappings_df.to_csv(OUT_MAPPINGS_CSV, index=False)

    # Chart only the hybrid retrain rows (exclude reference duplicate size if present)
    chart_df = metrics_df[metrics_df["run_type"] == "bertopic_retrain_hybrid"].copy()
    write_chart(chart_df)

    recommendation = recommend_min_size(chart_df)
    report = {
        "design": {
            "mode": "hybrid",
            "description": (
                "BERTopic retrained per subsample; topics mapped to fixed Phase 4 "
                "preferences via embeddings. Phase 3–5 files were not modified."
            ),
            "paper_ladder": [20000, 40000, 60000, 80000],
            "mvp_ladder": sample_sizes,
            "tau_sim": TAU_SIM,
            "stability_delta": STABILITY_DELTA,
            "embedding_model": EMBEDDING_MODEL_NAME,
        },
        "corpus_size": corpus_n,
        "metrics": all_metrics,
        "recommendation": recommendation,
        "outputs": [
            str(OUT_METRICS_CSV.name),
            str(OUT_MAPPINGS_CSV.name),
            str(OUT_CHART.name),
            str(OUT_REPORT_JSON.name),
            str(OUT_REPORT_MD.name),
        ],
    }
    with open(OUT_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    rec_size = recommendation["recommended_min_corpus_size"]
    md = f"""# Phase 6 Sensitivity Report (MVP hybrid)

## What changed (easy language)
- The full paper tests the pipeline at 20k / 40k / 60k / 80k reviews.
- This MVP run uses the same **4-step ladder**, scaled to your **{corpus_n}** reviews:
  `{sample_sizes}`.
- For each size we **re-find topics**, then match them to the **same Phase 4 preference
  list** (no new LLM taxonomy). That keeps later phases stable.
- Results are saved only as `phase6_*` files — Phase 3–5 outputs were **not** overwritten.

## Metrics tracked
- topic count
- how many of the 10 preferences get at least one topic
- average mapping similarity + high-confidence rate (sim ≥ {TAU_SIM})
- Jaccard similarity of the mapped preference set vs the previous sample size

## Results
| sample_size | topics | prefs covered | avg sim | high-conf | Jaccard vs prev |
|------------:|-------:|--------------:|--------:|----------:|----------------:|
"""
    for row in chart_df.itertuples(index=False):
        md += (
            f"| {int(row.sample_size)} | {int(row.n_topics)} | "
            f"{int(row.n_preferences_covered)}/{int(row.n_preferences_total)} | "
            f"{float(row.avg_similarity):.3f} | {float(row.high_confidence_rate):.3f} | "
            f"{float(row.jaccard_vs_previous):.3f} |\n"
        )

    md += f"""
## Recommendation
- Stability rule: consecutive Jaccard ≥ `{1 - STABILITY_DELTA:.2f}` (<{int(STABILITY_DELTA*100)}% change).
- Recommended minimum corpus size (MVP): **{rec_size if rec_size is not None else "not reached — keep collecting data"}**
- {recommendation["note"]}

## Later-phase safety
- Preference IDs (P01–P10) stay the Phase 4 taxonomy.
- Canonical files (`reviews_with_topics.csv`, `topic_preferences.csv`, etc.) unchanged.
- When the corpus grows toward 20k+, re-run this script with a larger ladder; optionally
  switch to a full LLM re-run mode only if you intentionally want a new taxonomy.
"""
    OUT_REPORT_MD.write_text(md, encoding="utf-8")

    print("\nPhase 6 complete.")
    print(f"  metrics → {OUT_METRICS_CSV.name}")
    print(f"  mappings → {OUT_MAPPINGS_CSV.name}")
    print(f"  chart → {OUT_CHART.name}")
    print(f"  report → {OUT_REPORT_MD.name}")
    print(f"  recommended min size → {rec_size}")


if __name__ == "__main__":
    main()
