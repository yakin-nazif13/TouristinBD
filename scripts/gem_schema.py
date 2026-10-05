"""The entity layer: types, states, and the grounding rule. BUILD_PLAN section 5.

This is the data model the hidden-gem engine is built on, kept in one module so
extraction, resolution, scoring and the verification queue cannot drift apart
about what a mention is.

The grounding rule (section 5.2) is the important part:

    "a HARD grounding rule: every entity must be an exact substring of the
     source text, or it is dropped. This keeps the project's no-hallucination
     guarantee and is measurable."

`ground` is what enforces it. An extractor may return anything; only spans that
can be located in the source text survive, and each survivor carries the
character offsets where it was found. That is what lets every published claim
link back to the text supporting it, which is the promise the government-facing
side of the product rests on.

Matching is tried in a fixed order and the winning kind is recorded, so the
strictness is auditable rather than a single yes/no:

    exact            the surface form appears verbatim
    case            differs only by letter case
    whitespace      differs only by internal whitespace
    normalized      differs only by Bangla Unicode normalisation (section 4.2)

Anything else is dropped and counted. The drop rate is a measurement in its own
right — section 6.1 asks for an LLM hallucination rate, and this is where it
comes from.

No third-party imports beyond pandas-free stdlib, so every consumer can import
it without pulling in torch or an API client.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_id import normalize_bangla, phonetic_key  # noqa: E402

# --- vocabulary (section 5.1) --------------------------------------------

ENTITY_TYPES = ["PLACE", "FOOD", "ACTIVITY", "ACCESS", "TIP"]

ENTITY_TYPE_HELP = {
    "PLACE": "a visitable location (beach stretch, temple, ghat, viewpoint)",
    "FOOD": "a dish, sweet or eatery tied to the area (e.g. kotkoti)",
    "ACTIVITY": "a thing to do (boat ride, trek, market visit)",
    "ACCESS": "a route or transport instruction",
    "TIP": "practical advice (season, price, safety, bargaining)",
}

# --- official visibility (section 5.4) -----------------------------------

VISIBILITY_LEVELS = ["V0", "V1", "V2", "V3"]

VISIBILITY_HELP = {
    "V0": "not on any map or list",
    "V1": "on the map, few reviews",
    "V2": "on the map, moderately reviewed",
    "V3": "well known / official",
}

# --- verification queue (section 5.7) ------------------------------------

VERIFICATION_STATES = ["candidate", "verified", "rejected", "sensitive"]

VERIFICATION_HELP = {
    "candidate": "extracted and resolved, awaiting a human decision",
    "verified": "a district officer confirmed it",
    "rejected": "a district officer rejected it",
    "sensitive": "fragile ecology, restricted area or a private/home business",
}

# Nothing auto-publishes, and `sensitive` never reaches the tourist side.
# Section 5.7: sensitive items stay in the government register only.
PUBLISHABLE_STATES = ["verified"]

# Section 5.5: minimum independent mentions before anything is a candidate.
MIN_INDEPENDENT_MENTIONS = 2

MATCH_KINDS = ["exact", "case", "whitespace", "normalized"]


@dataclass(frozen=True)
class Mention:
    """One grounded entity mention, traceable to a span of a real review."""

    review_id: str
    entity_type: str
    surface: str          # exactly as it appears in the source text
    start: int
    end: int
    match_kind: str
    sentence: str = ""    # the sentence it sits in, for evidence display
    language: str = ""
    extractor: str = ""
    confidence: float | None = None

    @property
    def phonetic(self) -> str:
        return phonetic_key(self.surface)

    def as_row(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "entity_type": self.entity_type,
            "surface": self.surface,
            "start": self.start,
            "end": self.end,
            "match_kind": self.match_kind,
            "sentence": self.sentence,
            "language": self.language,
            "extractor": self.extractor,
            "confidence": self.confidence,
            "phonetic_key": self.phonetic,
        }


@dataclass
class GroundingReport:
    """What the grounding rule kept and dropped, so the rate is reportable."""

    kept: int = 0
    dropped: int = 0
    by_match_kind: dict[str, int] = field(default_factory=dict)
    dropped_surfaces: list[str] = field(default_factory=list)
    dropped_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.kept + self.dropped

    @property
    def drop_rate(self) -> float:
        """Share of candidates that could not be found in the source text.

        For an LLM extractor this is its hallucination rate on this corpus —
        the number section 6.1 asks for.
        """
        return self.dropped / self.total if self.total else 0.0

    def note(self, kind: str) -> None:
        self.by_match_kind[kind] = self.by_match_kind.get(kind, 0) + 1

    def drop(self, surface: str, reason: str) -> None:
        self.dropped += 1
        self.dropped_reasons[reason] = self.dropped_reasons.get(reason, 0) + 1
        # Capped: a broken extractor would otherwise fill memory with its own
        # output, and a sample is enough to diagnose one.
        if len(self.dropped_surfaces) < 200:
            self.dropped_surfaces.append(surface)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.total,
            "kept": self.kept,
            "dropped": self.dropped,
            "drop_rate": round(self.drop_rate, 4),
            "by_match_kind": dict(sorted(self.by_match_kind.items())),
            "dropped_reasons": dict(sorted(self.dropped_reasons.items())),
            "dropped_examples": self.dropped_surfaces[:20],
        }


_WHITESPACE_RE = re.compile(r"\s+")


def _squeeze(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def find_span(text: str, surface: str, search_from: int = 0) -> tuple[int, int, str] | None:
    """Locate `surface` in `text`, returning (start, end, match_kind) or None.

    Progressively more forgiving, but every level still requires the span to
    exist in the source: the offsets returned always index into `text`, so the
    quoted evidence is the reviewer's words and not the extractor's.

    `search_from` skips earlier occurrences. A review that says "Cox's Bazar"
    twice should yield two mentions, and without this every repeat collapses
    onto the first hit and is discarded as a duplicate — which would
    under-count the mentions section 5.5 scores on.
    """
    if not text or not surface or not surface.strip():
        return None
    search_from = max(0, min(search_from, len(text)))

    index = text.find(surface, search_from)
    if index >= 0:
        return index, index + len(surface), "exact"

    lowered = text.lower()
    index = lowered.find(surface.lower(), search_from)
    if index >= 0:
        return index, index + len(surface), "case"

    # Internal whitespace differs ("Chor  Bijoy" vs "Chor Bijoy"). Built as a
    # regex over the surface's own tokens so the match is still a real span.
    tokens = [re.escape(t) for t in _squeeze(surface).split(" ") if t]
    if tokens:
        flexible = re.compile(r"\s+".join(tokens), re.IGNORECASE)
        found = flexible.search(text, search_from)
        if found:
            return found.start(), found.end(), "whitespace"

    # Bangla normalisation only (composed vs decomposed vowel signs). Compared
    # on normalised forms, then the span is recovered from the original text by
    # scanning, because normalisation can change length.
    normalised_surface = normalize_bangla(surface)
    if normalised_surface and normalised_surface != surface:
        for start in range(search_from, len(text)):
            for end in range(start + 1, min(len(text), start + len(surface) * 2 + 8) + 1):
                if normalize_bangla(text[start:end]) == normalised_surface:
                    # normalize_bangla strips outer whitespace, so the scan can
                    # match a span padded with it. Tighten to the real word, or
                    # the stored surface would carry a leading space and break
                    # exact comparison later.
                    while start < end and text[start].isspace():
                        start += 1
                    while end > start and text[end - 1].isspace():
                        end -= 1
                    return start, end, "normalized"
    return None


def sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing a span, for evidence display.

    Bangla's danda (U+0964) counts as a full stop alongLatin punctuation;
    without it every Bangla review would be one long "sentence".
    """
    if not text:
        return ""
    boundaries = ".!?।\n"
    left = 0
    for i in range(min(start, len(text) - 1), -1, -1):
        if text[i] in boundaries:
            left = i + 1
            break
    right = len(text)
    for i in range(max(end, 0), len(text)):
        if text[i] in boundaries:
            right = i + 1
            break
    return _squeeze(text[left:right])


