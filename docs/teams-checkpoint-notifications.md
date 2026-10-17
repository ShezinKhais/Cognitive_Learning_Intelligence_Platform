# Teams checkpoint notifications — issue #51

When a question is committed and delivered, the classroom enqueues a best-effort
Teams notification. Both manual delivery and the automatic question cycle use
this path. WebSocket delivery and question-close timers proceed immediately.

The bot posts an Adaptive Card into the linked meeting chat and sends targeted
meeting-stage notifications to active C.L.I.P students enrolled on the session's
course whose verified Entra identities appear in that chat's Teams roster.
Students do not need to keep the panel open to be selected. Unknown identities,
unmapped students and staff are excluded from targeted notifications. The
generic card is visible to the meeting chat; it contains course/session context
and a link, with no answers, scores or student names.

The server builds the card in Python. Its button uses the installed app's
`clip.meeting` tab deep link with the meeting chat context. The targeted payload
uses a URL dialog, as required by the Teams API; it opens the student page,
which now accepts Teams `task` as well as `sidePanel` frame contexts. Existing
login, student-role, consent and assigned-session checks still apply.

## Deployment

1. Apply migrations (`alembic upgrade head`). The new nullable columns on
   `teams_meeting_link` retain the connector service URL, conversation ID and
   tenant ID across restarts. No bearer token or secret is stored in them.
2. Configure `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID` for a single-tenant Azure
   Bot with the Teams channel. The token scope is `https://api.botframework.com/.default`.
3. Set `TEAMS_APP_ID` to the manifest's top-level app ID, and
   `TEAMS_APP_BASE_URL` to the HTTPS frontend origin included in `validDomains`.
   Set `TEAMS_NOTIFICATIONS_ENABLED=true`. Invalid/missing configuration fails
   startup when enabled; the default is off for local/mock deployments.
4. Install/configure the C.L.I.P meeting tab and bot. Approve the existing
   `OnlineMeeting.ReadBasic.Chat`, `OnlineMeetingParticipant.Read.Chat` and
   `OnlineMeetingNotification.Send.Chat` permissions in the tenant.
5. Link the session to the meeting and establish student identity mappings
   through the existing validated Entra login flow. A verified meeting start/end
   activity records the conversation reference; an already-running meeting
   needs another authenticated meeting event before it can notify.

Only the public-cloud `https://smba.trafficmanager.net/` connector is supported.
Other service hosts, arbitrary URLs, non-HTTPS destinations and redirects are
refused. References are saved only after Bot Framework token, channel and tenant
validation, and only against an existing meeting link.

## Failure behavior and limits

There are at most 100 pending tasks and two active sends per process. Each send
has a 12-second overall budget, shortened to the checkpoint's remaining time,
and four-second HTTP timeouts. Before sending, the database must still show an
active, unpaused session and an unclosed, unexpired delivery. Roster pagination
is capped at 10 pages of 100 members. Targeted requests contain at most 50 Teams
`29:` IDs; Entra IDs are used only for matching, never sent as recipients.

Missing links, references or eligible recipients skip the send. Failures are
logged without response bodies or secrets; 401 invalidates the cached bot token
for the next notification. A 207 is logged as partial delivery. There is no
automatic message retry, to avoid duplicate announcements. Tasks are cancelled
at shutdown and are not a durable outbox; a restart may lose a pending notice.
The next checkpoint creates a new attempt. Cloud notification arrival cannot be
guaranteed before a short question expires.

## Verification

```sh
cd backend
pytest -q tests/test_teams_notifications.py tests/test_teams_bot.py tests/test_classroom.py
ruff check .
ruff format --check .
python scripts/export_contract.py --check
```

Tests use a mock HTTP connector and test credentials. They cover token reuse,
host restrictions, reference persistence calls, recipient filtering and batching,
expired tasks, bounded queue/shutdown, sanitized failures and the delivery hook.
Database-backed reference/recipient tests run in CI with PostgreSQL.

Real-tenant validation remains required: start a linked meeting with an enrolled
test student (panel closed), deliver a checkpoint, verify one chat card and a
targeted notification, follow both links, answer, and confirm staff/unknown
accounts receive no targeted popup. Repeat with permission denied, bot removed,
expired checkpoint, reconnect and a process restart. Tenant approval is an
external prerequisite; automated tests do not prove tenant delivery.

API references:
- [Bot Connector authentication](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication)
- [Targeted in-meeting notifications](https://learn.microsoft.com/en-us/microsoftteams/platform/apps-in-teams-meetings/in-meeting-notification-for-meeting)
- [Meeting side-panel deep links](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/deep-link-application)
