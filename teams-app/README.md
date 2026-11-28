# The Teams app

C.L.I.P runs inside a Teams meeting as a side panel, with personal tabs for
students, lecturers and administrators, and a bot that hears when the
meeting starts and ends. Everything here also works without Teams, through
the mock adapter, which is how it runs until IT allows custom app uploads.

## What is here

| File | What it is |
| --- | --- |
| `manifest.json` | The app manifest, with `${{NAME}}` placeholders for the ids and the base URL |
| `color.png`, `outline.png` | The 192 and 32 pixel icons Teams requires |
| `.env.example` | The values the placeholders need |

The package is built from these by `backend/scripts/package_teams_app.py`.

## How a meeting reaches C.L.I.P

1. A lecturer links a session to a meeting:
   `PUT /api/v1/meetings/{meeting_id}` with `{"session_id": ...}`. The
   session then reports `teams_meeting_id`.
2. The meeting starts. Teams posts a `meetingStart` event to the bot at
   `POST /api/v1/teams/messages`. The bot checks the Bot Framework token,
   finds the linked session, and starts it as its lecturer.
3. The meeting ends. The bot ends the session, or cancels it if it never
   started.

A start the class cannot take, such as one with nothing staged, is logged
and acknowledged, since Teams would only retry it. The lecturer can still
start the class from the dashboard.

The mock adapter is `POST /api/v1/meetings/events`, with `started` or
`ended` and the meeting id. It drives the same service as the bot. It can
also create the session for a meeting that starts unlinked, when the event
names the course. Teams may deliver an event twice, and either path returns
the session unchanged the second time.

