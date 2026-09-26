# Cyber 1 Phase 4 Teams Security Review

## C.L.I.P. - Teams Permissions, Identities, Consent and Meeting Access

Role: Cyber 1  
Phase: Phase 4 - Microsoft Teams integration  
Reviewed against: PR #114 (General CS, `Shezin-Phase-4-Meetings`), stacked on #113  
Tests: `backend/tests/test_teams_security.py`, `backend/tests/test_live_consent.py`

---

## 1. Scope

PHASES.md asks Cyber 1 in Phase 4 to review Teams permissions, validate mapped
identities, apply least privilege, enforce consent across Teams surfaces and
test unauthorised meeting access.

The Teams surfaces reviewed:

| Surface | Where | How it authenticates |
|---|---|---|
| Bot messaging endpoint | `POST /api/v1/teams/messages` | Bot Framework JWT |
| Meeting routes (mock adapter) | `PUT /api/v1/meetings/{id}`, `POST /api/v1/meetings/events` | C.L.I.P. bearer token, terms consent, lecturer or admin |
| Live-session socket (web and Teams in-meeting panel) | `/ws/session` | C.L.I.P. bearer token in the `auth` event |
| Teams app manifest | `teams-app/manifest.json` | n/a: what every installing tenant grants |

Nothing here needs a Teams tenant. Every finding is exercised by tests using a
locally generated signing key in place of Bot Framework's.

---

## 2. Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | The bot acted on activities from any Bot Framework channel and any tenant | High | Fixed |
| F2 | The live-session socket admitted users without terms consent | High | Fixed |
| F3 | Engagement monitoring ignored engagement, camera and microphone consent, and a withdrawal did not stop collection | High | Fixed |
| F4 | The bot acted for a meeting's lecturer without checking their account still allowed it | Medium | Fixed |
| F5 | The manifest asked for permissions the app does not use | Medium | Fixed |
| R1-R5 | Residual risks owned by other workstreams or gated on Teams access | - | Documented, section 4 |

### F1 - The bot acted on any channel and any tenant (High)

**What was wrong.** `BotAuthenticator.verify` checked the token's signature,
issuer, audience, expiry and `serviceUrl`, which is everything Bot Framework
signs. The activity body is not signed. Two gaps followed:

- *Other channels.* Every Azure bot has the Web Chat channel on from creation,
  and Direct Line can be enabled beside it. Bot Framework signs what those
  channels deliver as validly as a Teams activity, but with a body the client
  wrote. A `meetingEnd` event typed into Web Chat, naming a linked meeting's id,
  would have ended that class. Meeting ids are visible to every participant
  through TeamsJS `getContext()`.
- *Other tenants.* Anyone can sideload a manifest carrying this bot's id into
  their own Microsoft 365 tenant, and Teams then delivers that tenant's
  activities to this endpoint with valid tokens.

The key endorsement check that Bot Framework's own SDKs perform (the signing
key must be endorsed for the activity's `channelId`) was also missing.

**Fix** (`app/services/teams_bot.py`, `app/api/v1/teams.py`):

1. The signing key's published `endorsements` are kept. PyJWK drops them, so
   `_BotFrameworkKeys` reads them from the raw key set in `fetch_data()`, the
   documented override point. A key not endorsed for the activity's channel, or
   absent from the published set, is refused with 401.
2. `BotAuthenticator.authorize` refuses with 403 any activity whose `channelId`
   is not `msteams`, or whose `channelData.tenant.id` is not this deployment's
   `TENANT_ID` (compared case-insensitively). A missing or malformed tenant is
   refused.
3. Rejections log `security_event=BOT_TOKEN_REJECTED` or
   `BOT_ACTIVITY_REJECTED`. Attacker-supplied values are logged with `repr` so
   they cannot forge log lines.

`TeamsActivity` gains an optional `channelId` field. The contract change is
additive and `openapi.json` is regenerated.

### F2 - The socket admitted users without terms consent (High)

**What was wrong.** Every REST route requires terms consent (`require_consents`),
but `/ws/session` only checked the token and session membership. The socket is
what the Teams in-meeting panel uses, so a user who had never accepted, or had
withdrawn, the terms could sit in a live class.

**Fix** (`app/api/v1/ws.py`, `app/realtime/classroom.py`, `app/realtime/hub.py`,
`app/api/v1/identity.py`):

- Joining a session needs terms consent. Consent is checked before membership,
  so a refused user learns nothing about the session. A refusal closes with
  4003 and the reason `consent required`.
- Withdrawing terms consent through `POST /auth/consent` closes the user's
  session sockets straight away (4003, `consent withdrawn`). The user's own
  channel, used for upload progress, is left open: it only carries the user's
  own events from actions that already required consent.
- If the withdrawal lands while a socket is still being admitted, a re-check
  after the join closes that socket too.

