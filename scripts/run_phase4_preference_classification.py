"""
Phase 4 — 4-stage LLM preference classification (Zhang et al. 2026 adapted).

Stage 1: Topic interpretation (LLM)
Stage 2: Preference hierarchy construction (LLM)
Stage 3: Topic–preference mapping via cosine similarity of embeddings
Stage 4: Long-tail identification (size < 2% AND SDD > 0.6)

Outputs under data/:
  stage1_topic_interpretations.{csv,json}
  preference_classification.{csv,json}
  topic_preference_mapping.{csv,json}
  long_tail_flags.{csv,json}
  topic_preferences.{csv,json}   # joined summary for later phases
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
load_dotenv(REPO_ROOT / ".env")
REVIEWS_PATH = DATA_DIR / "reviews_with_topics.csv"
TOPICS_PATH = DATA_DIR / "topics_summary.csv"

STAGE1_CSV = DATA_DIR / "stage1_topic_interpretations.csv"
STAGE1_JSON = DATA_DIR / "stage1_topic_interpretations.json"
PREF_CSV = DATA_DIR / "preference_classification.csv"
PREF_JSON = DATA_DIR / "preference_classification.json"
MAP_CSV = DATA_DIR / "topic_preference_mapping.csv"
MAP_JSON = DATA_DIR / "topic_preference_mapping.json"
LONGTAIL_CSV = DATA_DIR / "long_tail_flags.csv"
LONGTAIL_JSON = DATA_DIR / "long_tail_flags.json"
SUMMARY_CSV = DATA_DIR / "topic_preferences.csv"
SUMMARY_JSON = DATA_DIR / "topic_preferences.json"

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TAU_SIM = 0.4
SCARCITY_THRESHOLD = 0.02  # topic size < 2% of corpus
SDD_THRESHOLD = 0.6

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

STAGE1_PROMPT = """
You are a travel preference analyst for Bangladeshi tourism reviews.
Interpret the following BERTopic cluster from hotel and attraction reviews.

Grounding rules (important):
- Weight the top keywords and place mix heavily; do not let one venue in the samples dominate the label.
- If keywords and places point to heritage/history in Dhaka (or multiple historic sites), label that theme — even if some sample reviews are about another place.
- Prefer a label that covers the majority of reviews in the place mix.

Return ONLY a raw JSON object (no markdown) with:
- topic_id: integer
- interpreted_label: 3-6 word human-readable topic label
- interpretation: 1-2 sentences explaining what travelers discuss in this topic
- dimension_hint: one of "Culinary Experiences", "Accommodation", "Attractions & Activities", or "Cross-cutting"

Topic ID: {topic_id}
Topic name: {topic_name}
Top keywords: {top_keywords}
Place mix (top venues): {place_mix}
Review count: {review_count} (of {corpus_size} total)
Sample reviews (place-diverse):
{sample_reviews}
"""

STAGE2_PROMPT = """
You are building a Bangladesh tourism preference taxonomy for destination management.
Using the topic interpretations below, construct a 3-tier preference hierarchy
(Category → Subcategory → Preference) grounded in Bangladeshi tourism
(Culinary Experiences, Accommodation, Attractions & Activities; also Ecotourism,
Heritage, Coastal, Religious, Adventure, Nature where relevant).

Rules:
- Prefer fewer, coherent preferences over one preference per topic.
- Each preference should be mappable to one or more of the topics.
- Use concrete preference names (e.g. "Beachfront hotel service", "Heritage fort visits").
- Cover all provided topics.

Return ONLY a raw JSON object (no markdown) with this shape:
{{
  "preferences": [
    {{
      "preference_id": "P01",
      "category": "...",
      "subcategory": "...",
      "preference": "...",
      "description": "one sentence"
    }}
  ]
}}

