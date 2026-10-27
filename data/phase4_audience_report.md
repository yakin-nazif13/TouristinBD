# Phase 4 — Locals versus visitors

What domestic reviewers mention that foreign ones do not (BUILD_PLAN 5.6).

- Reviews: **14841**
- Domestic: **4579** · Foreign: **62** · Unknown: 10200
- Labelled: **31.3%** of the corpus

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
| PLACE | 1215 | 0 | 51.1% | 0.0% | no |
| ACTIVITY | 536 | 4 | 22.6% | 57.1% | no |
| FOOD | 338 | 2 | 14.2% | 28.6% | no |
| ACCESS | 277 | 0 | 11.7% | 0.0% | no |
| TIP | 11 | 1 | 0.5% | 14.3% | no |

## By division

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Chattogram | 1119 | 5 | 47.1% | 71.4% | yes |
| Sylhet | 333 | 2 | 14.0% | 28.6% | no |
| Khulna | 223 | 0 | 9.4% | 0.0% | no |
| Barishal | 218 | 0 | 9.2% | 0.0% | no |
| Rajshahi | 173 | 0 | 7.3% | 0.0% | no |
| Mymensingh | 122 | 0 | 5.1% | 0.0% | no |
| Rangpur | 96 | 0 | 4.0% | 0.0% | no |
| Dhaka | 93 | 0 | 3.9% | 0.0% | no |

## By visibility

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| unknown | 1162 | 7 | 48.9% | 100.0% | yes |
| V3 | 893 | 0 | 37.6% | 0.0% | no |
| V2 | 246 | 0 | 10.3% | 0.0% | no |
| V1 | 61 | 0 | 2.6% | 0.0% | no |
| V0 | 15 | 0 | 0.6% | 0.0% | no |

## By entity

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Bandarban | 262 | 0 | 11.0% | 0.0% | no |
| CNG auto-rickshaw | 160 | 0 | 6.7% | 0.0% | no |
| Picnic | 154 | 0 | 6.5% | 0.0% | no |
| Sitakunda | 149 | 0 | 6.3% | 0.0% | no |
| Padma | 139 | 0 | 5.9% | 0.0% | no |
| Bagerhat | 133 | 0 | 5.6% | 0.0% | no |
| Guava | 124 | 0 | 5.2% | 0.0% | no |
| Trekking and hiking | 100 | 0 | 4.2% | 0.0% | no |
| Khagrachari | 90 | 0 | 3.8% | 0.0% | no |
| Boat ride | 72 | 1 | 3.0% | 14.3% | no |
| Sreemangal | 71 | 0 | 3.0% | 0.0% | no |
| Engine boat (trawler) | 64 | 0 | 2.7% | 0.0% | no |
| Durgapur | 60 | 0 | 2.5% | 0.0% | no |
| Lalakhal | 54 | 0 | 2.3% | 0.0% | no |
| Swimming | 50 | 3 | 2.1% | 42.9% | no |

## What this does and does not establish

A group is marked comparable only with at least 5 mentions from
both audiences. Below that the shares are printed for completeness but no
difference should be read from them: a ratio built on two observations is
not a finding, and a significance test on single-digit counts produces a
p-value that means nothing.

## Notes

- reviewer_is_local_guide is deliberately not used: it is Google's contribution-volume badge, not a residency signal, and 274 of the 300 reviews that carry it are True — a proxy that says yes to nine in ten reviewers cannot separate two audiences
- 4641/14841 reviews could be labelled (31.3%); user_location is supplied by Booking.com but not by Google Maps
- no entity_type group has at least 5 mentions from both audiences, so no comparison is reported for it
- no entity group has at least 5 mentions from both audiences, so no comparison is reported for it
- 4554 of 6938 mentions sit in reviews that cannot be labelled. user_location comes from Booking.com, whose reviews are about hotels and rarely name another place, while almost every mention comes from a Google Maps review, which supplies no location. The source that identifies the reviewer is not the source that carries the evidence.
