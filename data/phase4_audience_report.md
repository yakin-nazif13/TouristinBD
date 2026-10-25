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
| PLACE | 94 | 0 | 86.2% | 0.0% | no |
| TIP | 11 | 1 | 10.1% | 100.0% | no |
| ACCESS | 4 | 0 | 3.7% | 0.0% | no |

## By division

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Chattogram | 36 | 1 | 33.0% | 100.0% | no |
| Khulna | 21 | 0 | 19.3% | 0.0% | no |
| Rajshahi | 20 | 0 | 18.4% | 0.0% | no |
| Sylhet | 16 | 0 | 14.7% | 0.0% | no |
| Mymensingh | 10 | 0 | 9.2% | 0.0% | no |
| Dhaka | 4 | 0 | 3.7% | 0.0% | no |
| Rangpur | 2 | 0 | 1.8% | 0.0% | no |
| Barishal | 0 | 0 | 0.0% | 0.0% | no |

## By visibility

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| V3 | 60 | 0 | 55.0% | 0.0% | no |
| V2 | 15 | 0 | 13.8% | 0.0% | no |
| unknown | 15 | 1 | 13.8% | 100.0% | no |
| V0 | 10 | 0 | 9.2% | 0.0% | no |
| V1 | 9 | 0 | 8.3% | 0.0% | no |

## By entity

| group | domestic | foreign | domestic share | foreign share | comparable |
| --- | --- | --- | --- | --- | --- |
| Padma | 13 | 0 | 11.9% | 0.0% | no |
| Bagerhat | 12 | 0 | 11.0% | 0.0% | no |
| Bandarban | 11 | 0 | 10.1% | 0.0% | no |
| Mahasthangarh | 7 | 0 | 6.4% | 0.0% | no |
| Cox's Bazar | 7 | 0 | 6.4% | 0.0% | no |
| Shoshi Lodge | 6 | 0 | 5.5% | 0.0% | no |
| Paharpur | 5 | 0 | 4.6% | 0.0% | no |
| Kantaji Temple | 4 | 0 | 3.7% | 0.0% | no |
| Durgapur | 4 | 0 | 3.7% | 0.0% | no |
| Best Time to Visit | 4 | 0 | 3.7% | 0.0% | no |
| Sreemangal | 3 | 0 | 2.8% | 0.0% | no |
| Bisnakandi | 3 | 0 | 2.8% | 0.0% | no |
| Jaflong | 3 | 0 | 2.8% | 0.0% | no |
| Rangamati | 2 | 0 | 1.8% | 0.0% | no |
| Sitakunda | 2 | 0 | 1.8% | 0.0% | no |

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
- no division group has at least 5 mentions from both audiences, so no comparison is reported for it
- no visibility group has at least 5 mentions from both audiences, so no comparison is reported for it
- no entity group has at least 5 mentions from both audiences, so no comparison is reported for it
- 2288 of 2398 mentions sit in reviews that cannot be labelled. user_location comes from Booking.com, whose reviews are about hotels and rarely name another place, while almost every mention comes from a Google Maps review, which supplies no location. The source that identifies the reviewer is not the source that carries the evidence.
- On this corpus the locals-versus-visitors question cannot be answered: every cell is too small on at least one side. This is a coverage limit, not a null result.
- Worth flagging: section 5.6 cannot be answered via reviewer location without conflicting with section 10, which keeps personal-data output off when scraping. Google Maps reviewer location is exactly the field that ethics stance excludes. The route that does not conflict is language — Bangla or Banglish text implies a domestic reviewer and needs no personal data at all — which becomes usable once the YouTube pass (section 3.3a) brings real Banglish into the corpus. Today the corpus has 5 such reviews.