Topic interpretations:
{topic_block}
"""


def keywords_from_topic_name(topic_name: str) -> str:
    """Fallback when topics_summary.top_keywords is empty (HF Phase 3 artifact)."""
    name = str(topic_name or "").strip()
    if not name:
        return ""
    # BERTopic names look like: 0_good_room_staff_hotel
    parts = name.split("_")
    if parts and parts[0].lstrip("~").lstrip("-").isdigit():
        parts = parts[1:]
    return ", ".join(p for p in parts if p)


def enrich_topic_keywords(topics: pd.DataFrame) -> pd.DataFrame:
    out = topics.copy()
    if "top_keywords" not in out.columns:
        out["top_keywords"] = ""
    filled = []
    for _, row in out.iterrows():
        kw = str(row.get("top_keywords", "") or "").strip()
        if not kw or kw.lower() == "nan":
            kw = keywords_from_topic_name(row.get("topic_name", ""))
        filled.append(kw)
    out["top_keywords"] = filled
    return out


def make_sample_reviews(texts: list[str], max_items: int = 4) -> str:
    lines = []
    for i, text in enumerate(texts[:max_items], start=1):
        cleaned = text.replace("\n", " ").strip()
        if len(cleaned) > 280:
            cleaned = cleaned[:277].rstrip() + "..."
        lines.append(f"{i}. {cleaned}")
    return "\n".join(lines)


def make_diverse_samples(topic_reviews: pd.DataFrame, max_items: int = 5) -> str:
    """
    Prefer place diversity so a mixed topic (e.g. heritage + Jaflong) isn't
    mislabeled from the first N reviews of one venue.
    """
    if topic_reviews.empty:
        return ""
    rows: list[str] = []
    if "place_name" in topic_reviews.columns:
        places = (
            topic_reviews["place_name"].fillna("unknown").astype(str).value_counts().index.tolist()
        )
        # round-robin across places
        buckets = {
            p: topic_reviews[topic_reviews["place_name"].fillna("unknown").astype(str) == p][
                "review_text_clean"
            ]
            .dropna()
            .astype(str)
            .tolist()
            for p in places
        }
        idx = {p: 0 for p in places}
        while len(rows) < max_items:
            added = False
            for p in places:
                i = idx[p]
                if i < len(buckets[p]):
                    rows.append(buckets[p][i])
                    idx[p] = i + 1
                    added = True
                    if len(rows) >= max_items:
                        break
            if not added:
                break
    else:
        rows = topic_reviews["review_text_clean"].dropna().astype(str).tolist()[:max_items]

    return make_sample_reviews(rows, max_items=max_items)


def place_mix_summary(topic_reviews: pd.DataFrame, top_n: int = 5) -> str:
    if topic_reviews.empty or "place_name" not in topic_reviews.columns:
        return "n/a"
    counts = topic_reviews["place_name"].fillna("unknown").astype(str).value_counts().head(top_n)
    return "; ".join(f"{name} ({count})" for name, count in counts.items())


def get_client_and_model():
    """
    Provider selection via LLM_PROVIDER=openai|gemini.
    Default: gemini (free-tier flash-lite works reliably for this project),
    else openai.
    """
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        provider = "gemini" if GEMINI_API_KEY else "openai"

    if provider == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        client = OpenAI(api_key=OPENAI_API_KEY)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return client, model, "openai"

    if not GEMINI_API_KEY:
        if OPENAI_API_KEY:
            client = OpenAI(api_key=OPENAI_API_KEY)
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            return client, model, "openai"
        raise RuntimeError(
            "Set GEMINI_API_KEY or OPENAI_API_KEY in your .env file before running Phase 4."
        )
    client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    return client, model, "gemini"


class TruncatedResponse(ValueError):
    """The model ran out of output budget mid-answer."""


def call_llm(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int = 800,
    *,
    provider: str = "openai",
) -> str:
    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise tourism preference analyst. "
                    "Always respond with a single raw JSON object only — "
                    "no markdown code fences, no explanation text."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    # OpenAI supports json_object mode; Gemini's OpenAI-compatible endpoint is flaky with it.
    if provider == "openai":
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    content = choice.message.content
    # Newer Gemini/OpenAI models spend part of their budget on internal
    # reasoning before emitting anything, so a budget sized for a plain
    # completion runs out mid-JSON. That surfaces here as a truncated object
    # (finish_reason="length"), which the caller answers by retrying with a
    # bigger budget rather than by blaming the model's JSON.
    if getattr(choice, "finish_reason", None) == "length":
        raise TruncatedResponse(
            f"response hit the {max_tokens}-token limit before finishing"
        )
    if content is None:
        raise ValueError("LLM returned empty content")
    return content.strip()


def parse_json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if not cleaned.startswith("{") and "{" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON response from LLM:\n{text}") from exc


# Transient server-side conditions: the request was fine, the model was busy or
# rate-limited. Worth waiting out. Anything else (bad key, unknown model,
# malformed request) will fail identically on every retry, so it fails fast.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# Ceiling for the automatic budget growth on a truncated response.
MAX_OUTPUT_TOKENS = 32000

# Starting budgets. Sized for a reasoning model's thinking tokens plus the
# answer; call_llm_json grows them automatically if a response still truncates.
STAGE1_MAX_TOKENS = 1500   # one topic interpretation
STAGE2_MAX_TOKENS = 8000   # the whole preference hierarchy in one response


def is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status is not None:
        return int(status) in RETRYABLE_STATUS
    # Parse failures and truncated responses are worth another sample; so are
    # raw connection errors, which carry no status code.
    return isinstance(exc, (ValueError, ConnectionError, TimeoutError))


def call_llm_json(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int = 800,
    *,
    provider: str = "openai",
    retries: int = 6,
) -> tuple[dict, str]:
    """One JSON-returning LLM call, retried with exponential backoff.

    Gemini answers a busy model with 503 "high demand", which clears on its own
    within seconds — but the whole phase dies if a single topic gives up too
    early, losing the calls already paid for. Backoff runs 2s, 4s, 8s, 16s, 32s
    (capped, with jitter so parallel runs don't retry in lockstep).
    """
    last_err: Exception | None = None
    budget = max_tokens
    for attempt in range(1, retries + 1):
        try:
            raw = call_llm(client, model, prompt, max_tokens=budget, provider=provider)
            return parse_json_object(raw), raw
        except Exception as exc:  # noqa: BLE001 — retry LLM/network/parse failures
            last_err = exc
            if not is_retryable(exc):
                raise RuntimeError(
                    f"LLM call failed and will not succeed on retry: {exc}"
                ) from exc
            if attempt == retries:
                break
            if isinstance(exc, TruncatedResponse):
                # Retrying at the same budget would truncate again; grow it
                # instead, and don't wait — nothing is rate-limiting us.
                budget = min(budget * 3, MAX_OUTPUT_TOKENS)
                print(f"    retry {attempt}/{retries} with a {budget}-token budget")
                continue
            delay = min(2.0 * 2 ** (attempt - 1), 32.0) + random.uniform(0, 1.0)
            print(f"    retry {attempt}/{retries} in {delay:.1f}s: {str(exc)[:140]}")
            time.sleep(delay)
    raise RuntimeError(f"LLM JSON call failed after {retries} attempts") from last_err


def save_table(rows: list[dict] | pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    records = df.to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  saved {csv_path.name} ({len(df)} rows)")


def stage1_interpret(
    client: OpenAI,
    model: str,
    reviews: pd.DataFrame,
    topics: pd.DataFrame,
    corpus_size: int,
    *,
    provider: str,
) -> list[dict]:
    print("\n=== Stage 1: Topic interpretation ===")
    results = []
    for _, topic in topics.iterrows():
        topic_id = int(topic["Topic"])
        if topic_id == -1:
            continue
        topic_name = str(topic.get("topic_name", f"topic_{topic_id}"))
        keywords = str(topic.get("top_keywords", ""))
        topic_mask = reviews["topic_id"] == topic_id
        topic_df = reviews.loc[topic_mask].copy()
        topic_reviews = topic_df["review_text_clean"].dropna().astype(str).tolist()
        if not topic_reviews:
            continue

        prompt = STAGE1_PROMPT.format(
            topic_id=topic_id,
            topic_name=topic_name,
            top_keywords=keywords,
            place_mix=place_mix_summary(topic_df),
            review_count=len(topic_reviews),
            corpus_size=corpus_size,
            sample_reviews=make_diverse_samples(topic_df),
        )
        print(f"  interpreting topic {topic_id}: {topic_name} ({len(topic_reviews)} reviews)")
        parsed, raw = call_llm_json(
            client, model, prompt, max_tokens=STAGE1_MAX_TOKENS, provider=provider
        )
        results.append(
            {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "top_keywords": keywords,
                "review_count": len(topic_reviews),
                "corpus_share": round(len(topic_reviews) / corpus_size, 4),
                "interpreted_label": parsed.get("interpreted_label", topic_name),
                "interpretation": parsed.get("interpretation", ""),
                "dimension_hint": parsed.get("dimension_hint", ""),
                "llm_raw": raw,
            }
        )
    save_table(results, STAGE1_CSV, STAGE1_JSON)
    return results


def stage2_build_hierarchy(
    client: OpenAI,
    model: str,
    stage1: list[dict],
    *,
    provider: str,
) -> list[dict]:
    print("\n=== Stage 2: Preference hierarchy construction ===")
    topic_block = "\n\n".join(
        (
            f"Topic {t['topic_id']}: {t['interpreted_label']}\n"
            f"Keywords: {t['top_keywords']}\n"
            f"Share: {t['corpus_share']:.1%} ({t['review_count']} reviews)\n"
            f"Dimension hint: {t['dimension_hint']}\n"
            f"Interpretation: {t['interpretation']}"
        )
        for t in stage1
    )
    prompt = STAGE2_PROMPT.format(topic_block=topic_block)
    parsed, raw = call_llm_json(
        client, model, prompt, max_tokens=STAGE2_MAX_TOKENS, provider=provider
    )
    prefs = parsed.get("preferences", [])
    if not isinstance(prefs, list) or not prefs:
        raise RuntimeError(f"Stage 2 returned no preferences. Raw response:\n{raw}")

    cleaned = []
    for i, p in enumerate(prefs, start=1):
        pid = str(p.get("preference_id") or f"P{i:02d}")
        cleaned.append(
            {
                "preference_id": pid,
                "category": str(p.get("category", "")).strip(),
                "subcategory": str(p.get("subcategory", "")).strip(),
                "preference": str(p.get("preference", "")).strip(),
                "description": str(p.get("description", "")).strip(),
            }
        )
    save_table(cleaned, PREF_CSV, PREF_JSON)
    with open(DATA_DIR / "stage2_hierarchy_raw.json", "w", encoding="utf-8") as f:
        json.dump({"raw": raw, "parsed": parsed}, f, ensure_ascii=False, indent=2)
    print(f"  built {len(cleaned)} preferences")
    return cleaned


def stage3_map_topics(
    stage1: list[dict],
    preferences: list[dict],
    embedder: SentenceTransformer,
) -> list[dict]:
    print("\n=== Stage 3: Topic–preference cosine mapping ===")
    topic_texts = [
        f"{t['interpreted_label']}. {t['interpretation']} Keywords: {t['top_keywords']}"
        for t in stage1
    ]
    pref_texts = [
        (
            f"{p['category']} > {p['subcategory']} > {p['preference']}. "
            f"{p['description']}"
        )
        for p in preferences
    ]
    topic_emb = embedder.encode(topic_texts, normalize_embeddings=True)
    pref_emb = embedder.encode(pref_texts, normalize_embeddings=True)
    sim_matrix = cosine_similarity(topic_emb, pref_emb)

    mappings = []
    for i, topic in enumerate(stage1):
        sims = sim_matrix[i]
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        # second-best for diagnostics
        order = np.argsort(sims)[::-1]
        second_idx = int(order[1]) if len(order) > 1 else best_idx
        second_sim = float(sims[second_idx])
        pref = preferences[best_idx]
        low_conf = best_sim < TAU_SIM
        mappings.append(
            {
                "topic_id": topic["topic_id"],
                "interpreted_label": topic["interpreted_label"],
                "preference_id": pref["preference_id"],
                "category": pref["category"],
                "subcategory": pref["subcategory"],
                "preference": pref["preference"],
                "similarity": round(best_sim, 4),
                "second_best_preference_id": preferences[second_idx]["preference_id"],
                "second_best_similarity": round(second_sim, 4),
                "confidence": "high" if best_sim >= TAU_SIM else "low",
                "needs_review": bool(low_conf),
                "tau_sim": TAU_SIM,
            }
        )
        flag = " ⚠ low-confidence" if low_conf else ""
        print(
            f"  topic {topic['topic_id']} → {pref['preference_id']} "
            f"({pref['preference']}) sim={best_sim:.3f}{flag}"
        )

    save_table(mappings, MAP_CSV, MAP_JSON)
    # persist similarity matrix for Phase 5
    np.save(DATA_DIR / "topic_preference_sim_matrix.npy", sim_matrix)
    return mappings


def stage4_long_tail(
    stage1: list[dict],
    mappings: list[dict],
    preferences: list[dict],
    embedder: SentenceTransformer,
    corpus_size: int,
) -> list[dict]:
    """
    Long-tail rule from the paper/roadmap: size < 2% AND SDD > 0.6.

    SDD (Semantic Difference Degree) for topic i =
      1 - max cosine similarity to any abundant topic (share >= 2%).
    If no other abundant topics exist, SDD = 1.0.
    """
    print("\n=== Stage 4: Long-tail identification ===")
    topic_texts = [
        f"{t['interpreted_label']}. {t['interpretation']}" for t in stage1
    ]
    topic_emb = embedder.encode(topic_texts, normalize_embeddings=True)
    sim = cosine_similarity(topic_emb)

    abundant_idxs = [
        i for i, t in enumerate(stage1) if t["review_count"] / corpus_size >= SCARCITY_THRESHOLD
    ]

    by_topic = {m["topic_id"]: m for m in mappings}
    rows = []
    for i, topic in enumerate(stage1):
        share = topic["review_count"] / corpus_size
        scarce = share < SCARCITY_THRESHOLD

        if abundant_idxs:
            # max sim to an abundant topic that is not itself
            sims_to_abundant = [
                float(sim[i, j]) for j in abundant_idxs if j != i
            ]
            max_sim_abundant = max(sims_to_abundant) if sims_to_abundant else 0.0
        else:
            max_sim_abundant = 0.0
        sdd = 1.0 - max_sim_abundant
        is_long_tail = bool(scarce and sdd > SDD_THRESHOLD)

        mapped = by_topic[topic["topic_id"]]
        preference_type = "long_tail" if is_long_tail else "mainstream"
        rows.append(
            {
                "topic_id": topic["topic_id"],
                "interpreted_label": topic["interpreted_label"],
                "preference_id": mapped["preference_id"],
                "preference": mapped["preference"],
                "review_count": topic["review_count"],
                "corpus_share": round(share, 4),
                "scarce": scarce,
                "max_sim_to_abundant": round(max_sim_abundant, 4),
                "sdd": round(sdd, 4),
                "sdd_threshold": SDD_THRESHOLD,
                "scarcity_threshold": SCARCITY_THRESHOLD,
                "preference_type": preference_type,
                "is_long_tail": is_long_tail,
            }
        )
        mark = "LONG-TAIL" if is_long_tail else "mainstream"
        print(
            f"  topic {topic['topic_id']}: share={share:.1%}, "
            f"SDD={sdd:.3f} → {mark}"
        )

    save_table(rows, LONGTAIL_CSV, LONGTAIL_JSON)

    # preference-level rollup: a preference is long-tail if ANY mapped topic is long-tail
    # and none of its topics are large mainstream-only... simpler: majority / any
    pref_types = {}
    for r in rows:
        pid = r["preference_id"]
        pref_types.setdefault(pid, []).append(r["is_long_tail"])
    for p in preferences:
        flags = pref_types.get(p["preference_id"], [False])
        p["preference_type"] = "long_tail" if any(flags) else "mainstream"
    save_table(preferences, PREF_CSV, PREF_JSON)
    return rows


def build_summary(
    stage1: list[dict],
    mappings: list[dict],
    long_tail: list[dict],
    preferences: list[dict],
) -> None:
    print("\n=== Writing joined topic_preferences summary ===")
    map_by_id = {m["topic_id"]: m for m in mappings}
    lt_by_id = {r["topic_id"]: r for r in long_tail}
    pref_by_id = {p["preference_id"]: p for p in preferences}
    rows = []
    for t in stage1:
        tid = t["topic_id"]
        m = map_by_id[tid]
        lt = lt_by_id[tid]
        pref = pref_by_id.get(m["preference_id"], {})
        signals = [s.strip() for s in str(t["top_keywords"]).split(",") if s.strip()][:3]
        rows.append(
            {
                "topic_id": tid,
                "topic_name": t["topic_name"],
                "top_keywords": t["top_keywords"],
                "review_count": t["review_count"],
                "interpreted_label": t["interpreted_label"],
                "interpretation": t["interpretation"],
                "dimension_hint": t["dimension_hint"],
                "preference_id": m["preference_id"],
                "category": m["category"],
                "subcategory": m["subcategory"],
                "preference_label": m["preference"],
                "preference_description": pref.get("description", ""),
                "similarity": m["similarity"],
                "confidence": m["confidence"],
                "needs_review": m["needs_review"],
                "preference_type": lt["preference_type"],
                "sdd": lt["sdd"],
                "corpus_share": lt["corpus_share"],
                "summary_signals": "; ".join(signals),
            }
        )
    save_table(rows, SUMMARY_CSV, SUMMARY_JSON)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 — LLM preference classification")
    parser.add_argument(
        "--model",
        help="override GEMINI_MODEL/OPENAI_MODEL for this run, e.g. gemini-3.5-flash. "
        "Pin a concrete version rather than a -latest alias when a run is being "
        "written up, so the result stays reproducible.",
    )
    args = parser.parse_args()
    if args.model:
        # get_client_and_model() reads these, so setting them here keeps the
        # single source of truth for provider selection.
        os.environ["GEMINI_MODEL"] = args.model
        os.environ["OPENAI_MODEL"] = args.model

    print("Loading Phase 3 topic artifacts")
    reviews = pd.read_csv(REVIEWS_PATH)
    topics = enrich_topic_keywords(pd.read_csv(TOPICS_PATH))
    # persist repaired keywords so later stages / humans see them
    topics.to_csv(TOPICS_PATH, index=False)
    print(f"  repaired top_keywords in {TOPICS_PATH.name}")

    corpus_size = len(reviews)
    client, model, provider = get_client_and_model()
    print(f"Using LLM: {provider}/{model}")
    print(f"Corpus size: {corpus_size} reviews; scarcity cut = {SCARCITY_THRESHOLD:.0%}")

    stage1 = stage1_interpret(
        client, model, reviews, topics, corpus_size, provider=provider
    )
    if not stage1:
        raise RuntimeError("No topics to classify. Run Phase 3 first.")

    preferences = stage2_build_hierarchy(
        client, model, stage1, provider=provider
    )

    print(f"\nLoading embedding model: {EMBEDDING_MODEL_NAME}")
    embedder = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")

    mappings = stage3_map_topics(stage1, preferences, embedder)
    long_tail = stage4_long_tail(
        stage1, mappings, preferences, embedder, corpus_size
    )
    build_summary(stage1, mappings, long_tail, preferences)

    n_lt = sum(1 for r in long_tail if r["is_long_tail"])
    n_low = sum(1 for m in mappings if m["needs_review"])
    print("\nPhase 4 complete.")
    print(f"  preferences: {len(preferences)}")
    print(f"  mappings: {len(mappings)} ({n_low} below τ_sim={TAU_SIM})")
    print(f"  long-tail topics: {n_lt}/{len(long_tail)}")


if __name__ == "__main__":
    main()
