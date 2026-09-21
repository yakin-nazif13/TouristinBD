"""
Phase 5 — inter-annotator agreement and human-judged mapping quality.

Reads every `data/human_labels/labels_<name>.csv` written by
`scripts/label_validation_sample.py` and reports:

  * pairwise Cohen's kappa and raw agreement for every pair of annotators
  * Fleiss' kappa across all annotators
  * a majority ("consensus") label per pair; ties are listed for adjudication
    and excluded from the accuracy figures rather than broken arbitrarily
  * the pipeline's quality against that consensus: precision, recall, F1 and
    accuracy of `expected_relation` (1 = the pipeline maps this topic to this
    preference), plus how often humans said "yes" within each pair type

Outputs:
    data/phase5_human_validation_report.json
    data/phase5_human_validation_report.md

With --write-back the consensus label is also written into the `human_label`
column of data/phase5_manual_review_sample.csv (ties stay blank), so the next
`build_phase8_database.py` run serves it through the API. Re-running Phase 5
regenerates that CSV with blank labels, but the per-annotator files in
data/human_labels/ are untouched, so just run this script again afterwards.

Run:
    python scripts/compute_human_agreement.py                  # needs every file complete
    python scripts/compute_human_agreement.py --allow-partial  # progress check
    python scripts/compute_human_agreement.py --write-back
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

SAMPLE_CSV = DATA_DIR / "phase5_manual_review_sample.csv"
LABELS_DIR = DATA_DIR / "human_labels"
OUT_JSON = DATA_DIR / "phase5_human_validation_report.json"
OUT_MD = DATA_DIR / "phase5_human_validation_report.md"

MIN_ANNOTATORS = 2


# ---------------------------------------------------------------------------
# Statistics (plain Python so CI needs no scikit-learn)


def cohen_kappa(a: list[int], b: list[int]) -> float | None:
    """Cohen's kappa for two raters over the same items. None if undefined."""
    if len(a) != len(b) or not a:
        raise ValueError("raters must label the same, non-empty set of items")
    n = len(a)
    categories = sorted(set(a) | set(b))
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in categories)
    if expected == 1.0:
        # Both raters used one identical category throughout: agreement is
        # perfect but chance-corrected agreement is undefined.
        return None
    return (observed - expected) / (1 - expected)


def fleiss_kappa(counts: list[list[int]]) -> float | None:
    """Fleiss' kappa. `counts[i][j]` = raters who put item i in category j."""
    if not counts:
        raise ValueError("no items")
    raters = sum(counts[0])
    if raters < 2 or any(sum(row) != raters for row in counts):
        raise ValueError("every item needs the same number (>= 2) of ratings")
    n_items = len(counts)
    n_cats = len(counts[0])
    p_j = [sum(row[j] for row in counts) / (n_items * raters) for j in range(n_cats)]
    p_i = [(sum(c * c for c in row) - raters) / (raters * (raters - 1)) for row in counts]
    p_bar = sum(p_i) / n_items
    p_e = sum(p * p for p in p_j)
    if p_e == 1.0:
        return None
    return (p_bar - p_e) / (1 - p_e)


def interpret_kappa(k: float | None) -> str:
    """Landis & Koch (1977) bands — the convention most tourism/NLP papers cite."""
    if k is None:
        return "undefined (no variation)"
    if k < 0:
        return "poor (below chance)"
    for upper, label in ((0.20, "slight"), (0.40, "fair"), (0.60, "moderate"),
                         (0.80, "substantial"), (1.00, "almost perfect")):
        if k <= upper:
            return label
    return "almost perfect"


def binary_scores(predicted: list[int], truth: list[int]) -> dict:
    tp = sum(p == 1 and t == 1 for p, t in zip(predicted, truth))
    fp = sum(p == 1 and t == 0 for p, t in zip(predicted, truth))
    fn = sum(p == 0 and t == 1 for p, t in zip(predicted, truth))
    tn = sum(p == 0 and t == 0 for p, t in zip(predicted, truth))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else None)
    return {
        "n": len(truth), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": (tp + tn) / len(truth) if truth else None,
    }


# ---------------------------------------------------------------------------
# Loading


def pair_key(topic_id: object, preference_id: object) -> str:
    return f"T{int(topic_id)}-{preference_id}"


def load_labels(allow_partial: bool) -> tuple[dict[str, dict[str, int]], list[str]]:
    """{annotator: {pair_key: label}} plus problems found."""
    problems: list[str] = []
    files = sorted(LABELS_DIR.glob("labels_*.csv"))
    labels: dict[str, dict[str, int]] = {}
    for path in files:
        name = path.stem.removeprefix("labels_")
        df = pd.read_csv(path)
        if not {"pair_key", "human_label"} <= set(df.columns):
            problems.append(f"{path.name}: needs pair_key and human_label columns")
            continue
        raw = df["human_label"]
        parsed = pd.to_numeric(raw, errors="coerce")
        bad = raw.notna() & ~parsed.isin([0, 1])
        if bad.any():
            problems.append(f"{path.name}: {int(bad.sum())} label(s) are not 0 or 1, "
                            f"e.g. {raw[bad].astype(str).head(3).tolist()}")
            continue
        missing = int(parsed.isna().sum())
        if missing and not allow_partial:
            problems.append(f"{path.name}: {missing} of {len(df)} pairs still unlabelled")
            continue
        labels[name] = {k: int(v) for k, v in zip(df["pair_key"], parsed) if pd.notna(v)}
    return labels, problems


