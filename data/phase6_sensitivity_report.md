# Phase 6 Sensitivity Report (MVP hybrid)

## What changed (easy language)
- The full paper tests the pipeline at 20k / 40k / 60k / 80k reviews.
- This MVP run uses the same **4-step ladder**, scaled to your **14841** reviews:
  `[4155, 6827, 10982, 14841]`.
- For each size we **re-find topics**, then match them to the **same Phase 4 preference
  list** (no new LLM taxonomy). That keeps later phases stable.
- Results are saved only as `phase6_*` files — Phase 3–5 outputs were **not** overwritten.

## Metrics tracked
- topic count
- how many of the preferences get at least one topic
- average mapping similarity + high-confidence rate (sim ≥ 0.4)
- Jaccard similarity of the mapped preference set vs the previous sample size

## Results
| sample_size | topics | prefs covered | avg sim | high-conf | Jaccard vs prev |
|------------:|-------:|--------------:|--------:|----------:|----------------:|
| 4155 | 39 | 19/20 | 0.435 | 0.667 | 1.000 |
| 6827 | 39 | 18/20 | 0.444 | 0.641 | 0.850 |
| 10982 | 39 | 17/20 | 0.437 | 0.641 | 0.842 |
| 14841 | 37 | 17/20 | 0.430 | 0.568 | 0.889 |

## Recommendation
- Stability rule: consecutive Jaccard ≥ `0.95` (<5% change).
- Recommended minimum corpus size (MVP): **not reached — keep collecting data**
- Smallest subsample where mapped preference-ID set changes <5% vs the previous size (Jaccard >= 0.95). None means the MVP corpus never fully stabilized — keep collecting toward the paper's 20k+ ladder.

## Later-phase safety
- Preference IDs (P01–P10) stay the Phase 4 taxonomy.
- Canonical files (`reviews_with_topics.csv`, `topic_preferences.csv`, etc.) unchanged.
- When the corpus grows toward 20k+, re-run this script with a larger ladder; optionally
  switch to a full LLM re-run mode only if you intentionally want a new taxonomy.
