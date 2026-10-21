# Place list import

- Source: `bangladesh_100_tourist_spots.csv` — 100 places in 8 divisions
- Final names: 3 place(s) with more than one name (the longer name is final)
- Existing data renamed: 2
- New reviews planned: **9501** (asking for ~12399 with a 1.3x allowance)

## Names

| Final name | Also known as | In the corpus |
|---|---|---|
| Somapura Mahavihara (Paharpur) | Sompur Mahavihar (Paharpur) | yes |
| Sundarbans (Karamjal Wildlife Centre) | Karamjal | yes |
| Kuakata Sea Beach | Kuakata Beach | yes |

## Renamed in the existing data

- Kuakata Beach → Kuakata Sea Beach
- Sompur Mahavihar (Paharpur) → Somapura Mahavihara (Paharpur)

## Not matched — confirm by editing `data/place_aliases.csv`

- **Cox's Bazar Beach** (20 reviews): no similar name in the list
- **Kaptai Lake** (20 reviews): Hatirjheel Lake (similarity 0.62, place_id `ChIJHZTyUjjHVTcRq6luV_pWc-0`); Boga Lake (similarity 0.6, place_id `ChIJwdJMT32CsjARSI1l57f2gXk`)
- **Saint Martins Island** (20 reviews): Saint Martin's Island West Beach (similarity 0.77, place_id `ChIJy5v59DsjrjARV2u5bul3B2A`)
- **Srimangal Tea Garden** (20 reviews): Noor Jahan Tea Garden (similarity 0.68, place_id `ChIJjTBNt8d5UTcRVHR4Gmznh84`); Shreepur Tea Garden (similarity 0.67, place_id `ChIJ-5k7RNFHUDcRZVQ8SedBWg8`)

## Close together but kept as separate places

- Bijoypur Lake / Sada Matir Pahar (White Clay Hills): 127 m apart, name similarity 0.21
- Bijoypur Lake / China Matir Pahar: 294 m apart, name similarity 0.27
- Sada Matir Pahar (White Clay Hills) / China Matir Pahar: 200 m apart, name similarity 0.5
- Mahasthan Archaeological Museum / Mahasthangarh Tourism Park: 328 m apart, name similarity 0.46

## Geography

- renamed in place_geography.csv: Sompur Mahavihar (Paharpur) -> Somapura Mahavihara (Paharpur)
- renamed in place_geography.csv: Kuakata Beach -> Kuakata Sea Beach

## Plan by division

```
            places  available  already   new
division                                    
Barishal         8      11537       20   598
Chattogram      32     130287       40  2800
Dhaka           11     147761       60  1500
Khulna           8      24230       40   797
Mymensingh       6       3858        0   503
Rajshahi        11      37669       20  1101
Rangpur          5      22407        0   702
Sylhet          19      44358       40  1500
```

## Running it

1. Try `data/scrape_batches/pilot.json` (and `pilot_bangla.json`) in the Apify console first. Check the export has both the original and the translated text columns.
2. Then run the files under `data/scrape_batches/relevant/`, `newest/` and `bangla/`.
3. Import each export: `python scripts/add_reviews.py EXPORT.csv --source google_maps --name NAME`. Names and coordinates are filled in from `data/place_names.csv`.

Input field names follow the actor's current schema; check them on its Input page if Apify rejects a file.
