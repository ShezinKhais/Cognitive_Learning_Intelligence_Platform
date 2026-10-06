# Free-text classification: accuracy baseline

Results of the free-text classifier (Phase 5, AI 1, issue #55) against the
hand-labelled answer set in this folder. The baseline is prompt
`free-text-v3` on `qwen2.5:3b`.

## Setup

| | |
|---|---|
| Answer set | 40 student answers, 8 per question, 5 questions from the sample lecture |
| Human labels | `label_luna`: 14 mastered, 11 partial, 15 struggling |
| Chat model | `qwen2.5:3b` through Ollama, on a laptop |
| Embedding model | `nomic-embed-text` (768 dimensions) |
| Prompt | `free-text-v3` |
| Command | `python -m scripts.evaluate_classifier --out results.csv` |

The model marks each key point as covered, partly covered or missed and must
quote the student's words as evidence. Code checks every quote is really in
the answer, then a fixed rule turns the marks into a label: every point
covered and nothing wrong is mastered, nothing covered is struggling, anything
else is partial.

## Headline result (free-text-v3)

| Measure | Value |
|---|---|
| Accuracy on marked answers | **66.7%** (26 of 39) |
| Accuracy counting the unreadable reply as wrong | 65.0% (26 of 40) |
| Macro F1 | **0.62** |
| Unreadable model replies | 1 of 40 |
| Chance level (three labels) | about 33% |

### Per label

| Label | Precision | Recall | F1 | Answers |
|---|---|---|---|---|
| Mastered | 0.67 | 0.71 | 0.69 | 14 |
| Partial | 0.43 | 0.27 | 0.33 | 11 |
| Struggling | 0.76 | 0.93 | 0.84 | 14 |

### Confusion matrix

Rows are the human label, columns the classifier's.

| | Mastered | Partial | Struggling |
|---|---|---|---|
| **Mastered** | 10 | 4 | 0 |
| **Partial** | 4 | 3 | 4 |
| **Struggling** | 1 | 0 | 13 |

### Per question

| Question | Topic | Correct |
|---|---|---|
| q1 | What logistic regression predicts | 4 of 8 (1 unreadable) |
| q2 | Probability to class | 6 of 8 |
| q3 | Odds ratios | 6 of 8 |
| q4 | Multinomial vs ordinal | 5 of 8 |
| q5 | Overfitting and regularisation | 5 of 8 |

## Prompt versions

| Prompt | What changed | Marked | Accuracy (marked) | Accuracy (of 40) | Macro F1 |
|---|---|---|---|---|---|
| v1 | First version, no evidence quotes | 4 of 5 (trial) | 25% | - | 0.17 |
| v2 | Must quote the answer, quotes checked in code, "be strict" | 36 of 40 | 69.4% | 62.5% | 0.67 |
| v3 | Accepts near-exact quotes, reads slightly broken replies | 39 of 40 | 66.7% | **65.0%** | 0.62 |

v1 was stopped after five answers because it marked almost everything as
mastered. On the 35 answers both v2 and v3 could read, each got 24 right, so
the difference in the table comes from which answers each could read. v3 is
kept because it reads 39 of 40 replies instead of 36.

## What goes wrong

| Mistake | Count | Answers | Why |
|---|---|---|---|
| Partial called mastered | 4 | a02, a06, a10, a21 | The model gives full credit to half-explained points |
| Partial called struggling | 4 | a16, a24, a32, a39 | The model gives no credit to loosely worded points |
| Mastered called partial | 4 | a08, a29, a33, a36 | The model misses one point the human accepted. a29 and a36 may be right under a strict checklist reading |
| Struggling called mastered | 1 | a30 | The answer uses the right words with the meaning reversed |
| Unreadable reply | 1 | a04 | The model returned broken JSON twice |

- **Struggling is reliable.** 13 of 14 struggling students are caught, which
  is what matters most for alerting a lecturer.
- **Partial is the weak spot.** Partial answers are wrong in both directions,
  and humans also find partial the hardest label to agree on.
- **Similarity alone cannot separate the labels.** Embedding similarity to the
  reference answer overlaps heavily, so it is used only for confidence, not
  for the label.

| Human label | Similarity min | Median | Max |
|---|---|---|---|
| Mastered | 0.763 | 0.847 | 0.915 |
| Partial | 0.657 | 0.765 | 0.933 |
| Struggling | 0.476 | 0.727 | 0.828 |

## Topic difficulty

`app/services/topic_difficulty.py` scores each topic as the average of its
answers' labels (mastered 0, partial 0.5, struggling 1): below 0.33 is easy,
0.66 and above is hard, between is medium, and a topic with fewer than 5
answers gets no level. Each eval question is its own topic here. The 39
answers the classifier could read give:

| Topic | Answers | Human | Classifier | Uncertain labels |
|---|---|---|---|---|
| What is logistic regression | 7 | 0.57 medium | 0.50 medium | 2 |
| Types of logistic regression | 8 | 0.56 medium | 0.56 medium | 3 |
| Binary classification threshold | 8 | 0.50 medium | 0.50 medium | 3 |
| Logistic regression and machine learning | 8 | 0.50 medium | 0.69 hard | 1 |
| Interpreting odds ratios | 8 | 0.38 medium | 0.38 medium | 3 |

The classifier gives the same level as the human for 4 of 5 topics, and the
same score for 3 of them, although it labels only 67% of single answers the
same. Its mistakes go both ways (partial called mastered as often as
struggling), so they mostly cancel out across a topic. The classifier is
more reliable for "which topic needs revisiting" than for one student's
answer. The eval questions were written at similar difficulty, so the scores
sit close together; a real class would spread them more.

Reproduce with `python -m scripts.topic_difficulty_report <results.csv>` on a
file written by `evaluate_classifier --out`.

## Limitations

- **The score is optimistic.** The prompt was adjusted while looking at these
  same 40 answers, so a fresh answer set would likely score a little lower.
- **The set is small.** Each answer is worth 2.5 percentage points, so
  differences of one or two answers are noise.
- **One labeller so far.** The second labelling (`label_nour`) will give
  Cohen's kappa between humans, which shows how high any classifier could
  reasonably score.
- **Small model.** A 7b model could not be run on the available laptop
  (it ran out of memory). A larger model is expected to help most on
  partial answers.

## Next steps

- Fill `label_nour` and report human agreement (Cohen's kappa).
- Re-run on a larger model when hardware allows, with the prompt unchanged.
- Label a fresh set of answers to get an unbiased score.
