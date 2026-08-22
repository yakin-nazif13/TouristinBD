# Phase 6 Sensitivity Report (MVP hybrid)

## What changed (easy language)
- The full paper tests the pipeline at 20k / 40k / 60k / 80k reviews.
- This MVP run uses the same **4-step ladder**, scaled to your **538** reviews:
  `[151, 247, 398, 538]`.
- For each size we **re-find topics**, then match them to the **same Phase 4 preference
  list** (no new LLM taxonomy). That keeps later phases stable.
- Results are saved only as `phase6_*` files — Phase 3–5 outputs were **not** overwritten.

## Metrics tracked
- topic count
- how many of the 10 preferences get at least one topic
- average mapping similarity + high-confidence rate (sim ≥ 0.4)
- Jaccard similarity of the mapped preference set vs the previous sample size

## Results
| sample_size | topics | prefs covered | avg sim | high-conf | Jaccard vs prev |
|------------:|-------:|--------------:|--------:|----------:|----------------:|
| 151 | 2 | 2/10 | 0.467 | 1.000 | 1.000 |
| 247 | 5 | 5/10 | 0.517 | 1.000 | 0.400 |
| 398 | 10 | 9/10 | 0.464 | 0.700 | 0.556 |
| 538 | 9 | 9/10 | 0.534 | 1.000 | 1.000 |

## Recommendation
- Stability rule: consecutive Jaccard ≥ `0.95` (<5% change).
- Recommended minimum corpus size (MVP): **538**
- Mapped preference set is stable at/above this size for the current taxonomy.

## Later-phase safety
- Preference IDs (P01–P10) stay the Phase 4 taxonomy.
- Canonical files (`reviews_with_topics.csv`, `topic_preferences.csv`, etc.) unchanged.
- When the corpus grows toward 20k+, re-run this script with a larger ladder; optionally
  switch to a full LLM re-run mode only if you intentionally want a new taxonomy.
