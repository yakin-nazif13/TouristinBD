"""Phase 4 — entity extraction. BUILD_PLAN section 5.2.

Section 5.2 names two methods and one non-negotiable rule:

    Baseline:     multilingual/Bangla NER (BanglaBERT or XLM-R).
    Main method:  constrained LLM extraction with a JSON schema.
    Hard rule:    every entity must be an exact substring of the source text,
                  or it is dropped.

The rule lives in `gem_schema.ground` and is applied to **every** extractor's
output, so no extractor can bypass it. What differs between extractors is only
how candidates are proposed.

Three are available:

  gazetteer   Offline, free, deterministic. Matches known Bangladeshi place
              names — the corpus's own places plus section 3.1's anchor list —
              inside reviews of *other* places. This is the probe section 0
              describes: "Even a crude pattern match finds about 50 secondary
              places mentioned inside reviews of other places." It needs no
              key and no model, so the whole downstream chain (resolution,
              scoring, the queue) can be built and tested without spending
              anything.

  gemini      Section 5.2's main method: constrained JSON extraction, reusing
              Phase 4's existing call_llm_json with its truncation retry and
              backoff. **Costs API quota** — one call per review — so it is
              never the default and prints an estimate before it starts.

  ner         Section 5.2's baseline: a token-classification model. Needs torch,
              so it runs on the Linux runner rather than locally.

Every run writes the same artifact, so the extractors are comparable:

    data/phase4_mentions.csv      one row per grounded mention
    data/phase4_extraction_report.{md,json}

The report carries the grounding drop rate, which for `gemini` is its
hallucination rate on this corpus — the number section 6.1 asks for.

Run:
    .venv/bin/python scripts/extract_mentions.py --extractor gazetteer
    .venv/bin/python scripts/extract_mentions.py --extractor gazetteer --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gem_schema import (  # noqa: E402
    ENTITY_TYPE_HELP,
    ENTITY_TYPES,
    GroundingReport,
    ground,
    has_bengali,
    is_generic,
    strip_article,
    strip_qualifier,
    term_pattern,
)
from language_id import normalize_bangla  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))

IN_CORPUS = DATA_DIR / "processed_reviews.csv"
IN_GEOGRAPHY = DATA_DIR / "place_geography.csv"
IN_LANGUAGE = DATA_DIR / "phase3_language_labels.csv"
# Bangla spellings of known places, mined from the corpus and reviewed
# (scripts/mine_bangla_place_names.py). Only `accept` rows are used.
IN_BANGLA_NAMES = DATA_DIR / "place_names_bn.csv"
# Foods, activities and transport named in the reviews, each spelling checked
# against real review text. Only `accept` rows are used.
IN_LEXICON = DATA_DIR / "food_activity_lexicon.csv"
OUT_MENTIONS = DATA_DIR / "phase4_mentions.csv"
OUT_REPORT_MD = DATA_DIR / "phase4_extraction_report.md"
OUT_REPORT_JSON = DATA_DIR / "phase4_extraction_report.json"

MENTION_COLUMNS = [
    "review_id", "entity_type", "surface", "start", "end", "match_kind",
    "sentence", "language", "extractor", "confidence", "phonetic_key",
]

# Section 3.1's anchor list, used as gazetteer seeds. These are the famous
# places; a mention of one inside a review of another is a cross-reference, and
# a mention of something *not* here is what the LLM extractor is for.
ANCHOR_SEEDS = [
    "Lalbagh Fort", "Ahsan Manzil", "Panam City", "Sonargaon",
    "National Botanical Garden", "Bhawal National Park",
    "Cox's Bazar", "Saint Martin", "Bandarban", "Nilgiri", "Nilachal",
    "Rangamati", "Kaptai", "Sitakunda", "Khagrachari", "Alutila",
    "Jaflong", "Ratargul", "Bisnakandi", "Lalakhal", "Srimangal", "Sreemangal",
    "Lawachara", "Tanguar Haor", "Madhabkunda", "Madhabpur Lake",
    "Sundarbans", "Karamjal", "Kotka", "Sixty Dome Mosque", "Bagerhat",
    "Mongla", "Kuakata", "Durga Sagar", "Bhimruli",
    "Paharpur", "Mahasthangarh", "Puthia", "Varendra Museum", "Padma",
    "Tajhat Palace", "Kantaji Temple", "Ramsagar", "Tetulia", "Kanchenjunga",
    "Birisiri", "Durgapur", "Shoshi Lodge", "Gazni", "Muktagachha",
    # Secondary places section 0 reports the probe already finding.
    "Fatrar Chor", "Chor Bijoy", "Char Bijoy", "Gangamati", "Chandranath",
    "Muradpur", "Boga Lake", "Sardar Bari", "Guliakhali", "Guliyakhali",
    "Fokirhat", "Pashur",
]

# ACCESS and TIP cues (section 5.1). Deliberately narrow: a cue list produces
# evidence the LLM extractor can be measured against, not a finished extractor.
ACCESS_CUES = [
    r"get off at [A-Z][\w' ]{2,30}",
    r"take a (?:CNG|bus|boat|rickshaw|launch|ferry|train)[\w' ]{0,30}",
    r"(?:engine )?boat from [A-Z][\w' ]{2,30}",
    r"bus from [A-Z][\w' ]{2,30}",
]
TIP_CUES = [
    r"best (?:season|time) (?:is|to visit)[\w' ]{0,30}",
    r"(?:go|visit) (?:early|in the morning|at sunrise|in winter)[\w' ]{0,20}",
    r"carry [\w' ]{3,30}",
    r"bargain[\w' ]{0,25}",
]


def load_gazetteer(corpus: pd.DataFrame) -> list[str]:
    """Known place names: the corpus's own, the geography file's, and the seeds.

    Both the full name and its qualifier-stripped form are included, because
    the corpus writes "Sundarbans (Karamjal Wildlife Centre)" while a review
    says "Sundarbans".
    """
    # A leading "the" is dropped from every name ("The Sundarbans" -> "Sundarbans"), so a
    # review saying "the Sundarbans" is recorded as the plain, well-known name and not as
    # a separate entity that the map lookup cannot place.
    names: set[str] = set()
    for name in corpus.get("place_name", pd.Series(dtype=str)).dropna().astype(str):
        names.add(strip_article(name.strip()))
        names.add(strip_article(strip_qualifier(name)))
    if IN_GEOGRAPHY.exists():
        geography = pd.read_csv(IN_GEOGRAPHY)
        for name in geography.get("place_name", pd.Series(dtype=str)).dropna().astype(str):
            names.add(strip_article(name.strip()))
            names.add(strip_article(strip_qualifier(name)))
    names.update(strip_article(n) for n in ANCHOR_SEEDS)

    # Short or generic names would match inside other words and inside every
    # review ("Padma" is fine, "sea" is not).
    usable = {n for n in names if len(n) >= 4 and not is_generic(n)}
    # Longest first, so "Saint Martin's Island" is proposed before "Saint Martin".
    return sorted(usable, key=lambda n: (-len(n), n))


def _accepted(path: Path) -> pd.DataFrame:
    """Rows of a reviewed list whose decision is `accept`."""
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    return frame[frame["decision"].astype(str).str.strip() == "accept"]


def load_bangla_names() -> dict[str, str]:
    """Accepted Bangla spelling -> the English gazetteer name it stands for."""
    frame = _accepted(IN_BANGLA_NAMES)
    if frame.empty:
        return {}
    return dict(zip(frame["bangla"].astype(str), frame["place"].astype(str)))


def load_lexicon() -> list[tuple[str, str]]:
    """Accepted (surface, entity_type) pairs, longest surface first."""
    frame = _accepted(IN_LEXICON)
    if frame.empty:
        return []
    pairs = {(str(s), str(t).upper()) for s, t in zip(frame["surface"], frame["entity_type"])}
    return sorted(pairs, key=lambda p: (-len(p[0]), p[0]))


def _name_tokens(name: str) -> set[str]:
    """Lowercased word tokens of a place name, punctuation removed.

    Parentheticals are kept as tokens rather than dropped, because the corpus
    writes "Sundarbans (Karamjal Wildlife Centre)" and a review of that page
    saying "Karamjal" is still talking about its own subject.
    """
    cleaned = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    return {t for t in cleaned.split() if t}


def _trim_to_word(text: str, start: int, end: int) -> str:
    """The span, pulled back to the last complete word and stripped of punctuation.

    A cue match that ends mid-word is extended backwards rather than forwards:
    guessing the rest of the word would invent text, and the grounding rule
    exists precisely to stop that.
    """
    end = min(end, len(text))
    # Mid-word only if the next character continues it.
    while end > start and end < len(text) and text[end].isalnum() and text[end - 1].isalnum():
        end -= 1
    return text[start:end].strip(" .,;:!?-")


def extract_gazetteer(text: str, place_name: str, gazetteer: list[str],
                      aliases: dict[str, str] | None = None,
                      lexicon: list[tuple[str, str]] | None = None) -> list[dict]:
    """Propose known names found in the text, except the review's own place.

    Excluding the review's own place is the point: a mention of Kuakata in a
    Kuakata review says nothing, while a mention of Fatrar Chor in one is the
    long-tail signal section 3.2 snowballs on.

    `aliases` are Bangla spellings, each standing for an English name; the
    own-place test uses the English name, so "বান্দরবান" in a review of
    Bandarban is excluded exactly as "Bandarban" is. `lexicon` adds foods,
    activities and transport, which are not excluded for the review's own place:
    a Kuakata review naming the crab fry it ate is evidence about Kuakata.
    """
    aliases = aliases or {}
    names = sorted(set(gazetteer) | set(aliases), key=lambda n: (-len(n), n))
    # Every token of the review's own place, so a *short form* of it is
    # excluded too. Comparing whole strings is not enough: a review of
    # "Kuakata Beach" saying "Kuakata" was being counted as a secondary
    # mention, and 224 of 440 mentions (51%) were self-mentions of exactly
    # that shape. A review talking about its own subject is not a discovery,
    # and section 3.2's whole premise is mentions found inside reviews of
    # *other* places.
    own_tokens = _name_tokens(place_name)
    candidates: list[dict] = []
    claimed: list[tuple[int, int]] = []

    for name in names:
        name_tokens = _name_tokens(aliases.get(name, name))
        if name_tokens and own_tokens and name_tokens <= own_tokens:
            continue
        # Word-boundary match so "Padma" does not fire inside "Padmasana". A
        # Bangla name gets term_pattern's boundary, which also allows a case
        # ending ("বান্দরবানের") and stops at a vowel sign.
        if has_bengali(name):
            pattern = term_pattern(name)
        else:
            pattern = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])", re.IGNORECASE)
        for found in pattern.finditer(text):
            span = (found.start(), found.end())
            # A longer name already covering this span wins (longest-first order).
            if any(s <= span[0] and span[1] <= e for s, e in claimed):
                continue
            claimed.append(span)
            # Offsets are passed through: this extractor knows exactly where it
            # matched, and a review naming one place twice must give two
            # mentions. Re-searching would collapse them onto the first hit.
            candidates.append({
                "surface": text[found.start():found.end()],
                "entity_type": "PLACE",
                "start": found.start(),
                "end": found.end(),
            })

    # Foods, activities and transport. A span already claimed by a place name is
    # skipped, so "Bhimruli Floating Guava Market" stays one place rather than
    # also yielding "guava"; a longer lexicon term likewise beats a shorter one.
    for surface, entity_type in lexicon or []:
        for found in term_pattern(surface).finditer(text):
            span = (found.start(), found.end())
            if any(s < span[1] and span[0] < e for s, e in claimed):
                continue
            claimed.append(span)
            candidates.append({
                "surface": text[found.start():found.end()],
                "entity_type": entity_type,
                "start": found.start(),
                "end": found.end(),
            })

    for pattern_list, entity_type in ((ACCESS_CUES, "ACCESS"), (TIP_CUES, "TIP")):
        for raw in pattern_list:
            for found in re.compile(raw, re.IGNORECASE).finditer(text):
                # The cue patterns cap their tail at a character count, which
                # lands mid-word ("...the precise Zero Poin"). Evidence quoted
                # in the district register has to be readable, so the span is
                # pulled back to the last whole word.
                surface = _trim_to_word(text, found.start(), found.end())
                if not surface:
                    continue
                start = text.find(surface, found.start())
                if start < 0:
                    continue
                candidates.append({
                    "surface": surface,
                    "entity_type": entity_type,
                    "start": start,
                    "end": start + len(surface),
                })
    return candidates


# --- the LLM extractor (section 5.2's main method) -----------------------

LLM_PROMPT = """You extract tourism entities from a single review of a place in Bangladesh.

