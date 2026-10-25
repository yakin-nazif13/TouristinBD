import argparse
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_scaling as scaling  # noqa: E402
import topic_embedding  # noqa: E402
from topic_embedding import STOP_WORDS, TOKEN_PATTERN  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
INPUT_PATH = DATA_DIR / "processed_reviews.csv"
OUTPUT_REVIEWS_PATH = DATA_DIR / "reviews_with_topics.csv"
OUTPUT_TOPICS_PATH = DATA_DIR / "topics_summary.csv"
MODEL_DIR = DATA_DIR / "bertopic_model_dir"
CHART_PATH = DATA_DIR / "topic_sizes_chart.png"
EMBEDDING_MODEL_NAME = topic_embedding.CLUSTER_MODEL_NAME
BANGLA_LABELS = ("bn", "bn-en-mixed")  # detected_language values for Bangla-script reviews
BANGLA_MAX_TOPICS = 20


def reassign_outliers(
    embeddings: np.ndarray, topics: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Give every BERTopic outlier (-1) the topic whose centre it is closest to.

    HDBSCAN leaves reviews it cannot place in a dense cluster as outliers, and an outlier
    contributes nothing to any preference. Here each one joins the nearest topic by cosine
    similarity to the topic's centroid (the mean embedding of its clustered reviews). The
    similarity is kept so a reassigned review can be told apart from a clustered one and
    filtered by confidence. Topic keywords are NOT recomputed: they describe the clusters
    the model actually found.

    Returns (final topics, per-review similarity to the assigned topic, reassigned mask).
    """
    topics = np.asarray(topics).copy()
    unit = embeddings / np.clip(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12, None)
    real = sorted(int(t) for t in set(topics.tolist()) if t != -1)
    if not real:
        return topics, np.zeros(len(topics)), np.zeros(len(topics), dtype=bool)
    centroids = np.vstack([unit[topics == t].mean(axis=0) for t in real])
    centroids /= np.clip(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12, None)

    sims = np.zeros(len(topics))
    clustered = topics != -1
    index = {t: i for i, t in enumerate(real)}
    sims[clustered] = [
        float(unit[i] @ centroids[index[int(topics[i])]]) for i in np.flatnonzero(clustered)
    ]
    outliers = np.flatnonzero(~clustered)
    if len(outliers):
        scores = unit[outliers] @ centroids.T
        best = scores.argmax(axis=1)
        topics[outliers] = np.array(real)[best]
        sims[outliers] = scores[np.arange(len(outliers)), best]
    return topics, sims, ~clustered


def build_texts(df: pd.DataFrame) -> list[str]:
    texts = []
    for _, row in df.iterrows():
        text = str(row.get("review_text_clean", "") or "").strip()
        if not text:
            texts.append("")
            continue
        texts.append(text)
    return texts


def extract_keywords(rep):
    """Extract keywords from BERTopic's representation format."""
    if isinstance(rep, str):
        # Simpler string representation
        return rep
    elif isinstance(rep, list) and rep and all(isinstance(item, str) for item in rep):
        # BERTopic's default: a plain list of words
        return ", ".join(rep)
    elif isinstance(rep, list) and all(isinstance(item, tuple) and len(item) == 2 for item in rep):
        # Tuple representation (word, probability)
        return ", ".join([word for word, _ in rep])
    else:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3: multilingual BERTopic over processed_reviews.csv")
    parser.add_argument("--seed", type=int, default=scaling.SEED,
                        help="UMAP random seed, so a re-run gives the same topics (default %(default)s)")
    parser.add_argument("--min-topic-size", type=int, default=0,
                        help="smallest cluster; default scales with corpus size (6 at ~540 reviews, ~40 at 10k)")
    parser.add_argument("--max-topics", type=int, default=0,
                        help="reduce to at most this many topics; default 'auto' up to 2000 reviews, "
                             f"{scaling.LARGE_CORPUS_MAX_TOPICS} above that")
    parser.add_argument("--keep-outliers", action="store_true",
                        help="leave BERTopic's -1 outliers unassigned (the pre-2026-10 behaviour)")
    parser.add_argument("--no-language-split", action="store_true",
                        help="cluster Bangla and other reviews together (they then form separate "
                             "topics by language and one huge generic Bangla topic)")
    parser.add_argument("--max-topics-bangla", type=int, default=BANGLA_MAX_TOPICS,
                        help="cap on the Bangla group's topics (default %(default)s)")
    parser.add_argument("--embedding-cache", default="",
                        help="optional .npy path: reuse embeddings from an earlier run on the same texts")
    args = parser.parse_args()

    print(f"Loading reviews from {INPUT_PATH}")
    reviews_df = pd.read_csv(INPUT_PATH).reset_index(drop=True)

    if "review_text_clean" not in reviews_df.columns:
        raise ValueError("processed_reviews.csv is missing the review_text_clean column")

    texts = build_texts(reviews_df)

    print(f"Initializing Hugging Face embedding model: {EMBEDDING_MODEL_NAME}")
    embedding_model = topic_embedding.load_cluster_encoder()

    # Embed once, so the same vectors serve the clustering and the outlier reassignment.
    cache = Path(args.embedding_cache) if args.embedding_cache else None
    if cache is not None and cache.exists() and np.load(cache).shape[0] == len(texts):
        embeddings = np.load(cache)
        print(f"Reusing {len(texts)} embeddings from {cache}")
    else:
        embeddings = np.asarray(embedding_model.encode(texts, show_progress_bar=False))
        if cache is not None:
            np.save(cache, embeddings)

    # Bangla-script reviews are clustered on their own. Even with a model that reads Bengali,
    # a Bangla review sits nearer other Bangla reviews than an English one about the same place,
    # so in one pass 4,000 of them collapsed into a single generic "nice place" topic, and the
    # preference that topic mapped to was credited with every Bangla park and fort review.
    if args.no_language_split or "detected_language" not in reviews_df.columns:
        groups = [("all", np.ones(len(texts), dtype=bool), args.max_topics)]
    else:
        is_bangla = reviews_df["detected_language"].isin(BANGLA_LABELS).to_numpy()
        groups = [("other", ~is_bangla, args.max_topics), ("bangla", is_bangla, args.max_topics_bangla)]
        groups = [g for g in groups if g[1].sum() >= 2 * scaling.MIN_TOPIC_SIZE_FLOOR]

    raw_topics = np.full(len(texts), -1)
    final_topics = np.full(len(texts), -1)
    similarity = np.zeros(len(texts))
    reassigned = np.zeros(len(texts), dtype=bool)
    names: dict[int, str] = {}
    topic_rows: list[pd.DataFrame] = []
    offset = 0
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for label, mask, cap in groups:
        idx = np.flatnonzero(mask)
        g_texts = [texts[i] for i in idx]
        min_topic_size = args.min_topic_size or scaling.choose_min_topic_size(len(idx))
        nr_topics = scaling.choose_nr_topics(len(idx), cap)
        print(
            f"Training BERTopic on the {label} group "
            f"(n={len(idx)}, min_topic_size={min_topic_size}, nr_topics={nr_topics}, seed={args.seed})"
        )
        # BERTopic's own UMAP defaults, plus a fixed seed: unseeded UMAP gave a different
        # clustering on every run, so Phase 4-8 results could not be reproduced.
        umap_model = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=args.seed)
        topic_model = BERTopic(
            embedding_model=embedding_model,
            umap_model=umap_model,
            min_topic_size=min_topic_size,
            nr_topics=nr_topics,
            vectorizer_model=CountVectorizer(ngram_range=(1, 2), stop_words=STOP_WORDS, token_pattern=TOKEN_PATTERN),
            top_n_words=10,
            verbose=False,
        )
        topic_model.fit_transform(g_texts, embeddings[idx])
        g_raw = topic_model.get_document_info(docs=g_texts)["Topic"].to_numpy()
        info = topic_model.get_topic_info().copy()

        if args.keep_outliers:
            g_final, g_sim, g_moved = g_raw.copy(), np.zeros(len(idx)), np.zeros(len(idx), dtype=bool)
        else:
            g_final, g_sim, g_moved = reassign_outliers(embeddings[idx], g_raw)
            print(f"  reassigned {int(g_moved.sum())} of {len(idx)} outlier review(s) to the nearest {label} topic")

        # Global ids: this group's topics follow the previous group's.
        shift = lambda a: np.where(a >= 0, a + offset, a)  # noqa: E731
        raw_topics[idx], final_topics[idx] = shift(g_raw), shift(g_final)
        similarity[idx], reassigned[idx] = g_sim, g_moved

        info = info[info["Topic"] != -1].copy()
        info["top_keywords"] = info["Representation"].apply(extract_keywords)
        info["Count"] = info["Topic"].map(pd.Series(g_final).value_counts()).fillna(0).astype(int)
        # BERTopic names a topic "<local id>_<words>"; re-stamp the global id.
        info["topic_name"] = [
            f"{int(t) + offset}_{str(n).split('_', 1)[1] if '_' in str(n) else n}"
            for t, n in zip(info["Topic"], info["Name"])
        ]
        info["Topic"] = info["Topic"] + offset
        info["language_group"] = label
        topic_rows.append(info[["Topic", "Count", "top_keywords", "topic_name", "language_group"]])
        names.update(dict(zip(info["Topic"], info["topic_name"])))
        suffix = "" if label in ("all", "other") else f"_{label}"
        model_path = MODEL_DIR / f"bertopic_model{suffix}.pkl"
        topic_model.save(model_path, serialization="pkl")
        offset += len(info)

    reviews_with_topics = reviews_df.copy()
    reviews_with_topics["topic_id"] = final_topics
    reviews_with_topics["topic_name"] = [names.get(int(t), "") for t in final_topics]
    reviews_with_topics["topic_id_raw"] = raw_topics
    reviews_with_topics["topic_assignment"] = np.where(reassigned, "reassigned", "cluster")
    reviews_with_topics["topic_similarity"] = np.round(similarity, 4)
    reviews_with_topics.to_csv(OUTPUT_REVIEWS_PATH, index=False)
    print(f"Reassigned {int(reassigned.sum())} of {len(raw_topics)} review(s) in total")

    topic_info = pd.concat(topic_rows, ignore_index=True)
    topic_info.to_csv(OUTPUT_TOPICS_PATH, index=False)
    model_path = MODEL_DIR / "bertopic_model.pkl"

    chart_df = topic_info.sort_values("Count", ascending=False)
    plt.figure(figsize=(12, 6))
    plt.bar(chart_df["topic_name"].astype(str), chart_df["Count"], color="#F2A93B")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Review count")
    plt.title("BERTopic topic sizes (Hugging Face embeddings)")
    plt.tight_layout()
    plt.savefig(CHART_PATH, dpi=150)
    plt.close()

    print(f"Saved topic assignments to {OUTPUT_REVIEWS_PATH}")
    print(f"Saved topic summary to {OUTPUT_TOPICS_PATH}")
    print(f"Saved BERTopic model to {model_path}")
    print(f"Saved topic chart to {CHART_PATH}")


if __name__ == "__main__":
    main()
