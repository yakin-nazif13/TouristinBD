"""Shared SQL fragments.

`v_review_preference` deliberately omits `review_text_clean` so that aggregate
queries over the view stay cheap. Anything that needs the text joins the base
`reviews` table back in — this module is the single place that spelling lives.
"""

from __future__ import annotations

REVIEW_SUMMARY_FROM = "FROM v_review_preference v JOIN reviews r ON r.review_id = v.review_id"

# A review expresses a preference when its topic is mapped to it, as the best match or, for a
# topic whose top two were too close to call, as the runner-up. `v.preference_id` only ever holds
# the best match, so filters by preference go through the topic instead.
PREFERENCE_TOPIC_FILTER = (
    "v.topic_id IN (SELECT topic_id FROM topic_preference_map WHERE LOWER(preference_id) = LOWER(?))"
)

REVIEW_SUMMARY_SELECT = """
    v.review_id, v.place_id, v.place_name, v.city, v.source, v.review_rating,
    r.review_text_clean, v.review_date, v.detected_language, v.topic_id,
    v.interpreted_label, v.preference_id, v.preference_label, v.preference_type
"""


def review_summary_sql(where: str, order: str = "ORDER BY v.text_length DESC") -> str:
    """Full SELECT for a list of review summaries, filtered by `where`."""
    return f"SELECT {REVIEW_SUMMARY_SELECT} {REVIEW_SUMMARY_FROM} {where} {order}"
