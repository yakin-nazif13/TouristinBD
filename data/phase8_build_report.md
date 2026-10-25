# Phase 8 — Database Build Report

- Built (UTC): 2026-10-23T17:23:23Z
- Database: `data/touristinbd.db` (schema version 2)

## Row counts

| table | rows |
| --- | --- |
| places | 116 |
| topics | 58 |
| reviews | 14841 |
| preferences | 20 |
| topic_preference_map | 80 |
| long_tail_flags | 58 |
| validation_precision | 58 |
| validation_coverage | 20 |
| validation_recommendations | 32 |
| validation_manual_sample | 50 |
| sensitivity_metrics | 5 |
| sensitivity_mappings | 154 |
| review_language | 14841 |
| entities | 467 |
| entity_variants | 537 |
| mentions | 2398 |

## Views

- `v_city_preference_rollup`
- `v_city_stats`
- `v_dataset_overview`
- `v_entity_evidence`
- `v_language_mix`
- `v_mention_evidence`
- `v_place_stats`
- `v_preference_frequency`
- `v_rating_distribution`
- `v_review_preference`
- `v_review_preference_all`
- `v_temporal_volume`
- `v_venue_preference_rollup`

## Build notes

- 22 near-tied topic(s) are also mapped to their runner-up preference
- phase5 manual review sample: 0/50 pairs carry a human_label
