# Running C.L.I.P in the team's Teams tenant

Tenant: `CLIP736.onmicrosoft.com`. C.L.I.P runs on one laptop in the Docker
demo stack, in production mode, and Teams reaches it through a dev tunnel.

## What each person sees

| Where | Who | What opens |
|---|---|---|
| Teams, **My Learning** tab | Students | The student dashboard, inside Teams |
| Teams, meeting side panel | Students | Their class panel: checkpoints, tutor, indicators |
| Teams, meeting side panel | Lecturer | The compact class controls, counts and alerts |
| Teams, pop-ups in a meeting | Students, lecturer | A new checkpoint (students), an alert (lecturer) |
| Teams, **Lecturer** tab | Lecturer | A launcher that opens the lecturer dashboard website |
| Teams, **Admin** tab | Admin | A launcher that opens the admin website |
| Browser | Lecturer, admin | The full websites, signed in with email and password |

Inside Teams nobody types a password: single sign-on uses the Microsoft
account Teams is signed in with. The server checks the Entra token, then
finds the C.L.I.P account by that account's sign-in name. On first use it
links the two by the token's tenant and object IDs; that link is also how
pop-ups find the right people in a meeting.

## Accounts

| Microsoft account | C.L.I.P role | Signs in |
|---|---|---|
| `admin2@CLIP736.onmicrosoft.com` | admin | Website (password), Teams |
| `lecturer@CLIP736.onmicrosoft.com` | lecturer | Website (password), Teams |
| `student1@` to `student4@` | students on CSIT321 | Teams only |

`backend/scripts/provision_teams_accounts.py` creates them (step 6). An
account must exist in C.L.I.P before it can sign in. A Microsoft account in
the tenant with no C.L.I.P account is told to ask the administrator.

## 1. Tenant settings (Teams admin, signed in as a global admin)

In the Teams admin center:

1. **Teams apps, Manage apps, Org-wide app settings:** allow custom apps.
2. **Teams apps, Setup policies, Global:** turn on **Upload custom apps**.
3. **Meetings, Meeting policies:** apps in meetings allowed (the default).

A policy change can take a few hours to reach every account.

## 2. Tunnel (one persistent address)

The address goes into the app registration, so it has to stay the same.
Create the tunnel once:

```bash
devtunnel user login
devtunnel create clip736 --allow-anonymous
devtunnel port create clip736 -p 8088
```

Then run `devtunnel host clip736` each time. Note the HTTPS address, for
example `https://abcd1234-8088.uks1.devtunnels.ms`. It is `BASE_URL` below.
Port 8088 is the demo stack's web server, which serves the pages, the API,
the socket and the bot on one origin.

## 3. Azure Bot and app registration (Azure portal, global admin)

One Entra app registration is both the bot and the single sign-on app.

1. Create an **Azure Bot**: type **Single Tenant**, pricing **F0**, and
   create a new Microsoft App ID.
2. Bot, **Configuration**: messaging endpoint `<BASE_URL>/api/v1/teams/messages`.
3. Bot, **Channels**: add **Microsoft Teams**.
4. Open the app registration (Configuration, **Manage Password**), and note:
   - **Application (client) ID**: `CLIENT_ID` and `BOT_ID`
   - **Directory (tenant) ID**: `TENANT_ID`
5. **Certificates and secrets:** add a client secret. Copy its value at once.
   It is `CLIENT_SECRET`.
6. **Expose an API:**
   - Set the Application ID URI to `api://<tunnel host>/<CLIENT_ID>`, for
     example `api://abcd1234-8088.uks1.devtunnels.ms/5b0e...`. The host
     only: no `https://` and no path.
   - Add a scope `access_as_user`, consent by admins and users.
   - Add both Teams clients under **Authorized client applications**, with
     that scope ticked:
     - `1fec8e78-bce4-4aaf-ab1b-5451cc387264` (Teams desktop and mobile)
     - `5e3ce6c0-2b1f-4285-8d4b-75ee78787346` (Teams on the web)
7. **API permissions:** Microsoft Graph delegated `openid`, `profile`,
   `email` and `offline_access`. Then select **Grant admin consent**.
8. **Manifest** (optional): `"accessTokenAcceptedVersion": 2`. Both token
   versions are accepted.

## 4. Settings

`deploy/demo.env` (git-ignored) already has a generated secret key and
database password, `CLIP_ENV=production`, the camera indicators on, and a
generated `TEAMS_APP_ID`. Fill in:

