# Live and post-session discussion catch-up

Lecturers open **Discussion minutes** from a live class or session report.
Publish timestamped teaching points, examples and anonymized student questions,
reviewed for sharing with the course. The form requires confirmation before
publication. Notes can be edited and removed. Retry uses the same note ID to
avoid duplicates after a lost HTTP response.

Students open **Catch up on this session** in the live panel or past-session
review. The session record refreshes every 5 seconds. The panel shows the latest recorded
discussion time, the published record and an assistant that searches those
notes. Choose all notes or the last 10/30 minutes before asking. During class
the window moves forward each time a question is submitted. After class it ends
at the latest recorded note.
Changing the window starts a new conversation.

The existing AI gateway, cancellation, request limits and tutor safety checks
apply. The assistant cites note timestamps, excerpts and a link to the full
record. Unmatched questions and empty windows produce the existing no-source
state. Note retrieval uses word overlap and returns up to the configured chat
source limit. A recap covers its cited sources, which may represent only part
of the discussion. Lecturer notes are refreshed on every question. The model
needs the configured Ollama service.

The chatbot's discussion sources are reviewed minutes and, when enabled,
automatic live transcript segments. Lecturers can write reviewed minutes
manually during class, or generate drafts from an available Teams transcript
after class using the workflow below. Lecture-slide chat retains its existing
source selection. C.L.I.P does not start Teams recording/transcription or stream Teams meeting audio.
The separately enabled [live lecturer microphone feature](live-transcription.md)
processes microphone chunks and shares automatic transcript text with the chatbot.

The publishing lecturer and admins can manage a session's notes. Students
must be enrolled on its course, accept terms, and use an active or ended
session. Notes remain available to those students after the session ends,
including students who missed the class. Prepared/cancelled sessions are
unavailable. Session deletion and the configured retention purge cascade to
the notes. Notes have no structured student identifiers. Automatic speech may nevertheless
contain personal references; lecturers must stop before private discussion and
remove such text. For reviewed minutes, publishers must remove personal
details and assessment solutions before confirming publication. The group
should approve the updated privacy wording before real-user deployment.

At most 1,400 entries of 2,000 characters can be held per session, including live speech. Edit existing
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

- 381 backend tests passed for transcript import/drafting, discussion, existing
  tutor behavior, API contract, authentication/consent and route auditing.
- 101 related retention, governance, privacy and student-review tests passed;
  two existing tests were skipped.
- 239 frontend unit tests passed; production build, browser typecheck and lint passed.
- Five Chromium browser tests passed for confirmed publication/edit/removal,
  ended-session time windows and full-source navigation, error recovery, retry
  identity, and transcript notice/draft/review/publication. Both the source
  navigation and draft-review screens passed WCAG A/AA automated checks.
- Migration downgrade and upgrade passed against a disposable PostgreSQL/pgvector
  database. The discussion/tutor/contract subset passed again after migration.

Browser responses and model output in these tests are deterministic fixtures.
They verify wiring and safety behavior, not real-model answer quality. Real
Ollama and Teams tenant acceptance remains necessary before demonstration.


## Teams transcript to draft minutes

1. The institution approves transcription, configures participant notification
   and any required consent, and enables Teams transcription for the organizer.
   The lecturer starts/stops transcription in Teams. Video recording is optional
   and is not needed by C.L.I.P.
2. End the C.L.I.P class and Teams transcription. Wait for Teams to make the
   transcript available. In **Discussion minutes**, refresh the transcript list.
   Choose the correct transcript by its creation time and confirm that participant
   notice and the institution's consent requirements have been met.
3. Click **Generate draft minutes**. C.L.I.P fetches the selected transcript from
   the session's linked meeting and asks the configured AI gateway to draft
   teaching points. This operation is lecturer-initiated; no webhook, unattended
   recording, background transcript subscription or live speech feed is installed.
4. Check each draft against **transcript evidence**. The evidence is an exact
   source quote, not proof that the AI summary is correct. Times are estimates
   based on transcript creation time plus cue offset. Correct timestamps, facts,
   personal details and assessment content before publishing.
