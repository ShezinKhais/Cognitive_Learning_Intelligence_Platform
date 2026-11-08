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
  pop-up that opens C.L.I.P, and so does everyone in the meeting chat when the
  class starts. Joins and leaves are kept as roster events, by Teams identity
  only.
- **Lecturer updates.** Pop-ups only the lecturer sees: an alert, how many
  answered a checkpoint, and engagement low across the class. Counts and
  course content only, never a name, at most one a minute (engagement every
  five), and **Mute** on the update page (`/lecturer/teams/update`) stops them
  for the rest of the class.
- **Students.** The checkpoint pop-up says how long is left. When the class
  ends, the meeting chat gets a card linking to the review. The lecturer's
  update page shows how many of the course's students have opened C.L.I.P in
  Teams, since only they get checkpoint pop-ups.

Participant events need the bot subscribed to them: in the Developer Portal,
the bot's **Meeting event subscriptions**, tick **Participant join** and
**Participant leave** beside meeting start and end. The manifest is unchanged:
its permissions already cover all of this.

## Not done yet

- **Checking the meeting organizer when a meeting is linked.** Nothing yet
  checks that the lecturer organises the meeting. It needs the bot's
  outbound calls to Teams, which need the tenant.
- **Replies from the bot.** The bot does not reply to messages. Replying
  needs outbound calls to Teams, which need the tenant.
- **Meeting chat and details tabs.** The meeting tab is offered only as the
  side panel. The chat and details tabs would open the same student panel,
  so they are left out until a surface for them exists.