def ground(
    review_id: str,
    text: str,
    candidates: list[dict],
    report: GroundingReport | None = None,
    extractor: str = "",
    language: str = "",
) -> tuple[list[Mention], GroundingReport]:
    """Apply the section 5.2 grounding rule to one review's candidates.

    `candidates` is whatever the extractor produced: dicts with at least
    `surface` and `entity_type`. Everything that cannot be located in `text`,
    or carries an unknown type, is dropped and counted.
    """
    report = report or GroundingReport()
    mentions: list[Mention] = []
    seen: set[tuple[str, int, int]] = set()
    # Where to resume searching for each surface, so a review that says a name
    # twice yields two mentions instead of one and a phantom duplicate.
    resume: dict[str, int] = {}

    for candidate in candidates:
        surface = str(candidate.get("surface") or "").strip()
        entity_type = str(candidate.get("entity_type") or "").strip().upper()

        if not surface:
            report.drop("", "empty-surface")
            continue
        if entity_type not in ENTITY_TYPES:
            report.drop(surface, f"unknown-type:{entity_type or 'blank'}")
            continue

        # An extractor that already knows where it found the text passes the
        # offsets through, and they are verified rather than trusted: the span
        # must still hold the surface, so the grounding rule is unchanged.
        offered_start = candidate.get("start")
        offered_end = candidate.get("end")
        if offered_start is not None and offered_end is not None:
            try:
                start, end = int(offered_start), int(offered_end)
            except (TypeError, ValueError):
                report.drop(surface, "bad-offsets")
                continue
            if not (0 <= start < end <= len(text)):
                report.drop(surface, "offsets-out-of-range")
                continue
            if text[start:end] != surface:
                report.drop(surface, "offsets-do-not-hold-surface")
                continue
            match_kind = "exact"
        else:
            located = find_span(text, surface, resume.get(surface.lower(), 0))
            if located is None:
                # The hallucination case: the extractor produced a name the
                # review does not contain — or claimed more occurrences of it
                # than the review actually has.
                report.drop(surface, "not-in-source")
                continue
            start, end, match_kind = located
            resume[surface.lower()] = end
        # The surface is re-read from the source rather than trusted, so a
        # case- or whitespace-variant is stored as the reviewer wrote it.
        actual = text[start:end]
        key = (entity_type, start, end)
        if key in seen:
            report.drop(surface, "duplicate-span")
            continue
        seen.add(key)

        confidence = candidate.get("confidence")
        mentions.append(Mention(
            review_id=review_id,
            entity_type=entity_type,
            surface=actual,
            start=start,
            end=end,
            match_kind=match_kind,
            sentence=sentence_around(text, start, end),
            language=language,
            extractor=extractor,
            confidence=None if confidence is None else float(confidence),
        ))
        report.kept += 1
        report.note(match_kind)

    return mentions, report


