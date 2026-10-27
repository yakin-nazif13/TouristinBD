# Phase 4 — Gem score

Five terms, fixed weights, every term stored per entity so a ranking can be
explained rather than asserted (BUILD_PLAN 5.5).

- Entities considered: 146
- Candidates (>= 2 distinct reviews): **54**
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
| 1 | Gangamati | **0.91** | V0 | 12 | 20 | 1.00 | 0.89 | 0.66 | 0.75 |
| 2 | Sardar Bari | **0.80** | V1 | 20 | 27 | 0.65 | 0.87 | 0.68 | 0.70 |
| 3 | Birisiri | **0.75** | V1 | 16 | 48 | 0.65 | 0.91 | 0.68 | 0.19 |
| 4 | Pashur | **0.75** | V1 | 10 | 11 | 0.65 | 0.87 | 0.56 | 0.40 |
| 5 | Fatrar Chor | **0.69** | V0 | 3 | 3 | 1.00 | 0.86 | 0.50 | 1.00 |
| 6 | Nilgiri | **0.68** | V2 | 10 | 13 | 0.30 | 0.93 | 0.67 | 0.50 |
| 7 | Lalakhal | **0.68** | V2 | 38 | 101 | 0.30 | 0.88 | 0.70 | 0.50 |
| 8 | Mongla | **0.67** | V2 | 30 | 39 | 0.30 | 0.85 | 0.59 | 0.63 |
| 9 | Sitakunda | **0.66** | V2 | 106 | 238 | 0.30 | 0.85 | 0.59 | 0.54 |
| 10 | Mahasthangarh | **0.65** | V2 | 36 | 80 | 0.30 | 0.79 | 0.61 | 0.56 |
| 11 | Kaptai | **0.65** | V2 | 19 | 20 | 0.30 | 0.85 | 0.69 | 0.26 |
| 12 | Muradpur | **0.64** | V2 | 24 | 28 | 0.30 | 0.76 | 0.54 | 0.54 |
| 13 | Sada Matir Pahar | **0.63** | V1 | 4 | 4 | 0.65 | 0.95 | 0.50 | 1.00 |
| 14 | Ahsan Manzil | **0.62** | V3 | 10 | 12 | 0.00 | 0.91 | 0.63 | 0.90 |
| 15 | Shashi Lodge | **0.61** | V1 | 4 | 13 | 0.65 | 0.77 | 0.54 | 1.00 |
| 16 | Sundarbans | **0.60** | V3 | 33 | 44 | 0.00 | 0.83 | 0.66 | 0.79 |
| 17 | Padma | **0.59** | V3 | 206 | 322 | 0.00 | 0.79 | 0.73 | 0.63 |
| 18 | Kolatoli Beach | **0.59** | V3 | 11 | 13 | 0.00 | 0.84 | 0.72 | 0.55 |
| 19 | China Matir Pahar | **0.59** | V2 | 8 | 9 | 0.30 | 0.83 | 0.56 | 0.50 |
| 20 | Sonargaon | **0.59** | V3 | 50 | 92 | 0.00 | 0.72 | 0.60 | 0.88 |
| 21 | Sreemangal | **0.58** | V3 | 101 | 177 | 0.00 | 0.82 | 0.67 | 0.60 |
| 22 | Saint Martin | **0.58** | V3 | 21 | 32 | 0.00 | 0.60 | 0.78 | 0.76 |
| 23 | Jaflong | **0.58** | V3 | 21 | 24 | 0.00 | 0.86 | 0.62 | 0.62 |
| 24 | Bagerhat | **0.58** | V3 | 132 | 219 | 0.00 | 0.75 | 0.63 | 0.74 |
| 25 | Khagrachari | **0.58** | V3 | 79 | 155 | 0.00 | 0.84 | 0.65 | 0.52 |
| 26 | Cox's Bazar | **0.57** | V3 | 181 | 282 | 0.00 | 0.72 | 0.69 | 0.60 |
| 27 | Durgapur | **0.57** | V3 | 63 | 88 | 0.00 | 0.89 | 0.61 | 0.41 |
| 28 | Rangamati | **0.56** | V3 | 75 | 104 | 0.00 | 0.81 | 0.67 | 0.36 |
| 29 | Bandarban | **0.56** | V3 | 365 | 664 | 0.00 | 0.78 | 0.65 | 0.43 |
| 30 | Kantajew Temple | **0.56** | V3 | 19 | 24 | 0.00 | 0.69 | 0.67 | 0.53 |
| 31 | Bichnakandi Tourist Spot | **0.55** | V3 | 29 | 67 | 0.00 | 0.84 | 0.64 | 0.31 |
| 32 | Paharpur | **0.54** | V3 | 20 | 25 | 0.00 | 0.83 | 0.47 | 0.50 |
| 33 | Alutila | **0.54** | V3 | 14 | 19 | 0.00 | 0.84 | 0.62 | 0.21 |
| 34 | Chandranath | **0.54** | V3 | 8 | 8 | 0.00 | 0.91 | 0.59 | 0.75 |
| 35 | Ratargul | **0.53** | V3 | 9 | 11 | 0.00 | 0.89 | 0.75 | 0.11 |
| 36 | Madhabpur Lake | **0.52** | V2 | 4 | 5 | 0.30 | 0.89 | 0.66 | 0.75 |
| 37 | Muktagachha | **0.51** | V2 | 3 | 3 | 0.30 | 1.00 | — | 1.00 |
| 38 | Boga Lake | **0.49** | V3 | 4 | 4 | 0.00 | 0.91 | 0.86 | 1.00 |
| 39 | Panam City | **0.47** | V3 | 8 | 8 | 0.00 | 0.89 | 0.58 | 0.12 |
| 40 | Guliakhali Sea Beach | **0.47** | V3 | 7 | 9 | 0.00 | 0.82 | 0.54 | 0.57 |
| 41 | Lalbagh Fort | **0.44** | V3 | 5 | 5 | 0.00 | 0.89 | 0.63 | 0.60 |
| 42 | Kotka | **0.43** | V3 | 5 | 6 | 0.00 | 0.91 | 0.67 | 0.40 |
| 43 | Kuakata Sea Beach | **0.42** | V3 | 3 | 3 | 0.00 | 0.74 | 0.78 | 1.00 |
| 44 | Hiron Point | **0.40** | V2 | 3 | 3 | 0.30 | 0.90 | 0.57 | 0.00 |
| 45 | Karamjal | **0.40** | V3 | 3 | 3 | 0.00 | 0.89 | 0.71 | 0.67 |
| 46 | Sajek Valley | **0.40** | V3 | 4 | 4 | 0.00 | 0.92 | 0.75 | 0.25 |
| 47 | Varendra Research Museum | **0.39** | V3 | 2 | 2 | 0.00 | 0.87 | 0.69 | 1.00 |
| 48 | T-badh | **0.39** | V3 | 4 | 5 | 0.00 | 0.75 | 0.73 | 0.50 |
| 49 | Lawachara National Park | **0.39** | V3 | 2 | 2 | 0.00 | 0.77 | 0.76 | 1.00 |
| 50 | Mohamaya Lake | **0.39** | V3 | 4 | 4 | 0.00 | 0.96 | 0.50 | 0.50 |
| 51 | Puthia | **0.38** | V2 | 3 | 3 | 0.30 | 0.82 | 0.50 | 0.00 |
| 52 | Bijoypur Lake | **0.36** | V3 | 2 | 2 | 0.00 | 1.00 | — | 1.00 |
| 53 | Nilachal | **0.36** | V3 | 3 | 3 | 0.00 | 0.92 | 0.43 | 0.67 |
| 54 | I-Badh | **0.24** | V3 | 2 | 2 | 0.00 | 0.88 | 0.34 | 0.00 |

## Notes

- `distinct` computed lexically (TF-IDF) for 6938 mention(s)
- 381 non-place entit(ies) not scored (ACCESS 101, ACTIVITY 17, FOOD 46, TIP 217); they are attributes of a place, see phase4_place_attributes.csv
- 35 candidate(s) are already official (V3), and the highest of them (Ahsan Manzil, 0.62) outranks 6 candidate(s) that are not — `mentions` saturates for a much-reviewed famous place. Use already_official to filter the register; the weights were not retuned after seeing this.
