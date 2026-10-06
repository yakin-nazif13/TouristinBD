# Phase 4 — Gem score

Five terms, fixed weights, every term stored per entity so a ranking can be
explained rather than asserted (BUILD_PLAN 5.5).

- Entities considered: 78
- Candidates (>= 2 distinct reviews): **13**
- Ablated this run: none

These weights were chosen before any ranking was inspected and have not
been changed since. Section 6.2 ablates every term against human-verified
gems, which is how the weighting gets settled empirically rather than by
whichever ordering looks most convincing.

## Weights

| term | weight | what it measures |
| --- | --- | --- |
| mentions | 0.3 | distinct reviews, saturating at 10 |
| hidden | 0.3 | inverse official visibility (V0 = 1.0) |
| distinct | 0.15 | how unusual the mention is for its host place |
| sentiment | 0.15 | mean sentiment of the mention sentences |
| recency | 0.1 | share of mentions in the last 3 years |

A term with no value for an entity is excluded and the remaining weights are
renormalised, so a missing term never acts as a zero.

## Ranked candidates

| # | entity | score | vis | reviews | mentions | hidden | distinct | sentiment | recency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Gangamati | **0.69** | V0 | 2 | 3 | 1.00 | 0.87 | 0.66 | 1.00 |
| 2 | Pashur | **0.62** | V1 | 4 | 5 | 0.65 | 0.75 | 0.59 | 1.00 |
| 3 | Bandarban | **0.61** | V3 | 12 | 21 | 0.00 | 0.67 | 0.72 | 1.00 |
| 4 | Saint Martin | **0.61** | V3 | 14 | 25 | 0.00 | 0.59 | 0.79 | 1.00 |
| 5 | Sitakunda | **0.60** | V2 | 7 | 12 | 0.30 | 0.72 | 0.64 | 1.00 |
| 6 | Sonargaon | **0.60** | V3 | 13 | 22 | 0.00 | 0.68 | 0.62 | 1.00 |
| 7 | Mongla | **0.57** | V2 | 6 | 10 | 0.30 | 0.78 | 0.58 | 1.00 |
| 8 | Muradpur | **0.51** | V2 | 4 | 4 | 0.30 | 0.74 | 0.62 | 1.00 |
| 9 | Cox's Bazar | **0.49** | V3 | 5 | 5 | 0.00 | 0.83 | 0.81 | 1.00 |
| 10 | Bagerhat | **0.49** | V3 | 6 | 10 | 0.00 | 0.73 | 0.64 | 1.00 |
| 11 | Rangamati | **0.43** | V3 | 5 | 9 | 0.00 | 0.77 | 0.72 | 0.60 |
| 12 | Sundarbans | **0.41** | V3 | 3 | 3 | 0.00 | 0.79 | 0.66 | 1.00 |
| 13 | Sreemangal | **0.37** | V3 | 3 | 13 | 0.00 | 0.69 | 0.73 | 0.67 |

## Notes

- `distinct` computed lexically (TF-IDF) for 182 mention(s)
- 8 candidate(s) are already official (V3), and the highest of them (Bandarban, 0.61) outranks 3 candidate(s) that are not — `mentions` saturates for a much-reviewed famous place. Use already_official to filter the register; the weights were not retuned after seeing this.
