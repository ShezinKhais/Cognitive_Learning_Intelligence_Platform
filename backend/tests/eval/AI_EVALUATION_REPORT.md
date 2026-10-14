# AI evaluation report (Phase 8, AI 1, #73)

What was tested in the AI 1 pipeline, how, with which models, and the
results. Every number comes from a script in `backend/scripts/`, run on the
test files in `backend/tests/`, and can be rerun with the command given in
each section. Where a weakness was found and fixed, both the before and after
results are given.

## Models

All models ran locally on an 8 GB laptop.

| Model | Size | Used for | Runs through |
|---|---|---|---|
| `qwen2.5:3b` | 3B, 1.9 GB | Writing questions, marking answers, summaries (app default) | Ollama |
| `qwen2.5:7b` | 7.6B, 4.7 GB | Comparison for marking and the option verifier | Ollama |
| `qwen2.5vl:3b` | 3.8B, 3.2 GB | Describing pictures in slides (captions) | Ollama |
| `nomic-embed-text` | 137M, 274 MB | Search embeddings (app default) | Ollama |
| `mxbai-embed-large` | 335M, 669 MB | Embedding comparison | Ollama |
| `all-minilm` | 23M, 45 MB | Embedding comparison | Ollama |
| Qwen2.5-0.5B and 1.5B (base) | 0.5B, 1.5B | Perplexity | Hugging Face |
| Gemma 3 1B (base, `gemma-3-1b-pt`) | 1B | Perplexity comparison | Hugging Face |
| Tesseract 5 | n/a | OCR of scanned pages | Command line |

## All results

| # | Area | Test | Measure | Model | Result |
|---|---|---|---|---|---|
| 1 | Reading files | Parser coverage, 8 files in 4 formats | Pages with text read | n/a | Every page with text read; corrupt file rejected safely |
| 2 | Reading files | OCR, 2 scanned lectures | Word recall | Tesseract 5 | **84–96%** clean scans, 42–90% poor scans |
| 3 | Search | Retrieval, 32 questions, 3 lectures | hit@5 / MRR | nomic-embed-text | 0.81 → **0.91** / 0.82 → **0.88** with image captions |
| 4 | Search | Embedding comparison, same 32 questions | hit@5 | 3 embedding models | nomic **0.91**, mxbai **0.94**, MiniLM **0.94** |
| 5 | Questions | Grounding, 25 drafts | Pass rate / judged correct | qwen2.5:3b | **36%** pass; **67%** (6 of 9) of passed judged correct |
| 6 | Questions | Option verifier, 9 judged questions | Wrong rejected / right kept | 3B, 7B | 3B: 1 of 3 / 6 of 6; 7B: 0 of 3 / 6 of 6 |
| 7 | Marking | Classification, 40 labelled answers | Accuracy / macro F1 | qwen2.5:3b | **80.0%** / 0.78 (v5); 0 unreadable replies |
| 8 | Marking | Human agreement, 2 labellers | Cohen's kappa | n/a | **0.85** (36 of 40 agreed) |
| 9 | Marking | Calibration | Accuracy when confidence ≥ 0.85 | qwen2.5:3b | **15 of 16** right (v5) |
| 10 | Marking | Consistency, same answers twice | Same label | qwen2.5:7b | 88% (kappa 0.82) at default temperature |
| 11 | Marking | Fairness, 26 reworded answers | Marks lowered by typos or simple English | qwen2.5:3b | 5 of 26 → **1 of 26** after fix |
| 12 | Marking | Cheating, 20 known attempts | Attempts that worked | qwen2.5:3b | 3 of 20 → **1 of 20** after fix |
| 13 | Marking | Cheating, 10 new (hold-out) attempts | Attempts that worked | qwen2.5:3b | **2 of 10** |
| 14 | Summaries | 26 summaries, 130 sentences | Sentences the AI wrote that passed the checks | qwen2.5:3b | about 8% → **100%** after fix |
| 15 | Language model | Perplexity, 6 lectures | Bits per byte | Qwen 1.5B vs Gemma 1B | Tie on everyday English; Qwen 10–27% better on lectures |
| 16 | Speed | GuideLLM load test | Wait for first word, 4 users | qwen2.5:3b | 106 s → **5 s** with 4 parallel slots |

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
| corrupt.pdf | none | Rejected with a clear error | n/a | n/a |

