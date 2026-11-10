# Question yield with lecturer evaluation (#235)

The Phase 8 test wrote 25 draft questions. 9 passed the automated checks, and
only 6 of those 9 were right (`../AI_EVALUATION_REPORT.md`, section 4). That
was one lecture, one judge, and the sample deck.

This study repeats the measurement properly: real course material, the model
and settings an upload uses today, more than one judge, and pass marks agreed
before anyone sees a result. It answers four questions:

1. Of the questions the AI writes, how many can a lecturer use?
2. How many pass the automated checks but are wrong?
3. What goes wrong, and how often?
4. How long does a lecturer spend checking and fixing them?

**No results are recorded yet.** The tool is ready; the run needs real course
material, a laptop with Ollama, and judges. Results go in a folder here and
are linked from #175.

## What does not change

A lecturer approves every question before a class sees it. The generator only
ever writes drafts, a draft becomes deliverable only when its lecturer
approves it (`tests/test_question_review.py`), and only an approved, staged
question can be delivered (`test_only_a_staged_question_can_be_delivered` in
`tests/test_session_lifecycle.py`). This study measures how much work that
approval is. It is not a case for removing it, whatever the numbers say.

## Step 0: agree the thresholds

`thresholds.json` holds four pass marks. **The numbers in it are a proposal
from AI 1, not a decision.** The team (and ideally a lecturer) changes them if
needed, then fills in `agreed_by` and `agreed_on` and commits the file. Until
then the tool only runs with `--rehearsal`, and a rehearsal's report says it
cannot be used as evidence.

| Key | Proposed | Meaning |
|---|---|---|
| `min_usable_share_of_passed` | 0.8 | Of the questions that pass the checks, at least 80% are usable, as they are or after a correction |
| `max_incorrect_share_of_passed` | 0.15 | At most 15% of them are wrong. Phase 8 measured 33% (3 of 9) |
| `min_usable_per_material` | 5 | Every lecture ends with at least 5 usable questions from the 15 asked for |
| `max_median_review_seconds` | 90 | Checking one question takes a lecturer at most 90 seconds, typically |

Agreeing first matters: a pass mark chosen after seeing the result is not a
pass mark.

## Step 1: write the questions

Pick lectures the model and the prompt were never tuned on, from real
courses, including some with diagrams, formulas and tables. Ask the lecturer
who owns them first. Then, from `backend/`, with Ollama running:

    python -m scripts.evaluate_question_yield run ~/course/week3.pptx ~/course/week4.pdf \
        --tags ~/course/tags.json --dir tests/eval/yield/run1

The tags file says what is on which page, so the report can show whether
questions about diagrams and formulas do worse than questions about plain
text. Pages not listed count as text only. The kinds are free: use the same
words across files.

    {
      "week3.pptx": {"diagram": [4, 9], "formula": [6, 7], "table": [11]},
      "week4.pdf": {"formula": [2, 3, 5]}
    }

The run processes each file exactly as an upload does: same model, prompt,
settings, checks and option verifier, read from `.env`. With
`IMAGE_CAPTIONING_ENABLED=true` it describes the pictures first, as an upload
would; without it, a diagram is invisible to the question writer, so turn it
on if the deployment will have it on. It writes three files:

| File | Holds |
|---|---|
| `run.json` | The commit, model, settings, prompt hashes, thresholds, and each material's hash and counts |
| `sheet.csv` | Every question that passed the checks, for the judges |
| `rejected.csv` | Every draft the checks rejected, with the reasons. Kept, not thrown away |

## Step 2: judge

Each judge marks every question in `sheet.csv`, alone, without seeing anyone
else's marks. At least two judges, and at least one of them a lecturer on the
course rather than a team member. With the lecture open beside the terminal:

    python -m scripts.evaluate_question_yield judge --name farhad --dir tests/eval/yield/run1

It shows one question at a time, with the answer the AI marked as right and
the sentence it quoted, and times each one. Ctrl+C stops it; running it again
carries on where it stopped. A judge who prefers a spreadsheet can copy
`sheet.csv` to `judged_<name>.csv` and fill in the last four columns, timing
themselves.

Judge as you would when approving the question for your own class:

| Verdict | Use it when |
|---|---|
| `usable` | You would approve it as it is |
| `edit` | You would approve it after a correction. Type the corrected wording, so the time counts the fix |
| `reject` | You would not use it, and fixing it means rewriting it |

For `edit` and `reject`, name the main problem:

| Problem | Means | Counts as wrong |
|---|---|---|
| `wrong_answer` | The marked answer is wrong | yes |
| `several_right` | More than one option is right, or none is | yes |
| `not_in_material` | The cited page does not support the question or its answer | yes |
| `unclear` | Ambiguous or badly worded | no |
| `trivial` | Tests nothing worth asking | no |
| `other` | Something else: say what in the note | no |

## Step 3: report

    python -m scripts.evaluate_question_yield report --dir tests/eval/yield/run1

writes `QUESTION_YIELD.md` in the run's folder: the yield, the questions that
passed but are wrong, the kinds of failure, review time, how far the judges
agreed, and each threshold as met or not met. Where judges disagree the
strictest one decides: one `reject` rejects the question. It can be run at any
point; a half-judged run says it is incomplete and claims no yield.

## Committing a run

The sheets quote the lecture material. Commit the run's folder only with the
lecturer's permission. Without it, commit `run.json` and `QUESTION_YIELD.md`
(they hold counts, file hashes and no lecture text) and keep the CSV files
somewhere the team can reach. Either way, link the report from #175.

## Limits to state with the results

- Judges are not blind to the answer the AI marked, as a lecturer approving a
  question is not either.
- Review time is measured in this tool, not in the app's review page.
- The automated checks may also reject good questions. `rejected.csv` keeps
  them so that can be looked at, but nobody judges them here.
- The numbers describe one model, one prompt and the lectures used. `run.json`
  records which.
