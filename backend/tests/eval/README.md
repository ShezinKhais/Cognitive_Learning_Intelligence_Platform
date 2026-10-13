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

Done: Luna and Nour agreed on 36 of 40 before discussing (Cohen's kappa 0.85).
They settled the other four together, and `label_final` holds the agreed label
for every answer: a24 struggling, a29 mastered, a36 partial, a40 struggling.
`evaluate_classifier` compares against `label_final` unless told otherwise.

Note on q2: slide 3 says "greater than 0 will predict 1", which is a typo for
0.5. The reference answer uses 0.5, as a lecturer would when approving it.

# Retrieval before and after #127

`retrieval_queries.json` holds questions about the sample lectures, each with
the slides or pages that answer it. For `lecture.pptx`, `image` questions are
answered only by a picture (slides 9, 12, 15 and 16); `text` questions by the
slide's text, and check that captions do not push the right text down. 21 more
text questions cover two lectures added in Phase 8, `cnn_lecture.pptx` and
`linear_regression_notes.pdf`, which have no pictures, so both ways score
them the same: they measure retrieval on a second topic and a PDF layout.

`python -m scripts.evaluate_retrieval --out tests/eval/RETRIEVAL_RESULTS.md`
chunks the lecture twice: as before #127 (heading levels dropped, pictures
left as placeholders) and as now (heading paths and captions). It embeds both
with the embedding model and scores where the first chunk from a right slide
ranks: hit@1, hit@5 and MRR. Captions are saved in `caption_cache.json`, so a
rerun does not wait for the vision model.

The sample PDF and Word document are left out on purpose: the default readers
find no heading levels and no pictures in them, so both ways chunk them the
same.

# Phase 8 additions

**More lectures.** `scripts/build_test_lectures.py` builds `cnn_lecture.pptx`
(12 slides on convolutions, padding, stride and pooling) and
`linear_regression_notes.pdf` (11 pages of notes, a section to a page) from
Dive into Deep Learning (d2l.ai, CC BY-SA 4.0). The built files are committed.

**OCR.** `python -m scripts.evaluate_ocr --out tests/eval/OCR_RESULTS.md` reads
two lectures saved as scans (`ocr/`), clean and poor, with Tesseract and scores
word recall, CER and WER against each page's true text. Needs
`brew install tesseract`.

**Option verifier.** `python -m scripts.evaluate_grounding --verify` runs the
check that each multiple choice question has exactly one right option, as
uploads do. `--check-accepted` runs only the verifier on the questions already
judged in `grounding_accepted.csv` and reports how many judged wrong it
rejects and how many judged right it keeps.

**Structured marking.** Prompt `free-text-v4` holds the classifier's reply to
a JSON schema. Rerun `evaluate_classifier` to compare unreadable replies with
v3.

**Confidence intervals.** `python -m scripts.confidence_intervals --out
tests/eval/CONFIDENCE_INTERVALS.md` bootstraps a 95% interval for every saved
result. It needs no model, so rerun it after any other script.
