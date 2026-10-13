# AI evaluation report (Phase 8, AI 1, #73)

Baseline metrics for the AI 1 pipeline: reading lecture files, finding the
right slide for a question, writing grounded questions, and marking free-text
answers. Every number here comes from a script in `backend/scripts/` run on
the sample lectures in `backend/tests/samples/`, and can be rerun with the
command given in each section.

All models run locally through Ollama on an 8 GB laptop: `nomic-embed-text`
for embeddings, `qwen2.5vl:3b` for image captions, and `qwen2.5:3b` (the app
default) or `qwen2.5:7b` for text.

## Summary

| Area | Measure | Result |
|---|---|---|
| Parser coverage | Pages or slides with text read | 40 of 41 across 4 formats; scanned PDF 0 of 1; corrupt PDF rejected safely |
| Retrieval | hit@5, all 11 questions | 0.55 before image captions, **0.82** after |
| Retrieval | MRR, all 11 questions | 0.55 before, **0.72** after |
| Retrieval | precision@5, text questions | **0.43** (best possible on these slides: 0.57) |
| Question grounding | Drafts passing the automatic checks | **36%** (9 of 25, `qwen2.5:3b`) |
| Question grounding | Accepted questions a human judged correct | **67%** (6 of 9) |
| Classification | Accuracy, all 40 answers | `qwen2.5:3b` **66%**, `qwen2.5:7b` **72.5%** (mean of 2 runs each) |
| Classification | Recall on struggling answers | 0.80 to 1.00 (on the replies read) |
| Human agreement | Cohen's kappa between two labellers | **0.85** (36 of 40 agreed) |
| Perplexity | Qwen2.5 1.5B vs 0.5B | 1.5B lower on all 6 texts |

## 1. Parser coverage

Can the pipeline read every kind of file a lecturer uploads?

`python -m scripts.parser_coverage --edge-cases --out tests/eval/PARSER_COVERAGE.md`

| File | Parser | Read | Pages with text | Headings | Images |
|---|---|---|---|---|---|
| lecture.pdf | pypdf | yes | 21 of 21 | 0 | 0 |
| lecture.pptx | python-pptx | yes | 17 of 18 | 17 | 4 |
| lecture.docx | python-docx | yes | 1 of 1 | 0 | 0 |
| lecture.txt | plain text | yes | 1 of 1 | 0 | 0 |
| scanned.pdf | pypdf | yes | 0 of 1 | 0 | 1 |
| corrupt.pdf | none | rejected with a clear error | - | - | - |

**Findings**

- Every real document was read. The one PowerPoint slide with no text is a
  picture-only slide, and its picture is captioned.
- PDFs give no headings with pypdf, so their chunks get no heading path.
  Docling would find them but is much slower, so it is used only for
  letter-spaced PDFs.
- A scanned PDF has no text layer, so nothing is read from it. OCR is not in
  scope; the lecturer gets a warning that the page had no readable text.
- A corrupt file fails safely with a message, and does not crash the worker.

## 2. Retrieval

When a student asks a question, does the right slide come back near the top?

`python -m scripts.evaluate_retrieval --out tests/eval/RETRIEVAL_RESULTS.md`

