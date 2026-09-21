# Human validation — protocol for the four annotators

The 50-pair sample in `data/phase5_manual_review_sample.csv` is the only check
on the pipeline that the pipeline did not produce itself. It is only worth
something if the four labels per pair are **independent**. Please follow this
exactly; the paper's methods section will describe it.

## The question

For each pair you see one **topic** (keywords, main places, 4 real reviews) and
one **tourist preference** (category, name, description). Answer:

> Does this TOPIC genuinely express this TOURIST PREFERENCE?
> **1 = yes**, **0 = no**

Say 1 when a traveller whose reviews fall in this topic is clearly seeking what
the preference describes. Say 0 when the link is only incidental (e.g. a hotel
topic that happens to mention a beach is not "coastal tourism"). If you hesitate,
decide anyway and add a note (`n` in the terminal tool). Notes are how we
explain disagreements later.

## Rules

1. Label alone. Do not discuss any pair until **all four** files are complete.
2. Do not ask ChatGPT, Gemini, Claude or any other model. The point is a human
   judgement independent of the LLM that built the taxonomy.
3. Do not open the Phase 5 reports, the sample CSV or the API's validation page
   while labelling. They show the similarity scores and the pipeline's answer.
4. Label in one or two sittings (about 45–60 minutes total). Take a break
   rather than rushing the last pairs.
5. Never edit another person's file.

## How to label

Pull the latest `main` first, then pick one method.

**Terminal (recommended).** Resumable, and saves after every answer:

```bash
python scripts/label_validation_sample.py --annotator yourname
#   1 = yes   0 = no   n = note   b = back   q = save and quit
python scripts/label_validation_sample.py --annotator yourname --status
```

**Spreadsheet.** Writes your blinded file, which you open in Excel or Google Sheets:

```bash
python scripts/label_validation_sample.py --annotator yourname --export-sheet
```

Fill only the `human_label` column with `1` or `0` (and `note` if you like).
Save it back as CSV under the same name, `data/human_labels/labels_yourname.csv`.

Each person sees the pairs in a different order. That is deliberate.

Commit only your own file:

```bash
git add data/human_labels/labels_yourname.csv
git commit -m "Human validation labels: yourname"
git push
```

## After everyone has pushed

One person runs:

```bash
python scripts/compute_human_agreement.py --write-back
python scripts/build_phase8_database.py
```

This writes `data/phase5_human_validation_report.md` with:

- pairwise Cohen's kappa
- Fleiss' kappa
- the pipeline's precision and recall against the majority label
- a list of the pairs you disagreed on

Only now discuss the disagreements. Record the outcome of that discussion
separately as adjudication. **Do not edit the original label files.** The
independent labels are what the kappa is computed on.

Reporting convention (Landis & Koch, 1977): 0.41–0.60 moderate, 0.61–0.80
substantial, above 0.80 almost perfect. Report the number whatever it is. A
moderate kappa honestly reported is a finding. A number that was massaged is a
problem.