The PowerPoint slide with no text is picture-only, and its picture is
captioned. PDFs give no headings with pypdf. `cnn_lecture.pptx` and
`linear_regression_notes.pdf` are adapted from Dive into Deep Learning
(d2l.ai, CC BY-SA 4.0).

## 2. OCR

How well are scanned pages read? Two lectures saved as image-only scans
(150 dpi), and again as poor scans (half resolution, blurred, tilted, low
JPEG quality, like a phone photo), scored against each page's true text.
`python -m scripts.evaluate_ocr --out tests/eval/OCR_RESULTS.md`

| Document | Scan | Pages read | Word recall | CER | WER | Seconds per page |
|---|---|---|---|---|---|---|
| Computer vision slides (21 pages) | Clean | 21 of 21 | **84.2%** | 5.0% | 22.1% | 0.4 |
| Computer vision slides | Poor | 20 of 21 | 41.9% | 30.0% | 62.7% | 0.3 |
| Logistic regression slides (18 pages) | Clean | 18 of 18 | **95.7%** | 15.3% | 21.7% | 0.6 |
| Logistic regression slides | Poor | 16 of 18 | 90.0% | 11.1% | 17.8% | 0.4 |

Word recall (share of true words found) is what search needs. CER and WER
also count text the original PDF's text layer lacks, such as the logo on
every slide. Formulas are read worst.

## 3. Retrieval

When a student asks a question, does the right slide come back near the top?
32 questions with their answering slides, written before running; 5 are
answered only by a picture. Each lecture is searched before and after image
captions. `python -m scripts.evaluate_retrieval --out tests/eval/RETRIEVAL_RESULTS.md`

| Questions | hit@1 | hit@5 | MRR | precision@5 |
|---|---|---|---|---|
| Picture (5) | 0.00 → 0.20 | 0.00 → 0.60 | 0.00 → 0.39 | 0.00 → 0.12 |
| Text (27) | 0.96 → 0.96 | 0.96 → 0.96 | 0.97 → 0.97 | 0.31 → 0.31 |
| All (32) | 0.81 → 0.84 | 0.81 → **0.91** | 0.82 → **0.88** | 0.26 → 0.28 |

Captions made picture-only slides findable and pushed no text answer down.
On the two new lectures, 20 of 21 questions found the right page first; the
miss (stride, ranked 11th) is missed by every embedding model below.

### Embedding comparison

The same test with the search model swapped (`EMBEDDING_MODEL=...`), after
captions.

| Embedding model | Size | hit@1 | hit@5 | MRR | Picture questions in top 5 |
|---|---|---|---|---|---|
| **nomic-embed-text** (app) | 274 MB | 0.84 | 0.91 | 0.88 | 3 of 5 |
| mxbai-embed-large | 669 MB | 0.88 | 0.94 | 0.90 | 4 of 5 |
| all-minilm | 45 MB | 0.88 | 0.94 | 0.89 | 4 of 5 |

All three tie on the 27 text questions; the difference is one picture
question. That is too small to justify a database migration (each model
gives vectors of a different length), so nomic-embed-text stays. all-minilm
matched the largest model at a sixth of nomic's size and is worth retesting
on a larger set.

## 4. Question grounding and option verifier

Are the questions the AI writes supported by the lecture? Each draft must
cite a real slide, quote text that is on it, and have an answer that text
supports. 5 rounds of 5 questions on `lecture.pptx`; the passed questions
were then judged by hand.
`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding`