11 questions about `lecture.pptx`, each with the slides that answer it. 5
are answered only by a picture, 6 by the slide's text. The lecture is chunked
twice: as before image captioning (#127) and as now.

| Questions | hit@1 | hit@5 | MRR | precision@5 |
|---|---|---|---|---|
| image (5) | 0.00 → 0.20 | 0.00 → 0.60 | 0.00 → 0.39 | 0.00 → 0.12 |
| text (6) | 1.00 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 | 0.43 → 0.43 |
| all (11) | 0.55 → 0.64 | 0.55 → 0.82 | 0.55 → 0.72 | 0.24 → 0.29 |

- **hit@k**: share of questions where an answering slide is in the top k.
- **MRR** (mean reciprocal rank): 1 if the answer is first, 0.5 if second,
  and so on, averaged.
- **precision@5**: share of the top 5 chunks that come from an answering slide.

**Findings**

- Before captions, questions about pictures could never be answered: those
  slides had no searchable text. After, 3 of 5 are found in the top 5.
- Captions did not push any text answer down: all 6 stay at rank 1.
- precision@5 looks low but is capped by the slides. Most answering slides
  have only 1 or 2 chunks, so the best possible precision@5 on the text
  questions is 0.57. 0.43 is 76% of that.
- Two picture questions still miss: one needs a value read off a graph
  (height where the probability is one half), which a 3B vision model does
  not describe precisely.

## 3. Question grounding

Are the questions the AI writes supported by the lecture?

`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding`, then
`--precision` after marking `grounded_luna` in `grounding_accepted.csv`.

Every draft question must pass three checks in code before a lecturer sees
it: the cited slide exists, the quoted excerpt is really on that slide, and
the excerpt supports the answer. 5 rounds of 5 questions on `lecture.pptx`:

| Measure | Value |
|---|---|
| Drafts | 25 |
| Accepted | 9 (36%) |
| Rejected | 16 |
| Replies that could not be read | 0 |

| Why rejected (a draft can fail more than one check) | Drafts |
|---|---|
| Answer not supported by the excerpt | 14 |
| Excerpt not found on the slide | 8 |
| Citation missing or wrong slide | 5 |

Accepted per round: 3, 3, 0, 2, 1.

**Human check of the accepted questions.** Luna compared each of the 9
accepted questions with its slide: **6 of 9 (67%) are correct.**

| Question | Problem |
|---|---|
| g04 | Circular: asks which method is used for maximum likelihood estimation, answer "Maximum Likelihood". Slide 3 also names gradient descent, a wrong option a student could defend. |
| g06 | Two correct options: slide 5 says both multinomial and ordinal models have three or more outcomes. |
| g09 | Wrong answer: says logistic regression can generate outputs; slide 6 says it cannot. Its excerpt is about overfitting, not the question. |

g07 is also a near-duplicate of g03.

**Findings**

- The checks stop the most common failure, answers that claim more than the
  slide says (14 drafts), and every misquote and wrong citation.
- They cannot judge whether a question is well formed, has one right answer,
  or whether the excerpt is about the question. That is why C.L.I.P keeps
  the lecturer's approval step before students see any question.
- Acceptance varies a lot between rounds (0 to 3 of 5), so one round is not
  a reliable measure: 5 rounds were run and pooled.

## 4. Free-text classification

Does the classifier give a student answer the same label as a human?

`OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_classifier --out tests/eval/results_qwen3b_run2.csv`

40 student answers to 5 questions, each labelled mastered, partial or
struggling by Luna and Nour separately. They agreed on 36 of 40 before
discussing (**Cohen's kappa 0.85**, strong agreement) and settled the other 4
together; the classifier is scored against those final labels. Prompt
`free-text-v3`.

| Model and run | Replies read | Accuracy (read) | Accuracy (all 40) | Macro F1 |
|---|---|---|---|---|
| `qwen2.5:7b` run 1 | 34 | 79.4% | 67.5% | 0.78 |
| `qwen2.5:7b` run 2 | 37 | 83.8% | 77.5% | 0.82 |
| `qwen2.5:3b` run 1 | 40 | 65.0% | 65.0% | 0.63 |
| `qwen2.5:3b` run 2 | 33 | 81.8% | 67.5% | 0.79 |

Mean accuracy over all 40: **7B 72.5%, 3B 66.3%.** Chance is about 33%.

Per label (runs with saved results; precision and recall on the replies read):

| Run | Mastered P / R | Partial P / R | Struggling P / R |
|---|---|---|---|
| 7B run 1 | 1.00 / 0.75 | 0.50 / 0.86 | 0.92 / 0.80 |
| 7B run 2 | 0.89 / 0.73 | 0.67 / 0.80 | 0.94 / 0.94 |
| 3B run 2 | 0.89 / 0.73 | 0.71 / 0.62 | 0.82 / 1.00 |

**Findings**

- The 7B model is more accurate, but needs more than twice the memory (4.7 GB
  against 1.9 GB); the 3B stays the default so it runs on a lecturer's laptop.
- **Struggling** is the label that matters most to a lecturer, and it is the
  most reliable: recall 0.80 to 1.00. **Partial** is the hardest, as it was
  for the two human labellers.
- Results vary between runs of the same model (3B: 65.0% then 81.8% on the
  replies read), so each model was run twice and the mean is reported.
- Every unreadable reply had the same cause: the model left out the
  `wrong_claim` field. A stricter output format (JSON schema) should remove
  these; until then they count as wrong in the "all 40" column.

## 5. Perplexity

How predictable is lecture text to a language model?

`python -m scripts.perplexity --out tests/eval/PERPLEXITY.md`

Perplexity is exp(mean negative log-likelihood per token): roughly how many
equally likely next tokens the model is choosing between. Lower is more
predictable. Ollama does not return token probabilities for a given text, so
this uses the Hugging Face Qwen2.5 base models directly.

| Model | everyday English | lecture.txt | lecture.pptx | pptx as PDF | lecture.docx | lecture.pdf |
|---|---|---|---|---|---|---|
| Qwen2.5-0.5B | 18.21 | 7.82 | 11.62 | 13.16 | 20.25 | 33.62 |
| Qwen2.5-1.5B | 14.12 | 5.52 | 9.89 | 10.97 | 13.48 | 20.11 |

Two controls: five paragraphs of everyday English written for this test, and
`lecture.pptx` exported to PDF, the same words in another format.

**Findings**

- The 1.5B model has lower perplexity than the 0.5B on every text, in line
  with the 7B classifying better than the 3B.
- The same slides as a PDF score only 11 to 13% higher, so the PDF format
  itself costs little. The computer-vision PDF's much higher score comes
  mostly from its content: symbols, formulas and page numbers like "2 / 21".
- Lecture slides are more predictable than everyday English: teaching text
  repeats the same terms. lecture.txt is lowest but is a short, plain test
  file written for this project, so it says little about real lectures.
- Perplexity measures fluency, not correctness, and was measured on the base
  models rather than the chat models the app runs. It is reported alongside
  the task metrics above, not instead of them.

## 6. How the evaluation methods were chosen

| Technique | Used | Where | Why |
|---|---|---|---|
| Task metrics against human labels (accuracy, precision, recall, F1) | yes | Classification | The classifier's job is to match a teacher's judgement |
| Inter-annotator agreement (Cohen's kappa) | yes | Classification | Shows the human labels are reliable enough to test against |
| Retrieval metrics (hit@k, MRR, precision@k) | yes | Retrieval | Standard for ranking; measures whether the right slide comes back |
| Rule-based checks | yes | Grounding | Each check is exact and cheap, and runs on every question in the app too |
| Human evaluation | yes | Grounding precision | Only a person can judge whether a question is fair and correct |
| Perplexity | yes | Language model | Intrinsic measure of how well each model fits lecture text |
| Repeated runs | yes | Grounding, classification | Model outputs vary between runs |
| BLEU / ROUGE | no | | Need one reference text to compare against; generated questions have many correct wordings |
| LLM as judge | no | | Would need a stronger model than the one being judged, and can share its mistakes; human review was feasible at this size |
| Standard benchmarks (e.g. MMLU) | no | | Measure general knowledge, not this task |

## Limits

- **Small test sets:** 40 answers, 11 retrieval questions, 25 drafts, one
  sample lecture per format. The numbers are a baseline, not a final verdict.
- **One labeller for grounding:** Luna judged the 9 accepted questions alone.
- **Different topics per sample file:** only the pptx and pptx-as-PDF pair
  isolates the effect of format.
- **Lost run:** the CSV for `qwen2.5:3b` run 1 was overwritten; its summary
  numbers were recorded before that.

## Next steps

1. Use a JSON schema for classifier replies to remove the unreadable replies.
2. Add a check that the excerpt is about the question, and a duplicate check,
   to catch g09- and g07-style questions.
3. Grow the labelled sets, and have a second person judge grounding.
4. Caption images in Word documents, and use Docling for PDF headings.