```
CLIENT_ID=<application (client) ID>
CLIENT_SECRET=<client secret value>
TENANT_ID=<directory (tenant) ID>
TEAMS_APP_BASE_URL=<BASE_URL>
TEAMS_NOTIFICATIONS_ENABLED=true
```

`teams-app/.env` (git-ignored) has the same `TEAMS_APP_ID`. Fill in
`BOT_ID` (the same as `CLIENT_ID`) and `BASE_URL`.

## 5. Start the stack

From the repository root, with Docker running:

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
```

The first build downloads the base images. Production mode refuses to start
with a weak key or password, or with Teams half configured, and the log says
which. `<BASE_URL>/api/v1/health` should report `teams_configured: true`.
Ollama on the host gives generated questions and the tutor. Without it, a
class runs from questions already approved.

## 6. Create the accounts

```bash
docker compose -p clip-demo -f docker-compose.demo.yml exec -T backend python - < backend/scripts/provision_teams_accounts.py
```

The script prints the lecturer's and admin's website passwords once. Hand
each one over in person. Running it again changes nothing. To issue new
staff passwords, add `--reset-passwords` after the `-`.

## 7. Build and upload the app

```bash
cd backend
python scripts/package_teams_app.py
```

This writes `teams-app/build/clip.zip`, or says what is missing. In the
Teams admin center: **Teams apps, Manage apps, Upload new app**. Then, on the
app's page, grant the meeting permissions: read meeting details, read
participants, send in-meeting notifications.

## 8. First run

1. As `lecturer@`: open C.L.I.P from Teams Apps, then the **Lecturer** tab,
   and open the dashboard. Sign in, upload material, approve questions and
   prepare a session.
2. Schedule a Teams meeting with `student1@` to `student4@`. In the meeting,
   add C.L.I.P from **Apps**. This installs the bot in the meeting chat.
3. As the meeting's organiser, open the C.L.I.P side panel and pick the
   session. Only the organiser (or an admin) can link a meeting: C.L.I.P asks
   Teams who organised it. Write `status` to the bot in the meeting chat to
   check the link.
4. Start the meeting. The session starts with it. Each student opens the side
   panel, is signed in by Teams, accepts the terms once, and waits for the
   first checkpoint.
5. Send a checkpoint. Expect a card in the meeting chat, a pop-up for each
   student, and the answered count rising in the lecturer's panel.
6. End the meeting. The session ends.

### Breakout rooms

Teams lets no app create breakout rooms or put people in them, so C.L.I.P
keeps its own plan and the lecturer mirrors it in Teams:

1. With the class running, open **Breakout rooms** on the lecturer website,
   choose how many rooms, select **Split evenly** (or pick each student's
   room), and **Send rooms to students**. Each student's panel shows their
   room.
2. In the meeting, open Teams **Breakout rooms**, create rooms with the same
   names, assign the same people, and open them.
3. The lecturer's live page shows which rooms are talking and which have gone
   quiet, from when students speak and answer, never what they say.
4. Close the rooms in Teams and select **Bring everyone back** in C.L.I.P.

A Teams breakout room has its own meeting id. If C.L.I.P is open in a room, a
student's panel shows the one class of theirs that is running.

Then work through the "Teams tenant" cases in the test plan (section 3.10)
and the real-tenant checks in `docs/teams-checkpoint-notifications.md`.

## When something does not work

| Symptom | Likely cause |
|---|---|
| Tabs are blank or say the page cannot be shown | Tunnel not running, or `BASE_URL` in the package is not the tunnel address. |
| "Sign in with Microsoft" shows an error in Teams | The Application ID URI, scope or authorised Teams clients (step 3.6) are wrong, or admin consent is missing. |
| "This Microsoft account has no C.L.I.P account yet" | Run step 6, or the account is not in the script's list. |
| The bot never starts the session | Messaging endpoint wrong, the Teams channel is missing, or C.L.I.P was not added to that meeting. |
| No pop-ups | `TEAMS_NOTIFICATIONS_ENABLED` is not true, the permissions in step 7 are not granted, or the student has not opened C.L.I.P in Teams once, so their account is not linked yet. |
| "Only the meeting's organiser can link a session" | Sign in to Teams as the account that scheduled the meeting, or link it as an admin. |
| "C.L.I.P is not in this meeting yet" | Add C.L.I.P from **Apps** in the meeting, so the bot is in its chat, then pick the session again. |
| The camera indicator cannot start in Teams | Teams asks for camera permission the first time. Allow it in the device prompt. |