| Measure | Value |
|---|---|
| Drafts | 25 |
| Passed the checks | 9 (36%) |
| Rejected: answer not supported by the quoted text | 14 |
| Rejected: quoted text not on the slide | 8 |
| Rejected: citation missing or wrong slide | 5 |
| Passed and judged correct by hand | **6 of 9 (67%)** |

The verifier shows the model the question and the cited slide, without the
answer key, and rejects the draft unless exactly the marked answer is
supported. `--check-accepted` tests it on the 9 judged questions.

| Verifier model | Judged wrong, rejected | Judged right, kept | Unreadable replies |
|---|---|---|---|
| qwen2.5:3b | 1 of 3 | 6 of 6 | 0 |
| qwen2.5:7b | 0 of 3 | 6 of 6 | 0 |

The verifier costs no good questions, so it stays on, but it shares the
writer's blind spots: the lecturer's approval remains the real check.

## 5. Marking free-text answers

Does the marker give an answer the same label as a teacher? 40 student answers
to 5 questions, labelled mastered, partial or struggling by two people
separately (kappa 0.85), disagreements settled together.
`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_classifier --out tests/eval/results_qwen3b_v5.csv`

| Model, prompt | Replies read | Accuracy (all 40) | Macro F1 |
|---|---|---|---|
| qwen2.5:3b, v3, run 2 | 33 | 67.5% | 0.79 |
| qwen2.5:7b, v3, run 1 | 34 | 67.5% | 0.78 |
| qwen2.5:7b, v3, run 2 | 37 | 77.5% | 0.82 |
| qwen2.5:3b, v4: reply held to a JSON schema | 40 | 77.5% | 0.76 |
| **qwen2.5:3b, v5: temperature 0, fairness fixes** | **40** | **80.0%** | **0.78** |

| Label (v5) | Precision | Recall | F1 | Answers |
|---|---|---|---|---|
| Mastered | 0.82 | 0.69 | 0.75 | 13 |
| Partial | 0.64 | 0.64 | 0.64 | 11 |
| Struggling | 0.89 | 1.00 | 0.94 | 16 |

Chance is about 33%. The schema (v4) ended unreadable replies; the 3B model
now matches the 7B's best run. The marker is slightly strict: 4 answers
labelled mastered by people were marked partial.

### Calibration and consistency

Is the marker's confidence honest, and does it repeat itself?
`python -m scripts.calibration_consistency --out tests/eval/CALIBRATION.md`

| Run | Mean confidence | Accuracy | ECE | Brier | Right when confidence ≥ 0.85 |
|---|---|---|---|---|---|
| qwen2.5:3b v4 | 0.73 | 78% | 0.14 | 0.18 | 14 of 16 |
| qwen2.5:3b v5 | 0.73 | 80% | 0.24 | 0.19 | **15 of 16** |

| Consistency | Answers | Same label | Cohen's kappa |
|---|---|---|---|
| qwen2.5:7b, run 1 vs run 2 (default temperature) | 33 | 29 (88%) | 0.82 |

The marker is under-confident overall, but a high-confidence label is nearly
always right, so labels below 0.85 are the ones for a lecturer to check. One
label in eight changed between identical runs, which is why v5 marks at
temperature 0.

### Fairness and cheating

Does the mark depend on how well a student writes, and can a student talk the
marker into a better mark? The 13 mastered answers were rewritten with typos
and in simpler English (same meaning); 20 cheating attempts were written
first, and 10 more (the hold-out) only after the fixes, so the fixes were
never tuned on them.
`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_robustness --out tests/eval/ROBUSTNESS.md`

| Test | Before (v4) | After (v5) |
|---|---|---|
| Typo rewrites marked lower than the original | 2 of 13 | **1 of 13** |
| Simple-English rewrites marked lower | 3 of 13 | **0 of 13** |
| Rewrites still marked mastered | 19 of 26 | **24 of 26** |
| Known cheating attempts that worked | 3 of 20 | **1 of 20** |
| Known attempts stopped before reaching the model | 7 of 20 | 19 of 20 |
| New (hold-out) attempts that worked | not tested | **2 of 10** |
| New attempts stopped before reaching the model | not tested | 2 of 10 |

