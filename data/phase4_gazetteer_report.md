# Phase 4 — Gazetteer and official visibility

How documented each discovered place already is (BUILD_PLAN 5.4), from
OpenStreetMap and Wikidata. **V0 — absent from both — is what makes
something a discovery rather than a site everyone already lists.**

A lookup that could not be performed is recorded as `unknown`, never V0.
Treating an outage as absence would manufacture discoveries.

- PLACE entities checked: **23**
- Coordinates recovered: **16** (these also serve section 3.6)

| level | meaning | entities |
| --- | --- | --- |
| V0 | not on any map or list | 4 |
| V1 | on the map, barely documented | 6 |
| V2 | moderately documented | 5 |
| V3 | well known / official | 8 |

## V0 — undocumented places found in review text

Each of these was mentioned in a review of somewhere else and appears in
neither OpenStreetMap nor Wikidata.

- **Gangamati**
- **Guliyakhali**
- **Fatrar Chor**
- **Chor Bijoy**

## Thresholds

- V3: 20+ Wikidata sitelinks, or OSM importance >= 0.35
- V2: 5+ sitelinks, or OSM importance >= 0.1
- V1: present in either source, below those
- V0: absent from both, both having been successfully consulted

Chosen by probing known and unknown places, not assumed. The plan's V1/V2
wording refers to Google Maps review counts, which an extracted entity
with no Maps page of its own does not have; sitelinks and importance are
the closest free documented proxies and are named here so the substitution
is visible.
