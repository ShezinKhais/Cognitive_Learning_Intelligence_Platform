# AI evaluation report (Phase 8, AI 1, #73)

Baseline metrics for the AI 1 pipeline: reading lecture files (including
scans), finding the right slide for a question, writing grounded questions,
and marking free-text answers. Every number comes from a script in
`backend/scripts/`, run on the sample lectures in `backend/tests/samples/`,
and can be rerun with the command given in each section. 95% confidence
intervals are in section 7.

All models run locally on an 8 GB laptop: through Ollama, `nomic-embed-text`
for embeddings, `qwen2.5vl:3b` for image captions and `qwen2.5:3b` (the app
default) or `qwen2.5:7b` for text; Tesseract 5 for OCR; the Qwen2.5 base
models through Hugging Face for perplexity.

## Summary

| Area | Measure | Result |
|---|---|---|
| Parser coverage | Pages with text read | 6 lectures in 4 formats read, every page with text found; corrupt PDF rejected safely |
| OCR | Share of true words found in a scan | **84–96%** clean scans, 42–90% poor scans |
| Retrieval | hit@5, 32 questions, 3 lectures | 0.81 before image captions, **0.91** after (0.78–1.00) |
| Retrieval | MRR, 32 questions | 0.82 before, **0.88** after |
| Retrieval | Text questions on 2 unseen lectures at rank 1 | **20 of 21** |
| Question grounding | Drafts passing the automatic checks | **36%** (9 of 25, `qwen2.5:3b`) |
| Question grounding | Accepted questions a human judged correct | **67%** (6 of 9) |
| Option verifier | Wrong questions rejected / right questions kept | 3B: 1 of 3 / 6 of 6; 7B: 0 of 3 / 6 of 6 |
| Classification | Accuracy, all 40 answers, `qwen2.5:3b` with schema replies | **77.5%** (65–90%), 0 unreadable replies |
| Classification | Accuracy before the schema (v3), mean of 2 runs | 3B 66.3%, 7B 72.5% |
| Human agreement | Cohen's kappa between two labellers | **0.85** (0.70–0.96), 36 of 40 agreed |
| Perplexity | Qwen2.5 1.5B vs 0.5B | 1.5B lower on all 6 texts |

## 1. Parser coverage

Can the pipeline read every kind of file a lecturer uploads?

`python -m scripts.parser_coverage --edge-cases --out tests/eval/PARSER_COVERAGE.md`

| File | Parser | Pages with text | Headings | Images |
|---|---|---|---|---|
| lecture.pdf | pypdf | 21 of 21 | 0 | 0 |
| lecture.pptx | python-pptx | 17 of 18 | 17 | 4 |
| lecture.docx | python-docx | 1 of 1 | 0 | 0 |
| lecture.txt | plain text | 1 of 1 | 0 | 0 |
| cnn_lecture.pptx | python-pptx | 12 of 12 | 12 | 0 |
| linear_regression_notes.pdf | pypdf | 11 of 11 | 0 | 0 |
| scanned.pdf | pypdf + OCR | 1 of 1 | 0 | 0 |
| corrupt.pdf | none | rejected with a clear error | - | - |

- The one PowerPoint slide with no text (slide 9) is picture-only, and its
  picture is captioned.
- PDFs give no headings with pypdf, so their chunks get no heading path.
- A scanned page is now read with OCR (section 2). Without Tesseract it is
  skipped, and the lecturer is told how to have it read.
- `cnn_lecture.pptx` and `linear_regression_notes.pdf` were added in Phase 8,
  adapted from Dive into Deep Learning (d2l.ai, CC BY-SA 4.0) by
  `scripts/build_test_lectures.py`, to test a second and third topic and a
  multi-page PDF.

## 2. OCR

How well are scanned pages read?

`python -m scripts.evaluate_ocr --out tests/eval/OCR_RESULTS.md`

A PDF page with no text layer is read from its picture with Tesseract (at
most 60 pages per upload). Two lectures were saved as image-only scans at 150
dpi, and again as poor scans (half resolution, blurred, tilted 1.5 degrees,
low JPEG quality, like a phone photo). Each page is scored against its true
text from the original PDF.

| Document | Scan | Pages read | Word recall | CER | WER | Seconds per page |
|---|---|---|---|---|---|---|
| Computer vision slides (21 pages) | clean | 21 of 21 | **84.2%** | 5.0% | 22.1% | 0.4 |
| Computer vision slides | poor | 20 of 21 | 41.9% | 30.0% | 62.7% | 0.3 |
| Logistic regression slides (18 pages) | clean | 18 of 18 | **95.7%** | 15.3% | 21.7% | 0.6 |
| Logistic regression slides | poor | 16 of 18 | 90.0% | 11.1% | 17.8% | 0.4 |

- **Word recall** is the share of the true words OCR found, in any order:
  what search needs. **CER / WER** are the character and word edits needed to
  reach the true text, over its length.
- CER and WER also count, as errors, text OCR reads that the text layer does
  not hold: the university logo on every slide and chart labels. That is why
  the logistic regression clean scan has a higher CER than its poor scan:
  blurring removes the small logo text.
