# Confidence thresholds for marking free-text answers

Part of #251. Which confidence levels the code uses, what the evaluated
results say about them, and what the team still has to agree.

## Where each threshold is used

| Value | Where | What it does |
|---|---|---|
| 0.35 | `free_text_classifier.MIN_CONFIDENCE`, `REVIEW_CONFIDENCE`, `KEYWORD_LIST_CONFIDENCE` | Lowest confidence the marker gives. Answers refused for instructions to the marker, and keyword lists, get exactly this. |
| 0.6 | `free_text_classifier.UNCHECKED_CONFIDENCE` | Confidence when there is no similarity score to cross-check the model. |
| 0.6 | `topic_difficulty.UNCERTAIN_BELOW`, `ai_explainability.LOW_CLASSIFIER_CONFIDENCE` | Below it, a label counts as uncertain and never suggests practising a topic on its own. |
| 0.6 | `frontend/src/features/review/reviewDisplay.ts`, `progress.ts`, `StudentReviewPage.tsx` | Below it the student sees "Uncertain, ask your lecturer" instead of the label, and the label is left out of topic progress. At or above it the student sees "N% sure of this reading". |
| 0.85 | `classifier_evaluation.confidence_buckets`, the report | Where the evaluation says labels are "nearly always right". Not used by the app. |
| 0.95 | `free_text_classifier.MAX_CONFIDENCE`, `QUICK_CHECK_CONFIDENCE` | Highest confidence. |

The backend and the frontend agree on 0.6. A label at exactly 0.6 (no
similarity to check against) is shown with its label, not as uncertain.

## What the results say (40 answers, v5 and v6)

From `CALIBRATION.md` and `CALIBRATION_v6.md`:

| Confidence | Labels right, v5 | Labels right, v6 |
|---|---|---|
| Below 0.6 | 9 of 11 (82%) | 10 of 12 (83%) |
| 0.6 to 0.85 | 8 of 13 (62%) | 8 of 13 (62%) |
| 0.85 and up | 15 of 16 (94%) | 14 of 15 (93%) |

| If "uncertain" started below | v6: labels hidden as uncertain (how many wrong) | v6: labels shown (how many wrong) |
|---|---|---|
| 0.35 | 0 (0) | 40 (8) |
| 0.6 (today) | 12 (2) | 28 (6) |
| 0.85 | 25 (7) | 15 (1) |

v6 AUROC is 0.59 (v5 0.62): confidence is only a little better than a coin
toss at telling right labels from wrong ones, except above 0.85.

In plain words:

- The 0.6 threshold hides 12 labels, but 10 of them were right; it still
  shows 6 of the 8 mistakes. Labels between 0.6 and 0.85 were wrong more
  often than labels below 0.6, in both runs.
- 0.85 would show only 1 mistake, but would hide 25 of 40 labels (63%), so
  most answers would say "ask your lecturer".
- A student seeing "75% sure of this reading" is in the band that was right
  62% of the time, so the percentage overstates it there.
- Keyword lists that `is_keyword_list` catches get 0.35 and so show as
  uncertain; the ones it misses are shown as mastered (#279).
- The set is small (40 answers, one lecture, one topic): moving one or two
  answers changes these counts a lot. These must be checked on the fresh
  held-out set (`fresh/`) and on v6 before anything is changed.

## Decisions for the team (not made in code)

- [ ] Keep 0.6 as the "Uncertain, ask your lecturer" threshold, or move it,
      once the v6 and fresh-set results are in.
- [ ] Keep showing "N% sure" to students, or show words instead (for example
      "fairly sure" / "sure"), since the raw number is not well calibrated.
- [ ] Should 0.6 to 0.85 labels be flagged to the lecturer for a check even
      when they are shown to the student?
- [ ] Whatever is agreed, change the backend constants and the three frontend
      files together so they stay the same.
