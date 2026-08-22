# Phase 5 Validation Report

## Thresholds
- tau_sim: `0.4`
- ambiguity_margin: `0.08`
- min_topics_per_preference: `3`
- max_topics_per_preference: `20`

## Direction 1 (Topic -> Preference)
- total topics: `10`
- low-similarity flags: `0`
- ambiguous flags: `0`
- pass: `10`

## Direction 2 (Preference -> Topic)
- total preferences: `10`
- under-coverage: `10`
- over-coverage: `0`
- adequate: `0`

## Manual Review Sample
- rows: `50`
- mapped positives: `10`
- second-best challengers: `10`
- hard negatives: `15`
- random negatives: `15`

## Interpretation (MVP Context)

**Direction 1 — all pass.** Every topic-to-preference mapping has similarity ≥ 0.4 and
a large enough gap from the next best (≥ 0.08), so no remaps are needed.

**Direction 2 — all under-coverage.** The `min_topics_per_preference=3` threshold is
borrowed from the source paper's 1,071-topic run. With only 10 BERTopic topics and
~1 topic per place, **1 mapped topic per preference is structurally expected at MVP
scale**, not a modeling error. When the corpus grows (more reviews → more topics),
this gap will close naturally. No merges or taxonomy restructuring are needed now;
the one actionable exception to monitor is **P10** (mapped_topic_count=0 — no topic
mapped to it, meaning it was constructed by the LLM but has no direct evidence from
the corpus at this scale; safe to drop or fold into P03 after human review).

**Next step:** fill `human_label` column in `phase5_manual_review_sample.csv` to
compute precision/recall once a human rater reviews the 50 pairs.

## Output Files
- `data/phase5_direction1_precision_checks.csv`
- `data/phase5_direction2_coverage_checks.csv`
- `data/phase5_manual_review_sample.csv`
- `data/phase5_recommendations.csv`
- `data/phase5_validation_report.json`
