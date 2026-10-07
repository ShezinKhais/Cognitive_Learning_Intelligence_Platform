# Free-text classification: labelled answer set

Hand-labelled student answers used to measure how well the free-text
classifier (Phase 5, AI 1) agrees with a human. This is the accuracy
baseline for issue #55.

- `questions.json`: five free-text questions from the sample lecture
  (`backend/tests/samples/lecture.pptx`), each with a reference answer, the
  key points that answer contains, and the slide excerpt it came from.
- `answers_to_label.csv`: forty student answers, eight per question, with an
  empty label column for each labeller.

## How to label

Two people label every answer, separately, without looking at each other's
column. Open the CSV in Excel, Numbers or Google Sheets and fill your own
column (`label_luna` or `label_nour`) with exactly one of:

| Label | Use it when the answer |
|---|---|
| `mastered` | covers every key point in the reference answer and says nothing wrong. Different wording is fine. |
| `partial` | gets some key points right but misses at least one, or is right but mixed with a small error. |
| `struggling` | is wrong, holds a misconception, is off topic, only repeats keywords or the question, or is blank or "I don't know". |

Judge the meaning, not the wording or spelling. Use the `key_points` in
`questions.json` as the checklist. If you are unsure, pick the closest label
and write why in `notes`; those are the cases worth discussing.

When both columns are full, compare them. Where you disagree, talk it
through and agree a final label. How often you agreed before discussing is
worth reporting too, since it shows how clear the labels are.

Note on q2: slide 3 says "greater than 0 will predict 1", which is a typo for
0.5. The reference answer uses 0.5, as a lecturer would when approving it.
