"""Turn a list of tourist spots into everything the next data collection needs.

    .venv/bin/python scripts/import_place_list.py ~/Downloads/bangladesh_100_tourist_spots.csv
    .venv/bin/python scripts/import_place_list.py list.csv --dry-run         # show the plan, write nothing

The list needs at least: name, division, district, place_id, latitude, longitude
(google_maps_url, review_count and category are used when present).

WHAT IT DOES
1. One final name per place. A location often has several names: the list says
   "Kuakata Sea Beach", the first scrape said "Kuakata Beach". Wherever the same
   location has more than one name, THE LONGER NAME IS FINAL (a tie goes to the name
   already in the corpus). Every other name is kept as an alias, so reviews that arrive
   under any of them are filed under the final name.
   Written to data/place_names.csv, which add_reviews.py and Phase 2 read.
2. Places already in the corpus are recognised by exact name or by data/place_aliases.csv
   (a file you edit: alias, place_id, note). Looks-similar-but-not-sure cases are only
   SUGGESTED in the report, never merged on a guess: merging Karamjal into the Sundarbans,
   or a beach into its island, would hide a place from the register.
3. data/place_geography.csv gets a row for every place (division, district, town and
   coordinates). Existing rows keep what a person entered and gain the coordinates.
4. A collection plan for the Apify "Google Maps reviews" actor: how many NEW reviews to
   take from each place (more from big hubs, a floor for thin divisions, never more
   than a place has), written as ready-to-paste inputs in data/scrape_batches/ plus
   data/scrape_plan.csv and data/scrape_targets.csv.
5. If an existing place was renamed, brings the existing data in line: Phase 2 is re-run
   and the mention / entity / gem-score / database steps are refreshed. Raw scrape files
   and the human validation labels are never edited. Use --no-refresh to skip this.

Safe to run again: the outputs are rebuilt from the list, the alias file and the raw
batches, so the same input gives the same result.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import place_names as pn  # noqa: E402
from corpus_schema import in_bangladesh  # noqa: E402

DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
SCRIPTS = REPO_ROOT / "scripts"

DIVISIONS = ["Barishal", "Chattogram", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"]
REQUIRED = ["name", "division", "district", "place_id", "latitude", "longitude"]

# Share of the new reviews each division should supply. Hubs get more, but the two
# divisions that had no places at all (Rangpur, Mymensingh) get a real floor.
DEFAULT_SHARES = {
    "Chattogram": 0.295, "Dhaka": 0.158, "Sylhet": 0.158, "Rajshahi": 0.116,
    "Khulna": 0.084, "Rangpur": 0.074, "Barishal": 0.063, "Mymensingh": 0.053,
}
# Three passes, so the data is not all one slice of Google's ordering. "most relevant"
# returns the longest reviews, which is where mentions of other places live.
PASSES = {
    "relevant": {"sort": "mostRelevant", "language": "en", "share": 0.6},
    "newest": {"sort": "newest", "language": "en", "share": 0.2},
    "bangla": {"sort": "mostRelevant", "language": "bn", "share": 0.2},
}
TIERS = [50, 100, 200, 400, 800, 1600]   # an Apify run has ONE maxReviews, so places are grouped
SAME_PLACE_METRES = 150
NEAR_PAIR_METRES = 400
FUZZY_SUGGEST = 0.6

GEO_COLUMNS = ["place_name", "city", "district", "division", "place_kind", "notes", "lat", "lng", "place_id"]


# --------------------------------------------------------------------------- reading


def split_district(value: str) -> tuple[str, str]:
    """'Chattogram (Sitakunda)' -> district 'Chattogram', town 'Sitakunda'."""
    match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", str(value).strip())
    if match and match.group(1):
        return match.group(1).strip(), match.group(2).strip()
    return str(value).strip(), str(value).strip()


def read_list(path: Path) -> tuple[pd.DataFrame, list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    df = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return df, [f"the list is missing column(s): {', '.join(missing)}"], notes
    df = df.copy()
    for column in ("google_maps_url", "category", "review_count", "google_rating"):
        if column not in df.columns:
            df[column] = ""
    for column in REQUIRED:
        df[column] = df[column].str.strip()
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0).astype(int)

    bad_div = sorted(set(df["division"]) - set(DIVISIONS))
    if bad_div:
        errors.append(f"unknown division(s): {', '.join(bad_div)} (expected one of {', '.join(DIVISIONS)})")
    blank = df[(df["name"] == "") | (df["place_id"] == "")]
    if len(blank):
        errors.append(f"{len(blank)} row(s) have no name or place_id (rows {', '.join(map(str, blank.index + 2))})")
    for index, row in df.iterrows():
        try:
            lat, lng = float(row["latitude"]), float(row["longitude"])
        except ValueError:
            errors.append(f"row {index + 2} ({row['name']}): latitude/longitude are not numbers")
            continue
        if not in_bangladesh(lat, lng):
            errors.append(f"row {index + 2} ({row['name']}): {lat}, {lng} is outside Bangladesh (swapped?)")

    dup = df.duplicated("place_id", keep="first")
    if dup.any():
        notes.append(f"dropped {int(dup.sum())} repeated place_id row(s): {', '.join(df.loc[dup, 'name'])}")
        df = df[~dup]
    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["lng"] = pd.to_numeric(df["longitude"], errors="coerce")
    parts = df["district"].map(split_district)
    df["district_clean"] = parts.map(lambda p: p[0])
    df["city"] = parts.map(lambda p: p[1])
    return df.reset_index(drop=True), errors, notes


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def similar(a: str, b: str) -> float:
    a, b = pn.norm(a), pn.norm(b)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        ratio = max(ratio, 0.85)
    return ratio


def merge_close_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """The same location listed twice under different place_ids and names.

    Close together AND similarly named = one place. Close together but named
    differently (two viewpoints on one hill) are kept apart and only reported.
    """
    merged, near = [], []
    drop: set[int] = set()
    extra_ids: dict[int, list[str]] = {}
    extra_names: dict[int, list[str]] = {}
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            if i in drop or j in drop:
                continue
            a, b = df.iloc[i], df.iloc[j]
            metres = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if metres > NEAR_PAIR_METRES:
                continue
            score = similar(a["name"], b["name"])
            if metres <= SAME_PLACE_METRES and score >= FUZZY_SUGGEST:
                keep, lose = (i, j) if a["review_count"] >= b["review_count"] else (j, i)
                drop.add(lose)
                extra_ids.setdefault(keep, []).append(df.iloc[lose]["place_id"])
                extra_names.setdefault(keep, []).append(df.iloc[lose]["name"])
                merged.append({"kept": df.iloc[keep]["name"], "merged_in": df.iloc[lose]["name"], "metres": round(metres)})
            else:
                near.append({"a": a["name"], "b": b["name"], "metres": round(metres), "similarity": round(score, 2)})
    out = df.copy()
    out["other_place_ids"] = [("|".join(extra_ids.get(i, []))) for i in range(len(out))]
    out["merged_names"] = [("|".join(extra_names.get(i, []))) for i in range(len(out))]
    return out.drop(index=list(drop)).reset_index(drop=True), merged, near


# --------------------------------------------------------------------------- existing data


def existing_places(data_dir: Path) -> dict[str, dict]:
    """Every place name in the raw batches, with its source and review count."""
    found: dict[str, dict] = {}
    for path in sorted(data_dir.glob("real_reviews_*.csv")):
        frame = pd.read_csv(path, usecols=lambda c: c in {"place_name", "source"})
        for name, group in frame.groupby("place_name"):
            record = found.setdefault(str(name), {"rows": 0, "sources": set()})
            record["rows"] += len(group)
            if "source" in group:
                record["sources"] |= set(group["source"].dropna().astype(str))
    return found


def read_aliases(data_dir: Path) -> list[tuple[str, str]]:
    path = data_dir / pn.ALIASES_NAME
    if not path.exists():
        return []
    frame = pd.read_csv(path, dtype=str).fillna("")
    if not {"alias", "place_id"} <= set(frame.columns):
        raise SystemExit(f"{path.name} needs the columns: alias, place_id, note")
    return [(r.alias.strip(), r.place_id.strip()) for r in frame.itertuples(index=False) if r.alias.strip()]


def match_existing(df: pd.DataFrame, existing: dict[str, dict], aliases: list[tuple[str, str]]):
    """existing names -> list entries. Returns (matches, unmatched names, warnings)."""
    by_name = {pn.norm(n): pid for n, pid in zip(df["name"], df["place_id"])}
    known_ids = set(df["place_id"]) | {p for ids in df["other_place_ids"] for p in ids.split("|") if p}
    alias_map: dict[str, str] = {}
    warnings: list[str] = []
    for alias, pid in aliases:
        if pid not in known_ids:
            warnings.append(f"alias {alias!r} points at place_id {pid}, which is not in the list; ignored")
            continue
        alias_map[pn.norm(alias)] = pid
    other_to_main = {p: pid for pid, ids in zip(df["place_id"], df["other_place_ids"]) for p in ids.split("|") if p}

    matches: dict[str, list[tuple[str, str]]] = {}
    unmatched: list[str] = []
    for name in existing:
        key = pn.norm(name)
        pid = alias_map.get(key) or by_name.get(key)
        if pid is None:
            unmatched.append(name)
            continue
        if alias_map.get(key) and by_name.get(key) and alias_map[key] != by_name[key]:
            warnings.append(f"{name!r} matches two list entries; the alias file wins")
        pid = other_to_main.get(pid, pid)
        matches.setdefault(pid, []).append((name, "alias" if key in alias_map else "same name"))
    return matches, unmatched, warnings


def suggestions(unmatched: list[str], existing: dict[str, dict], df: pd.DataFrame) -> list[dict]:
    out = []
    for name in unmatched:
        if "booking.com" in {s.lower() for s in existing[name]["sources"]}:
            continue  # hotels are not in a list of tourist spots
        best = sorted(((similar(name, n), n, pid) for n, pid in zip(df["name"], df["place_id"])), reverse=True)[:2]
        best = [b for b in best if b[0] >= FUZZY_SUGGEST]
        out.append({"existing": name, "rows": existing[name]["rows"],
                    "candidates": [(round(s, 2), n, pid) for s, n, pid in best]})
    return out


def choose_final(list_name: str, existing_names: list[str], alias_names: list[str]) -> tuple[str, str]:
    """The longer name wins. A tie goes to a name already in the corpus, then the list."""
    candidates = [(n, 0) for n in existing_names] + [(n, 1) for n in alias_names] + [(list_name, 2)]
    final = min(candidates, key=lambda c: (-len(c[0].strip()), c[1], c[0]))[0].strip()
    why = "only name" if len({n.strip() for n, _ in candidates}) == 1 else "longest of the names"
    return final, why


# --------------------------------------------------------------------------- allocation


def weighted_waterfill(weights: list[float], caps: list[int], total: int) -> list[int]:
    """Split `total` in proportion to `weights`, never giving anyone more than their cap."""
    n = len(weights)
    alloc = [0.0] * n
    active = [i for i in range(n) if caps[i] > 0 and weights[i] > 0]
    remaining = float(min(total, sum(caps)))
    while active and remaining > 1e-9:
        weight_sum = sum(weights[i] for i in active)
        clipped = [i for i in active if remaining * weights[i] / weight_sum >= caps[i] - alloc[i]]
        if not clipped:
            for i in active:
                alloc[i] += remaining * weights[i] / weight_sum
            remaining = 0
            break
        for i in clipped:
            remaining -= caps[i] - alloc[i]
            alloc[i] = caps[i]
        active = [i for i in active if i not in clipped]
    floors = [int(math.floor(a)) for a in alloc]
    leftover = int(round(min(total, sum(caps)))) - sum(floors)
    order = sorted(range(n), key=lambda i: alloc[i] - floors[i], reverse=True)
    for i in order:
        if leftover <= 0:
            break
        if floors[i] < caps[i]:
            floors[i] += 1
            leftover -= 1
    return floors


def allocate(df: pd.DataFrame, existing_rows: dict[str, int], total: int, quotas: dict[str, int] | None = None) -> pd.Series:
    """New reviews to take from each place. Weighted by sqrt(popularity), capped at what exists."""
    shares = {d: DEFAULT_SHARES.get(d, 0.0) for d in DIVISIONS}
    scale = sum(shares.values())
    div_quota = {d: int(round(total * s / scale)) for d, s in shares.items()}
    div_quota.update(quotas or {})
    out = pd.Series(0, index=df.index, dtype=int)
    for division, group in df.groupby("division"):
        caps = [max(0, int(rc) - existing_rows.get(pid, 0)) for rc, pid in zip(group["review_count"], group["place_id"])]
        weights = [math.sqrt(max(int(rc), 1)) for rc in group["review_count"]]
        out.loc[group.index] = weighted_waterfill(weights, caps, div_quota.get(division, 0))
    return out


def tier_for(ask: int, available: int) -> int:
    ask = max(1, min(ask, max(available, 1)))
    return next((t for t in TIERS if t >= ask), TIERS[-1])


# --------------------------------------------------------------------------- writing


def update_geography(data_dir: Path, registry: pd.DataFrame, name_sets: dict[str, set[str]]) -> tuple[pd.DataFrame, list[str], list[str]]:
    path = data_dir / "place_geography.csv"
    geo = pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=GEO_COLUMNS)
    for column in GEO_COLUMNS:
        if column not in geo.columns:
            geo[column] = ""
    geo = geo[GEO_COLUMNS + [c for c in geo.columns if c not in GEO_COLUMNS]]
    conflicts: list[str] = []
    renamed: list[str] = []
    rows = []
    for r in registry.itertuples(index=False):
        names = {pn.norm(n) for n in name_sets[r.place_id]}
        hit = geo[geo["place_name"].map(pn.norm).isin(names)]
        if len(hit):
            index = hit.index[0]
            if geo.at[index, "place_name"] != r.canonical_name:
                renamed.append(f"{geo.at[index, 'place_name']} -> {r.canonical_name}")
                geo.at[index, "place_name"] = r.canonical_name
            for column, value in (("lat", str(r.lat)), ("lng", str(r.lng)), ("place_id", str(r.place_id))):
                geo.at[index, column] = value
            for column, value in (("city", r.city), ("district", r.district), ("division", r.division)):
                if not geo.at[index, column]:
                    geo.at[index, column] = value
                elif geo.at[index, column] != value and column == "division":
                    conflicts.append(f"{r.canonical_name}: division is {geo.at[index, column]!r} in the geography file but "
                                     f"{value!r} in the list (kept the file's)")
        else:
            rows.append({"place_name": r.canonical_name, "city": r.city, "district": r.district, "division": r.division,
                         "place_kind": "attraction", "notes": "from the tourist-spot list", "lat": str(r.lat), "lng": str(r.lng),
                         "place_id": str(r.place_id)})
    if rows:
        geo = pd.concat([geo, pd.DataFrame(rows)], ignore_index=True)
    return geo, renamed, conflicts


def rewrite_place_column(path: Path, reg: pn.Registry) -> int:
    """Change only the place_name values in a derived file; every other byte of text is kept."""
    if not path.exists():
        return 0
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "place_name" not in frame.columns:
        return 0
    new, changed = pn.canonicalize(frame["place_name"], reg)
    if not changed:
        return 0
    count = int((new != frame["place_name"]).sum())
    frame["place_name"] = new
    frame.to_csv(path, index=False)
    return count


def refresh(data_dir: Path, online: bool) -> list[str]:
    """Bring regenerable files in line after an existing place was renamed."""
    py = sys.executable
    steps = [
        ("clean the text (phase 2)", [py, str(SCRIPTS / "run_phase2_preprocessing.py")]),
        ("find mentions", [py, str(SCRIPTS / "extract_mentions.py"), "--extractor", "gazetteer"]),
        ("merge spelling variants", [py, str(SCRIPTS / "resolve_entities.py")]),
        ("check against the maps", [py, str(SCRIPTS / "build_gazetteer.py")] + ([] if online else ["--offline"])),
        ("score hidden-gem candidates", [py, str(SCRIPTS / "score_gems.py")]),
        ("update the verification queue", [py, str(SCRIPTS / "verification_queue.py"), "--export-register"]),
        ("refresh the statistics (phase 7)", [py, str(SCRIPTS / "run_phase7_statistics_visualization.py")]),
        ("rebuild the database", [py, str(SCRIPTS / "build_phase8_database.py")]),
    ]
    log = []
    for label, command in steps:
        print(f"  … {label}", flush=True)
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, env=os.environ.copy())
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip()[-800:]
            log.append(f"FAILED: {label}\n{tail}")
            print(f"  ✗ {label} failed:\n{tail}")
            break
        log.append(f"ok: {label}")
        print(f"  ✓ {label}")
    return log


# --------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="the tourist-spot list")
    parser.add_argument("--total", type=int, default=9500, help="new reviews wanted in total (default 9500)")
    parser.add_argument("--overcollect", type=float, default=1.3,
                        help="ask for this much extra, since short reviews and repeats are dropped (default 1.3)")
    parser.add_argument("--quota", action="append", default=[], metavar="DIVISION=N",
                        help="set one division's number of new reviews, e.g. --quota Rangpur=900")
    parser.add_argument("--format", choices=["placeIds", "urls"], default="placeIds",
                        help="how places are given to the actor (default placeIds)")
    parser.add_argument("--pilot-places", default="Kuakata Sea Beach;Sajek Valley;Tanguar Haor",
                        help="semicolon-separated places for the small test run")
    parser.add_argument("--dry-run", action="store_true", help="show the plan and write nothing")
    parser.add_argument("--no-refresh", action="store_true", help="do not re-run the pipeline after a rename")
    parser.add_argument("--online", action="store_true", help="refresh with live map lookups (default: use the cache)")
    args = parser.parse_args()

    source = Path(args.csv).expanduser()
    if not source.exists():
        print(f"error: {source} does not exist")
        return 1
    quotas = {}
    for item in args.quota:
        division, _, number = item.partition("=")
        if division not in DIVISIONS or not number.isdigit():
            print(f"error: --quota expects DIVISION=NUMBER with a division from {', '.join(DIVISIONS)}; got {item!r}")
            return 1
        quotas[division] = int(number)

    df, errors, notes = read_list(source)
    if errors:
        print("The list has problems:")
        for e in errors:
            print(f"  - {e}")
        return 1
    df, merged, near = merge_close_duplicates(df)
    print(f"Read {len(df)} places from {source.name}" + (f" ({'; '.join(notes)})" if notes else ""))

    existing = existing_places(DATA_DIR)
    aliases = read_aliases(DATA_DIR)
    matches, unmatched, warnings = match_existing(df, existing, aliases)
    alias_names_by_id: dict[str, list[str]] = {}
    for alias, pid in aliases:
        alias_names_by_id.setdefault(pid, []).append(alias)

    # ---- final names
    rows, decisions, name_sets = [], [], {}
    for r in df.itertuples(index=False):
        existing_names = [n for n, _ in matches.get(r.place_id, [])]
        alias_names = [a for a in alias_names_by_id.get(r.place_id, []) if a not in existing_names]
        merged_names = [m for m in r.merged_names.split("|") if m]
        final, why = choose_final(r.name, existing_names, alias_names + merged_names)
        every = {r.name, *existing_names, *alias_names, *merged_names, final}
        name_sets[r.place_id] = every
        others = sorted(n for n in every if n.strip() != final)
        rows.append({
            "place_id": r.place_id, "canonical_name": final, "list_name": r.name, "aliases": "|".join(others),
            "division": r.division, "district": r.district_clean, "city": r.city, "lat": r.lat, "lng": r.lng,
            "google_maps_url": r.google_maps_url, "google_review_count": r.review_count,
            "other_place_ids": r.other_place_ids,
        })
        if len(every) > 1:
            decisions.append({"final": final, "others": others, "why": why, "in_corpus": bool(existing_names)})
    registry = pd.DataFrame(rows, columns=pn.REGISTRY_COLUMNS)

    clash = registry["canonical_name"].map(pn.norm).duplicated(keep=False)
    if clash.any():
        print("error: two different places ended up with the same final name:")
        print(registry.loc[clash, ["place_id", "canonical_name"]].to_string(index=False))
        return 1
    seen: dict[str, str] = {}
    for r in registry.itertuples(index=False):
        for name in {r.canonical_name, r.list_name, *[a for a in r.aliases.split("|") if a]}:
            key = pn.norm(name)
            if key in seen and seen[key] != r.canonical_name:
                print(f"error: the name {name!r} belongs to both {seen[key]!r} and {r.canonical_name!r}; "
                      f"fix {pn.ALIASES_NAME} or the list")
                return 1
            seen[key] = r.canonical_name

    # ---- how many existing reviews each place already has (under any of its names)
    existing_rows = {pid: sum(existing[n]["rows"] for n in {m for m, _ in matches.get(pid, [])}) for pid in registry["place_id"]}
    registry_obj_final = dict(zip(registry["place_id"], registry["canonical_name"]))
    renamed_existing = sorted({(old, registry_obj_final[pid]) for pid, ms in matches.items() for old, _ in ms
                               if old != registry_obj_final[pid]})
    target = allocate(df, existing_rows, args.total, quotas)
    plan = df[["place_id", "division", "district_clean", "review_count"]].copy()
    plan.insert(1, "place_name", [registry_obj_final[p] for p in plan["place_id"]])
    plan["existing_reviews"] = [existing_rows[p] for p in plan["place_id"]]
    plan["target_new"] = target.values
    plan["ask_total"] = [int(math.ceil(t * args.overcollect)) if t else 0 for t in plan["target_new"]]
    for name, spec in PASSES.items():
        plan[f"{name}_max"] = [
            tier_for(int(math.ceil(a * spec["share"])), rc) if a else 0
            for a, rc in zip(plan["ask_total"], plan["review_count"])
        ]
    plan = plan.rename(columns={"district_clean": "district", "review_count": "google_review_count"})

    # ---- report to the screen
    print(f"\nFinal names: {len(decisions)} place(s) have more than one name")
    for d in decisions:
        print(f"  {d['final']}   <- also: {', '.join(d['others'])}" + ("   [already in the corpus]" if d["in_corpus"] else ""))
    for old, new in renamed_existing:
        print(f"  RENAME in existing data: {old!r} -> {new!r}")
    if merged:
        print(f"\nListed twice (same spot, similar names): {len(merged)} merged")
        for m in merged:
            print(f"  kept {m['kept']!r}, merged in {m['merged_in']!r} ({m['metres']} m apart)")
    sugg = suggestions(unmatched, existing, df)
    if sugg:
        print("\nIn the corpus but not matched to the list (add a line to data/place_aliases.csv if it IS the same place):")
        for s in sugg:
            cand = "; ".join(f"{n} [{score}] {pid}" for score, n, pid in s["candidates"]) or "no similar name in the list"
            print(f"  {s['existing']} ({s['rows']} reviews): {cand}")
    for w in warnings:
        print(f"  warning: {w}")
    by_div = plan.groupby("division").agg(places=("place_id", "count"), available=("google_review_count", "sum"),
                                          already=("existing_reviews", "sum"), new=("target_new", "sum"))
    print(f"\nCollection plan: {int(plan['target_new'].sum())} new reviews (asking for ~{int(plan['ask_total'].sum())} with the {args.overcollect}x allowance)")
    print(by_div.to_string())

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    # ---- write
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    registry.to_csv(pn.registry_path(DATA_DIR), index=False)
    geo, geo_renamed, conflicts = update_geography(DATA_DIR, registry, name_sets)
    geo.to_csv(DATA_DIR / "place_geography.csv", index=False)

    targets_path = DATA_DIR / "scrape_targets.csv"
    old_status = {}
    if targets_path.exists():
        old = pd.read_csv(targets_path, dtype=str).fillna("")
        for r in old.itertuples(index=False):
            key = getattr(r, "place_id", "") or pn.norm(r.place_name)
            old_status[key] = {"status": r.status, "collected_at": r.collected_at, "notes": r.notes, "round": r.round}
    t_rows = []
    for p, reg_row in zip(plan.itertuples(index=False), registry.itertuples(index=False)):
        prior = old_status.get(p.place_id) or old_status.get(pn.norm(p.place_name)) or {}
        status = prior.get("status") if prior.get("status") in ("done", "running", "partial") else (
            "partial" if p.existing_reviews else "todo")
        t_rows.append({"place_name": p.place_name, "division": p.division, "district": p.district, "source": "google_maps",
                       "maps_url": reg_row.google_maps_url, "status": status, "round": prior.get("round") or 0,
                       "collected_at": prior.get("collected_at", ""),
                       "notes": prior.get("notes") or (f"{p.existing_reviews} reviews already in corpus" if p.existing_reviews else ""),
                       "place_id": p.place_id, "lat": reg_row.lat, "lng": reg_row.lng, "target_new": p.target_new})
    pd.DataFrame(t_rows).to_csv(targets_path, index=False)
    plan.to_csv(DATA_DIR / "scrape_plan.csv", index=False)

    out_dir = DATA_DIR / "scrape_batches"
    if out_dir.exists():
        for old_file in out_dir.rglob("*.json"):
            old_file.unlink()
    url_of = dict(zip(registry["place_id"], registry["google_maps_url"]))

    def batch_input(ids: list[str], max_reviews: int, sort: str, language: str) -> dict:
        body = {"maxReviews": max_reviews, "reviewsSort": sort, "language": language,
                "reviewsOrigin": "all", "personalData": False}
        if args.format == "urls":
            return {"startUrls": [{"url": url_of[i]} for i in ids], **body}
        return {"placeIds": ids, **body}

    written = []
    for name, spec in PASSES.items():
        for (division, tier), group in plan[plan[f"{name}_max"] > 0].groupby(["division", f"{name}_max"]):
            target_file = out_dir / name / f"{division.lower()}_{int(tier)}.json"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(json.dumps(batch_input(list(group["place_id"]), int(tier), spec["sort"], spec["language"]),
                                              indent=2) + "\n", encoding="utf-8")
            written.append(target_file)
    pilot_ids = []
    for wanted in [w.strip() for w in args.pilot_places.split(";") if w.strip()]:
        hit = registry[registry["canonical_name"].map(pn.norm).eq(pn.norm(wanted)) | registry["list_name"].map(pn.norm).eq(pn.norm(wanted))]
        if len(hit):
            pilot_ids.append(hit.iloc[0]["place_id"])
        else:
            print(f"  note: pilot place {wanted!r} is not in the list")
    if pilot_ids:
        (out_dir / "pilot.json").write_text(json.dumps(batch_input(pilot_ids, 200, "mostRelevant", "en"), indent=2) + "\n", encoding="utf-8")
        (out_dir / "pilot_bangla.json").write_text(json.dumps(batch_input(pilot_ids, 100, "mostRelevant", "bn"), indent=2) + "\n", encoding="utf-8")

    # ---- the report file
    lines = ["# Place list import", "",
             f"- Source: `{source.name}` — {len(df)} places in {df['division'].nunique()} divisions",
             f"- Final names: {len(decisions)} place(s) with more than one name (the longer name is final)",
             f"- Existing data renamed: {len(renamed_existing)}",
             f"- New reviews planned: **{int(plan['target_new'].sum())}** (asking for ~{int(plan['ask_total'].sum())} with a {args.overcollect}x allowance)",
             "", "## Names", "", "| Final name | Also known as | In the corpus |", "|---|---|---|"]
    lines += [f"| {d['final']} | {', '.join(d['others'])} | {'yes' if d['in_corpus'] else 'no'} |" for d in decisions] or ["| – | – | – |"]
    lines += ["", "## Renamed in the existing data", ""] + ([f"- {o} → {n}" for o, n in renamed_existing] or ["- none"])
    lines += ["", "## Not matched — confirm by editing `data/place_aliases.csv`", ""]
    lines += [f"- **{s['existing']}** ({s['rows']} reviews): " + ("; ".join(f"{n} (similarity {sc}, place_id `{pid}`)" for sc, n, pid in s["candidates"]) or "no similar name in the list")
              for s in sugg] or ["- none"]
    lines += ["", "## Close together but kept as separate places", ""] + (
        [f"- {n['a']} / {n['b']}: {n['metres']} m apart, name similarity {n['similarity']}" for n in near] or ["- none"])
    lines += ["", "## Geography", ""] + ([f"- renamed in place_geography.csv: {r}" for r in geo_renamed] + [f"- conflict: {c}" for c in conflicts]
                                       or ["- no renames or conflicts"])
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    lines += ["", "## Plan by division", "", by_div.to_markdown() if hasattr(by_div, "to_markdown") and _has_tabulate() else "```\n" + by_div.to_string() + "\n```"]
    lines += ["", "## Running it", "",
              "1. Try `data/scrape_batches/pilot.json` (and `pilot_bangla.json`) in the Apify console first. Check the export has both the original and the translated text columns.",
              "2. Then run the files under `data/scrape_batches/relevant/`, `newest/` and `bangla/`.",
              "3. Import each export: `python scripts/add_reviews.py EXPORT.csv --source google_maps --name NAME`. Names and coordinates are filled in from `data/place_names.csv`.",
              "", "Input field names follow the actor's current schema; check them on its Input page if Apify rejects a file."]
    (DATA_DIR / "place_import_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nWrote {pn.REGISTRY_NAME}, place_geography.csv, scrape_targets.csv, scrape_plan.csv, {len(written)} batch file(s) + pilot, place_import_report.md")

    # ---- bring existing data in line with any rename
    if renamed_existing and not args.no_refresh:
        print(f"\n{len(renamed_existing)} existing place(s) were renamed; refreshing what depends on place names")
        reg = pn.load_registry(DATA_DIR)
        topics_changed = rewrite_place_column(DATA_DIR / "reviews_with_topics.csv", reg)
        if topics_changed:
            print(f"  updated place_name in reviews_with_topics.csv ({topics_changed} rows; topics untouched)")
        log = refresh(DATA_DIR, args.online)
        if any(line.startswith("FAILED") for line in log):
            print("\nThe refresh stopped early. Fix the problem above and re-run this command (it is safe to repeat).")
            return 1
    elif renamed_existing:
        print("\nExisting places were renamed but --no-refresh was given. Run Phase 2 and the pipeline steps before trusting the corpus.")
    return 0


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    sys.exit(main())