Return JSON only, shaped exactly:
{{"mentions": [{{"surface": "...", "entity_type": "...", "confidence": 0.0}}]}}

entity_type must be one of:
{types}

Rules you must follow:
1. `surface` MUST be copied character-for-character from the review text below.
   Do not translate it, correct its spelling, expand it or change its case.
   Anything not found verbatim in the review is discarded by the caller, so
   inventing text only loses the mention.
2. Do not return the review's own place ("{place_name}") as a PLACE.
3. Do not return generic categories ("the beach", "the hotel"). Only named or
   specifically described things.
4. If the review mentions nothing of these kinds, return {{"mentions": []}}.

Review (place: {place_name}, language: {language}):
---
{text}
---"""


def extract_gemini(text: str, place_name: str, language: str, client, model, provider) -> list[dict]:
    """Constrained JSON extraction. One API call; costs quota."""
    import run_phase4_preference_classification as phase4

    prompt = LLM_PROMPT.format(
        types="\n".join(f"  {t}: {ENTITY_TYPE_HELP[t]}" for t in ENTITY_TYPES),
        place_name=place_name,
        language=language or "unknown",
        text=text,
    )
    payload = phase4.call_llm_json(client, model, prompt, max_tokens=1200, provider=provider)
    mentions = payload.get("mentions", []) if isinstance(payload, dict) else []
    return [m for m in mentions if isinstance(m, dict)]


def extract_ner(text: str, pipeline) -> list[dict]:
    """Baseline token-classification extractor. Needs torch."""
    candidates = []
    for entity in pipeline(text):
        word = str(entity.get("word") or entity.get("entity_group") or "").strip()
        if word and not is_generic(word):
            candidates.append({
                "surface": word,
                "entity_type": "PLACE",
                "confidence": float(entity.get("score", 0.0)),
            })
    return candidates


# --- runner --------------------------------------------------------------


def language_by_review() -> dict[str, str]:
    if not IN_LANGUAGE.exists():
        return {}
    frame = pd.read_csv(IN_LANGUAGE)
    if not {"review_id", "language_label"} <= set(frame.columns):
        return {}
    return dict(zip(frame["review_id"].astype(str), frame["language_label"].astype(str)))


def text_for(row: pd.Series) -> str:
    """The text to extract from: the reviewer's own words where they exist.

    Section 4.4: "Entity extraction: always on the original text." The clean
    analysis text is the fallback for rows collected before Phase 1's fix.
    """
    original = row.get("review_text_original")
    if isinstance(original, str) and original.strip():
        return original
    return str(row.get("review_text_clean") or "")


def concept_table(mentions: pd.DataFrame) -> pd.DataFrame:
    """Lexicon mentions grouped by concept: reviews, mentions, spellings seen."""
    frame = _accepted(IN_LEXICON)
    if frame.empty or mentions.empty:
        return pd.DataFrame()
    # Normalised on both sides: a reviewer's Bangla may use the decomposed form
    # of a letter that the lexicon stores composed.
    concept_of = {(normalize_bangla(str(s)).lower(), str(t).upper()): str(c)
                  for s, t, c in zip(frame["surface"], frame["entity_type"], frame["concept"])}
    rows = mentions.assign(concept=[
        concept_of.get((normalize_bangla(str(s)).lower(), str(t)))
        for s, t in zip(mentions["surface"], mentions["entity_type"])
    ]).dropna(subset=["concept"])
    if rows.empty:
        return pd.DataFrame()
    table = rows.groupby(["entity_type", "concept"]).agg(
        reviews=("review_id", "nunique"),
        mentions=("review_id", "size"),
        spellings=("surface", lambda s: ", ".join(sorted(set(s.astype(str).str.lower())))),
    ).reset_index()
    return table.sort_values(["entity_type", "reviews"], ascending=[False, False])


def write_reports(mentions: pd.DataFrame, report: GroundingReport, extractor: str,
                  n_reviews: int, notes: list[str]) -> None:
    by_type = mentions["entity_type"].value_counts().to_dict() if not mentions.empty else {}
    payload = {
        "extractor": extractor,
        "n_reviews": n_reviews,
        "n_mentions": int(len(mentions)),
        "reviews_with_a_mention": int(mentions["review_id"].nunique()) if not mentions.empty else 0,
        "by_entity_type": {k: int(v) for k, v in sorted(by_type.items())},
        "distinct_surfaces": int(mentions["surface"].nunique()) if not mentions.empty else 0,
        "grounding": report.as_dict(),
        "notes": notes,
    }
    OUT_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase 4 — Entity extraction",
        "",
        f"Extractor: **{extractor}**. Section 5.2's grounding rule is applied to every",
        "candidate: a surface form that cannot be located in the review is dropped.",
        "",
        f"- Reviews processed: **{n_reviews}**",
        f"- Grounded mentions: **{len(mentions)}**",
        f"- Reviews with at least one: {payload['reviews_with_a_mention']}",
        f"- Distinct surface forms: {payload['distinct_surfaces']}",
        "",
        "## Grounding",
        "",
        f"- Candidates proposed: {report.total}",
        f"- Kept: {report.kept}",
        f"- Dropped: {report.dropped} (**{report.drop_rate:.1%}**)",
        "",
    ]
    if extractor == "gemini":
        lines += [
            "For an LLM extractor the drop rate *is* the hallucination rate on this",
            "corpus — the measurement section 6.1 asks for.",
            "",
        ]
    if report.by_match_kind:
        lines += ["| match kind | mentions |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(report.by_match_kind.items())]
        lines.append("")
    if report.dropped_reasons:
        lines += ["| drop reason | candidates |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(report.dropped_reasons.items())]
        lines.append("")
    if by_type:
        lines += ["## By entity type", "", "| type | mentions |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(by_type.items())]
        lines.append("")
    if not mentions.empty:
        top = mentions["surface"].value_counts().head(20)
        lines += ["## Most-mentioned surfaces", "", "| surface | mentions |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in top.items()]
        lines.append("")

        bangla = mentions[mentions["surface"].astype(str).map(has_bengali)]
        payload["bangla_script_mentions"] = int(len(bangla))
        lines += [
            "## Mentions written in Bangla script",
            "",
            f"- **{len(bangla)}** mention(s) in {bangla['review_id'].nunique()} review(s), "
            f"from the reviewed spellings in `{IN_BANGLA_NAMES.name}` and `{IN_LEXICON.name}`",
            "",
        ]

        concepts = concept_table(mentions)
        if not concepts.empty:
            payload["concepts"] = concepts.to_dict(orient="records")
            lines += [
                "## Foods, activities and transport",
                "",
                "Every spelling below was found in real review text before it was added",
                f"(`{IN_LEXICON.name}`, which also records each rejected spelling and why).",
                "",
                "| type | concept | reviews | mentions | spellings found |",
                "| --- | --- | --- | --- | --- |",
            ]
            for _, row in concepts.iterrows():
                lines.append(f"| {row['entity_type']} | {row['concept']} | {row['reviews']} | "
                             f"{row['mentions']} | {row['spellings']} |")
            lines.append("")
        OUT_REPORT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=["gazetteer", "gemini", "ner"], default="gazetteer")
    parser.add_argument("--limit", type=int, help="process only the first N reviews")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--model", help="override the model for --extractor gemini/ner")
    parser.add_argument(
        "--yes", action="store_true",
        help="skip the cost confirmation for --extractor gemini",
    )
    args = parser.parse_args()

    if not IN_CORPUS.exists():
        print(f"error: {IN_CORPUS} does not exist; run Phase 2 first")
        return 1

    corpus = pd.read_csv(IN_CORPUS)
    if args.limit:
        corpus = corpus.head(args.limit)
    languages = language_by_review()
    notes: list[str] = []

    print(f"Phase 4 — extracting entities from {len(corpus)} review(s) with `{args.extractor}`")

    client = model = provider = pipeline = None
    gazetteer: list[str] = []
    aliases: dict[str, str] = {}
    lexicon: list[tuple[str, str]] = []

    if args.extractor == "gazetteer":
        gazetteer = load_gazetteer(corpus)
        aliases = load_bangla_names()
        lexicon = load_lexicon()
        notes.append(f"gazetteer of {len(gazetteer)} known names (corpus + geography + 3.1 anchors)")
        notes.append(f"{len(aliases)} reviewed Bangla spelling(s) of those names ({IN_BANGLA_NAMES.name})")
        notes.append(f"{len(lexicon)} reviewed food / activity / transport spelling(s) ({IN_LEXICON.name})")
        print(f"  gazetteer: {len(gazetteer)} names + {len(aliases)} Bangla spellings")
        print(f"  lexicon: {len(lexicon)} food / activity / transport spellings")
    elif args.extractor == "gemini":
        # One call per review against a paid quota. Never silent.
        print(
            f"\n  This makes {len(corpus)} LLM calls against your API quota.\n"
            "  Phase 4's existing taxonomy run is separate from this.\n"
        )
        if not args.yes:
            print("  Refusing to spend quota without --yes. Re-run with --yes to proceed.")
            return 1
        import run_phase4_preference_classification as phase4

        if args.model:
            os.environ["GEMINI_MODEL"] = args.model
        client, model, provider = phase4.make_client()
        notes.append(f"LLM extraction with {model} ({provider}), {len(corpus)} calls")
    else:
        from transformers import pipeline as hf_pipeline

        model_id = args.model or "Davlan/xlm-roberta-base-ner-hrl"
        pipeline = hf_pipeline("ner", model=model_id, aggregation_strategy="simple")
        notes.append(f"NER baseline with {model_id}")

    report = GroundingReport()
    rows: list[dict] = []
    for _, row in corpus.iterrows():
        review_id = str(row["review_id"])
        text = text_for(row)
        if not text.strip():
            continue
        place_name = str(row.get("place_name") or "")
        language = languages.get(review_id, str(row.get("detected_language") or ""))

        if args.extractor == "gazetteer":
            candidates = extract_gazetteer(text, place_name, gazetteer, aliases, lexicon)
        elif args.extractor == "gemini":
            try:
                candidates = extract_gemini(text, place_name, language, client, model, provider)
            except Exception as exc:
                notes.append(f"review {review_id}: {type(exc).__name__}: {exc}")
                continue
        else:
            candidates = extract_ner(text, pipeline)

        # The generic guard runs before grounding so "the beach" is not counted
        # as a dropped hallucination — it was found, it just is not an entity.
        candidates = [c for c in candidates if not is_generic(c.get("surface", ""))]

        mentions, report = ground(
            review_id, text, candidates, report=report,
            extractor=args.extractor, language=language,
        )
        rows.extend(m.as_row() for m in mentions)

    frame = pd.DataFrame(rows, columns=MENTION_COLUMNS) if rows else pd.DataFrame(columns=MENTION_COLUMNS)
    print(f"  grounded mentions: {len(frame)}")
    print(f"  candidates proposed: {report.total}, dropped: {report.dropped} ({report.drop_rate:.1%})")
    if not frame.empty:
        print("  by type: " + ", ".join(
            f"{k}={v}" for k, v in sorted(frame['entity_type'].value_counts().items())))

    if args.dry_run:
        print(f"\n  --dry-run: would write {OUT_MENTIONS.name} and its report")
        return 0

    OUT_MENTIONS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_MENTIONS, index=False)
    write_reports(frame, report, args.extractor, len(corpus), notes)
    print(f"\n  wrote {OUT_MENTIONS.name}, {OUT_REPORT_MD.name}, {OUT_REPORT_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
