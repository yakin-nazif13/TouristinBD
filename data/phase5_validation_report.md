# Phase 5 Validation Report

## Thresholds
- tau_sim: `0.4`
- ambiguity_margin: `0.08`
- min_topics_per_preference: `3`
- max_topics_per_preference: `20`

## Direction 1 (Topic -> Preference)
- total topics: `58`
- low-similarity flags: `0`
- ambiguous flags: `22`
- pass: `36`
- near-tied topics also mapped to their runner-up preference: `22` (`data/topic_preference_secondary.csv`)

## Direction 2 (Preference -> Topic)
- total preferences: `20`
- under-coverage: `9`
- over-coverage: `0`
- adequate: `11`

## Manual Review Sample
- rows: `50`
- mapped positives: `10`
- second-best challengers: `10`
- hard negatives: `15`
- random negatives: `15`

## Output Files
- `data/phase5_direction1_precision_checks.csv`
- `data/phase5_direction2_coverage_checks.csv`
- `data/phase5_manual_review_sample.csv`
- `data/phase5_recommendations.csv`
- `data/topic_preference_secondary.csv`
- `data/phase5_validation_report.json`
