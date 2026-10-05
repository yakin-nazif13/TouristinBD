# Phase 3 — Language pipeline

Four-way label (BUILD_PLAN 4.1) on the reviewer's own text where Phase 2
kept it, plus section 4.2 normalisation and a phonetic matching key.

- Reviews: **538**
- Bangla / Banglish / mixed: **0.9%** (section 3 targets at least 20% of the collected corpus)
- Labelled from the reviewer's original text: 0.0%

## By label

| label | reviews |
| --- | --- |
| bn | 4 |
| en | 532 |
| mixed | 1 |
| other | 1 |

## How each label was reached

| method | reviews |
| --- | --- |
| lid | 452 |
| script | 4 |
| script-mix | 1 |
| short-text | 81 |

## Notes

- no trained Banglish classifier; using the lexicon heuristic (train it with scripts/banglish_classifier.py --train)
- fastText lid.176 not present; using langdetect for Latin-script languages

> Below the 20% Bangla/Banglish target. The corpus was collected through
> Google's translation, so the reviewer's own words were mostly never
> stored (weakness W6). The YouTube pass in section 3.3a is what changes
> this, not a better classifier.
