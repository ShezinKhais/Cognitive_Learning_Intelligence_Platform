# Fresh held-out marking sets (#251)

The 40 answers in `../answers_to_label.csv` and the 30 cheating attempts in
`../robustness_*.csv` were used while the prompt and screening rules were
written, so scores on them are optimistic. These sets are new, on a different
lecture (`tests/samples/cnn_lecture.pptx`, convolutional networks), and must
**never be used to change the prompt or the rules**. If a result here leads to
a fix, the fix is checked on a newer set, not this one.

- `questions.json`: five questions (c1 to c5), each with a reference answer,
  key points and the slide excerpt.
- `answers_to_label.csv`: 40 empty rows, 8 per question, for real answers.
- `adversarial.csv`: 15 empty rows for new cheating attempts.

## 1. Collect answers

Ask classmates (not the people labelling) to answer the five questions in
their own words, after reading the slides, without seeing the reference
answers. Aim for a mix: some full, some half right, some wrong. Paste each
answer into `student_answer`. Do not edit spelling. Leave a row empty if you
have fewer than 40 answers; empty rows are skipped.

## 2. Label independently

Two people who did not write the questions or the answers fill `label_a`
and `label_b` (`mastered`, `partial` or `struggling`), each without looking
at the other's column, using the rules in `../README.md` and the key points.
Then they agree `label_final` together. Write who labelled in the commit
message, not in the file.

## 3. Write cheating attempts

Someone who has not read the screening rules in
`app/services/free_text_classifier.py` (Cyber 1 is ideal) fills
`student_answer` in `adversarial.csv` with answers that try to get a better
mark than they earn: telling the marker what to do, pretending to be the
system, keyword lists, other languages, anything. None should earn more than
`struggling`.

## 4. Run (Ollama running, from backend/, `source .venv/bin/activate`)

```bash
OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_classifier \
  --questions tests/eval/fresh/questions.json \
  --answers tests/eval/fresh/answers_to_label.csv \
  --agree label_a label_b \
  --out tests/eval/fresh/results_qwen3b_v6.csv
```

```bash
OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_robustness --only-new \
  --questions tests/eval/fresh/questions.json \
  --new tests/eval/fresh/adversarial.csv \
  --out tests/eval/fresh/ROBUSTNESS_v6.md
```

```bash
python -m scripts.calibration_consistency \
  --run tests/eval/fresh/results_qwen3b_v6.csv "qwen2.5:3b v6, fresh set" \
  --out tests/eval/fresh/CALIBRATION_v6.md
```

## What to report

Accuracy and per-label precision and recall (from the first command),
labeller agreement (kappa), right at each confidence level and the threshold
table, attempts refused vs marked struggling vs worked, and the limits:
how many answers, from how many students, one lecture.