The fixes (v5): mark at temperature 0, tell the model that simple English and
typos cost nothing, match a quoted word to the student's misspelling, mark a
bare list of keywords as struggling, and screen out more instructions to the
marker. A second v4 run lowered 7 rewrites and let 4 attempts through: v4
varied from run to run. The screening rules catch only 2 of the 10 new
attempts, so phrase rules do not carry over; the model stopped 6 more. The 3
attempts that still work are keyword lists dressed as sentences
("Regularisation. Overfitting. Penalty.").

Since review (v6): marking a bare keyword list struggling without the model
also failed short correct sentences ("Dropout prevents co adaptation"), so
such an answer now goes to the model with its confidence capped at 0.6 and a
note, and two broad screening rules ("see the reference answer", any closing
tag such as `</p>`) were narrowed. The two keyword-list attempts (x04, x18) are
therefore no longer stopped before the model; the table above is v5 and is
to be rerun on v6.

## 6. Summaries

Are the lecturer and student summaries true to the data? Code counts the
results; the model writes the sentences; every number, label and slide in a
sentence is checked against the facts, and a sentence that fails twice is
replaced by the plain facts. 10 lecturer summaries and 2 per student for 8
students. `OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_summaries --out tests/eval/SUMMARIES.md`

| Summary | Before (v3): AI summary used | After (v4): AI sentences used | Wrong facts shown |
|---|---|---|---|
| Lecturer (10) | 1 of 10 | **50 of 50 sentences** (all first try) | 0 |
| Student (16) | 1 of 16 | **80 of 80 sentences** (6 after a retry) | 0 |

v3 asked for free text and threw the whole summary away for one bad sentence;
most failures were sentences naming no topic, or two topics with one topic's
numbers. v4 asks for one sentence per topic as JSON, checks each against its
own topic, and retries only the topics that failed.

## 7. Perplexity: Qwen vs Gemma

How well does a language model fit lecture text? Ollama gives no token
probabilities, so base models were run through Hugging Face.
`python -m scripts.perplexity --out tests/eval/PERPLEXITY_QWEN_GEMMA.md`

Bits per byte (lower is better). Unlike perplexity per token, it can compare
models with different tokenizers.

| Text | Qwen2.5-1.5B | Gemma 3 1B | Qwen better by |
|---|---|---|---|
| Everyday English (control) | 0.812 | 0.814 | tie |
| lecture.txt | 0.518 | 0.705 | 27% |
| lecture.pptx | 0.766 | 0.921 | 17% |
| lecture.docx | 0.840 | 0.932 | 10% |
| lecture.pdf | 1.031 | 1.208 | 15% |
| cnn_lecture.pptx | 0.819 | 1.034 | 21% |
| linear_regression_notes.pdf | 0.730 | 0.897 | 19% |

Per token, Gemma looked better on everyday English (13.78 vs 14.12), but its
tokens are longer, so the comparison is unfair; per byte the two tie. On
every lecture Qwen fits the text better, so the app stays on Qwen. Within
Qwen, the 1.5B model had lower perplexity than the 0.5B on all 6 texts
(`PERPLEXITY.md`).

## 8. Speed: GuideLLM load test

How long do students wait when several ask at once? GuideLLM 0.8.1 sent 700
token prompts to `qwen2.5:3b` through Ollama on the laptop, for 5 minutes at
each level, 0 errors in every run. Results in `guidellm_qwen3b.json` and
`guidellm_qwen3b_parallel4.json`.

| Students at once | Wait for first word, default | Wait for first word, 4 parallel slots | Full answer, default | Full answer, parallel | Total speed, default | Total speed, parallel |
|---|---|---|---|---|---|---|
| 1 | 4.4 s | 4.4 s | 34 s | 18 s | 10 tokens/s | 10 tokens/s |
| 4 | 106 s | **4.9 s** | 141 s | **39 s** | 10 tokens/s | **17 tokens/s** |
| 8 | 118 s | 68 s | 135 s | 123 s | 10 tokens/s | 17 tokens/s |

