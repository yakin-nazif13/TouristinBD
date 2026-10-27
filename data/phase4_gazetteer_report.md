# Phase 4 — Gazetteer and official visibility

How documented each discovered place already is (BUILD_PLAN 5.4), from
OpenStreetMap and Wikidata. **V0 — absent from both — is what makes
something a discovery rather than a site everyone already lists.**

A lookup that could not be performed is recorded as `unknown`, never V0.
Treating an outage as absence would manufacture discoveries.

- PLACE entities checked: **70**
- Coordinates recovered: **65** (these also serve section 3.6)

| level | meaning | entities |
| --- | --- | --- |
| V0 | not on any map or list | 3 |
| V1 | on the map, barely documented | 7 |
| V2 | moderately documented | 18 |
| V3 | well known / official | 42 |

## V0 — undocumented places found in review text

Each of these was mentioned in a review of somewhere else and appears in
neither OpenStreetMap nor Wikidata.

- **Gangamati**
- **Fatrar Chor**
- **Chor Bijoy**

## Raised by our own place list

Found on our Google Maps place list, so on a map whatever OpenStreetMap
and Wikidata say. Only ever raised, never lowered.

| entity | OSM / Wikidata | now | listed as | Google reviews |
| --- | --- | --- | --- | --- |
| Bichnakandi Tourist Spot | V0 | V3 | Bichnakandi Tourist Spot | 5263 |
| Jaflong | V2 | V3 | Jaflong Zero Point | 5402 |
| Kantajew Temple | V2 | V3 | Kantajew Temple | 4827 |
| Alutila | V2 | V3 | Alutila Cave | 5418 |
| Kuakata | V2 | V3 | Kuakata Sea Beach | 6898 |
| Nilgiri | V1 | V2 | Nilgiri | 600 |
| Kolatoli Beach | V1 | V3 | Kolatoli Beach | 4676 |
| Ratargul | V2 | V3 | Ratargul Swamp Forest | 7366 |
| Guliakhali Sea Beach | V0 | V3 | Guliakhali Sea Beach | 4448 |
| China Matir Pahar | V0 | V2 | China Matir Pahar | 201 |
| Chandranath | V2 | V3 | Chandranath Hill | 2400 |
| Panam City | V1 | V3 | Panam City | 3362 |
| T-badh | V0 | V3 | T-Badh | 7902 |
| Boga Lake | V1 | V3 | Boga Lake | 1058 |
| Mohamaya Lake | V0 | V3 | Mohamaya Lake | 1879 |
| Sada Matir Pahar | V0 | V1 | Sada Matir Pahar (White Clay Hills) | 91 |
| Sajek Valley | V2 | V3 | Sajek Valley | 15776 |
| Nilachal | V1 | V3 | Nilachal Tourist Center | 6651 |
| Tanguar Haor | V2 | V3 | Tanguar Haor | 5300 |
| Hiron Point | V1 | V2 | Hiron Point (Nilkamal) | 539 |
| Karamjal | V0 | V3 | Sundarbans (Karamjal Wildlife Centre) | 2382 |
| Lawachara National Park | V2 | V3 | Lawachara National Park | 6557 |
| Bijoypur Lake | V0 | V3 | Bijoypur Lake | 2004 |
| I-Badh | V0 | V3 | I-Badh | 2798 |
| Madhabkunda | V1 | V3 | Madhabkunda Waterfall | 1850 |
| Varendra Research Museum | V2 | V3 | Varendra Research Museum | 2685 |
| Foy's lake | V2 | V3 | Foy's Lake | 1969 |
| Nafakhum Waterfall | V1 | V2 | Nafakhum Waterfall | 401 |
| Natore Rajbari | V2 | V3 | Natore Rajbari | 4383 |
| patenga sea beach | V2 | V3 | Patenga Sea Beach | 7013 |
| Ramna park | V1 | V3 | Ramna Park | 46109 |

## Thresholds

- V3: 20+ Wikidata sitelinks, or OSM importance >= 0.35
- V2: 5+ sitelinks, or OSM importance >= 0.1
- V1: present in either source, below those
- V0: absent from both, both having been successfully consulted
- On our place list: V3 at 1000+ Google reviews, V2 at 100+, otherwise V1 — never V0

Chosen by probing known and unknown places, not assumed. The plan's V1/V2
wording refers to Google Maps review counts, which an extracted entity
with no Maps page of its own does not have; sitelinks and importance are
the closest free documented proxies and are named here so the substitution
is visible.
