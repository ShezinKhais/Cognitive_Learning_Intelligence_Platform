# Student revision and catch-up acceptance

AI2 scope: #241 and the student experience in #239. This checklist supplements
real Teams acceptance; automated browser tests use synthetic accounts and mocked
streams, not microphone speech or Microsoft Graph delivery.

## Preconditions

Use a test course with two enrolled student accounts and a lecturer. Enable
`VITE_SOCRATIC_CHAT_ENABLED=true` for the frontend build. Configure the existing
AI gateway and retrieval service. For live speech and automatic transcripts,
follow `docs/live-transcription.md` and the Graph configuration guides. Never
use production student data as a test fixture.

## End-to-end student checks

1. Start a lecture, deliver an approved MCQ with a known answer and source.
   Student A answers incorrectly; student B answers correctly. Deliver another
   checkpoint to A and let its answer window close without answering.
2. While the lecture is active, confirm `/student-reviews/{sessionId}` refuses
   review access. Ask the material tutor for the current checkpoint's answer:
   its existing guard must refuse direct answers. The review changes do not
   expose answer keys through the live session API.
3. With the lecturer's explicit consent, start live microphone transcription.
   Say an identifiable synthetic teaching point. Check that a published note
   appears with its time and unreviewed/incomplete notice. Ask the discussion
   chatbot about that point and inspect its note citation. Record elapsed time,
   omissions and vocabulary errors; do not infer accuracy from the mock tests.
4. Stop speech capture, then end the lecture. Open the student's review shortcut.
   Confirm the wrong answer displays the student's saved response, reference
   answer, stored key points where available and a source button. No generated
   explanation is substituted for a missing reference or source.
5. Open **Unanswered checkpoints**. Confirm the missed question is separate from
   wrong answers, includes the reference and source, and is not assigned a
   comprehension mark. A student with zero submissions can still read misses.
6. Open sources for both entries. Check the material title and page/slide against
   the approved question. Reload: saved responses and source links remain,
   while chat conversations clear. Compare A and B: neither sees the other's
   responses or missed records. Cross-account response/missed IDs must return 404.
7. Ask the **Socratic learning assistant** for help with the material after the
   lecture. Then use **Ask about the discussion** to ask what was said in class.
   Each starts with its own conversation; material help is guided, and discussion
   catch-up is based on lecturer-published notes. Test the selected time range.
8. If Graph fetching is enabled, finish the Teams meeting and wait for an actual
   transcript notification/fetch. Confirm the resulting draft is private until
   the lecturer reviews and publishes it. Correct and remove a published note,
   and re-check student retrieval. Exercise manual import if automatic fetching
   fails. No Teams recording is downloaded by these review changes.
9. With 21+ recorded missed checkpoints, use Next/Previous independently of the
   submitted-answer pages. Check missing references, removed sources, API errors,
   keyboard access, mobile layout and the separate unavailable-engagement state.

## Evidence to record in #175 / #239

Record commit SHA, deployed frontend/backend versions, browser/Teams version,
feature settings (no secrets), test account codes, date, expected/actual result,
screenshots, defect links, and transcript delay/quality measurements. Mark tests
**not run** or **blocked** when tenant permissions, hardware or services prevent
execution. Leave #239 open until its real-meeting acceptance criteria are met.

## Automated regression coverage

- `backend/tests/test_student_review.py`: ended-session/current-member isolation,
  own missed-record source lookup, missing references, bounded pagination and
  zero-submission reviews; no model-generated scoring.
- `backend/tests/test_tutor_chat.py`: authorized ended-session material tutoring,
  current membership revocation, and existing live-answer restrictions.
- `backend/tests/test_discussion.py` and existing transcription/Graph suites:
  published/private data boundaries and transcript lifecycle under test doubles.
- `frontend/e2e/studentReview.spec.ts`: wrong versus unanswered, source expansion,
  independent pagination, reload, separate material/discussion conversations,
  access denial and accessibility checks in branded Chrome/Edge CI.

Ideas for reference answers and ended-session tutoring were adapted from
Shezin's existing `Shezin-Student-Review` branch. Its browser-storage persistence
was not adopted: conversations remain in memory and disappear on reload.
