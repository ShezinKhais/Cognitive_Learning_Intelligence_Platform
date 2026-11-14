# Retrieval across whole courses (#252)

The first retrieval test (`../RETRIEVAL_RESULTS.md`, #127) asked 32 questions
of three sample lectures, one lecture at a time. The tutor really searches
**every lecture of a course at once**, and drops any excerpt further than a
cutoff (`RETRIEVAL_MAX_DISTANCE`, now 0.65 in `app/services/tutor_guardrails.py`)
from the question, so it can say the material does not cover it. That cutoff
was set by hand and never measured.

This test measures both:

1. **Finding the right page:** where the first excerpt from a page that
   answers a question ranks, and whether the top excerpt names the right
   lecture and page, split by kind of question.
2. **Saying "not in the material":** for questions nothing in the course
   answers (off-topic, or from another course), whether the tutor would stay
   quiet; for questions a page does answer, whether it would wrongly refuse.
   It does this at the current cutoff, and at the cutoff that does best on the
   **dev** questions, scored on the **held-out** questions, which are never
   used to choose it.

## The questions

`queries.json` holds the courses (each a list of lecture files) and the
questions. Each question has:

| Field | Means |
|---|---|
| `id` | unique, such as `c017` |
| `course` | one of the courses |
| `split` | `dev` (may be used to choose the cutoff) or `heldout` (never) |
| `kinds` | one or more of the kinds below |
| `query` | the question, as a student would type it to the tutor |
| `answers` | the lecture files and pages that answer it; `[]` for an off-topic or other-course question |

Kinds: `text`, `diagram`, `table`, `image-only` (only a picture, photo or plot
answers it), `formula`, `code`, `student-wording` (worded as a student would,
not as the slide is), `arabic`, `scanned` (the page is a scan read with OCR),
`off-topic` (nothing in any course), `other-course` (only another course's
lecture answers it).

A sixth course, "logistic regression (scanned)", is the repository's own
`tests/eval/ocr/lecture_pptx_as_pdf_scanned.pdf`: the sample slides saved as
image-only scans. Its 11 answerable questions are the ones the #127 test asked
of the same slides (page for page), written by another person, so the
`scanned` rows show what OCR costs. Copy the file into the materials folder
before running, and install Tesseract (`brew install tesseract` on a Mac);
without it the scan has no text and its questions count as misses.

The first 131 questions cover 10 MIT OpenCourseWare lectures in 5 courses,
written from what each page **shows**, not from what the app reads from it,
so a page the app reads badly shows up as a miss. A fixed random third of them
(seed 252) is held out. The OpenStax Word notes are left out: a Word file has
no pages, so "the right page" cannot be scored (#269).

## Writing held-out questions (please do this before seeing any results)

Questions written by someone who has not seen the results are the strongest
test. Add them with `"split": "heldout"`:

- Open the lecture, pick a page, and write the question **a student would
  ask**, in your own words. Do not copy the slide's sentence.
- List **every** page that answers it, not just the first one you found.
- Mix the kinds: some about diagrams, tables, formulas and pictures, a few in
  Arabic, and a few the course **cannot** answer (`off-topic` or
  `other-course`, with `"answers": []`).
- Give each a new `id` (`c132`, `c133`, …).

The test refuses a file with a mistake in it (an unknown course, a material
not in that course, a question with no pages) and names the question, so a
typo costs a second, not a run.

## Running it

From `backend/`, with Ollama running and the embedding model pulled
(`ollama pull nomic-embed-text`), and the lecture files in one folder:

    python -m scripts.evaluate_course_retrieval --materials ~/clip-pilot \
        --out ~/clip-pilot/retrieval/RETRIEVAL_COURSES.md

Files are read, captioned and chunked as an upload does (with the settings in
`.env`), so the result describes the app as it is. Captions are saved in the
materials folder, so a rerun is quick. The report lists each file's SHA-256 so a
rerun can be checked against the same files. Commit the report, not the
lecture files.

## Limits

- The lectures are MIT OpenCourseWare, not UOWD courses; the issue asks for
  real course material, and a UOWD course should be added with its lecturer's
  permission.
- The answer pages were labelled by one person (Claude, while preparing the
  set) and should be checked by a second.
- Questions written by the same person who wrote the dev set are only partly
  independent; the held-out questions you add are the independent part.