Which meeting holds which session is stored in the database
(`teams_meeting_link`, through BBIS's `DatabaseMeetingDirectory`), so links
survive a restart.

## Sharing the class to the meeting stage

In a meeting, the lecturer's panel has a **Share to the meeting stage**
button while the class is live. It asks Teams to open the same meeting page
the side panel uses, large, for everyone. The link carries only the session
id. Teams opens it in each person's own client, so each person reaches C.L.I.P
signed in as themselves and sees only what their own role and enrolment
allow. Nothing about a student is shared with the others.

It needs the manifest's `meetingStage` context and the delegated
`MeetingStage.Write.Chat` permission, both added here. The button is hidden
outside Teams, and says so when a meeting does not allow sharing. Real
stage sharing only works in a real Teams meeting.

### Trying it without Teams

The mock adapter can stand in for the stage, so the student's stage view can
be checked locally. With the backend running (the Docker demo on port 8088
will do), in `frontend/.env.local` set the switches below (the live class is
off by default in the dev server, and the student panel stays on "Waiting for
your lecturer" without it) and run `npm run dev`:

```
VITE_TEAMS_MOCK_ENABLED=true
VITE_LIVE_SESSIONS_ENABLED=true
VITE_SOCRATIC_CHAT_ENABLED=true
VITE_MATERIAL_PIPELINE_ENABLED=true
CLIP_BACKEND_URL=http://127.0.0.1:8088
```

The student's side panel then rests as a small paperclip with their checkpoint
count, and opens by itself when the lecturer sends a checkpoint.

1. Lecturer window, a simulated meeting: open
   `http://localhost:5173/teams/meeting?teamsMock=1&meetingId=test-meeting`,
   signed in as the lecturer, with a live session linked to that meeting.
   The **Share to the meeting stage** button shows; clicking it opens the
   stage link in a new window.
2. Student window (another browser or incognito, signed in as a student):
   open `http://localhost:5173/teams/meeting?teamsMock=1&meetingId=test-meeting&frame=content`.
   This is the stage frame: the live class, full width, with the checkpoint.

The mock is never available in a production build, so the Docker demo's web
image on 8088 cannot do this; use the Vite dev server.

## Running it without Teams

With the backend and frontend running:

```bash
cd backend
python scripts/mock_meeting.py link  my-meeting <session_id>
python scripts/mock_meeting.py start my-meeting
python scripts/mock_meeting.py end   my-meeting
```

`start` with `--course CODE` creates the session for an unlinked meeting.
The script signs a development token with the local secret, so it only
works against a backend sharing the same `.env`, and never in production.

## Running it in Teams

For the team's tenant (CLIP736), follow `docs/teams-tenant-setup.md`: it runs
the demo stack in production mode behind a tunnel, with Teams single sign-on,
and covers the accounts, the Azure registration and the upload. The steps
below are the short version for a development server.

This needs the "Upload custom apps" permission on the tenant.

1. **Tunnel.** Teams loads the tabs and posts to the bot over HTTPS, so
   expose the frontend dev server. Vite proxies `/api` and `/ws` to the
   backend, so one tunnel covers the tabs, the API, the socket and the bot:

   ```bash
   devtunnel host -p 5173 --allow-anonymous
   ```

2. **Registrations.** Create the Teams app and the bot's Entra app
   registration. Set the bot's messaging endpoint to
   `<tunnel URL>/api/v1/teams/messages`. Put the bot's app id, secret and
   tenant in `backend/.env` as `CLIENT_ID`, `CLIENT_SECRET` and `TENANT_ID`.
   With all three set, `/health` reports `teams_configured: true` and the
   bot endpoint accepts activities. Without them it answers 503.

3. **Package.** Copy `.env.example` to `.env`, fill it in, and build:

   ```bash
   cd backend
   python scripts/package_teams_app.py
   ```

   This writes `teams-app/build/clip.zip`, which git ignores. It refuses a
   package Teams would reject, and `--check` checks the manifest and icons
   alone, as CI does.

4. **Upload.** In Teams, Apps, Manage your apps, Upload an app. Add it to a
   meeting, and it is installed in the meeting chat, which is what lets the
   bot hear the meeting start and end. The manifest asks for the
   `OnlineMeeting.ReadBasic.Chat` permission for this.


## In the meeting

With `TEAMS_NOTIFICATIONS_ENABLED`, the bot does more than start and end a
linked class (`backend/app/services/teams_meeting_flow.py` and
`teams_notifications.py`):

- **A meeting with nothing linked.** When it starts, the bot reads the
  meeting's title and organiser from Teams. A title naming one course the
  organiser teaches ("CSIT321 Week 5") starts that class, and a card in the
  meeting chat says so, with a **Not a class** button that ends it. Any other
  title gets an **Is this a class?** card listing the organiser's courses.
  Only the organiser's press counts. The organiser must have opened C.L.I.P
  in Teams once, so their Teams account is linked.
- **People joining.** Whoever joins a meeting whose class is running gets a
  pop-up that opens C.L.I.P (one who joins late is told how many checkpoints
  they missed), and so does everyone in the meeting chat when the
  class starts. Joins and leaves are kept as roster events, by Teams identity
  only.
- **Lecturer updates.** Pop-ups only the lecturer sees: an alert, how many
  answered a checkpoint (and, for multiple choice, how many were right and the
  most common wrong answer), engagement low across the class, and a summary when
  the class ends (who came, the share of answers given, the hardest topic). Counts and
  course content only, never a name, at most one a minute (engagement every
  five), and **Mute** on the update page (`/lecturer/teams/update`) stops them
  for the rest of the class.
- **Students.** A checkpoint arrives as a pop-up over the meeting
  (480 by 520 pixels), never as a tab: it shows the question only, the student
  answers in it, and **Back to the lecture** closes it. The meeting stays on
  screen throughout. If the tenant has not granted the meeting notification
  permission, the meeting chat gets a card instead, and its **Answer now**
  opens the same pop-up rather than the app's tab, which would minimise the
  meeting. The checkpoint pop-up says how long is left, and ten seconds before it
  closes, students who have not answered get a last call
  (`TEAMS_LAST_CALL_ENABLED`, on by default; only for windows of 25 seconds or
  more). When the class
  ends, the meeting chat gets a card linking to the review. The lecturer's
  update page shows how many of the course's students have opened C.L.I.P in
  Teams, since only they get checkpoint pop-ups.

Participant events need the bot subscribed to them: in the Developer Portal,
the bot's **Meeting event subscriptions**, tick **Participant join** and
**Participant leave** beside meeting start and end. The manifest is unchanged:
its permissions already cover all of this.

## C.L.I.P in every lecturer's meeting

Without anything set up, a lecturer adds C.L.I.P to each meeting from Apps.
After that nothing else is needed: the bot knows the meeting from its chat,
the organiser joining a meeting with no class gets a pop-up asking whether
it is one, and the meeting's link can still be pasted on the website. A
short invitation link (`teams.microsoft.com/meet/<number>`) is resolved by
Microsoft Graph for the signed-in meeting organiser. The app uses the meeting
number and discards the passcode. Short links require `OnlineMeetings.Read.All`
(application permission) and a Teams application access policy granting
C.L.I.P access for the organiser. With those unavailable, link using C.L.I.P
inside Teams or paste the full invitation link. The normal meeting
installation and organiser checks still apply.

`TEAMS_AUTO_JOIN_ENABLED=true` in the demo environment file enables automatic
installation for qualifying classes. Recreate the Compose backend with
`docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d backend`
after changing it. Every
`TEAMS_AUTO_JOIN_INTERVAL_SECONDS` (300 by default) the backend reads the next
`TEAMS_AUTO_JOIN_DAYS` (14) of each linked lecturer's calendar and, for each
Teams meeting they organise whose title names one of their course codes, puts
C.L.I.P and its tab into the meeting and sends them a Teams activity notice
saying which class it will run. The notice opens the C.L.I.P tab in that
meeting. Meetings without a course code in the title (staff meetings,
one-to-ones) are never touched, and students' calendars are never read.

Progress is stored per meeting chat in `teams_auto_join`, so a restart
resumes a half-finished install. Once a meeting's tab is pinned it is never
touched again: a lecturer who removes C.L.I.P from a class meeting keeps it
removed.

It needs these Microsoft Graph **application** permissions on the C.L.I.P app
registration, with admin consent, granted by the tenant's administrator:

| Permission | For |
|---|---|
| `Calendars.Read` | Finding the Teams meetings a lecturer organises |
| `TeamsAppInstallation.ReadWriteSelfForChat.All` | Adding C.L.I.P to a meeting's chat |
| `TeamsTab.ReadWriteSelfForChat.All` | Pinning the C.L.I.P tab in the meeting |
| `TeamsActivity.Send` | The notice to the lecturer |
| `AppCatalog.Read.All` | Only when `TEAMS_CATALOG_APP_ID` is not set |

`Calendars.Read` covers every mailbox in the tenant unless an Exchange
application access policy limits it to a lecturers' group; do that outside a
test tenant. `TEAMS_CATALOG_APP_ID` is the app's id in the organisation's
catalog (Teams admin center, Manage apps, C.L.I.P, App ID), not the manifest
id. The activity notice needs the manifest's `activities` entry, so upload
`clip.zip` again after this version (0.3.8).

The sweep reuses an existing C.L.I.P tab it can identify and serializes
tab creation across sweeps. If the meeting already has duplicate tabs,
the organiser can remove the extra tab in Teams. The sweep does not remove
meeting tabs. For a fresh meeting that still lacks C.L.I.P after the next
sweep, check the course code in the title, the organiser's linked account,
and the tenant app permissions, or add C.L.I.P from the meeting's Apps menu.

## Not done yet

- **Checking the meeting organizer when a meeting is linked.** Nothing yet
  checks that the lecturer organises the meeting. It needs the bot's
  outbound calls to Teams, which need the tenant.
- **Replies from the bot.** The bot does not reply to messages. Replying
  needs outbound calls to Teams, which need the tenant.
- **Meeting chat and details tabs.** The meeting tab is offered only as the
  side panel. The chat and details tabs would open the same student panel,
  so they are left out until a surface for them exists.
