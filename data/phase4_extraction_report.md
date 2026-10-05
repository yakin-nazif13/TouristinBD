# Phase 4 — Entity extraction

Extractor: **gazetteer**. Section 5.2's grounding rule is applied to every
candidate: a surface form that cannot be located in the review is dropped.

- Reviews processed: **538**
- Grounded mentions: **440**
- Reviews with at least one: 169
- Distinct surface forms: 69

## Grounding

- Candidates proposed: 440
- Kept: 440
- Dropped: 0 (**0.0%**)

| match kind | mentions |
| --- | --- |
| exact | 440 |

## By entity type

| type | mentions |
| --- | --- |
| ACCESS | 11 |
| PLACE | 411 |
| TIP | 18 |

## Most-mentioned surfaces

| surface | mentions |
| --- | --- |
| Jaflong | 37 |
| Kuakata | 32 |
| Ahsan Manzil | 28 |
| Kaptai | 26 |
| Saint Martin | 25 |
| Cox's Bazar | 24 |
| Sonargaon | 22 |
| Guliakhali | 22 |
| Bandarban | 21 |
| Nilachal | 21 |
| Ratargul | 20 |
| Karamjal | 20 |
| Paharpur | 14 |
| Sreemangal | 13 |
| Sitakunda | 12 |
| Srimangal | 10 |
| Bagerhat | 10 |
| Mongla | 10 |
| Rangamati | 8 |
| Pashur | 5 |

## Notes

- gazetteer of 87 known names (corpus + geography + 3.1 anchors)
