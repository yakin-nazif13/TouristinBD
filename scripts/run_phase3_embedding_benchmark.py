"""Phase 3 — embedding model benchmark. BUILD_PLAN section 4.3.

    "Candidates: paraphrase-multilingual-MiniLM-L12-v2 (current), LaBSE,
     intfloat/multilingual-e5-base, BAAI/bge-m3.
     Test set: about 200 triples of (Bangla original, English translation,
     Banglish version), built from real reviews with Google's translations as
     the English side, plus hand-written Banglish.
     Metrics: cross-lingual retrieval accuracy@1 and @5 in both directions;
     encoding speed on CPU.
     Choose the model for Phases 3-4 and the product from this table."

Why this matters beyond a table: every later phase leans on one embedding
model. Section 5.3 resolves entity mentions with it, Phase 6's sensitivity
analysis maps topics to preferences with it, and the product's search ranks
with it. Picking it by measurement rather than by whichever was installed first
is the difference between a defensible choice and an accident.

Two commands:

    python scripts/run_phase3_embedding_benchmark.py --build-triples
    python scripts/run_phase3_embedding_benchmark.py

The first extracts (Bangla original, English translation) pairs from the corpus
— real reviews whose own words Phase 2 kept alongside the platform translation
— and writes `data/embedding_triples.csv` with an empty `bn_latn` column.

**That column is the human input**, and section 4.3 asks for it to be
hand-written: there is no honest way to generate a Banglish rendering of a
Bangla sentence automatically and then use it to score models on how well they
match Banglish. Rows with it blank are still scored on the bn <-> en direction;
the Banglish directions are reported only over the rows that have it.

The benchmark refuses to print a table from a test set too small to mean
anything, rather than reporting an accuracy over nine triples.

Needs sentence-transformers, so on a machine where torch cannot load (Windows
Smart App Control) run it through .github/workflows/phase3-embeddings.yml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_id import script_shares  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
TRIPLES = DATA_DIR / "embedding_triples.csv"
OUT_CSV = DATA_DIR / "phase3_embedding_benchmark.csv"
OUT_MD = DATA_DIR / "phase3_embedding_benchmark.md"
OUT_JSON = DATA_DIR / "phase3_embedding_benchmark.json"

# Section 4.3's candidates. The first is what the project uses today, kept so
# the table says what changing would buy.
CANDIDATES = {
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "labse": "sentence-transformers/LaBSE",
    "e5-base": "intfloat/multilingual-e5-base",
    "bge-m3": "BAAI/bge-m3",
}

# e5 and bge are trained with instruction prefixes and score materially worse
# without them. Leaving them off would make the comparison look decisive when
# it was only misconfigured.
QUERY_PREFIX = {"e5-base": "query: ", "bge-m3": ""}
PASSAGE_PREFIX = {"e5-base": "passage: ", "bge-m3": ""}

TARGET_TRIPLES = 200
# Below this, accuracy@5 over the set is too coarse to separate models: with 20
# triples every model scores a multiple of 5%.
MIN_TRIPLES = 30

TRIPLE_COLUMNS = ["triple_id", "review_id", "place_name", "bn", "en", "bn_latn", "source"]


# --- metrics (pure numpy, so they are testable without torch) ------------


def retrieval_accuracy(queries: np.ndarray, passages: np.ndarray, ks=(1, 5)) -> dict[str, float]:
    """Cross-lingual retrieval accuracy@k for aligned query/passage rows.

    Row i of `queries` is the translation of row i of `passages`, so the
    correct answer for query i is passage i. Both are expected L2-normalised,
    making the dot product a cosine.
    """
    if len(queries) == 0 or len(queries) != len(passages):
        return {f"acc@{k}": float("nan") for k in ks}
    similarity = queries @ passages.T
    # Rank of the true passage for each query: how many score strictly higher.
    true_scores = np.diag(similarity)[:, None]
    ranks = (similarity > true_scores).sum(axis=1) + 1
    return {f"acc@{k}": float((ranks <= k).mean()) for k in ks}


def normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# --- the test set --------------------------------------------------------


def build_triples() -> int:
    """Extract (Bangla original, English translation) pairs from the corpus."""
    if not IN_CORPUS.exists():
        print(f"error: {IN_CORPUS} does not exist; run Phase 2 first")
        return 1

    corpus = pd.read_csv(IN_CORPUS)
    if "review_text_original" not in corpus.columns:
        print(
            "The corpus has no `review_text_original` column, so there are no\n"
            "translation pairs to build a test set from.\n\n"
            "Every committed review was collected through Google's translation with\n"
            "the reviewer's own words discarded (weakness W2, fixed in Phase 1 but\n"
            "only for new batches). Re-scrape with the actor's original-text output\n"
            "enabled — docs/DATA_COLLECTION.md section 2 — and the pairs appear on\n"
            "their own.\n\n"
            f"Writing an empty {TRIPLES.name} so the schema is visible."
        )
        pd.DataFrame(columns=TRIPLE_COLUMNS).to_csv(TRIPLES, index=False)
        return 1

    original = corpus["review_text_original"].astype("string")
    english = corpus["review_text_clean"].astype("string")
    # A usable pair needs Bangla script on one side, English on the other, and
    # the two actually differing — a row where they match was never translated.
    usable = (
        original.notna()
        & english.notna()
        & (original.str.strip() != "")
        & (original != english)
        & original.map(lambda t: script_shares(t)[0] > 0.5 if isinstance(t, str) else False)
        & english.map(lambda t: script_shares(t)[1] > 0.8 if isinstance(t, str) else False)
    )

    rows = corpus[usable]
    triples = pd.DataFrame({
        "triple_id": [f"T{i:04d}" for i in range(1, len(rows) + 1)],
        "review_id": rows["review_id"].astype(str).values,
        "place_name": rows["place_name"].values if "place_name" in rows else "",
        "bn": original[usable].values,
        "en": english[usable].values,
        "bn_latn": "",
        "source": "corpus-translation-pair",
    })
    TRIPLES.parent.mkdir(parents=True, exist_ok=True)
    triples.to_csv(TRIPLES, index=False)

    print(f"wrote {TRIPLES} with {len(triples)} pair(s)")
    print(f"  section 4.3 asks for about {TARGET_TRIPLES}")
    if len(triples) < MIN_TRIPLES:
        print(
            f"\n  Too few to benchmark on ({len(triples)} < {MIN_TRIPLES}). The corpus is\n"
            "  almost entirely translated English with the originals never stored, so\n"
            "  the pairs arrive with the re-scrape and the YouTube pass.\n"
        )
    print(
        "\n  The `bn_latn` column is left blank for a person to fill: section 4.3\n"
        "  asks for hand-written Banglish, and generating it automatically would\n"
        "  mean scoring models against machine output rather than how people\n"
        "  actually write. Rows left blank are still scored bn <-> en."
    )
    return 0


def read_triples() -> pd.DataFrame:
    if not TRIPLES.exists():
        return pd.DataFrame(columns=TRIPLE_COLUMNS)
    frame = pd.read_csv(TRIPLES)
    for column in TRIPLE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame


# --- the benchmark -------------------------------------------------------


def encode(model, texts: list[str], prefix: str = "") -> tuple[np.ndarray, float]:
    """Encode on CPU, returning (normalised vectors, seconds elapsed)."""
    prepared = [prefix + t for t in texts]
    started = time.perf_counter()
    vectors = model.encode(prepared, batch_size=16, show_progress_bar=False,
                           convert_to_numpy=True, normalize_embeddings=False)
    elapsed = time.perf_counter() - started
    return normalise(np.asarray(vectors, dtype=np.float32)), elapsed


def benchmark_model(key: str, model_id: str, triples: pd.DataFrame) -> dict:
    from sentence_transformers import SentenceTransformer

    print(f"\n  {key}  ({model_id})")
    model = SentenceTransformer(model_id, device="cpu")

    bn = triples["bn"].astype(str).tolist()
    en = triples["en"].astype(str).tolist()
    query_prefix = QUERY_PREFIX.get(key, "")
    passage_prefix = PASSAGE_PREFIX.get(key, "")

    bn_vectors, bn_seconds = encode(model, bn, query_prefix)
    en_vectors, en_seconds = encode(model, en, passage_prefix)

    result = {
        "model": key,
        "model_id": model_id,
        "n_triples": len(triples),
        "dimensions": int(bn_vectors.shape[1]),
        "texts_per_second_cpu": round(len(bn + en) / max(1e-9, bn_seconds + en_seconds), 2),
    }
    for direction, (queries, passages) in {
        "bn_to_en": (bn_vectors, en_vectors),
        "en_to_bn": (en_vectors, bn_vectors),
    }.items():
        for metric, value in retrieval_accuracy(queries, passages).items():
            result[f"{direction}_{metric}"] = round(value, 4)

    # The Banglish directions are scored only over rows a person filled in.
    banglish = triples[triples["bn_latn"].astype(str).str.strip() != ""]
    result["n_banglish"] = len(banglish)
    if len(banglish) >= MIN_TRIPLES:
        latn_vectors, _ = encode(model, banglish["bn_latn"].astype(str).tolist(), query_prefix)
        en_subset, _ = encode(model, banglish["en"].astype(str).tolist(), passage_prefix)
        for direction, (queries, passages) in {
            "bnlatn_to_en": (latn_vectors, en_subset),
            "en_to_bnlatn": (en_subset, latn_vectors),
        }.items():
            for metric, value in retrieval_accuracy(queries, passages).items():
                result[f"{direction}_{metric}"] = round(value, 4)
    else:
        print(
            f"    skipping the Banglish directions: {len(banglish)} filled row(s), "
            f"need {MIN_TRIPLES}"
        )

    print(
        f"    bn->en acc@1 {result['bn_to_en_acc@1']:.3f}  "
        f"en->bn acc@1 {result['en_to_bn_acc@1']:.3f}  "
        f"{result['texts_per_second_cpu']} texts/s"
    )
    return result


def write_reports(results: list[dict], triples: pd.DataFrame) -> None:
    frame = pd.DataFrame(results)
    frame.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps({
        "n_triples": int(len(triples)),
        "n_banglish": int((triples["bn_latn"].astype(str).str.strip() != "").sum()),
        "target_triples": TARGET_TRIPLES,
        "meets_target": len(triples) >= TARGET_TRIPLES,
        "results": results,
    }, indent=2) + "\n", encoding="utf-8")

    best = max(results, key=lambda r: r.get("bn_to_en_acc@1", 0))
    lines = [
        "# Phase 3 — Embedding model benchmark",
        "",
        "Cross-lingual retrieval over (Bangla original, English translation) pairs",
        "from the corpus (BUILD_PLAN 4.3). Accuracy@k asks whether the true",
        "translation is in the top k of all candidates, so chance is 1/n.",
        "",
        f"- Triples: **{len(triples)}** (section 4.3 asks for about {TARGET_TRIPLES})",
        f"- With hand-written Banglish: {int((triples['bn_latn'].astype(str).str.strip() != '').sum())}",
        "",
        "| model | dim | bn→en @1 | bn→en @5 | en→bn @1 | en→bn @5 | texts/s (CPU) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        lines.append(
            f"| `{row['model']}` | {row['dimensions']} | {row['bn_to_en_acc@1']:.3f} | "
            f"{row['bn_to_en_acc@5']:.3f} | {row['en_to_bn_acc@1']:.3f} | "
            f"{row['en_to_bn_acc@5']:.3f} | {row['texts_per_second_cpu']} |"
        )
    lines += [
        "",
        f"Best bn→en accuracy@1: **`{best['model']}`** ({best['model_id']}).",
        "",
        "## How to adopt a model",
        "",
        "Set it in the scripts that embed — Phase 3's topic step, Phase 4's",
        "topic-preference mapping and Phase 6 — then re-run Phase 3 onward.",
        "Speed matters as much as accuracy here: the product encodes on CPU on a",
        "free-tier host, so a model that wins by a point and runs four times",
        "slower is not obviously the right choice.",
    ]
    if len(triples) < TARGET_TRIPLES:
        lines += [
            "",
            f"> Fewer than {TARGET_TRIPLES} triples, so treat this ordering as provisional",
            "> and report the triple count beside it.",
        ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-triples", action="store_true", help="extract the test set and exit")
    parser.add_argument(
        "--models",
        default=",".join(CANDIDATES),
        help="comma-separated subset of: " + ", ".join(CANDIDATES),
    )
    args = parser.parse_args()

    if args.build_triples:
        return build_triples()

    triples = read_triples()
    print(f"Phase 3 — embedding benchmark over {len(triples)} triple(s)")
    if len(triples) < MIN_TRIPLES:
        print(
            f"\nRefusing to benchmark: {len(triples)} triple(s), need at least {MIN_TRIPLES}.\n"
            "Accuracy@5 over a set this small cannot separate four models — every\n"
            "score would be a multiple of 1/n and the ordering would be noise.\n\n"
            f"  1. build the test set:  python {Path(__file__).name} --build-triples\n"
            "  2. the pairs come from reviews whose original text was kept, so\n"
            "     re-scrape with original-text output on (docs/DATA_COLLECTION.md)\n"
        )
        return 1

    chosen = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in chosen if m not in CANDIDATES]
    if unknown:
        print(f"error: unknown model(s) {unknown}; choose from {list(CANDIDATES)}")
        return 1

    results = []
    for key in chosen:
        try:
            results.append(benchmark_model(key, CANDIDATES[key], triples))
        except Exception as exc:  # a model that will not load must not lose the rest
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            results.append({
                "model": key, "model_id": CANDIDATES[key], "n_triples": len(triples),
                "dimensions": 0, "texts_per_second_cpu": 0.0, "error": f"{type(exc).__name__}: {exc}",
                "bn_to_en_acc@1": 0.0, "bn_to_en_acc@5": 0.0,
                "en_to_bn_acc@1": 0.0, "en_to_bn_acc@5": 0.0, "n_banglish": 0,
            })

    if not any("error" not in r for r in results):
        print("\nevery model failed to load; no table written")
        return 1

    write_reports(results, triples)
    print(f"\n  wrote {OUT_CSV.name}, {OUT_MD.name}, {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
