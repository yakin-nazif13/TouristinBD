"""Phase 5 — tests for the human-validation tooling.

Covers the statistics against published reference values, the blinding of the
annotator sheet, and the full label -> agreement -> write-back flow on a
throwaway copy of the data directory (the real labels are never touched).

Run:
    .venv/bin/python scripts/test_phase5_human_validation.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import compute_human_agreement as agree  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
CONTEXT_FILES = ("phase5_manual_review_sample.csv", "topics_summary.csv",
                 "reviews_with_topics.csv", "preference_classification.csv")
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def run(script: str, *args: str, data_dir: Path, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data_dir)}
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / script), *args],
                          cwd=REPO_ROOT, env=env, input=stdin, capture_output=True, text=True)


def test_statistics() -> None:
    print("\nstatistics — reference values")
    # 2x2 table [[20, 5], [10, 15]]: po = 0.70, pe = 0.50 -> kappa = 0.40.
    a = [1] * 20 + [1] * 5 + [0] * 10 + [0] * 15
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    check("Cohen's kappa on a textbook 2x2 table is 0.40", abs(agree.cohen_kappa(a, b) - 0.40) < 1e-9,
          str(agree.cohen_kappa(a, b)))
    check("identical varied ratings give kappa 1", agree.cohen_kappa([0, 1, 1, 0], [0, 1, 1, 0]) == 1.0, "")
    check("a constant rater pair is undefined, not 1", agree.cohen_kappa([1, 1], [1, 1]) is None, "")
    check("systematic disagreement is negative", agree.cohen_kappa([0, 1, 0, 1], [1, 0, 1, 0]) < 0, "")

    # Fleiss (1971) worked example as reproduced on Wikipedia: kappa = 0.210.
    table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    k = agree.fleiss_kappa(table)
    check("Fleiss' kappa reproduces the published 0.210 example", round(k, 3) == 0.210, str(k))
    check("Landis & Koch bands", agree.interpret_kappa(0.65) == "substantial"
          and agree.interpret_kappa(-0.1).startswith("poor"), "")
    s = agree.binary_scores([1, 1, 0, 0], [1, 0, 1, 0])
    check("precision / recall / F1", (s["precision"], s["recall"], s["f1"]) == (0.5, 0.5, 0.5), str(s))


def test_blinding(data: Path) -> None:
    print("\nlabelling sheet — blinding")
    result = run("label_validation_sample.py", "--annotator", "Alpha", "--export-sheet", data_dir=data)
    check("the sheet exports", result.returncode == 0, result.stderr[-300:])
    sheet = pd.read_csv(data / "human_labels" / "labels_alpha.csv")
    check("50 pairs, one row each", len(sheet) == 50 and sheet["pair_key"].is_unique, str(len(sheet)))
    leaked = {"similarity", "pair_type", "expected_relation", "interpreted_label"} & set(sheet.columns)
    check("no similarity, pair type, expected answer or LLM label in the sheet", not leaked, str(leaked))
    check("every pair shows real example reviews", sheet["topic_examples"].str.len().gt(50).all(), "")
    check("every pair shows the preference description",
          sheet["preference_description"].fillna("").str.len().gt(20).all(), "")

    run("label_validation_sample.py", "--annotator", "beta", "--export-sheet", data_dir=data)
    other = pd.read_csv(data / "human_labels" / "labels_beta.csv")
    check("annotators see different orders", sheet["pair_key"].tolist() != other["pair_key"].tolist(), "")
    again = build_again(data, "alpha")
    check("an annotator's order is stable across machines", again == sheet["pair_key"].tolist(), "")
    shutil.rmtree(data / "human_labels")


def build_again(data: Path, name: str) -> list[str]:
    code = ("import sys; sys.path.insert(0, %r); import label_validation_sample as l; "
            "print(','.join(l.build_blinded_sheet(%r)['pair_key']))") % (str(REPO_ROOT / "scripts"), name)
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data), "PYTHONHASHSEED": "999"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    return out.stdout.strip().split(",")


def test_end_to_end(data: Path) -> None:
    print("\nlabel -> agreement -> write-back")
    # Interactive session: answer three, add a note, quit; then resume and finish.
    result = run("label_validation_sample.py", "--annotator", "yakin", data_dir=data, stdin="1\n0\nn\nunsure\n1\nq\n")
    check("the interactive session exits cleanly", result.returncode == 0, result.stderr[-300:])
    partial = pd.read_csv(data / "human_labels" / "labels_yakin.csv")
    check("answers are saved after every pair", int(partial["human_label"].notna().sum()) == 3,
          str(partial["human_label"].notna().sum()))
    raw = (data / "human_labels" / "labels_yakin.csv").read_text()
    check("labels are stored as 1/0, not 1.0/0.0", ",1.0," not in raw and ",0.0," not in raw, "floats found")

    sample = pd.read_csv(data / "phase5_manual_review_sample.csv")
    sample["pair_key"] = [agree.pair_key(t, p) for t, p in zip(sample["topic_id"], sample["preference_id"])]
    truth = dict(zip(sample["pair_key"], sample["expected_relation"].astype(int)))

    result = run("compute_human_agreement.py", data_dir=data)
    check("the report refuses incomplete files by default", result.returncode != 0, result.stdout[-200:])

    # Four synthetic annotators: two agree with the pipeline everywhere, one
    # flips 5 pairs, one flips a different 5 -> known ties and known kappas.
    keys = list(truth)
    flips = {"farhan": set(keys[:5]), "rifat": set(keys[5:10])}
    for name in ("yakin", "tanisha", "farhan", "rifat"):
        order = pd.read_csv(data / "human_labels" / "labels_yakin.csv") if name == "yakin" else None
        sheet = order if order is not None else _export(data, name)
        sheet["human_label"] = [1 - truth[k] if k in flips.get(name, set()) else truth[k] for k in sheet["pair_key"]]
        sheet.to_csv(data / "human_labels" / f"labels_{name}.csv", index=False)

    result = run("compute_human_agreement.py", "--write-back", data_dir=data)
    check("the report runs on complete files", result.returncode == 0, result.stdout[-400:] + result.stderr[-400:])
    report = json.loads((data / "phase5_human_validation_report.json").read_text())
    check("six annotator pairs are compared", len(report["pairwise_cohen_kappa"]) == 6,
          str(len(report["pairwise_cohen_kappa"])))
    check("no ties: every flipped pair is outvoted 3-1", report["ties"] == [], str(report["ties"]))
    p = report["pipeline_vs_consensus"]
    check("consensus equals the pipeline -> precision and recall 1.0",
          p["precision"] == 1.0 and p["recall"] == 1.0, str(p))
    perfect = [r for r in report["pairwise_cohen_kappa"] if set(r["annotators"]) == {"tanisha", "yakin"}][0]
    check("identical annotators get kappa 1.0", perfect["cohen_kappa"] == 1.0, str(perfect))
    check("disagreements are listed for adjudication", len(report["disagreements"]) == 10,
          str(len(report["disagreements"])))
    check("a markdown report is written", (data / "phase5_human_validation_report.md").exists(), "")
    written = pd.read_csv(data / "phase5_manual_review_sample.csv")
    check("--write-back fills human_label for all 50 pairs", written["human_label"].notna().sum() == 50,
          str(written["human_label"].notna().sum()))

    # A 2-2 split must become a tie, never a silently broken label.
    for name in ("farhan", "rifat"):
        sheet = pd.read_csv(data / "human_labels" / f"labels_{name}.csv")
        sheet["human_label"] = [1 - truth[k] if k == keys[20] else v for k, v in zip(sheet["pair_key"], sheet["human_label"])]
        sheet.to_csv(data / "human_labels" / f"labels_{name}.csv", index=False)
    run("compute_human_agreement.py", data_dir=data)
    report = json.loads((data / "phase5_human_validation_report.json").read_text())
    check("a 2-2 split is reported as a tie", report["ties"] == [keys[20]], str(report["ties"]))
    check("ties are excluded from the precision/recall sample", report["pipeline_vs_consensus"]["n"] == 49,
          str(report["pipeline_vs_consensus"]["n"]))

    bad = pd.read_csv(data / "human_labels" / "labels_rifat.csv")
    bad.loc[0, "human_label"] = 2
    bad.to_csv(data / "human_labels" / "labels_rifat.csv", index=False)
    result = run("compute_human_agreement.py", data_dir=data)
    check("a label other than 0/1 is rejected", result.returncode != 0 and "not 0 or 1" in result.stdout,
          result.stdout[-300:])


def _export(data: Path, name: str) -> pd.DataFrame:
    run("label_validation_sample.py", "--annotator", name, "--export-sheet", data_dir=data)
    return pd.read_csv(data / "human_labels" / f"labels_{name}.csv")


def main() -> None:
    print("Phase 5 — human validation tooling tests")
    test_statistics()
    with tempfile.TemporaryDirectory() as raw:
        data = Path(raw)
        for name in CONTEXT_FILES:
            shutil.copy2(DATA_DIR / name, data / name)
        test_blinding(data)
        test_end_to_end(data)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 5 human-validation tests passed.")


if __name__ == "__main__":
    main()
