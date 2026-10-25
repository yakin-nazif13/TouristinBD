# Phase 3 — Language pipeline

Four-way label (BUILD_PLAN 4.1) on the reviewer's own text where Phase 2
kept it, plus section 4.2 normalisation and a phonetic matching key.

- Reviews: **14841**
- Bangla / Banglish / mixed: **29.7%** (section 3 targets at least 20% of the collected corpus)
- Labelled from the reviewer's original text: 96.4%

## By label

| label | reviews |
| --- | --- |
| (none) | 3 |
| bn | 4042 |
| bn-latn | 92 |
| en | 10402 |
| mixed | 274 |
| other | 28 |

## How each label was reached

| method | reviews |
| --- | --- |
| heuristic | 107 |
| lid | 8801 |
| no-letters | 3 |
| script | 4042 |
| script-mix | 259 |
| short-text | 1629 |

## Notes

- no trained Banglish classifier; using the lexicon heuristic (train it with scripts/banglish_classifier.py --train)
- fastText lid.176 not present; using langdetect for Latin-script languages
