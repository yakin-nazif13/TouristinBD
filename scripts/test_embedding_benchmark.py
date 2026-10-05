"""Embedding benchmark tests — BUILD_PLAN section 4.3.

The model loading itself needs torch and runs on the Linux runner
(.github/workflows/phase3-embeddings.yml). Everything around it is testable
here, and it is the part that would silently produce a wrong table:

  1. retrieval accuracy@k, against cases whose answer can be worked out by
     hand — including the one that matters, where a model ranks the true
     translation second;
  2. the triple builder on a synthetic corpus that *does* have original text,
     since the committed one does not;
  3. the builder rejecting pairs that are not a Bangla/English pair at all;
  4. the refusal to benchmark a test set too small to separate models;
  5. the report table being written from results without a model present.

Run:
    .venv/bin/python scripts/test_embedding_benchmark.py
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def test_retrieval_accuracy() -> None:
    print("retrieval accuracy@k")
    import run_phase3_embedding_benchmark as bench

    # Identical sides: every query's true passage is its nearest neighbour.
    vectors = bench.normalise(np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]))
    scores = bench.retrieval_accuracy(vectors, vectors)
    check("perfectly aligned sides score 1.0", scores["acc@1"] == 1.0, str(scores))

    # Three orthogonal queries whose true passages are deliberately permuted,
    # so every query's top hit is someone else's passage.
    identity = np.eye(3)
    permuted = identity[[1, 2, 0]]
    scores = bench.retrieval_accuracy(identity, permuted)
    check("a permuted pairing scores 0 at k=1", scores["acc@1"] == 0.0, str(scores))
    check("but is found within k=5 when n=3", scores["acc@5"] == 1.0, str(scores))

    # The case the metric exists for: the true passage is retrieved, but ranked
    # second. A plain argmax would call this a miss and report nothing else;
    # acc@1 must be 0 while acc@5 is 1.
    #   q0 . p0 = 0.994 (true)   q0 . p1 = 1.000  -> true pair at rank 2
    #   q1 . p1 = 0.000 (true)   q1 . p0 = 0.110  -> true pair at rank 2
    queries = bench.normalise(np.array([[1.0, 0.0], [0.0, 1.0]]))
    passages = bench.normalise(np.array([[0.9, 0.1], [0.99, 0.0]]))
    scores = bench.retrieval_accuracy(queries, passages)
    check("a true passage ranked second gives acc@1 = 0", scores["acc@1"] == 0.0, str(scores))
    check("and acc@5 = 1", scores["acc@5"] == 1.0, str(scores))

    empty = bench.retrieval_accuracy(np.zeros((0, 3)), np.zeros((0, 3)))
    check("an empty set gives NaN, not 0.0 or a crash",
          all(np.isnan(v) for v in empty.values()), str(empty))
    mismatched = bench.retrieval_accuracy(np.eye(3), np.eye(2))
    check("mismatched side lengths give NaN",
          all(np.isnan(v) for v in mismatched.values()), str(mismatched))

    zeros = bench.normalise(np.zeros((2, 3)))
    check("normalise does not divide by zero", np.isfinite(zeros).all())


def _synthetic_corpus(path: Path) -> None:
    """A corpus that has what the committed one lacks: kept original text."""
    rows = []
    bangla = [
        "কুয়াকাটার সমুদ্র সৈকত খুব সুন্দর ছিল",
        "রাতারগুল জলাবন নৌকা দিয়ে ঘুরে দেখলাম",
        "লালবাগ কেল্লার স্থাপত্য অসাধারণ",
        "জাফলং এর পাথর আর নদী দেখতে ভালো লাগলো",
    ]
    english = [
        "The sea beach at Kuakata was very beautiful",
        "We toured the Ratargul swamp forest by boat",
        "The architecture of Lalbagh Fort is extraordinary",
        "The stones and river at Jaflong were lovely to see",
    ]
    for i in range(40):
        j = i % len(bangla)
        rows.append({
            "review_id": f"r{i:03d}",
            "source": "google_maps",
            "place_name": f"Place {j}",
            "review_text_clean": f"{english[j]} (visit {i})",
            "review_text_original": f"{bangla[j]} ({i})",
            "detected_language": "bn",
        })
    # One row that is not a translation pair: both sides English.
    rows.append({
        "review_id": "r900", "source": "google_maps", "place_name": "Place 0",
        "review_text_clean": "Great place and very clean facilities throughout",
        "review_text_original": "Great place and very clean facilities throughout",
        "detected_language": "en",
    })
    # One row whose "original" is English, so it is not a Bangla source either.
    rows.append({
        "review_id": "r901", "source": "google_maps", "place_name": "Place 1",
        "review_text_clean": "The food was good and the staff were helpful",
        "review_text_original": "The food was decent and staff helpful enough",
        "detected_language": "en",
    })
    pd.DataFrame(rows).to_csv(path, index=False)


def test_build_triples() -> None:
    print("\nthe triple builder")
    tmp = Path(tempfile.mkdtemp(prefix="triples_"))
    try:
        data = tmp / "data"
        data.mkdir()
        _synthetic_corpus(data / "processed_reviews.csv")
        os.environ["TOURISTINBD_DATA_DIR"] = str(data)

        import run_phase3_embedding_benchmark as bench
        importlib.reload(bench)

        check("the builder succeeds on a corpus with originals", bench.build_triples() == 0)
        triples = pd.read_csv(data / "embedding_triples.csv")
        check("40 translation pairs are found", len(triples) == 40, str(len(triples)))
        check("the schema is the documented one",
              list(triples.columns) == bench.TRIPLE_COLUMNS, str(list(triples.columns)))
        check("bn_latn is left blank for a person",
              triples["bn_latn"].isna().all() or (triples["bn_latn"].astype(str).str.strip() == "").all(),
              str(triples["bn_latn"].head(2).tolist()))
        check("the English side is English",
              all("Kuakata" in t or "Ratargul" in t or "Lalbagh" in t or "Jaflong" in t
                  for t in triples["en"]))
        # Both rejects: an identical pair and an English-to-English pair.
        check("a non-translation pair is excluded",
              "r900" not in set(triples["review_id"]), "r900 leaked in")
        check("an English-only pair is excluded",
              "r901" not in set(triples["review_id"]), "r901 leaked in")
        check("review_id is kept so a triple traces back to its review",
              triples["review_id"].str.startswith("r").all())
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_refusals() -> None:
    print("\nrefusing a test set too small to mean anything")
    tmp = Path(tempfile.mkdtemp(prefix="triples_small_"))
    try:
        data = tmp / "data"
        data.mkdir()
        os.environ["TOURISTINBD_DATA_DIR"] = str(data)

        import run_phase3_embedding_benchmark as bench
        importlib.reload(bench)

        pd.DataFrame({
            "triple_id": ["T1", "T2"], "review_id": ["a", "b"], "place_name": ["p", "p"],
            "bn": ["ক", "খ"], "en": ["a", "b"], "bn_latn": ["", ""], "source": ["x", "x"],
        }).to_csv(data / "embedding_triples.csv", index=False)

        sys.argv = ["run_phase3_embedding_benchmark.py"]
        check("two triples are refused", bench.main() == 1)
        check("no table is written from a refused run",
              not (data / "phase3_embedding_benchmark.csv").exists())

        # A missing file must behave the same way, not crash.
        (data / "embedding_triples.csv").unlink()
        check("a missing test set is refused the same way", bench.main() == 1)
        check("read_triples returns the documented schema when absent",
              list(bench.read_triples().columns) == bench.TRIPLE_COLUMNS)
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_report_writing() -> None:
    print("\nthe report table (no model needed)")
    tmp = Path(tempfile.mkdtemp(prefix="triples_report_"))
    try:
        data = tmp / "data"
        data.mkdir()
        os.environ["TOURISTINBD_DATA_DIR"] = str(data)

        import run_phase3_embedding_benchmark as bench
        importlib.reload(bench)

        triples = pd.DataFrame({
            "triple_id": [f"T{i}" for i in range(40)],
            "review_id": [f"r{i}" for i in range(40)],
            "place_name": ["p"] * 40, "bn": ["ক"] * 40, "en": ["a"] * 40,
            "bn_latn": [""] * 40, "source": ["x"] * 40,
        })
        results = [
            {"model": "minilm", "model_id": "m1", "n_triples": 40, "dimensions": 384,
             "texts_per_second_cpu": 120.0, "bn_to_en_acc@1": 0.70, "bn_to_en_acc@5": 0.90,
             "en_to_bn_acc@1": 0.68, "en_to_bn_acc@5": 0.88, "n_banglish": 0},
            {"model": "labse", "model_id": "m2", "n_triples": 40, "dimensions": 768,
             "texts_per_second_cpu": 30.0, "bn_to_en_acc@1": 0.85, "bn_to_en_acc@5": 0.97,
             "en_to_bn_acc@1": 0.83, "en_to_bn_acc@5": 0.95, "n_banglish": 0},
        ]
        bench.write_reports(results, triples)
        report = (data / "phase3_embedding_benchmark.md").read_text(encoding="utf-8")
        check("the table is written", "| model |" in report)
        check("the best model is named", "`labse`" in report, report[:400])
        check("the triple count is stated", "**40**" in report)
        check("falling short of 200 is flagged", "provisional" in report)
        check("speed is reported beside accuracy", "texts/s" in report)
        check("the csv is written", (data / "phase3_embedding_benchmark.csv").exists())

        import json
        payload = json.loads((data / "phase3_embedding_benchmark.json").read_text(encoding="utf-8"))
        check("the json records the target", payload["meets_target"] is False, str(payload)[:200])
        check("the json keeps both models", len(payload["results"]) == 2)
    finally:
        os.environ.pop("TOURISTINBD_DATA_DIR", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_prefixes() -> None:
    print("\ninstruction prefixes")
    import run_phase3_embedding_benchmark as bench

    # e5 is trained with query:/passage: and scores materially worse without
    # them. A benchmark that omitted them would look decisive while being
    # misconfigured.
    check("e5 gets its query prefix", bench.QUERY_PREFIX.get("e5-base") == "query: ")
    check("e5 gets its passage prefix", bench.PASSAGE_PREFIX.get("e5-base") == "passage: ")
    check("minilm gets none", bench.QUERY_PREFIX.get("minilm", "") == "")
    check("all four candidates are listed",
          set(bench.CANDIDATES) == {"minilm", "labse", "e5-base", "bge-m3"},
          str(set(bench.CANDIDATES)))

    class StubModel:
        """Records what it was asked to encode, so the prefix can be checked."""

        def __init__(self):
            self.seen: list[str] = []

        def encode(self, texts, **kwargs):
            self.seen.extend(texts)
            return np.ones((len(texts), 4), dtype=np.float32)

    stub = StubModel()
    vectors, seconds = bench.encode(stub, ["hello"], "query: ")
    check("encode applies the prefix", stub.seen == ["query: hello"], str(stub.seen))
    check("encode returns normalised vectors",
          abs(float(np.linalg.norm(vectors[0])) - 1.0) < 1e-6, str(np.linalg.norm(vectors[0])))
    check("encode times itself", seconds >= 0.0)


def main() -> None:
    print("Embedding benchmark tests (BUILD_PLAN 4.3)\n")
    test_retrieval_accuracy()
    test_build_triples()
    test_refusals()
    test_report_writing()
    test_prefixes()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All embedding benchmark tests passed.")


if __name__ == "__main__":
    main()
