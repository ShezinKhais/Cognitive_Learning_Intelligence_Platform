# Teams demo: quick start

How to run C.L.I.P for the team's Teams tenant on your own laptop, with plain
commands. The full setup, including the tenant, the bot and Entra, is in
[teams-tenant-setup.md](teams-tenant-setup.md). That is done once and is
already done for `CLIP736`.

## What you need

- Docker Desktop, running.
- The Dev Tunnels CLI: `winget install Microsoft.devtunnel`, then
  `devtunnel user login` with an account allowed to host the `clip736`
  tunnel. Ask Shezin, who owns it.
- Ollama, optional. Without it a class still runs from questions already
  approved; the tutor and question generation need it.
- Two git-ignored settings files, handed over privately, never committed or
  posted in chat:
  - `deploy/demo.env`: keys, database password, Teams and bot settings.
  - `teams-app/.env`: the bot ID and tunnel address, only needed to rebuild
    the app package.

Only one laptop runs the demo at a time, because Teams points at one tunnel
address: `https://swwrmrn9-8088.inc1.devtunnels.ms`.

## Start

From the repository root:

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
```

The first build downloads the base images and takes a few minutes. Wait until
this answers:

```bash
curl http://localhost:8088/api/v1/health
```

Then open the tunnel in its own terminal and leave it running while Teams is
in use:

```bash
devtunnel host clip736
```

For the AI features, also run `ollama serve`.

## Accounts (once per database)

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend python - < backend/scripts/provision_teams_accounts.py
```

It prints the lecturer and admin website passwords once. Running it again
changes nothing; add `--reset-passwords` after the `-` to issue new ones.

## Stop

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env stop
```

Then close the tunnel terminal. The data is kept for next time. Every
command needs `--env-file deploy/demo.env`; without it Docker stops with
"required variable ... is missing a value".

## In Teams

There is one C.L.I.P tab. It signs in with Teams and shows each person their
own page: students get My Learning, lecturers and admins get a button that
opens their website. In a meeting, add C.L.I.P from Apps for the side panel.

The first time the tab opens, the tunnel may show "You are about to connect
to a developer tunnel". Choose Continue.

## Rebuilding the app package

Only needed when the manifest or the tunnel address changes:

```bash
cd backend
python scripts/package_teams_app.py
```

This writes `teams-app/build/clip.zip`. CLIP is already in the org catalog,
so upload it in the Teams admin center: Teams apps, Manage apps, CLIP,
Upload file. Raise `version` in `teams-app/manifest.json` first, or Teams
keeps the old one. "Upload an app" in Teams itself refuses it, because the
app ID is already in use.

## When something does not work

| You see | Do |
|---|---|
| Backend keeps restarting, log says `password authentication failed for user "clip"` | The database was created with an older `DEMO_DB_PASSWORD`. Ask whoever set it up for that one, or reset the demo database (this deletes its data). |
| `required variable ... is missing a value` | Add `--env-file deploy/demo.env` to the command. |
| Teams tab is blank or says it cannot reach C.L.I.P | The tunnel terminal is closed, or the stack is down. Check the health URL. |
| "This page is for another role" | That page is for a different role. Use the one C.L.I.P tab. |
| Logs | `docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env logs --tail 100 backend` |
