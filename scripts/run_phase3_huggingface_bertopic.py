from pathlib import Path
import pandas as pd
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
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
    print(f"Loading reviews from {INPUT_PATH}")
    reviews_df = pd.read_csv(INPUT_PATH)

    if "review_text_clean" not in reviews_df.columns:
        raise ValueError("processed_reviews.csv is missing the review_text_clean column")

    texts = build_texts(reviews_df)

    print(f"Initializing Hugging Face embedding model: {EMBEDDING_MODEL_NAME}")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")

    print("Training BERTopic with multilingual sentence embeddings")
    topic_model = BERTopic(
        embedding_model=embedding_model,
        min_topic_size=6,
        nr_topics="auto",
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