- Maths formulas are read worst; poor scans of the formula-heavy computer
  vision slides lose more than half their words.

## 3. Retrieval

When a student asks a question, does the right slide come back near the top?

`python -m scripts.evaluate_retrieval --out tests/eval/RETRIEVAL_RESULTS.md`

32 questions, each with the slides or pages that answer it, written before
running: 11 about `lecture.pptx` (5 answered only by a picture), 11 about
`cnn_lecture.pptx` and 10 about `linear_regression_notes.pdf`. Each lecture
is chunked before and after image captions (Phase 6, #127).

| Questions | hit@1 | hit@5 | MRR | precision@5 |
|---|---|---|---|---|
| Picture (5) | 0.00 → 0.20 | 0.00 → 0.60 | 0.00 → 0.39 | 0.00 → 0.12 |
| Text (27) | 0.96 → 0.96 | 0.96 → 0.96 | 0.97 → 0.97 | 0.31 → 0.31 |
| lecture.pptx (11) | 0.55 → 0.64 | 0.55 → 0.82 | 0.55 → 0.72 | 0.24 → 0.29 |
| cnn_lecture.pptx (11) | 0.91 | 0.91 | 0.92 | 0.18 |
| linear_regression_notes.pdf (10) | 1.00 | 1.00 | 1.00 | 0.38 |
| All (32) | 0.81 → 0.84 | 0.81 → 0.91 | 0.82 → 0.88 | 0.26 → 0.28 |

- **hit@k**: share of questions with an answering slide in the top k.
  **MRR**: mean of 1/rank of the first answering slide. **precision@5**: share
  of the top 5 chunks from an answering slide.
- Captions made picture-only slides findable (0 → 3 of 5 in the top 5) and
  pushed no text answer down. The new lectures have no pictures, so they
  score the same before and after.
- On the two lectures added in Phase 8, 20 of 21 questions found the right
  page first. The miss: "What happens when the convolution window moves more
  than one pixel at a time?" ranked the stride slide 11th, behind the
  cross-correlation slide, which also describes the window sliding.
- precision@5 is capped by the slides: most answer slides make only one or
  two chunks.

## 4. Question grounding

Are the questions the AI writes supported by the lecture?

`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding`, then
`--precision` after marking `grounded_luna` in `grounding_accepted.csv`.

Each draft must cite a real slide, quote an excerpt that is really on it, and
have an answer the excerpt supports. 5 rounds of 5 questions on
`lecture.pptx`:

| Measure | Value |
|---|---|
| Drafts | 25 |
| Accepted | 9 (36%), per round 3, 3, 0, 2, 1 |
| Rejected: answer not supported by the excerpt | 14 |
| Rejected: excerpt not found on the slide | 8 |
| Rejected: citation missing or wrong slide | 5 |
| Accepted and judged correct by hand | **6 of 9 (67%)** |

The three judged wrong: g04 is circular, g06 has two correct options (slide
5 gives "three or more outcomes" for both multinomial and ordinal), and g09
has a wrong answer (it says logistic regression can generate outputs; slide
6 says it cannot).

**Option verifier.** Added in Phase 8 to catch g06 and g09: after a draft
passes the checks above, the model is shown the question, its options and the
cited slide, without the answer key, and asked which options the slide
supports. Anything but exactly the marked answer rejects the draft
(`QUESTION_VERIFICATION_ENABLED`, on by default). Tested against the
hand-judged questions with `--check-accepted`:

| Verifier model | Judged wrong, rejected | Judged right, kept | Unreadable replies |
|---|---|---|---|
| qwen2.5:3b | 1 of 3 (g09) | 6 of 6 | 0 |
| qwen2.5:7b | 0 of 3 | 6 of 6 | 0 |

Both models named exactly the marked answer for 8 or 9 of the 9 questions,
including the wrong ones. The verifier answers the quiz rather than checking
the slide, and shares the generator's blind spots; the larger model did no
better. It costs nothing in good questions, so it stays on, but the
lecturer's approval remains the real check.

## 5. Free-text classification

Does the classifier give a student answer the same label as a human?

`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_classifier --out tests/eval/results_qwen3b_v4.csv`

40 student answers to 5 questions, labelled mastered, partial or struggling
by Luna and Nour separately: 36 of 40 agreed (Cohen's kappa 0.85); the other
4 were settled together.

| Model, prompt | Replies read | Accuracy (all 40) | Macro F1 |
|---|---|---|---|
| qwen2.5:3b, v3, run 1 | 40 | 65.0% | 0.63 |
| qwen2.5:3b, v3, run 2 | 33 | 67.5% | 0.79 |
| qwen2.5:7b, v3, run 1 | 34 | 67.5% | 0.78 |
| qwen2.5:7b, v3, run 2 | 37 | 77.5% | 0.82 |
| **qwen2.5:3b, v4 (schema replies)** | **40** | **77.5%** | 0.76 |

Chance is about 33%.

- In v3 every unreadable reply was missing its `wrong_claim` field. v4 holds
  the reply to a JSON schema (Ollama structured output): no reply was
  unreadable, and the small 3B model matched the 7B's best run.
- v4 per label (precision / recall): mastered 0.79 / 0.85, partial
  0.70 / 0.64, struggling 0.81 / 0.81. Partial is the hardest label, for the
  model and for the two labellers.
- Two struggling answers were marked mastered (a12, and a40, one of the four
  the labellers disagreed on).

## 6. Perplexity

How predictable is lecture text to a language model?

`python -m scripts.perplexity --out tests/eval/PERPLEXITY.md`

Perplexity = exp(mean negative log-likelihood per token); lower is more
predictable. Ollama does not return token probabilities, so the Qwen2.5 base
models are used through Hugging Face. Measured before the two Phase 8
lectures were added.

| Text | Qwen2.5-0.5B | Qwen2.5-1.5B |
|---|---|---|
| Plain-text lecture | 7.82 | 5.52 |
| PowerPoint lecture | 11.62 | 9.89 |
| Same PowerPoint as PDF | 13.16 | 10.97 |
| Everyday English (control, 5 paragraphs) | 18.21 | 14.12 |
| Word lecture | 20.25 | 13.48 |
| PDF lecture (computer vision) | 33.62 | 20.11 |

- The 1.5B model is lower on every text, in line with the larger classifier
  doing better.
- The same slides as a PDF score only 11 to 13% higher, so the PDF lecture's
  high score comes mostly from its symbols and page numbers, not the format.
- Perplexity measures fluency, not correctness, so it sits beside the task
  metrics, not in place of them.

## 7. Confidence intervals

`python -m scripts.confidence_intervals --out tests/eval/CONFIDENCE_INTERVALS.md`

95% percentile bootstrap intervals, 10,000 resamples, items resampled whole
so paired measures stay paired. No model is needed.

| Measure | Value | 95% interval | n |
|---|---|---|---|
| Retrieval hit@5, after captions | 0.91 | 0.78 to 1.00 | 32 |
| Retrieval hit@5, gain from captions | 0.09 | 0.00 to 0.22 | 32 |
| Retrieval MRR, after captions | 0.88 | 0.77 to 0.97 | 32 |
| Retrieval MRR, gain from captions | 0.06 | 0.01 to 0.14 | 32 |
| Grounding: drafts passing the checks | 36% | 20% to 56% | 25 |
| Grounding precision | 67% | 33% to 100% | 9 |
| Marking accuracy, qwen2.5:3b v4 | 78% | 65% to 90% | 40 |
| Marking accuracy, qwen2.5:7b v3 run 2 | 78% | 65% to 90% | 40 |
| Cohen's kappa, Luna vs Nour | 0.85 | 0.70 to 0.96 | 40 |

- The MRR gain from captions stays above 0, so it is unlikely to be chance;
  the hit@5 gain's interval reaches 0, since only 5 of 32 questions are about
  pictures.
- Grounding precision on 9 questions could be anywhere from 33% to 100%: the
  set is too small to pin it down.

## 8. How the evaluation methods were chosen

| Technique | Used | Where | Why |
|---|---|---|---|
| Accuracy, precision, recall, F1 against human labels | yes | Classification | The classifier's job is to match a teacher's judgement |
| Inter-annotator agreement (Cohen's kappa) | yes | Classification | Shows the human labels are reliable enough to test against |
| hit@k, MRR, precision@k | yes | Retrieval | Standard ranking measures |
| CER, WER, word recall | yes | OCR | Standard OCR measures, plus one that ignores reading order |
| Rule-based checks | yes | Grounding | Exact and cheap; the app runs them on every question |
| Human evaluation | yes | Grounding precision | Only a person can judge whether a question is fair and correct |
| LLM as verifier | yes, tested | Grounding | Measured against human judgements; shares the generator's blind spots |
| Perplexity | yes | Language model | Intrinsic measure of how well a model fits lecture text |
| Bootstrap confidence intervals | yes | All | The test sets are small |
| Repeated runs | yes | Grounding, classification | Model outputs vary between runs |
| BLEU / ROUGE | no | | Need one reference text; a good question has many correct wordings |
| General benchmarks (e.g. MMLU) | no | | Measure general knowledge, not this task |

## Limits

- Small test sets: 40 answers, 32 retrieval questions, 25 drafts, 9 judged
  questions. The intervals in section 7 show how much the numbers could move.
- One person judged the accepted questions.
- The Phase 8 lectures were written for testing from an open textbook; real
  course lectures from lecturers would be a stronger test.
- Perplexity was measured before the Phase 8 lectures were added.
- The CSV of the first `qwen2.5:3b` v3 run was overwritten; its summary
  numbers were recorded first.

## Next steps

1. Test with real course lectures, and grow the labelled answer and question
   sets, with a second person judging grounding.
2. A verifier that must quote the slide for each option it accepts, checked
   in code, to catch questions with two right answers.
3. OCR for formulas, and Docling for PDF headings.
4. Captions for images in Word files.
