# Phase 4 — Entity resolution

Clusters mentions of the same real thing (BUILD_PLAN 5.3). Unresolved
spelling variants split one place's evidence, and section 5.5 needs 2-3
independent mentions before anything becomes a candidate — so this step is
what stops variants suppressing the gems the project is looking for.

- Distinct surface forms in: **81**
- Entities out: **78**
- Entities with more than one variant: **3**
  - of which substantive (not just letter case): **1**
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
| Cox's Bazar | Cox's Bazar, Cox's Bazar Beach | 5 |

## Case-only groups

Trivially easy; listed separately so they are not read as evidence that
resolution works.

- Rangamati, rangamati
- Muradpur, muradpur

## Evaluation against the hand-made variant groups

- Gold surfaces: 34 (21 present in the corpus)
- B-cubed precision: 0.9524
- B-cubed recall: 0.8571
- **B-cubed F1: 0.9023**
- Cluster purity: 0.9524

Gold surfaces the corpus does not contain, so they could not be scored:

- `Ahsan Manzil`
- `Char Bijoy`
- `Guliakhali`
- `Gulyakhali`
- `Jaflong`
- `Kaptai`
- `Karamjal`
- `Kuakata`
- `Nilachal`
- `Paharpur`
- `Ratargul`
- `Srimangal`
- `kaptai`

## Notes

- embedding signal unavailable (needs torch); phonetic + string + geography only