# ---------------------------------------------------------------------------
# Analysis


def analyse(sample: pd.DataFrame, labels: dict[str, dict[str, int]]) -> dict:
    sample = sample.copy()
    sample["pair_key"] = [pair_key(t, p) for t, p in zip(sample["topic_id"], sample["preference_id"])]
    annotators = sorted(labels)

    # Only pairs every annotator has labelled enter the agreement statistics.
    common = [k for k in sample["pair_key"] if all(k in labels[a] for a in annotators)]

    pairwise = []
    for a, b in itertools.combinations(annotators, 2):
        xs = [labels[a][k] for k in common]
        ys = [labels[b][k] for k in common]
        kappa = cohen_kappa(xs, ys) if common else None
        pairwise.append({
            "annotators": [a, b],
            "cohen_kappa": kappa,
            "interpretation": interpret_kappa(kappa),
            "raw_agreement": sum(x == y for x, y in zip(xs, ys)) / len(common) if common else None,
            "n": len(common),
        })
    valid = [p["cohen_kappa"] for p in pairwise if p["cohen_kappa"] is not None]
    mean_pairwise = sum(valid) / len(valid) if valid else None

    counts = [[sum(labels[a][k] == 0 for a in annotators), sum(labels[a][k] == 1 for a in annotators)]
              for k in common]
    fleiss = fleiss_kappa(counts) if common and len(annotators) >= 2 else None

    consensus: dict[str, int | None] = {}
    ties: list[str] = []
    for k, (zeros, ones) in zip(common, counts):
        if ones > zeros:
            consensus[k] = 1
        elif zeros > ones:
            consensus[k] = 0
        else:
            consensus[k] = None
            ties.append(k)

    by_key = sample.set_index("pair_key")
    decided = [k for k in common if consensus[k] is not None]
    predicted = [int(by_key.loc[k, "expected_relation"]) for k in decided]
    truth = [consensus[k] for k in decided]
    pipeline = binary_scores(predicted, truth)

    per_type = []
    for ptype, group in sample.groupby("pair_type", sort=True):
        keys = [k for k in group["pair_key"] if k in consensus and consensus[k] is not None]
        yes = sum(consensus[k] for k in keys)
        per_type.append({
            "pair_type": ptype,
            "pipeline_expects": int(group["expected_relation"].iloc[0]) if group["expected_relation"].nunique() == 1 else None,
            "decided_pairs": len(keys),
            "human_yes": yes,
            "human_yes_rate": yes / len(keys) if keys else None,
        })

    per_annotator = []
    for a in annotators:
        keys = [k for k in sample["pair_key"] if k in labels[a]]
        scores = binary_scores([int(by_key.loc[k, "expected_relation"]) for k in keys],
                               [labels[a][k] for k in keys])
        per_annotator.append({"annotator": a, "labelled": len(keys),
                              "yes_rate": sum(labels[a][k] for k in keys) / len(keys) if keys else None,
                              "pipeline_precision": scores["precision"], "pipeline_recall": scores["recall"]})

    disagreements = [
        {"pair_key": k, "yes": ones, "no": zeros,
         "topic_id": int(by_key.loc[k, "topic_id"]), "preference_id": by_key.loc[k, "preference_id"],
         "pair_type": by_key.loc[k, "pair_type"]}
        for k, (zeros, ones) in zip(common, counts) if zeros and ones
    ]

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "annotators": annotators,
        "pairs_in_sample": len(sample),
        "pairs_labelled_by_all": len(common),
        "pairwise_cohen_kappa": pairwise,
        "mean_pairwise_cohen_kappa": mean_pairwise,
        "mean_pairwise_interpretation": interpret_kappa(mean_pairwise),
        "fleiss_kappa": fleiss,
        "fleiss_interpretation": interpret_kappa(fleiss),
        "consensus": {k: v for k, v in consensus.items()},
        "ties": ties,
        "pipeline_vs_consensus": pipeline,
        "by_pair_type": per_type,
        "per_annotator": per_annotator,
        "disagreements": disagreements,
    }


