import argparse
import os
import sys
from pathlib import Path
import pandas as pd
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_scaling as scaling  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
INPUT_PATH = DATA_DIR / "processed_reviews.csv"
OUTPUT_REVIEWS_PATH = DATA_DIR / "reviews_with_topics.csv"
OUTPUT_TOPICS_PATH = DATA_DIR / "topics_summary.csv"
MODEL_DIR = DATA_DIR / "bertopic_model_dir"
CHART_PATH = DATA_DIR / "topic_sizes_chart.png"
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


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
    args = parser.parse_args()

    print(f"Loading reviews from {INPUT_PATH}")
    reviews_df = pd.read_csv(INPUT_PATH)

    if "review_text_clean" not in reviews_df.columns:
        raise ValueError("processed_reviews.csv is missing the review_text_clean column")

    texts = build_texts(reviews_df)

    print(f"Initializing Hugging Face embedding model: {EMBEDDING_MODEL_NAME}")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")

    min_topic_size = args.min_topic_size or scaling.choose_min_topic_size(len(texts))
    nr_topics = scaling.choose_nr_topics(len(texts), args.max_topics)
    print(
        f"Training BERTopic with multilingual sentence embeddings "
        f"(n={len(texts)}, min_topic_size={min_topic_size}, nr_topics={nr_topics}, seed={args.seed})"
    )
    # BERTopic's own UMAP defaults, plus a fixed seed: unseeded UMAP gave a different
    # clustering on every run, so Phase 4-8 results could not be reproduced.
    umap_model = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=args.seed)
    topic_model = BERTopic(
        embedding_model=embedding_model,
        umap_model=umap_model,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        vectorizer_model=CountVectorizer(ngram_range=(1, 2), stop_words="english"),
        top_n_words=10,
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(texts)

    document_info = topic_model.get_document_info(docs=texts)
    reviews_with_topics = reviews_df.reset_index(drop=True).copy()
    reviews_with_topics["topic_id"] = document_info["Topic"].reset_index(drop=True)
    reviews_with_topics["topic_name"] = document_info["Name"].reset_index(drop=True)
    reviews_with_topics.to_csv(OUTPUT_REVIEWS_PATH, index=False)

    topic_info = topic_model.get_topic_info().copy()
    topic_info = topic_info[topic_info["Topic"] != -1].copy()
    topic_info["top_keywords"] = topic_info["Representation"].apply(extract_keywords)
    topic_info = topic_info[["Topic", "Count", "top_keywords", "Name"]].rename(columns={"Name": "topic_name"})
    topic_info.to_csv(OUTPUT_TOPICS_PATH, index=False)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / "bertopic_model.pkl"
    topic_model.save(model_path, serialization="pkl")

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