5. **Review in publishing form** copies one draft into the existing editor with
   the sharing checkbox cleared. The lecturer must approve and publish it. Only
   then can students or their chatbot retrieve it. Published drafts can be
   corrected/removed through the normal notes controls.

A recurring meeting can have several transcripts. Only entries whose creation
time falls from 30 minutes before the class's scheduled start through its actual
end are offered. Older/later occurrences cannot be requested by changing the
transcript identifier. If the class timing/link is wrong, the import fails closed.
Separate transcription segments can be selected and drafted individually. Oversized imports fail explicitly; failed model calls do not publish partial
results. Draft summaries can omit discussion and always require review.

### Tenant setup (Shezin / institution administrator)

This feature is disabled by default. It uses the existing backend `CLIENT_ID`,
`CLIENT_SECRET` and the real directory `TENANT_ID`, plus
`TEAMS_TRANSCRIPTS_ENABLED=true`. The bot must be in the meeting and the class
must have its persisted Teams link/reference. Bot Framework meeting details
supply the organizer's verified Entra object ID and `msGraphResourceId`; the
browser cannot provide an arbitrary meeting, organizer or content URL.

The app registration needs Microsoft Graph **application** permission
`OnlineMeetingTranscript.Read.All`, tenant admin consent, and an application
access policy scoped to the approved meeting organizers. The tenant must allow
Graph API transcript access. Existing SSO scopes and the Bot Framework token
are insufficient: the backend obtains a separate Graph token for
`https://graph.microsoft.com/.default`. `TEAMS_BOT_TOKEN_TENANT=botframework.com`
may still be used by the bot, but it must not replace the real `TENANT_ID`.
No `OnlineMeetingRecording.Read.All` permission or recording download is used.
Do not add secrets to the frontend or repository.

A public webhook is not required for the lecturer-initiated import. Validate
with a scheduled test meeting in the actual tenant; availability, access policy
propagation and transcript processing delays can vary. Disabled, unavailable,
forbidden, throttled, malformed and oversized results have explicit error states.
Manual reviewed minutes remain available when import/model access fails.

### Processing, retention and safeguards

- Graph hosts and endpoints are fixed; redirects, supplied content URLs and
  pagination URLs are never followed. Lists that need pagination are refused.
- Raw transcript responses are bounded to 256 KB. Timed speech is bounded to
  80,000 characters, at most 12 segments of 7,000 characters. A long individual
  cue or excess total is refused rather than cut silently.
- WebVTT speaker labels, email addresses and URLs are removed before model
  drafting. This does not reliably remove every spoken name or personal detail.
  The model is told to omit those; human review remains mandatory.
- Transcripts are untrusted data. Instruction-bearing/unsafe text is refused,
  model output is parsed/checked, and evidence must be an exact source quote.
  Lexical grounding is a coarse check, not an accuracy guarantee.
- Drafting uses the existing AI gateway at background priority, without holding
  a database connection while Graph/model calls run. Two imports may run at a
  time, at most one per staff account per minute. Generation has a four-minute
  deadline; disconnect/cancel stops further work and releases the import slot.
- C.L.I.P stores no raw VTT, transcript evidence or unpublished draft in its
  database, application logs, browser local/session storage or backups. Review
  evidence/drafts live in request/browser memory and disappear on leaving the
  page. Only approved note text/timestamps are persisted, with the existing
  session retention/purge cascade. The configured AI service processes transcript
  text; deploy it within the institution's approved processing environment.
- Microsoft 365 retains its own transcript and any recording under its policies.
  Deleting C.L.I.P notes does not erase those originals. Recording/transcription
  consent is separate from local camera/microphone indicator consent. The
  lecturer's checkbox attests institutional notice/consent; it does not obtain
  individual participant agreement. Configure and verify that in Teams.

Microsoft reference documentation:
- [Meeting details and Graph resource ID](https://learn.microsoft.com/en-us/microsoftteams/platform/apps-in-teams-meetings/meeting-apps-apis)
- [List meeting transcripts and permissions](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts?view=graph-rest-1.0)
- [Get transcript content](https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0)
- [Transcription settings](https://learn.microsoft.com/en-us/microsoftteams/meeting-transcription-captions)
- [Recording/transcription consent](https://learn.microsoft.com/en-gb/microsoftteams/recording-transcription-overview)
