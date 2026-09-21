"""Phase 6 — the stratified samples must be identical on every run.

The sensitivity analysis (the ~400-review stability floor) is only a result if
someone else can reproduce it. Earlier code seeded each stratum with Python's
built-in `hash()`, which is salted per process, so two runs with the same
RANDOM_SEED drew different samples. This suite runs the sampler in separate
processes with different PYTHONHASHSEED values and demands identical output.

The heavy research imports (BERTopic, sentence-transformers, ...) are stubbed,
so this runs in CI without torch.

Run:
    .venv/bin/python scripts/test_phase6_reproducibility.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PASSED: list[str] = []
FAILED: list[str] = []

# Imports the sampler with stand-ins for anything heavy that is not installed,
# draws each size in the MVP ladder, and prints the chosen review ids.
PROBE = r"""
import sys, types, importlib
sys.path.insert(0, {scripts!r})
for name in ("bertopic", "sentence_transformers", "matplotlib", "matplotlib.pyplot",
             "sklearn", "sklearn.feature_extraction", "sklearn.feature_extraction.text",
             "sklearn.metrics", "sklearn.metrics.pairwise"):
    try:
        importlib.import_module(name)
    except Exception:
        mod = types.ModuleType(name)
        for attr in ("BERTopic", "SentenceTransformer", "CountVectorizer", "cosine_similarity"):
            setattr(mod, attr, object)
        sys.modules[name] = mod
if "matplotlib" in sys.modules and not hasattr(sys.modules["matplotlib"], "pyplot"):
    sys.modules["matplotlib"].pyplot = sys.modules["matplotlib.pyplot"]
import pandas as pd
import run_phase6_sensitivity_analysis as p6
df = pd.read_csv(p6.REVIEWS_PATH)
for frac in p6.SAMPLE_FRACTIONS:
    n = int(round(len(df) * frac))
    ids = p6.stratified_sample(df, n, p6.RANDOM_SEED)["review_id"].astype(str).tolist()
    print(n, ",".join(ids))
"""


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def draw(hash_seed: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    code = PROBE.format(scripts=str(REPO_ROOT / "scripts"))
    return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True)


def main() -> None:
    print("Phase 6 — reproducibility of the stratified samples")
    runs = {seed: draw(seed) for seed in ("0", "1", "12345")}
    for seed, result in runs.items():
        check(f"sampler runs (PYTHONHASHSEED={seed})", result.returncode == 0, result.stderr[-400:])
    if FAILED:
        finish()

    outputs = {seed: r.stdout for seed, r in runs.items()}
    check(
        "identical samples under different PYTHONHASHSEED values",
        len(set(outputs.values())) == 1,
        "samples differ between processes — a salted hash() is back in the sampler",
    )

    lines = outputs["0"].strip().splitlines()
    sizes = [int(line.split(" ", 1)[0]) for line in lines]
    check("one sample per size in the ladder", len(lines) == 4, f"{len(lines)} lines")
    for line in lines:
        n, ids = line.split(" ", 1)
        id_list = ids.split(",")
        check(f"sample of {n} has exactly {n} unique reviews",
              len(id_list) == int(n) == len(set(id_list)), f"{len(id_list)} ids")
    check("sizes increase", sizes == sorted(sizes), str(sizes))

    source = (REPO_ROOT / "scripts" / "run_phase6_sensitivity_analysis.py").read_text()
    check("no built-in hash() in the Phase 6 script", "hash(str(" not in source, "found hash(str(")
    finish()


def finish() -> None:
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 6 reproducibility tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
