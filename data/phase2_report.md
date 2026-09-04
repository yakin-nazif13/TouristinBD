# Phase 2 — preprocessing report

Generated: 2026-09-04T02:11:03Z

- Inputs: real_reviews_batch1.csv, real_reviews_booking_batch1.csv
- Output: `data/processed_reviews.csv` — **538 reviews** across 27 places (from 540 raw rows)
- Dropped: 1 too short, 1 duplicate text, 0 duplicate id
- By source: {'google_maps': 300, 'booking.com': 238}
- By detected language: {'en': 530, 'bn-en-mixed': 5, 'bn': 2, 'nl': 1}

## Notes

- loaded 300 row(s) from real_reviews_batch1.csv
- loaded 240 row(s) from real_reviews_booking_batch1.csv
- dropped as too short (< 10 chars): 'Bad. No'
- dropped as an exact duplicate of an earlier review: 'Good. Good. Good'
