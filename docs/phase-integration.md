# Cross-phase integration checkpoint

For the combined branch and its remaining release gates, see
[the phases 1–6 integration candidate](phases-1-6-integration-candidate.md).
The main-only inventory below records the earlier baseline, not this branch.

Checked against `main` at `aa79ed7` on 2026-10-16. This is an integration
checkpoint, not evidence that every open PR has shipped or passed a live demo.

## Connections, not one port per phase

All phases share the same frontend and FastAPI application. Do not open a new
port for each phase or expose the database/model server to students.

| Component | Local address | Connection |
|---|---|---|
| Frontend development | http://localhost:5173 | Browser entry point; proxies `/api` and `/ws` |
| Built frontend preview | http://localhost:4173 | Same proxies; local verification only, not a production server |
| FastAPI | http://localhost:8000 | REST `/api/v1`, WebSocket `/ws/session`, Teams bot `/teams/messages` |
| PostgreSQL + pgvector | localhost:5432 | Backend only, `DATABASE_URL` |
| Ollama | http://localhost:11434/v1 | Backend only, `OLLAMA_BASE_URL` |

Copy `frontend/.env.example` to `frontend/.env`. `CLIP_BACKEND_URL` is read by
Vite, not bundled as a browser API URL. Both transports use it, including
uploads, tutor streaming, live questions and upload-progress sockets. For an
alternate backend port, start uvicorn with `--port 8010` and set
`CLIP_BACKEND_URL=http://localhost:8010`. Restart Vite after changing it.

The frontend fails on an occupied port rather than silently switching away
from the port configured in a Teams tunnel. A frontend port change must also
be reflected in the tunnel/Teams configuration. A production reverse proxy
must route `/api`, `/ws` (with Upgrade support) and `/teams` to FastAPI and all
other paths to the built frontend. Do not use Vite preview in production.

## Remaining integration boundaries

These PRs were open at inspection time. Their status can change; recheck them
before release. This branch does not merge them or duplicate their work.

| Workflow | Verified boundary on main | Dependency / next step |
|---|---|---|
| Login, consent, timetable/roster import | Backend and frontend exist | Import real linked course/student records before a session demo |
| Upload → generation → question review | Pipeline and progress socket exist | Enable `VITE_MATERIAL_PIPELINE_ENABLED` only with working database/models |
| Browse sessions → join live class | `GET /sessions`, `GET /sessions/{id}` and response listing still raise 501 | [#154](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/154) wires these routes; resolve review findings first |
| Checkpoint → comprehension → tutor | Tutor route exists; frontend gated | Enable `VITE_SOCRATIC_CHAT_ENABLED` only with material/chunks and available models; #154 also wires asynchronous free-text marking |
| Local attention → lecturer indicators | Browser sensor controls and backend summaries exist | Opt-in only; `VITE_LOCAL_ATTENTION_ENABLED` needs local assets; never transmit raw media |
| Breakout groups / private refocus / scheduled jobs | Not all orchestration is on main | [#147](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/147), including its review findings |
| Student post-session review / source links | Not yet on main | [#140](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/140) |
| Browser/client-AI hardening evidence | Not yet on main | [#150](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/150); real Teams and device sign-off still separate |
| In-meeting checkpoint notification | JSON builder alone does not send a message | [#155](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/155), tenant registration/permissions and real Teams validation |

Feature flags stay off by default: enabling the live-session flag while the
session-list handler returns 501 does not connect that workflow. Never bypass
authorization or replace API failures with fake successful data to make a demo
appear complete.

## Repeatable verification

1. Start Docker/PostgreSQL and Ollama; pull the configured language and embedding
   models. Install backend dependencies and apply `alembic upgrade head`.
2. Start a **single** backend process on port 8000. Check
   `curl http://localhost:8000/api/v1/ready` and resolve unavailable dependencies.
3. In `frontend/`, run `npm ci`, `npm test`, `npm run lint`, `npm run build`.
   `npm test` now runs in CI too (previously CI only typechecked/linted/built).
4. Run `npm run dev`; check `curl http://localhost:5173/api/v1/health`.
   Stop it, run `npm run preview`, and check the same endpoint on port 4173.
5. In `backend/`, run `pytest -q`, `ruff check .`, `ruff format --check .`,
   and `python scripts/export_contract.py --check`. Database skips are not proof
   of database correctness: use CI with PostgreSQL or a local test database.
6. After the dependent PRs are reviewed and merged, exercise lecturer upload →
   approve questions → start; student join → answer → feedback → tutor with
   citations; end → student review. Repeat with a disconnect/reconnect, denied
   camera/microphone access and a second student to verify data separation.

The new proxy tests start real Vite dev/preview servers against an ephemeral
mock backend. They verify POST body and Authorization preservation and an HTTP
WebSocket upgrade on `/ws/session`, on a non-default backend port. They do not
claim to test database-backed authentication, full WebSocket message/replay
semantics, model quality or a real Teams meeting.

Dependency auditing also reports high-severity transitive build-tool advisories
in the existing lockfile. `npm audit` reported no automatic fix for these at
inspection time. They remain release follow-up work; no untested forced major
dependency upgrade is included here.

### Local results for this change

- Frontend: 94 tests passed, including four proxy/config tests; lint and
  production build passed.
- Backend: 1,576 passed, 278 skipped (primarily unavailable database), one
  failure in `test_a_vector_chart_is_converted_trimmed_and_described`.
  The backend is unchanged from main: this machine's LibreOffice produced a
  blank WMF page, which the existing converter safely rejects. Do not count
  this as successful WMF conversion or hide it by disabling the test.
- Backend lint, formatting and generated REST/WebSocket contract checks passed.

No real-tenant Teams, browser/device or full database-backed end-to-end sign-off
is claimed by these results.
