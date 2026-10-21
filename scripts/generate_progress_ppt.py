"""Generates docs/TouristinBD_Progress.pptx from the Phase 1-9 status in docs/PROGRESS.md.

Run:
    .venv/bin/python scripts/generate_progress_ppt.py
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

NAVY = RGBColor(0x0B, 0x2E, 0x4E)
TEAL = RGBColor(0x11, 0x8A, 0x7E)
GREY = RGBColor(0x44, 0x44, 0x44)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SLIDES = [
    ("Phase 1 — Data Collection", [
        "538 real reviews: 300 Google Maps + 240 Booking.com",
        "15 attractions + 12 hotels across 4 districts",
        "Ratings normalized to a common 1-5 scale",
    ]),
    ("Phase 2 — Preprocessing", [
        "Merged sources into one schema; cleaned text, fixed encoding",
        "Removed 2 bad rows -> 538 final reviews",
        "Real language detection: 530 English, 5 code-mixed, 2 Bengali, 1 Dutch",
    ]),
    ("Phase 3 — Topic Modeling (BERTopic)", [
        "Multilingual sentence-transformer embeddings",
        "26 topics + 1 outlier group (~9% of reviews)",
        "Mix of place-specific and cross-cutting experience topics",
    ]),
    ("Phase 4 — LLM Preference Classification", [
        "4-stage pipeline: topic interpretation -> hierarchy -> cosine mapping -> long-tail rule",
        "10 preferences, 10/10 high-confidence topic mappings (sim >= 0.76)",
        "0 long-tail topics at current corpus size",
    ]),
    ("Phase 5 — Bidirectional Validation", [
        "Direction 1 (topic->preference precision): 10/10 pass",
        "Direction 2 (preference->topic coverage): under-coverage at MVP scale (expected, ~10 topics)",
        "50-pair manual review sample built for human labeling",
    ]),
    ("Phase 6 — Sensitivity Analysis", [
        "Re-clustered at 151 / 247 / 398 / 538 reviews",
        "Preference coverage rises 2/10 -> 9/10 as corpus grows",
        "Mappings stabilize (Jaccard = 1.0) at the full 538-review corpus",
    ]),
    ("Phase 7 — Statistics & Visualization", [
        "Reusable aggregate tables: overview, ratings, temporal, preference frequency, city/venue rollups",
        "Chart set + statistical tests (rank-sum / Mann-Whitney) with graceful zero-data handling",
        "Dashboard payload manifest for Phase 8 API / future frontend",
    ]),
    ("Phase 8 — Backend API + Database", [
        "SQLite database rebuilt idempotently from any subset of Phase 2-7 outputs",
        "Schema-drift tolerant: unknown columns dropped, missing ones become NULL",
        "FastAPI: 35+ endpoints (places, reviews, taxonomy, analytics, research, search, recommend, compare)",
        "97 tests: 68 API smoke tests + 29 forward-compatibility rebuild tests, all passing",
    ]),
    ("Phase 9 — Retrieval-Based Chatbot", [
        "POST /api/chat — no LLM call, no API key needed",
        "Keyword-based intent detection + live database entity matching (place/city/preference)",
        "Reuses tested Phase 8 logic in-process; new data is picked up automatically",
        "31 new tests, all 128 total tests passing after refactor",
    ]),
]


def add_title_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    bg.shadow.inherit = False

    title = slide.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.7), Inches(1.5))
    tf = title.text_frame
    tf.text = "TouristinBD"
    p = tf.paragraphs[0]
    p.font.size = Pt(54)
    p.font.bold = True
    p.font.color.rgb = WHITE

    sub = slide.shapes.add_textbox(Inches(0.8), Inches(3.9), Inches(11.7), Inches(1.2))
    tf2 = sub.text_frame
    tf2.text = "Preference-Based Tourism Recommendation for Bangladesh"
    tf2.paragraphs[0].font.size = Pt(24)
    tf2.paragraphs[0].font.color.rgb = RGBColor(0xC9, 0xE8, 0xE3)

    sub2 = slide.shapes.add_textbox(Inches(0.8), Inches(4.6), Inches(11.7), Inches(0.8))
    tf3 = sub2.text_frame
    tf3.text = "Progress Report — Phases 1 to 9"
    tf3.paragraphs[0].font.size = Pt(18)
    tf3.paragraphs[0].font.color.rgb = RGBColor(0xC9, 0xE8, 0xE3)


def add_bullet_slide(prs, heading, bullets, accent=TEAL):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bar = slide.shapes.add_shape(1, 0, 0, Inches(0.25), prs.slide_height)
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False

    title = slide.shapes.add_textbox(Inches(0.7), Inches(0.4), Inches(11.8), Inches(1.0))
    tf = title.text_frame
    tf.text = heading
    tf.paragraphs[0].font.size = Pt(32)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = NAVY

    body = slide.shapes.add_textbox(Inches(0.9), Inches(1.6), Inches(11.3), Inches(5.2))
    btf = body.text_frame
    btf.word_wrap = True
    for i, b in enumerate(bullets):
        p = btf.paragraphs[0] if i == 0 else btf.add_paragraph()
        p.text = b
        p.level = 0
        p.font.size = Pt(20)
        p.font.color.rgb = GREY
        p.space_after = Pt(14)


def add_scope_slide(prs):
    add_bullet_slide(prs, "MVP Scope & Approach", [
        "~540 real reviews (Google Maps + Booking.com), not the paper's 80k-scale corpus",
        "Full 4-stage LLM preference pipeline, localized to Bangladesh tourism",
        "Bidirectional validation on a sampled subset, not the full dataset",
        "SQLite to start (Postgres migration deferred)",
        "Core principle: every later phase can add data without breaking earlier phases",
    ], accent=RGBColor(0x8A, 0x5A, 0x11))


def add_pipeline_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title = slide.shapes.add_textbox(Inches(0.7), Inches(0.4), Inches(11.8), Inches(1.0))
    tf = title.text_frame
    tf.text = "End-to-End Pipeline"
    tf.paragraphs[0].font.size = Pt(32)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = NAVY

    stages = [
        "Raw scrapes", "Clean reviews", "BERTopic topics", "LLM preferences",
        "Validation", "Sensitivity", "Aggregates", "API + DB", "Chatbot",
    ]
    n = len(stages)
    box_w = Inches(1.28)
    gap = Inches(0.08)
    total_w = box_w * n + gap * (n - 1)
    start_x = int((prs.slide_width - total_w) / 2)
    y = Inches(3.1)
    for i, label in enumerate(stages):
        x = start_x + i * (box_w + gap)
        box = slide.shapes.add_shape(1, x, y, box_w, Inches(1.3))
        box.fill.solid()
        box.fill.fore_color.rgb = TEAL if i < 8 else RGBColor(0x8A, 0x5A, 0x11)
        box.line.color.rgb = WHITE
        box.shadow.inherit = False
        tfb = box.text_frame
        tfb.word_wrap = True
        tfb.text = label
        tfb.paragraphs[0].font.size = Pt(11)
        tfb.paragraphs[0].font.bold = True
        tfb.paragraphs[0].font.color.rgb = WHITE
        tfb.paragraphs[0].alignment = PP_ALIGN.CENTER

    cap = slide.shapes.add_textbox(Inches(0.9), Inches(4.8), Inches(11.3), Inches(1.5))
    ctf = cap.text_frame
    ctf.word_wrap = True
    ctf.text = "Every aggregate downstream is a SQL view, not a copied table — rebuilding the database after adding new reviews refreshes every phase automatically, with no code changes."
    ctf.paragraphs[0].font.size = Pt(18)
    ctf.paragraphs[0].font.color.rgb = GREY


def add_closing_slide(prs):
    add_bullet_slide(prs, "What's Next", [
        "Phase 10 — Itinerary builder + comparison tool, on /api/recommend and /api/compare",
        "Phase 11 — Wire frontend/index.html to real API (chat, recommend, compare)",
        "Phase 12 — Deployment (Postgres + hosted API + hosted frontend)",
    ])


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    add_title_slide(prs)
    add_scope_slide(prs)
    for heading, bullets in SLIDES:
        add_bullet_slide(prs, heading, bullets)
    add_pipeline_slide(prs)
    add_closing_slide(prs)

    out = "docs/TouristinBD_Progress.pptx"
    prs.save(out)
    print(f"wrote {out} ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
