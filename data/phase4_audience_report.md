# Phase 4 — Locals versus visitors

What domestic reviewers mention that foreign ones do not (BUILD_PLAN 5.6).

- Reviews: **538**
- Domestic: **176** · Foreign: **62** · Unknown: 300
- Labelled: **44.2%** of the corpus

## How the label is derived

| signal | use |
| --- | --- |
| `user_location` | stated country; Bangladesh -> domestic, else foreign |
| `language_label` | Bangla/Banglish/mixed -> domestic, where no location exists |
| `reviewer_is_local_guide` | **not used** — see below |

The plan lists `reviewer_is_local_guide` as a proxy, but it is Google's badge
for contribution volume rather than a statement of residency, and 274 of the
300 reviews carrying it are True. A signal that applies to nine in ten
reviewers cannot separate two audiences, so using it would produce a
confident-looking split that means nothing.

## By entity_type

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| ACCESS | 0 | 0 | — | 0.0% | no |
| PLACE | 0 | 0 | — | 0.0% | no |
| TIP | 0 | 1 | — | 100.0% | no |

## By division

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Barishal | 0 | 0 | — | 0.0% | no |
| Chattogram | 0 | 1 | — | 100.0% | no |
| Dhaka | 0 | 0 | — | 0.0% | no |
| Khulna | 0 | 0 | — | 0.0% | no |
| Rajshahi | 0 | 0 | — | 0.0% | no |
| Sylhet | 0 | 0 | — | 0.0% | no |

## By visibility

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| V0 | 0 | 0 | — | 0.0% | no |
| V1 | 0 | 0 | — | 0.0% | no |
| V2 | 0 | 0 | — | 0.0% | no |
| V3 | 0 | 0 | — | 0.0% | no |
| unknown | 0 | 1 | — | 100.0% | no |

## By entity

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Bagerhat | 0 | 0 | — | 0.0% | no |
| Bandarban | 0 | 0 | — | 0.0% | no |
| Best Time to Visit | 0 | 0 | — | 0.0% | no |
| Best time to visit | 0 | 0 | — | 0.0% | no |
| Boga Lake | 0 | 0 | — | 0.0% | no |
| Carry water | 0 | 0 | — | 0.0% | no |
| Carry water but don't litter | 0 | 0 | — | 0.0% | no |
| Chandranath | 0 | 0 | — | 0.0% | no |
| Chor Bijoy | 0 | 0 | — | 0.0% | no |
| Cox's Bazar | 0 | 0 | — | 0.0% | no |
| Fatrar Chor | 0 | 0 | — | 0.0% | no |
| Fokirhat | 0 | 0 | — | 0.0% | no |
| Gangamati | 0 | 0 | — | 0.0% | no |
| Go early | 0 | 1 | — | 100.0% | no |
| Go in the morning to beat the crowd | 0 | 0 | — | 0.0% | no |

## What this does and does not establish

A group is marked comparable only with at least 5 mentions from
both audiences. Below that the shares are printed for completeness but no
difference should be read from them: a ratio built on two observations is
not a finding, and a significance test on single-digit counts produces a
p-value that means nothing.

## Notes

- reviewer_is_local_guide is deliberately not used: it is Google's contribution-volume badge, not a residency signal, and 274 of the 300 reviews that carry it are True — a proxy that says yes to nine in ten reviewers cannot separate two audiences
- 238/538 reviews could be labelled (44.2%); user_location is supplied by Booking.com but not by Google Maps
- no entity_type group has at least 5 mentions from both audiences, so no comparison is reported for it
- no division group has at least 5 mentions from both audiences, so no comparison is reported for it
- no visibility group has at least 5 mentions from both audiences, so no comparison is reported for it
- no entity group has at least 5 mentions from both audiences, so no comparison is reported for it
- 181 of 182 mentions sit in reviews that cannot be labelled. user_location comes from Booking.com, whose reviews are about hotels and rarely name another place, while almost every mention comes from a Google Maps review, which supplies no location. The source that identifies the reviewer is not the source that carries the evidence.
- On this corpus the locals-versus-visitors question cannot be answered: every cell is too small on at least one side. This is a coverage limit, not a null result.
- Worth flagging: section 5.6 cannot be answered via reviewer location without conflicting with section 10, which keeps personal-data output off when scraping. Google Maps reviewer location is exactly the field that ethics stance excludes. The route that does not conflict is language — Bangla or Banglish text implies a domestic reviewer and needs no personal data at all — which becomes usable once the YouTube pass (section 3.3a) brings real Banglish into the corpus. Today the corpus has 5 such reviews.
