# Phase 4 — Entity resolution

Clusters mentions of the same real thing (BUILD_PLAN 5.3). Unresolved
spelling variants split one place's evidence, and section 5.5 needs 2-3
independent mentions before anything becomes a candidate — so this step is
what stops variants suppressing the gems the project is looking for.

- Distinct surface forms in: **537**
- Entities out: **467**
- Entities with more than one variant: **50**
  - of which substantive (not just letter case): **15**
  - case-only: 35

Weights (fixed in advance): {'phonetic': 0.4, 'string': 0.25, 'containment': 0.2, 'geography': 0.15}, merge threshold 0.72.

Surfaces carrying 0 mentions are the corpus's own place names, added so a
short form found in someone else's review has an official name to resolve
against. A place having reviews is not the same as its name being mentioned,
so they contribute no mentions to the evidence counts.

## Substantive variant groups

Spelling and local-vs-official cases — what section 5.3 is actually about.

| entity | variants | mentions |
| --- | --- | --- |
| Cox's Bazar | Cox'S Bazar, Cox's Bazar, Cox's Bazar Beach, Cox's Bazar beach, Cox's bazar, cox's Bazar, cox's bazar | 282 |
| Sreemangal | Sreemangal, Srimangal, Srimangal Tea Garden, sreemangal, srimangal | 109 |
| Best Time to Visit | Best Time to Visit, Best Time to Visit The best time to visit, Best time to visit, best time to visit | 32 |
| Jaflong | Jaflong, Jaflong Zero Point, jaflong | 24 |
| Kaptai lake | Kaptai, Kaptai Lake, Kaptai lake | 13 |
| Shoshi Lodge | Shashi Lodge, Shoshi Lodge | 13 |
| Ahsan Manzil | Ahsan Manzil, Ahsan Manzil Museum | 5 |
| Chandranath | Chandranath, Chandranath Hill | 3 |
| Kotka | Kotka, Kotka Sea Beach | 3 |
| Kuakata Sea Beach | Kuakata, Kuakata Sea Beach, Kuakata sea beach | 3 |
| best time to visit is during the rainy season | best time to visit is during rainy season, best time to visit is during the rainy season | 3 |
| go early in the morning to | Go Early in the Morning, go early in the morning to | 3 |
| Lawachara National Park | Lawachara, Lawachara National Park | 2 |
| Foy's lake | Foy's Lake, Foy's Lake Resort, Foy's lake | 1 |
| Nilachal | Nilachal, Nilachal Tourist Center | 1 |

## Case-only groups

Trivially easy; listed separately so they are not read as evidence that
resolution works.

- AluTila Cave, Alutila Cave, Alutila cave
- Bandarban, bandarban
- Bisnakandi, bisnakandi
- China Matir Pahar, China Matir pahar
- Durgapur, durgapur
- Guliyakhali, guliyakhali
- Hiron Point, Hiron point, hiron point
- I-Badh, i-badh
- Kantajew Temple, Kantajew temple
- Khagrachari, khagrachari
- Lalakhal, lalakhal
- Madhabpur Lake, madhabpur lake
- Mahasthangarh, mahasthangarh
- Mongla, mongla
- Muradpur, muradpur
- Nilgiri, nilgiri
- Padma, padma
- Panam City, Panam city, panam city
- Pashur, pashur
- PUTHIA, Puthia
- Ramna Park, Ramna park
- Rangamati, rangamati
- Sajek Valley, Sajek valley, sajek valley
- Sardar Bari, Sardar bari, sardar bari
- Sitakunda, sitakunda
- Sundarbans, sundarbans
- T-Badh, T-badh, t-badh
- Take a CNG or Auto, take a CNG or auto
- Visit early in the morning or, visit early in the morning or
- Carry water, carry water
- Go early, go early
- Kolatoli Beach, kolatoli beach
- Mohamaya Lake, mohamaya lake
- Patenga Sea Beach, patenga sea beach
- Varendra Research Museum, varendra research museum

## Notes

- embedding signal unavailable (needs torch); phonetic + string + geography only
