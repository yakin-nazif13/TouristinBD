# Phase 4 — Gem score

Five terms, fixed weights, every term stored per entity so a ranking can be
explained rather than asserted (BUILD_PLAN 5.5).

- Entities considered: 467
- Candidates (>= 2 distinct reviews): **76**
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
| 1 | Best Time to Visit | **0.95** | unknown | 31 | 32 | — | 0.88 | 0.90 | 0.97 |
| 2 | Bisnakandi | **0.85** | V0 | 28 | 64 | 1.00 | 0.84 | 0.64 | 0.32 |
| 3 | Kantaji Temple | **0.85** | V0 | 16 | 21 | 1.00 | 0.66 | 0.69 | 0.50 |
| 4 | Sardar Bari | **0.80** | V1 | 14 | 17 | 0.65 | 0.87 | 0.68 | 0.71 |
| 5 | Gangamati | **0.79** | V0 | 6 | 7 | 1.00 | 0.87 | 0.66 | 0.83 |
| 6 | Nilgiri | **0.76** | V1 | 9 | 9 | 0.65 | 0.92 | 0.67 | 0.56 |
| 7 | Pashur | **0.75** | V1 | 10 | 11 | 0.65 | 0.87 | 0.56 | 0.40 |
| 8 | visit early in the morning or | **0.74** | unknown | 5 | 5 | — | 0.92 | 0.85 | 1.00 |
| 9 | Guliyakhali | **0.73** | V0 | 6 | 8 | 1.00 | 0.81 | 0.54 | 0.50 |
| 10 | China Matir Pahar | **0.71** | V0 | 5 | 6 | 1.00 | 0.76 | 0.56 | 0.60 |
| 11 | T-badh | **0.69** | V0 | 4 | 5 | 1.00 | 0.75 | 0.73 | 0.50 |
| 12 | Jaflong | **0.67** | V2 | 21 | 24 | 0.30 | 0.86 | 0.62 | 0.62 |
| 13 | Panam City | **0.67** | V1 | 8 | 8 | 0.65 | 0.90 | 0.58 | 0.12 |
| 14 | Mongla | **0.67** | V2 | 30 | 39 | 0.30 | 0.85 | 0.59 | 0.63 |
| 15 | Sitakunda | **0.66** | V2 | 56 | 91 | 0.30 | 0.80 | 0.59 | 0.62 |
| 16 | best time to visit is during the winter months | **0.66** | unknown | 3 | 3 | — | 0.89 | 0.92 | 1.00 |
| 17 | Mahasthangarh | **0.66** | V2 | 36 | 80 | 0.30 | 0.79 | 0.61 | 0.56 |
| 18 | Lalakhal | **0.65** | V2 | 19 | 47 | 0.30 | 0.80 | 0.70 | 0.37 |
| 19 | Kolatoli Beach | **0.65** | V1 | 5 | 5 | 0.65 | 0.78 | 0.72 | 0.80 |
| 20 | Boga Lake | **0.65** | V1 | 3 | 3 | 0.65 | 0.91 | 0.86 | 1.00 |
| 21 | go early in the morning to | **0.65** | unknown | 3 | 3 | — | 0.88 | 0.87 | 1.00 |
| 22 | Muradpur | **0.64** | V2 | 13 | 17 | 0.30 | 0.70 | 0.54 | 0.62 |
| 23 | best time to visit this place | **0.63** | unknown | 6 | 6 | — | 0.81 | 0.82 | 0.17 |
| 24 | Kaptai lake | **0.63** | V2 | 13 | 13 | 0.30 | 0.80 | 0.69 | 0.15 |
| 25 | go early in the morning or | **0.63** | unknown | 3 | 3 | — | 0.91 | 0.74 | 1.00 |
| 26 | carry water | **0.62** | unknown | 3 | 3 | — | 0.89 | 0.76 | 1.00 |
| 27 | Best Time to Visit Winter | **0.62** | unknown | 2 | 2 | — | 0.89 | 0.95 | 1.00 |
| 28 | best time to visit is during the monsoon season | **0.62** | unknown | 3 | 3 | — | 0.75 | 0.89 | 1.00 |
| 29 | visit in winter | **0.62** | unknown | 3 | 3 | — | 0.83 | 0.80 | 1.00 |
| 30 | Shoshi Lodge | **0.61** | V1 | 4 | 13 | 0.65 | 0.76 | 0.54 | 1.00 |
| 31 | bargain | **0.61** | unknown | 5 | 6 | — | 0.94 | 0.64 | 0.40 |
| 32 | best time to visit is during the dry season | **0.60** | unknown | 2 | 2 | — | 0.81 | 0.94 | 1.00 |
| 33 | Sundarbans | **0.60** | V3 | 33 | 44 | 0.00 | 0.83 | 0.66 | 0.79 |
| 34 | carry your essentials | **0.60** | unknown | 2 | 2 | — | 0.91 | 0.82 | 1.00 |
| 35 | Saint Martin | **0.60** | V3 | 17 | 28 | 0.00 | 0.56 | 0.78 | 0.94 |
| 36 | Bagerhat | **0.59** | V3 | 68 | 97 | 0.00 | 0.77 | 0.63 | 0.84 |
| 37 | carry food | **0.59** | unknown | 3 | 3 | — | 0.93 | 0.55 | 1.00 |
| 38 | Sonargaon | **0.59** | V3 | 50 | 92 | 0.00 | 0.72 | 0.60 | 0.88 |
| 39 | Padma | **0.58** | V3 | 133 | 194 | 0.00 | 0.76 | 0.73 | 0.61 |
| 40 | visit in winter season | **0.58** | unknown | 2 | 2 | — | 0.91 | 0.72 | 1.00 |
| 41 | Sreemangal | **0.58** | V3 | 72 | 109 | 0.00 | 0.77 | 0.67 | 0.60 |
| 42 | Cox's Bazar | **0.57** | V3 | 181 | 282 | 0.00 | 0.72 | 0.69 | 0.60 |
| 43 | Birisiri | **0.57** | V1 | 4 | 5 | 0.65 | 0.84 | 0.68 | 0.25 |
| 44 | Khagrachari | **0.56** | V3 | 42 | 66 | 0.00 | 0.81 | 0.65 | 0.45 |
| 45 | Rangamati | **0.55** | V3 | 53 | 66 | 0.00 | 0.78 | 0.67 | 0.38 |
| 46 | best time to visit is during the rainy season | **0.55** | unknown | 3 | 3 | — | 0.71 | 0.83 | 0.67 |
| 47 | Bandarban | **0.55** | V3 | 251 | 411 | 0.00 | 0.75 | 0.65 | 0.43 |
| 48 | Durgapur | **0.55** | V3 | 28 | 32 | 0.00 | 0.82 | 0.61 | 0.36 |
| 49 | I-Badh | **0.54** | V0 | 2 | 2 | 1.00 | 0.88 | 0.34 | 0.00 |
| 50 | take a CNG | **0.54** | unknown | 2 | 2 | — | 0.94 | 0.53 | 1.00 |
| 51 | Paharpur | **0.54** | V3 | 16 | 19 | 0.00 | 0.81 | 0.47 | 0.50 |
| 52 | bus from Gulistan | **0.53** | unknown | 2 | 2 | — | 0.92 | 0.50 | 1.00 |
| 53 | Visit early morning | **0.52** | unknown | 2 | 2 | — | 0.90 | 0.82 | 0.50 |
| 54 | go early | **0.52** | unknown | 3 | 3 | — | 0.90 | 0.50 | 0.67 |
| 55 | visit early in the morning | **0.51** | unknown | 2 | 2 | — | 0.81 | 0.85 | 0.50 |
| 56 | Alutila | **0.51** | V2 | 6 | 6 | 0.30 | 0.82 | 0.66 | 0.17 |
| 57 | Kuakata Sea Beach | **0.51** | V2 | 3 | 3 | 0.30 | 0.74 | 0.78 | 1.00 |
| 58 | Hiron Point | **0.51** | V1 | 3 | 3 | 0.65 | 0.90 | 0.57 | 0.00 |
| 59 | Madhabpur Lake | **0.51** | V2 | 3 | 3 | 0.30 | 0.85 | 0.66 | 1.00 |
| 60 | Chandranath | **0.50** | V2 | 3 | 3 | 0.30 | 0.90 | 0.59 | 1.00 |
| 61 | Best time to visit this place is during winter | **0.50** | unknown | 2 | 2 | — | 0.79 | 0.82 | 0.50 |
| 62 | take a boat ride | **0.50** | unknown | 2 | 2 | — | 0.89 | 0.72 | 0.50 |
| 63 | Sajek Valley | **0.49** | V2 | 4 | 4 | 0.30 | 0.92 | 0.75 | 0.25 |
| 64 | Varendra Research Museum | **0.48** | V2 | 2 | 2 | 0.30 | 0.87 | 0.69 | 1.00 |
| 65 | go early morning | **0.48** | unknown | 2 | 2 | — | 0.82 | 0.70 | 0.50 |
| 66 | Lawachara National Park | **0.48** | V2 | 2 | 2 | 0.30 | 0.77 | 0.76 | 1.00 |
| 67 | bargaining | **0.48** | unknown | 3 | 3 | — | 0.94 | 0.45 | 0.33 |
| 68 | Kantajew Temple | **0.47** | V2 | 3 | 3 | 0.30 | 0.91 | 0.56 | 0.67 |
| 69 | Take a CNG or Auto | **0.46** | unknown | 2 | 2 | — | 0.92 | 0.51 | 0.50 |
| 70 | Ahsan Manzil | **0.46** | V3 | 5 | 5 | 0.00 | 0.91 | 0.63 | 0.80 |
| 71 | bus from Barisal | **0.46** | unknown | 3 | 3 | — | 0.80 | 0.50 | 0.33 |
| 72 | Alutila cave | **0.44** | V2 | 4 | 4 | 0.30 | 0.81 | 0.55 | 0.25 |
| 73 | Lalbagh Fort | **0.44** | V3 | 5 | 5 | 0.00 | 0.89 | 0.63 | 0.60 |
| 74 | Puthia | **0.38** | V2 | 3 | 3 | 0.30 | 0.82 | 0.50 | 0.00 |
| 75 | boat from Mongla | **0.37** | unknown | 2 | 2 | — | 0.79 | 0.53 | 0.00 |
| 76 | Kotka | **0.36** | V3 | 3 | 3 | 0.00 | 0.90 | 0.67 | 0.33 |

## Notes

- `distinct` computed lexically (TF-IDF) for 2398 mention(s)
- 15 candidate(s) are already official (V3), and the highest of them (Sundarbans, 0.60) outranks 29 candidate(s) that are not — `mentions` saturates for a much-reviewed famous place. Use already_official to filter the register; the weights were not retuned after seeing this.