4003 is the contract's existing close code, so no client needs to change.

### F3 - Engagement monitoring ignored consent (High)

**What was wrong.** `ConsentType` is granular ("declining one must never block
the others"), and the consent route promises that revoking camera or microphone
consent "must stop collection immediately". The live classroom never read
consent. Every student shown a question was scored, reported to the lecturer and
eligible for attention prompts, and client `signal.attention` gaze and face data
was kept regardless of camera consent.

**Fix** (`app/realtime/consent.py`, new; the classroom, socket, attention and
consent route):

| Consent | Without it |
|---|---|
| `terms` | Cannot be in the class (F2) |
| `engagement_monitoring` | Still sees questions, answers and gets feedback. No engagement score is computed or reported, `signal.attention` is refused with error `CONSENT_REQUIRED`, and no attention prompt is sent |
| `camera` | Gaze and face presence are dropped from any signal before it is kept |
| `microphone` | Voice activity is dropped from any signal before it is kept |

Dropped signal parts are left out rather than scored as zero, and engagement
scoring renormalises over the rest, so declining never lowers a score. This is
tested.

The classroom holds a `ConsentRegistry`, injected like its settings. It assumes
nobody consents unless told otherwise, so nothing is monitored on an assumption.
The socket fills it from the consent store when a user joins. The registry is
versioned, so a read that a withdrawal overtook while the socket awaited the
database cannot overwrite it.

**Withdrawals apply at once and grants at the next join.** `POST /auth/consent`
applies a withdrawal to every running class immediately:

- The student's engagement evidence and score are dropped.
- Any prompt waiting on them is taken down, and no outcome is recorded for it.
- Camera or microphone parts of their stored signal are removed.

A grant is not applied mid-request. The `@audit_action` decorator writes its
audit row in the same transaction after the handler returns, so committing
early to apply a grant would break the guarantee that a consent change and its
audit record are stored together. Instead a grant is read back from the store
at the student's next join. Narrowing early is always safe; widening early is
not.

### F4 - The bot acted for any account (Medium)

**What was wrong.** For a meeting event, `meeting_owner` built a lecturer
`Principal` from the session's `instructor_id` without looking at the account.
A lecturer who had been disabled, was no longer staff, or had withdrawn terms
consent would still have had their sessions started and ended by Teams. The
bot held more authority than the person it acted for.

**Fix** (`app/services/session_lifecycle.py`, `app/auth/service.py`):
`meeting_owner` now resolves the account as it stands now:

- It must be active.
- It must be a lecturer or admin.
- It must hold terms consent.

The bot then acts as that account, with lecturer rights even when the
account is an admin's: running one session needs only ownership, which
matches by user id. Otherwise it logs
`security_event=TEAMS_ACT_AS_REFUSED` and acknowledges the activity without
acting, since a retry by Teams could not fix it.

`active_user` and `granted_consents` are now shared by the bearer-token path,
`require_consents`, the socket and the bot, so there is one definition of "the
account as it stands now" instead of several.

### F5 - The manifest asked for more than the app uses (Medium)

Every permission in the manifest is granted in every tenant that installs the
app.

| Entry | Decision | Why |
|---|---|---|
| `permissions: messageTeamMembers` | Removed | Nothing sends proactive direct messages. In-meeting notifications use the RSC permission below |
| `devicePermissions: ["media"]` | Removed | Nothing uses camera or microphone until Phase 6 (optional). Re-add it with AI 2's Phase 6 permission flow, privacy indicator and one-click disable |
| Bot scope `personal` | Removed | The bot does nothing in a personal chat, so the scope only let any user in the tenant message it. Meeting events need `groupChat`, which stays |
| `permissions: identity` | Kept | Needed for the user's Teams identity |
| RSC `OnlineMeeting.ReadBasic.Chat` | Kept | Needed for the meeting start and end events the bot acts on |
| RSC `OnlineMeetingParticipant.Read.Chat` | Kept | Needed for BBIS's participant and roster sync |
| RSC `OnlineMeetingNotification.Send.Chat` | Kept | Needed for AI 2's in-meeting notification card |
| `validDomains: [BASE_DOMAIN]` | Kept | Only the deployment's own domain |

`test_the_manifest_asks_only_for_what_the_app_uses` pins this list, so a new
permission fails the build until it has been reviewed and the test updated.

Static tabs (student, lecturer, admin) are visible to every user in personal
scope, and Teams cannot hide them by role. That is not an access-control gap:
each page is gated by the frontend's `RoleGate` and every API it calls
enforces the role on the server.

---

## 3. Unauthorised Meeting Access: Tests

Existing tests in #114 already cover: another lecturer linking or driving a
session, a student sending meeting events, taking a meeting that holds another
lecturer's session, linking a finished session, and bad, expired, foreign or
missing bot tokens. This review adds:

| Test | Expects |
|---|---|
| Forged `meetingEnd` from Web Chat, Direct Line or the Emulator, with a key endorsed for them | 403, class still active |
| Activity naming no channel | 401, class still active |
| Activity from another tenant | 403, class still active |
| Activity with no or a malformed tenant (5 shapes) | 403, class still active |
| Tenant differing only in case | Accepted |
| Key not endorsed for Teams | 401 |
| Key not in Bot Framework's published set | 401 |
| Key with no endorsements | Judged on its other claims, as Bot Framework's SDKs do |
| Endorsements read from the published key set | Kept per key |
| Bot, for a lecturer who withdrew terms | Acknowledged, class not started |
| Bot, for a disabled account or one no longer staff | Acknowledged, class not started |
| Bot, for an admin's class | Acts with lecturer rights only |
| Meeting routes, not signed in | 401 |
| Meeting routes, lecturer without terms consent | 403 `CONSENT_REQUIRED` |
| Student without terms consent joins their own class | 4003 `consent required` |
| Student withdraws terms mid-class | Socket closed 4003 |
| Student without monitoring consent sends `signal.attention` | Error `CONSENT_REQUIRED` |
| Student who declined monitoring | Answers accepted; no score, no prompt |
| Declining the camera | Score rests on the same evidence as sending nothing |
| Withdrawing monitoring mid-class | Score dropped, waiting prompt taken down, nothing recorded, no further prompts |
| Withdrawing the camera mid-class | Stored gaze and face dropped |
| Withdrawing terms | Only that user's class sockets closed |
| A stale consent read overtaken by a withdrawal | The withdrawal holds |
| Monitoring consent gone at the next join | Kept score no longer reported |
| Consent route | Withdrawal applied at once, grant at the next join |

Each fix was also checked against its tests: every guard was disabled in turn
(22 mutations) and its test failed each time.

---

## 4. Residual Risks and Requirements for Other Workstreams

**R1 - Meeting-link squatting (General CS, BBIS; needs Teams access).**
`PUT /meetings/{id}` trusts the meeting id a lecturer supplies. A lecturer could
link another lecturer's meeting to their own session before its owner does, and
that meeting would then start and end the wrong class. The owner's own link is
refused (409) until an admin relinks. The fix is to verify the meeting's
organiser before linking, either through the bot's meeting context
(`TeamsInfo.get_meeting_info`) or Graph `onlineMeetings`, once the tenant exists.

**R2 - Teams identity mapping (BBIS).** When Teams users are mapped to C.L.I.P.
users:

- Key the mapping on the tenant id and Entra object id (`tid`, `oid`), never on
  UPN, email or display name.
- Only accept mappings from this deployment's tenant (see F1).
- Never trust an identity the client reports through TeamsJS `getContext()`.
  It is not authentication. A Teams tab signs in with a C.L.I.P. token, or with
  a Teams SSO token validated on the server (issuer, audience, `tid`).
- Keep the mapping one to one, and refuse a second C.L.I.P. user for the same
  `oid`.

**R3 - Teams SSO (AI 2, Cyber 2).** If tabs adopt Teams SSO,
`webApplicationInfo.resource` must change from the RSC placeholder to
`api://<BASE_DOMAIN>/<BOT_ID>`, and the token must be validated on the server
as in R2. It is unchanged until then.

**R4 - Close reason in the student panel (AI 2).** The student panel reads a
4003 after connecting as "the session has ended". A socket closed for
withdrawn consent carries the reason `consent withdrawn` and could say so. The
contract is unchanged; the reason is available to use.

**R5 - Course ownership (BBIS).** The data model has no course-to-lecturer
assignment, so any lecturer may create a session for any course. This predates
Phase 4 and applies equally to the meeting route that creates a session.
Membership is still enforced for students. The fix needs a data-model change.

---

## 5. Verification

- `ruff check .` and `ruff format --check .` pass.
- The full `pytest` suite passes against Postgres 16 with pgvector, as CI runs it.
- `python scripts/export_contract.py --check` passes.
- Existing tests changed only where a test's user now needs consent a real user
  would hold. No assertion was weakened.

---

## 6. Overall Result

Before the fixes, a message typed into Web Chat could end a live class, a Teams
install in another organisation could reach the bot, a user without consent
could sit in a class through the Teams panel, and engagement monitoring ignored
the consent the platform promises to respect.

After the fixes:

- The bot acts only on endorsed Teams activities from this tenant, and only for
  a lecturer who could act themselves.
- Every live-class surface enforces terms consent.
- Engagement, camera and microphone consent each govern exactly what they
  describe, and withdrawing any of them takes effect at once.
- The manifest asks for no more than the app uses.
