# Phase 4 — Entity resolution

Clusters mentions of the same real thing (BUILD_PLAN 5.3). Unresolved
spelling variants split one place's evidence, and section 5.5 needs 2-3
independent mentions before anything becomes a candidate — so this step is
what stops variants suppressing the gems the project is looking for.

- Distinct surface forms in: **96**
- Entities out: **78**
- Entities with more than one variant: **11**
  - of which substantive (not just letter case): **9**
  - case-only: 2

Weights (fixed in advance): {'phonetic': 0.4, 'string': 0.25, 'containment': 0.2, 'geography': 0.15}, merge threshold 0.72.

Surfaces carrying 0 mentions are the corpus's own place names, added so a
short form found in someone else's review has an official name to resolve
against. A place having reviews is not the same as its name being mentioned,
so they contribute no mentions to the evidence counts.

## Substantive variant groups

Spelling and local-vs-official cases — what section 5.3 is actually about.

| entity | variants | mentions |
| --- | --- | --- |
| Jaflong | Jaflong, Jaflong Zero Point, jaflong | 39 |
| Kuakata | Kuakata, Kuakata Beach | 32 |
| Kaptai | Kaptai, Kaptai Lake, kaptai | 30 |
| Ahsan Manzil | Ahsan Manzil, Ahsan Manzil Museum | 28 |
| Cox's Bazar | Cox's Bazar, Cox's Bazar Beach, Cox's bazar, cox's Bazar, cox's bazar | 27 |
| Guliakhali | Guliakhali, Guliakhali Sea Beach, Guliyakhali | 24 |
| Sreemangal | Sreemangal, Srimangal, Srimangal Tea Garden | 23 |
| Nilachal | Nilachal, Nilachal Tourist Center | 21 |
| Ratargul | Ratargul, Ratargul Swamp Forest | 20 |

## Case-only groups

Trivially easy; listed separately so they are not read as evidence that
resolution works.

- Rangamati, rangamati
- Muradpur, muradpur

## Evaluation against the hand-made variant groups

- Gold surfaces: 34 (32 present in the corpus)
- B-cubed precision: 0.9688
- B-cubed recall: 0.9688
- **B-cubed F1: 0.9688**
- Cluster purity: 0.9688

Gold surfaces the corpus does not contain, so they could not be scored:

- `Char Bijoy`
- `Gulyakhali`

## Notes

- embedding signal unavailable (needs torch); phonetic + string + geography only