def fmt(x: float | None, digits: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def write_reports(report: dict) -> None:
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    p = report["pipeline_vs_consensus"]
    lines = [
        "# Phase 5 — human validation report",
        "",
        f"Generated: {report['generated_at_utc']}",
        "",
        f"- Annotators: {', '.join(report['annotators'])} ({len(report['annotators'])})",
        f"- Pairs labelled by everyone: {report['pairs_labelled_by_all']} / {report['pairs_in_sample']}",
        f"- **Fleiss' kappa: {fmt(report['fleiss_kappa'])}** ({report['fleiss_interpretation']})",
        f"- Mean pairwise Cohen's kappa: {fmt(report['mean_pairwise_cohen_kappa'])} "
        f"({report['mean_pairwise_interpretation']})",
        f"- Ties (no majority, excluded below): {len(report['ties'])}"
        + (f" — {', '.join(report['ties'])}" if report["ties"] else ""),
        "",
        "## Pairwise Cohen's kappa",
        "",
        "| Annotators | kappa | Interpretation | Raw agreement | n |",
        "|---|---|---|---|---|",
    ]
    for row in report["pairwise_cohen_kappa"]:
        lines.append(f"| {' / '.join(row['annotators'])} | {fmt(row['cohen_kappa'])} | "
                     f"{row['interpretation']} | {fmt(row['raw_agreement'])} | {row['n']} |")
    lines += [
        "",
        "## Pipeline mapping vs. human consensus",
        "",
        "`expected_relation = 1` means the pipeline maps the topic to the preference.",
        "",
        f"- Precision: **{fmt(p['precision'])}**  Recall: **{fmt(p['recall'])}**  "
        f"F1: {fmt(p['f1'])}  Accuracy: {fmt(p['accuracy'])}  (n = {p['n']})",
        f"- Confusion: TP {p['tp']}, FP {p['fp']}, FN {p['fn']}, TN {p['tn']}",
        "",
        "| Pair type | Pipeline expects | Decided pairs | Humans said yes | Yes rate |",
        "|---|---|---|---|---|",
    ]
    for row in report["by_pair_type"]:
        lines.append(f"| {row['pair_type']} | {row['pipeline_expects']} | {row['decided_pairs']} | "
                     f"{row['human_yes']} | {fmt(row['human_yes_rate'], 2)} |")
    lines += ["", "## Per annotator", "",
              "| Annotator | Labelled | Yes rate | Pipeline precision | Pipeline recall |",
              "|---|---|---|---|---|"]
    for row in report["per_annotator"]:
        lines.append(f"| {row['annotator']} | {row['labelled']} | {fmt(row['yes_rate'], 2)} | "
                     f"{fmt(row['pipeline_precision'])} | {fmt(row['pipeline_recall'])} |")
    if report["disagreements"]:
        lines += ["", "## Pairs with any disagreement (discuss only after all labels are in)", "",
                  "| Pair | Type | Yes | No |", "|---|---|---|---|"]
        for row in report["disagreements"]:
            lines.append(f"| {row['pair_key']} | {row['pair_type']} | {row['yes']} | {row['no']} |")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def write_back(sample: pd.DataFrame, consensus: dict[str, int | None]) -> int:
    keys = [pair_key(t, p) for t, p in zip(sample["topic_id"], sample["preference_id"])]
    values = [consensus.get(k) for k in keys]
    sample = sample.copy()
    sample["human_label"] = pd.array([v if v is not None else pd.NA for v in values], dtype="Int64")
    sample.to_csv(SAMPLE_CSV, index=False)
    return int(sample["human_label"].notna().sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-partial", action="store_true",
                        help="use whatever is labelled so far (progress check; not for the report)")
    parser.add_argument("--write-back", action="store_true",
                        help="write consensus labels into phase5_manual_review_sample.csv")
    args = parser.parse_args()

    if not SAMPLE_CSV.exists():
        print(f"error: {SAMPLE_CSV} not found — run Phase 5 first")
        return 1
    sample = pd.read_csv(SAMPLE_CSV)
    labels, problems = load_labels(args.allow_partial)
    for problem in problems:
        print(f"  ! {problem}")
    if len(labels) < MIN_ANNOTATORS:
        print(f"error: need at least {MIN_ANNOTATORS} usable annotator files in {LABELS_DIR}, "
              f"found {len(labels)}. Each annotator runs:\n"
              "  python scripts/label_validation_sample.py --annotator <name>")
        return 1
    if problems and not args.allow_partial:
        print("error: fix the files above (or use --allow-partial for a progress check)")
        return 1

    report = analyse(sample, labels)
    write_reports(report)
    p = report["pipeline_vs_consensus"]
    print(f"Annotators: {', '.join(report['annotators'])}; pairs labelled by all: "
          f"{report['pairs_labelled_by_all']}/{report['pairs_in_sample']}")
    print(f"Fleiss' kappa: {fmt(report['fleiss_kappa'])} ({report['fleiss_interpretation']})")
    print(f"Mean pairwise Cohen's kappa: {fmt(report['mean_pairwise_cohen_kappa'])}")
    print(f"Pipeline vs consensus: precision {fmt(p['precision'])}, recall {fmt(p['recall'])}, "
          f"F1 {fmt(p['f1'])} (n={p['n']}, {len(report['ties'])} tie(s) excluded)")
    print(f"Wrote {OUT_MD.name} and {OUT_JSON.name}")

    if args.write_back:
        if args.allow_partial:
            print("refusing --write-back with --allow-partial: only complete labels go into the sample")
            return 1
        n = write_back(sample, report["consensus"])
        print(f"Wrote {n} consensus label(s) into {SAMPLE_CSV.name}; now run "
              "scripts/build_phase8_database.py so the API serves them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
