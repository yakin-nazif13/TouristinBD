# Phase 8 — Database Build Report

- Built (UTC): 2026-10-05T23:51:38Z
- Database: `data/touristinbd.db` (schema version 2)

## Row counts

| table | rows |
| --- | --- |
| places | 27 |
| topics | 11 |
| reviews | 538 |
| preferences | 5 |
| topic_preference_map | 10 |
| long_tail_flags | 10 |
| validation_precision | 10 |
| validation_coverage | 5 |
| validation_recommendations | 4 |
| validation_manual_sample | 50 |
| sensitivity_metrics | 5 |
| sensitivity_mappings | 33 |
| review_language | 538 |
| entities | 78 |
| entity_variants | 81 |
| mentions | 182 |

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
- `v_temporal_volume`
- `v_venue_preference_rollup`

## Build notes

- phase5 manual review sample: 0/50 pairs carry a human_label
