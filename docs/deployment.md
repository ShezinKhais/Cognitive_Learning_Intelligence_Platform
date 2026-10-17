# Demo deployment

Owner: General CS, Phase 8. Files: `docker-compose.demo.yml`, `backend/Dockerfile`,
`frontend/Dockerfile`, `frontend/nginx.conf`, `deploy/demo.env.example`,
`backend/scripts/smoke_test.py`.

One command starts the whole platform on one machine: database, backend and web
server, with a single published port. It is built for showing the project to a
marker or running a class on a laptop. It is not a production deployment; see
[What is not covered](#what-is-not-covered).

It runs in development mode by default, so the demo accounts from the README exist
and no model is needed to sign in.

## Services

| Service | Image | What it does |
|---|---|---|
| `db` | `pgvector/pgvector:pg16` | PostgreSQL with the `vector`, `uuid-ossp` and `pg_trgm` extensions (`init-db.sql`). No published port. |
| `backend` | built from `backend/Dockerfile` | Runs `alembic upgrade head`, then one uvicorn process on port 8000. Not published. |
| `web` | built from `frontend/Dockerfile` | nginx. Serves the built SPA and proxies `/api/` and `/ws/` to the backend. The only published port, 8088 by default. |

The stack is its own compose project (`clip-demo`) with its own volumes, so it never
touches the development database started by `docker-compose.yml`. Always pass
`-p clip-demo`.

## Run it

From the repository root:

```bash
cp deploy/demo.env.example deploy/demo.env
# Replace CLIP_SECRET_KEY and DEMO_DB_PASSWORD. Hex from this is fine for both:
python -c "import secrets; print(secrets.token_hex(32))"

docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env ps
```

`deploy/demo.env` is ignored by git through the `*.env` rule. Do not commit it.

When all three services report `healthy`, open <http://localhost:8088> and sign in with a
demo account from the README. To stop the stack and keep its data:

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env down
```

### Settings

Set in `deploy/demo.env`. The compose file reads them, so changing the Vite switches
needs `--build`.

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_PORT` | `8088` | The one published port. |
| `CLIP_ENV` | `development` | `development` or `production`. |
| `CLIP_SECRET_KEY` | none, required | Signs login tokens. |
| `DEMO_DB_PASSWORD` | none, required | Password for the `clip` database role. Keep it URL-safe; it is placed in `DATABASE_URL`. |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` | An Ollama on the host machine is used if one is running. |
| `OLLAMA_MODEL`, `EMBEDDING_MODEL` | `qwen2.5`, `nomic-embed-text` | As in the README. |
| `AI_WARMUP_ENABLED` | `false` | Do not load a model at startup. |
| `VITE_*_ENABLED` | `true` | Show the live session, tutor chat and material pages. Baked into the web image. |

Without Ollama the platform still starts and classes still run. Question generation, the
tutor and material processing report the model as unavailable, and `/api/v1/ready` lists
Ollama as not ok without failing readiness.

## The backend runs as one process

The image starts uvicorn with `--workers 1` and the compose file sets
`WEB_CONCURRENCY=1`. Do not raise either. A live session's question timer, open
question and waiting prompts are held in the process that holds its sockets
(`backend/app/realtime/classroom.py`). A second worker would restore the same session and
run its question cycle again, so every student would be asked twice. In production the
backend refuses to start with more than one.

Scaling out means moving that state out of the process first. That is not done.

The container is stopped with SIGTERM and given 30 seconds (`stop_grace_period`). The
entrypoint ends with `exec uvicorn`, so the signal reaches uvicorn. The app then stops its
scheduled jobs (a purge in progress is cancelled, having deleted only whole batches), stops
the session timers, and waits for running material jobs and reports before exiting.
Sessions stay active in the database and carry on when the backend is next used.

## The proxy

`frontend/nginx.conf` does the following.

| Path | Behaviour |
|---|---|
| `/` and any unknown path | `index.html`, so a reload on a client route such as `/login` works. `index.html` is not cached; `/assets/` is cached for a year. |
| `/api/` | Proxied. Read timeout 120 s. |
| `/api/v1/sessions/{id}/chat` | Proxied with buffering off, so the tutor's NDJSON reply arrives as it is written. The backend also sends `X-Accel-Buffering: no`. Read timeout 300 s. |
| `/ws/` | Proxied with the WebSocket upgrade. Read and send timeout 2 hours. |
| `/healthz` | Answers `ok` from nginx itself. Used by the container health check. |

The sockets: the frontend sends no keepalive of its own. uvicorn sends a protocol ping
every 20 seconds, which nginx counts as activity, so the proxy timeout is not what keeps
a socket open. It is set to 2 hours anyway, so that a class that is quiet on the wire
for a long time is never cut off by the proxy.

Other behaviour:

- `X-Request-ID` from the caller is passed on; if absent, nginx makes one. The backend
  puts it in every log line for the request.
- `X-Forwarded-For` is set and uvicorn is started with `--proxy-headers`, so audit and
  login-lockout records carry the client's address and not the proxy's. The backend
  trusts any sender (`FORWARDED_ALLOW_IPS=*`), which is safe only because its port is
  not published.
- Uploads: nginx allows bodies up to 60 MB. The backend limit is 50 MB.
- Compression: gzip for scripts, styles, JSON, SVG and wasm over 1 KB. The tutor's
  NDJSON stream is left uncompressed, since gzip would hold its words back.
- Headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`
  (camera and microphone for this origin only), `Strict-Transport-Security`, and a
  `Content-Security-Policy`. No `X-Frame-Options` is sent.
- The CSP allows scripts, styles, fonts, workers and connections from this origin only,
  plus `res.cdn.office.net`, where the Teams SDK reads Microsoft's list of Teams hosts.
  `wasm-unsafe-eval` lets the attention models' WebAssembly compile; no `eval` and no
  inline script is allowed. `style-src` allows inline styles for style attributes.
  `frame-ancestors` is the Teams list [teams-frontend-security.md](teams-frontend-security.md)
  requires.
- HSTS is ignored over plain http, so a local demo is unaffected. It takes effect once
  TLS is terminated in front of nginx.
- The API sets `nosniff`, `Referrer-Policy: no-referrer` and `Content-Security-Policy:
  default-src 'none'` on its own answers, for any route to it that does not pass through
  nginx. It sets no `frame-ancestors`: framing is decided by nginx for the pages Teams
  loads.

## Sign-in

The access token lasts an hour and is kept in the tab's memory only. A refresh token
is set at sign-in as an httpOnly cookie, scoped to `/api/v1/auth`, and lasts until the
sign-in ends (`MAX_SIGN_IN_HOURS`). The client uses it to get a new access token before
the old one expires, and on every reload or new tab. An access token cannot be
refreshed, so one taken from a page stops working within the hour.

In production the cookie is `Secure; SameSite=None; Partitioned`, because a Teams tab
is a cross-site iframe and only such a cookie is sent there. To stop another site
using it, refresh and sign-out require an `X-CLIP-Refresh: 1` header, which a page on
another origin cannot add without a CORS preflight, and production answers no
preflight. In development the cookie is `SameSite=Lax` and not `Secure`, since the dev
server is plain http.

Failed sign-ins are counted per account (5 in 15 minutes locks the account) and per
address (`LOGIN_FAILURES_PER_ADDRESS` in `LOGIN_FAILURE_WINDOW_MINUTES`, then 429).
The address count is held in memory, which is the whole count with the one worker the
image runs.

## Data

| Volume | Holds | Survives `down` | Removed by `down -v` |
|---|---|---|---|
| `clip-demo_demo_pgdata` | The database. | yes | yes |
| `clip-demo_demo_data` | Uploaded material (`/data/uploads`). | yes | yes |

Session reports are built in memory and kept for an hour, so they need no volume and do
not survive a restart (see [reports.md](reports.md)). Reportlab, which draws the PDF, is a
normal dependency of the backend, so the image already includes it.

The backend deletes upload files older than `DATA_RETENTION_DAYS` once a day (see
[the retention purge](reports.md#the-retention-purge)), which is why the uploads sit on a
volume the backend can write to. Database tables are not purged yet.

Migrations run each time the backend container starts. Running them again when the
database is current changes nothing.

To start from nothing:

```bash
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env down -v
```

In development mode the demo accounts are written into the `user` table at startup, and
they stay there. Reset the volumes (`down -v`) before switching a stack to production;
see the checklist.

## Smoke test

`backend/scripts/smoke_test.py` checks a running stack from outside, through nginx. It
needs `httpx` and `websockets`, which the backend's dependencies already include.

```bash
cd backend
python scripts/smoke_test.py --base http://localhost:8088
```

It checks health, readiness, the SPA and a deep-link fallback, the 401 error envelope,
sign-in and terms consent for the demo lecturer and student, and a WebSocket that
authenticates, answers a ping, stays open and idle (25 seconds; `--idle` changes it), and
answers a second ping. One line is printed per check, and the exit status is 1 if any
failed. It uses the development accounts, so it passes only against `CLIP_ENV=development`.

## Load test

`python -m scripts.loadtest` (see `backend/scripts/loadtest/__init__.py`) is run from a
source checkout, from `backend/`. It does not test the containers. It starts its own
backend in production mode against a throwaway database named `clip_load` on the
development Postgres from `backend/.env`, and drops it afterwards. What it checks, and how
to read its results, is in [load-and-recovery.md](load-and-recovery.md).

```bash
cd backend
python -m scripts.loadtest --students 40 --out ../docs/load-test-results.json
```

`--database-outage` stops and starts the container named by `--database-container`
(`clip-postgres` by default). Do not use it while anyone else is using that database.

## Production checklist

Setting `CLIP_ENV=production` makes the backend refuse to start unless all of these hold.
Change them in `deploy/demo.env`, then recreate the backend.

| Requirement | Why |
|---|---|
| `CLIP_SECRET_KEY` is at least 32 characters and not the default. | Anyone who knows the key can forge a token for any user. |
| The database password is not a known weak one and is at least 12 characters. | Checked by the backend at startup. |
| The database host is not `localhost`. | Inside this stack it is `db`, which passes. |
| One worker. | See above. |
| Every store a live session needs is registered. | The log names what is missing. |

Also, the things the backend does not check:

1. **Start from fresh volumes.** A stack that ran in development already has the demo
   accounts, with the passwords in the README, in its `user` table. Production reads that
   table, so they would still sign in. Run `down -v` first.
2. **Create real users.** Production reads accounts from the database only, and the API
   has no sign-up route. The only account-related admin routes import a timetable and a
   roster. Insert the first administrator into the `user` table yourself; the scripts are
   not in the backend image.
3. Interactive API docs (`/docs`, `/redoc`) and CORS are switched off in production.
4. Put TLS in front of it (below), then set `DEMO_PORT` to a loopback or internal address.

## What is not covered

| Not covered | Notes |
|---|---|
| TLS | The stack serves plain HTTP. Teams requires HTTPS for tab pages. Terminate TLS in front of `web` (a reverse proxy, a load balancer, or a tunnel) and keep the `Upgrade` headers on `/ws/`. |
| Teams app registration and tunnel | See `teams-app/README.md`. The manifest needs the public HTTPS host that serves this stack. |
| More than one host | The backend is one process and its live state is in memory. |
| Backups | The database volume is not backed up. Use `pg_dump` against the `db` container. |
| Content security policy beyond `frame-ancestors` | A deployment decision. |
| Model hosting | Ollama is expected on the host, not in the stack. |
