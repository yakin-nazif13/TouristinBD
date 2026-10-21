"""One final name per place.

The same location often arrives under several names: the tourist-spot list says
"Kuakata Sea Beach", the first scrape says "Kuakata Beach", Google's own title may
say something else again. If each spelling is treated as a place, one place's
reviews are split across several and every count, rating and itinerary is wrong.

`scripts/import_place_list.py` decides the final name (the longest of the names
known for that location) and saves it in `data/place_names.csv`. This module reads
that file so the two steps that bring text into the corpus agree:

    add_reviews.py              new batches get the final name on the way in
    run_phase2_preprocessing.py older batches get it too (raw files are never edited)

Only the standard library and pandas are used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REGISTRY_NAME = "place_names.csv"
ALIASES_NAME = "place_aliases.csv"
REGISTRY_COLUMNS = [
    "place_id", "canonical_name", "list_name", "aliases", "division", "district", "city",
    "lat", "lng", "google_maps_url", "google_review_count", "other_place_ids",
]


def norm(name: object) -> str:
    """The form names are compared in: case, spacing and quote style do not matter."""
    text = str(name if name is not None else "")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class Registry:
    by_name: dict[str, str] = field(default_factory=dict)        # norm(any known name) -> final name
    by_id: dict[str, str] = field(default_factory=dict)          # Google place_id -> final name
    coords: dict[str, tuple[float, float]] = field(default_factory=dict)   # final name -> (lat, lng)
    id_of: dict[str, str] = field(default_factory=dict)          # final name -> place_id

    def __bool__(self) -> bool:
        return bool(self.by_name or self.by_id)


def registry_path(data_dir: Path) -> Path:
    return Path(data_dir) / REGISTRY_NAME


def load_registry(data_dir: Path) -> Registry:
    """An empty registry when the file does not exist yet, so nothing changes."""
    path = registry_path(data_dir)
    reg = Registry()
    if not path.exists():
        return reg
    frame = pd.read_csv(path, dtype=str).fillna("")
    for row in frame.itertuples(index=False):
        final = row.canonical_name.strip()
        if not final:
            continue
        names = [final, row.list_name, *[a for a in str(row.aliases).split("|") if a.strip()]]
        for name in names:
            if name.strip():
                reg.by_name[norm(name)] = final
        for pid in [row.place_id, *[p for p in str(row.other_place_ids).split("|") if p.strip()]]:
            if pid.strip():
                reg.by_id[pid.strip()] = final
        reg.id_of[final] = row.place_id.strip()
        try:
            reg.coords[final] = (float(row.lat), float(row.lng))
        except ValueError:
            pass
    return reg


def canonicalize(names: pd.Series, reg: Registry, place_ids: pd.Series | None = None) -> tuple[pd.Series, dict[str, str]]:
    """Map a column of place names to their final names.

    A Google place_id, when the export has one, wins over the name (it cannot be
    misspelled). Names the registry does not know pass through untouched.
    Returns the new column and {old name: final name} for what actually changed.
    """
    if not reg:
        return names, {}
    result = names.copy()
    if place_ids is not None:
        by_id = place_ids.astype("string").map(reg.by_id)
        result = by_id.where(by_id.notna(), result)
    by_name = names.map(lambda n: reg.by_name.get(norm(n)) if pd.notna(n) else None)
    result = by_name.where(by_name.notna() & (result == names), result)
    changed = {}
    for old, new in zip(names, result):
        if pd.notna(old) and old != new:
            changed[old] = new
    return result, changed
