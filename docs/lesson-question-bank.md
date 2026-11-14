# Lecturer question bank and lesson selection

Implements #246 and the optional lesson-alignment workflow in #247. Reuses
Shezin's `Shezin-Question-Reuse` authoring/reuse/take-back implementation with
additional source validation, independent lesson copies and race tests.

## Write or reuse a question

1. Open **Materials**, then the material's question review page.
2. Choose **Write a question**. For an MCQ, provide distinct choices and select
   the correct one. For a written question, provide a reference answer and at
   least one marking key point. A topic helps when preparing a lesson.
3. Optionally enter a source page/slide and an exact passage. Supplied references
   must match indexed content in that material. Without a reference, the question
   remains explicitly without a source; the system does not invent one.
4. Review the wording, answer and source, then choose **Save, ready to send**.
   Saving a lecturer-authored question is an explicit lecturer approval. Generated
   drafts still require their existing review/approval step.
5. For an already delivered question, **Ask again** creates a new staged copy.
   Its original ID, historical answers, classifications and session binding stay
   intact. Malformed legacy questions must be corrected through a new reviewed
   question rather than copied into another live class.
6. **Back to review** takes an unassigned staged question out of the bank so it
   can be edited. A delivery and take-back serialize on the question row; a
   delivered question can never be changed back to draft. A lesson-bound copy
   must instead be removed through its prepared lesson's selection.

## Prepare a lesson

The web lecturer class page and Teams meeting panel show **Checkpoints for this
lesson** before the class starts. Existing sessions use the course bank until
this opt-in selection is saved.

1. Enable **Use only selected checkpoints in this lesson**.
2. Find approved questions by material name and/or topic. Browse pages without
   losing selected questions; review each answer and source before choosing it.
3. Confirm the selection and save. Up to 100 questions can be selected. Each
   lesson gets independent copies, even when two lessons use the same original.
4. Save or discard unsaved changes before starting. The server also locks the
   session against concurrent start/selection changes. Selection is fixed once
   the session starts; pause does not reopen the plan for edits.
5. An empty or exhausted explicit selection sends no additional course-bank
   questions. The readiness warning and manual delivery list use the same rule.
   The material tutor also uses the selected questions' eligible materials.
6. To return to the course-bank workflow, turn the option off, confirm and save
   before starting. Only unused lesson copies are removed; bank originals and
   historical deliveries/responses are protected.

This aligns checkpoints with the lecturer's chosen lesson. It does not infer
what the lecturer has covered from microphone audio or automatically select a
slide while presenting.

## Deployment and API

Apply `alembic upgrade head` before running this version. Migration
`e9a1b2c3d4e5` adds a non-null, default-false session flag. Existing sessions
retain their previous behavior. Question copies use the existing question table.
For a release rollback, stop active classes first: the older release does not
implement selected-only delivery. Downgrading removes the flag and retains
question/history rows.

Staff-only, terms-protected, owner-checked endpoints:

- `POST /materials/{material_id}/questions`: write an approved manual question.
- `POST /materials/{material_id}/questions/{question_id}:reuse`: copy a delivered
  question into the staged bank.
- `GET /sessions/{session_id}/question-plan`: current selection and editability.
- `GET /sessions/{session_id}/question-plan/candidates`: paginated, course/lecturer
  scoped reviewed questions; optional material/topic filters.
- `PUT /sessions/{session_id}/question-plan`: confirm and save a prepared lesson.

Plan reads are `no-store`. Answer keys/reference answers remain staff-only;
student delivery payloads are unchanged. Plan writes are audited. A source ID
outside the lesson's lecturer/course scope fails atomically without replacing
an existing selection. Re-filing a selected material cannot bypass delivery or
retrieval course boundaries.

## Validation

`backend/tests/test_question_plan.py` exercises independent simultaneous plans,
source/ownership boundaries, history protection, empty/exhausted plans, stable
resave, candidate filters, manual source validation, and start/take-back locks.
The reused review tests cover authoring, reuse and take-back. Browser coverage
is in `frontend/e2e/questionBank.spec.ts`, using synthetic requests in Chrome and
Edge. These tests establish workflow behavior, not AI accuracy or teaching
outcomes; those evaluations remain separate issues.