Medians. Parallel slots (`OLLAMA_NUM_PARALLEL=4`) serve up to 4 students at
once; beyond that requests queue, and total speed stops at the laptop's limit
of about 17 tokens/s. The single-student full answer differs because the
answers were shorter in the second run. A class needs a GPU server with
parallel slots; the AI gateway's priority queue keeps live-class requests
first.

## 9. Confidence intervals

The test sets are small, so each result is given with a 95% bootstrap
interval (10,000 resamples, items resampled whole). No model is needed.
`python -m scripts.confidence_intervals --out tests/eval/CONFIDENCE_INTERVALS.md`

| Measure | Value | 95% interval | n |
|---|---|---|---|
| Retrieval hit@5, after captions | 0.91 | 0.78 to 1.00 | 32 |
| Retrieval MRR, gain from captions | 0.06 | 0.01 to 0.14 | 32 |
| Grounding: drafts passing the checks | 36% | 20% to 56% | 25 |
| Grounding precision | 67% | 33% to 100% | 9 |
| Marking accuracy, qwen2.5:3b v4 | 78% | 65% to 90% | 40 |
| Marking accuracy, qwen2.5:3b v5 | 80% | 68% to 92% | 40 |
| Cohen's kappa, two labellers | 0.85 | 0.70 to 0.96 | 40 |

The MRR gain from captions stays above 0, so it is unlikely to be chance. v4
and v5 accuracy overlap: v5's gain is one answer, so it shows the fixes did
not make normal marking worse, not that they made it better.

## Evaluation methods

| Technique | Where | Why |
|---|---|---|
| Accuracy, precision, recall, F1 against human labels | Marking | The marker's job is to match a teacher |
| Cohen's kappa between two labellers | Marking | Shows the human labels are reliable enough to test against |
| hit@k, MRR, precision@k | Retrieval, embeddings | Standard ranking measures |
| CER, WER, word recall | OCR | Standard OCR measures, plus one that ignores reading order |
| Rule-based checks | Grounding, summaries | Exact and cheap; the app runs them on every output |
| Human judgement | Grounding | Only a person can judge whether a question is fair and correct |
| LLM as verifier | Grounding | Tested against human judgements |
| ECE, Brier score, AUROC | Calibration | Whether confidence can be trusted |
| Repeated runs, kappa between runs | Consistency | Model outputs vary between runs |
| Rewritten inputs (typos, simple English) | Fairness | Same meaning should get the same mark |
| Adversarial inputs, with a hold-out set | Cheating | Measures defences on attempts they were not tuned on |
| Perplexity, bits per byte | Language model | Fit to lecture text, comparable across tokenizers |
| Load testing (GuideLLM) | Speed | Wait times and throughput under several users |
| Bootstrap confidence intervals | All | The test sets are small |
| Not used: BLEU / ROUGE | n/a | A good question or summary has many correct wordings |
| Not used: general benchmarks (MMLU) | n/a | They measure general knowledge, not these tasks |

## Limits

- Small test sets: 40 answers, 32 retrieval questions, 25 drafts, 9 judged
  questions, 30 cheating attempts. Section 9 shows how far the numbers could
  move.
- One person judged the accepted questions.
- Test lectures come from an open textbook and the sample deck; real course
  lectures would be a stronger test.
- The speed test ran on one laptop, not the server the app would use.

## Next steps

1. Test with real course lectures, and grow the labelled sets, with a second
   person judging grounding.
2. Catch keyword lists dressed as sentences, then test on a fresh hold-out
   set of cheating attempts.
3. Flag labels below 0.85 confidence for the lecturer to check.
4. Retest all-minilm on a larger question set before any embedding change.
5. Deploy on a GPU server with `OLLAMA_NUM_PARALLEL` set, and rerun the load
   test there.
