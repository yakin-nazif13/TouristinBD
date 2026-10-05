"""Provenance schema shared by the ingestion and pipeline scripts.

BUILD_PLAN section 3.5 adds six provenance columns to the corpus:

    source_type      google_maps | booking | youtube | blog | tripadvisor
    collected_at     ISO timestamp of the scrape
    anchor_place      the famous place whose page the text came from
    discovery_round  0 for anchors, 1.. for snowball rounds
    lat, lng         place coordinates

They are written by `add_reviews.py` at import time and carried through Phase 2
as optional columns, so a batch that lacks them still imports and the committed
538-review corpus still reproduces byte for byte.

Because the two original batches predate these columns, downstream code must
never assume they are present. `source_type_of` derives the value from the
older `source` column instead of leaving a hole, and `with_provenance` adds
every missing column so a phase script can read one stable shape regardless of
which batches the corpus happens to contain.

No third-party imports at module level beyond pandas: the health report and the
tests import this without pulling in torch or BERTopic.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# --- the six columns from BUILD_PLAN 3.5 --------------------------------

PROVENANCE_COLUMNS = [
    "source_type",
    "collected_at",
    "anchor_place",
    "discovery_round",
    "lat",
    "lng",
]

# The vocabulary 3.5 fixes for source_type. Anything else is kept verbatim
# rather than coerced, so an unforeseen source shows up in the health report as
# itself instead of silently becoming "other".
SOURCE_TYPES = ["google_maps", "booking", "youtube", "blog", "tripadvisor"]

# `source` was free text before 3.5 existed ("booking.com", "google_maps").
# These map the values actually present in the committed corpus onto the
# controlled vocabulary.
_SOURCE_TO_TYPE = {
    "google_maps": "google_maps",
    "google maps": "google_maps",
    "googlemaps": "google_maps",
    "booking.com": "booking",
    "booking": "booking",
    "youtube": "youtube",
    "blog": "blog",
    "tripadvisor": "tripadvisor",
}

ANCHOR_ROUND = 0


def utc_now_iso() -> str:
    """Collection timestamp, second resolution, always UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def source_type_of(source: object) -> str:
    """Map a legacy `source` value onto the 3.5 vocabulary.

    Unknown values pass through lowercased so they stay visible rather than
    being bucketed into a catch-all.
    """
    text = str(source or "").strip().lower()
    if not text:
        return ""
    return _SOURCE_TO_TYPE.get(text, text)


def with_provenance(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with all six provenance columns present.

    Missing columns are added; `source_type` is derived from `source` and
    `discovery_round` defaults to 0 (anchor), because every review collected
    before snowballing existed came from an anchor place by definition. The
    remaining columns are left empty rather than guessed: a fabricated
    coordinate or scrape date would be indistinguishable from a real one.
    """
    out = df.copy()
    for column in PROVENANCE_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA

    blank_type = out["source_type"].isna() | (out["source_type"].astype("string").str.strip() == "")
    if "source" in out.columns:
        out.loc[blank_type, "source_type"] = out.loc[blank_type, "source"].map(source_type_of)

    out["discovery_round"] = pd.to_numeric(out["discovery_round"], errors="coerce").fillna(ANCHOR_ROUND).astype(int)
    out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lng"] = pd.to_numeric(out["lng"], errors="coerce")
    return out


# Bangladesh's bounding box, used to reject a coordinate that parsed fine but
# cannot be a place in the corpus (a swapped lat/lng pair, most often).
BD_LAT_RANGE = (20.5, 26.7)
BD_LNG_RANGE = (88.0, 92.7)


def in_bangladesh(lat: object, lng: object) -> bool:
    """True when the pair is a usable Bangladeshi coordinate."""
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if lat_f != lat_f or lng_f != lng_f:  # NaN
        return False
    return (
        BD_LAT_RANGE[0] <= lat_f <= BD_LAT_RANGE[1]
        and BD_LNG_RANGE[0] <= lng_f <= BD_LNG_RANGE[1]
    )