# --- generic-name guard --------------------------------------------------

# Section 5.1 names this edge case directly: 'generic "the beach" vs a named
# stretch'. A mention whose surface is only these words is not an entity, and
# letting them through would make every beach review mention one "place".
GENERIC_SURFACES = {
    "the beach", "beach", "the sea", "sea", "the river", "river", "the hotel",
    "hotel", "the room", "room", "the place", "place", "the food", "food",
    "the staff", "staff", "the park", "park", "the lake", "lake", "the forest",
    "forest", "the temple", "temple", "the mosque", "mosque", "the market",
    "market", "the island", "island", "the hill", "hill", "the fort", "fort",
    "the museum", "museum", "the garden", "garden", "the city", "city",
    "the village", "village", "the road", "road", "the bridge", "bridge",
}


def is_generic(surface: str) -> bool:
    """True when a surface form names a category rather than a place.

    A blank surface counts as generic so that callers using this as a filter
    reject it, rather than each having to check for emptiness first.
    """
    cleaned = _squeeze(str(surface or "")).lower().strip(".,;:!?")
    return not cleaned or cleaned in GENERIC_SURFACES


def strip_qualifier(name: str) -> str:
    """Drop a trailing parenthetical, as Phase 9's matcher already does.

    "Sundarbans (Karamjal Wildlife Centre)" -> "Sundarbans". The corpus's own
    place names carry these, so resolution needs both forms.
    """
    return _squeeze(re.sub(r"\s*\([^)]*\)\s*$", "", str(name or "")))


def ascii_fold(text: str) -> str:
    """Strip diacritics from Latin text, for comparison only."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c))
