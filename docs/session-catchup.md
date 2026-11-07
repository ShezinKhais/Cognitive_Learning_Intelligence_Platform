# Live and post-session discussion catch-up

Lecturers open **Discussion minutes** from a live class or session report.
Publish timestamped teaching points, examples and anonymized student questions,
reviewed for sharing with the course. The form requires confirmation before
publication. Notes can be edited and removed. Retry uses the same note ID to
avoid duplicates after a lost HTTP response.

Students open **Catch up on this session** in the live panel or past-session
review. Notes refresh every 15 seconds. The panel shows the latest recorded
discussion time, the published record and an assistant that searches those
notes. Choose all notes or the last 10/30 minutes before asking. During class
the window ends when selected. After class it ends at the latest recorded note.
Changing the window starts a new conversation.

The existing AI gateway, cancellation, request limits and tutor safety checks
apply. The assistant cites note timestamps, excerpts and a link to the full
record. Unmatched questions and empty windows produce the existing no-source
state. Note retrieval uses word overlap and returns up to the configured chat
source limit. A recap covers its cited sources, which may represent only part
of the discussion. Lecturer notes are refreshed on every question. The model
needs the configured Ollama service.

This implementation's source is lecturer-published minutes. Automatic Teams
transcript ingestion is a separate integration dependency. No meeting audio
or transcript is captured. Lecture-slide chat retains its existing source
selection.

The publishing lecturer and admins can manage a session's notes. Students
must be enrolled on its course, accept terms, and use an active or ended
session. Notes remain available to those students after the session ends,
including students who missed the class. Prepared/cancelled sessions are
unavailable. Session deletion and the configured retention purge cascade to
the notes. Notes hold no student identifiers. Publishers must remove personal
details and assessment solutions before confirming publication. The group
should approve the updated privacy wording before real-user deployment.

At most 200 notes of 2,000 characters can be published per session. Edit existing
notes when the cap is reached. Publication/removal are audited. Requests and
responses use the existing private API cache policy. Chat conversations are
not persisted.

Run `alembic upgrade head` before deployment. Enable the existing
`VITE_SOCRATIC_CHAT_ENABLED=true` frontend flag and configure the Ollama service
for chat; published minutes remain readable with chat disabled. Verify live publication, course isolation,
ended-session reload, note correction/removal, time windows and citations using
synthetic minutes. Model and Teams tenant acceptance require their respective
running services.

## Validation (7 November 2026)

- 364 backend tests passed for discussion, existing tutor behavior, API contract,
  authentication/consent and route auditing.
- 101 related retention, governance, privacy and student-review tests passed;
  two existing tests were skipped.
- 239 frontend unit tests passed; production build, browser typecheck and lint passed.
- Four Chromium browser tests passed for confirmed publication/edit/removal,
  ended-session time windows and full-source navigation, error recovery and
  retry identity. The source-navigation screen passed WCAG A/AA automated checks.
- Migration downgrade and upgrade passed against a disposable PostgreSQL/pgvector
  database. The discussion/tutor/contract subset passed again after migration.

Browser responses and model output in these tests are deterministic fixtures.
They verify wiring and safety behavior, not real-model answer quality. Real
Ollama and Teams tenant acceptance remains necessary before demonstration.
