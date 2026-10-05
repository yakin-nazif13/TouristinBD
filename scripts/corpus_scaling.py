"""Corpus-size-dependent settings shared by the pipeline scripts.

Everything in Phases 3-4 was tuned on 538 reviews. These helpers keep that
behaviour at that size (so the committed artifacts still reproduce) and let the
settings grow sensibly with the corpus instead of being edited by hand.

No third-party imports on purpose: tests and the health report import this
without pulling in torch/BERTopic.
"""

from __future__ import annotations

# --- Phase 3 -------------------------------------------------------------
MIN_TOPIC_SIZE_FLOOR = 6        # the value used at the 538-review MVP size
MIN_TOPIC_SIZE_FRACTION = 0.004  # 0.4% of the corpus: 538 -> 6, 10,000 -> 40
SMALL_CORPUS_LIMIT = 2000        # at or below this, BERTopic picks the topic count itself ("auto")
LARGE_CORPUS_MAX_TOPICS = 40     # above it, reduce to this many so Phase 4 stays affordable
SEED = 42


def choose_min_topic_size(n_docs: int) -> int:
    """Smallest cluster BERTopic may form. Grows with the corpus; never below 6."""
    return max(MIN_TOPIC_SIZE_FLOOR, round(n_docs * MIN_TOPIC_SIZE_FRACTION))


def choose_nr_topics(n_docs: int, max_topics: int | None = None):
    """BERTopic's `nr_topics`: "auto" for small corpora, an integer cap for large ones.

    Phase 4 makes one LLM call per topic and puts the whole topic list into one
    Stage-2 prompt, so an unbounded topic count does not scale to 10k reviews.
    An explicit `max_topics` always wins (0 or None means "use the default rule").
    """
    if max_topics:
        return max_topics
    return "auto" if n_docs <= SMALL_CORPUS_LIMIT else LARGE_CORPUS_MAX_TOPICS


# --- Phase 4 -------------------------------------------------------------
def scarcity_threshold(n_topics: int, default: float = 0.02) -> float:
    """Share below which a topic counts as scarce in the long-tail rule.

    The paper's fixed 2% assumes roughly ten topics. With many topics
    most of them are small, so a fixed 2% would call nearly everything long-tail.
    Cap it at half of the average topic share so "scarce" always means
    "clearly smaller than a typical topic". At the MVP size (10 topics, average
    share 10%) this returns the default 2% unchanged.
    """
    if n_topics <= 0:
        return default
    return min(default, 0.5 / n_topics)
