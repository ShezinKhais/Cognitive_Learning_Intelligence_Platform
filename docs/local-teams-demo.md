# Try the Teams panel locally, without Teams

Shows what a student sees in the Teams meeting side panel, and the lecturer's
**Share to the meeting stage** button, using the Teams mock. No tenant, bot
or tunnel is needed. Windows PowerShell commands; the same steps work
elsewhere with the usual changes.

What you need: Git, Node, and **Docker Desktop running** (its engine must say
"running" before step 2).

## 1. Get the code

```
git fetch origin Shezin-Phase-2-Fixes
git checkout Shezin-Phase-2-Fixes
git pull origin Shezin-Phase-2-Fixes
```

If Git says local changes would be overwritten, stash them first:
`git stash push -u -m "before teams demo"`.

## 2. Start the backend and database in Docker

Create the config, once. It is git-ignored, so it is never in a fresh clone:

```
copy deploy\demo.env.example deploy\demo.env
$k1 = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
$k2 = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
(Get-Content deploy\demo.env) -replace '^CLIP_SECRET_KEY=.*', "CLIP_SECRET_KEY=$k1" -replace '^DEMO_DB_PASSWORD=.*', "DEMO_DB_PASSWORD=$k2" | Set-Content -Encoding ascii deploy\demo.env
```

Build and start (several minutes the first time):

```
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env ps
```

Wait until `db`, `backend` and `web` all say `healthy`, and
`http://localhost:8088/api/v1/health` loads.

## 3. Put a class and two questions in (once)

There is no AI model in this setup, so the questions go straight into the
database. Same PowerShell window, one block at a time.

```
$B = "http://localhost:8088/api/v1"
function Login($e,$p){ (Invoke-RestMethod -Method Post -Uri "$B/auth/login" -ContentType application/json -Body (@{email=$e;password=$p}|ConvertTo-Json)).access_token }
$A = Login "admin@clip.example.com" "AdminPass123!"
$L = Login "lecturer@clip.example.com" "LecturerPass123!"
$S = Login "student@clip.example.com" "StudentPass123!"
foreach($t in $A,$L,$S){ Invoke-RestMethod -Method Post -Uri "$B/auth/consent" -Headers @{Authorization="Bearer $t"} -ContentType application/json -Body '{"consent_type":"terms","granted":true}' | Out-Null }
Invoke-RestMethod -Method Put  -Uri "$B/courses/CLIP101/lecturers" -Headers @{Authorization="Bearer $A"} -ContentType application/json -Body '{"lecturer_ids":["22222222-2222-2222-2222-222222222222"]}' | Out-Null
Invoke-RestMethod -Method Post -Uri "$B/courses/CLIP101/students"  -Headers @{Authorization="Bearer $A"} -ContentType application/json -Body '{"email":"student@clip.example.com"}' | Out-Null
"done"
```

```
$sql = @"
insert into source_material (id, course_id, uploaded_by_user_id, filename, content_type, size_bytes, status)
select gen_random_uuid(), c.id, '22222222-2222-2222-2222-222222222222', 'demo-lecture.pdf', 'application/pdf', 10, 'completed' from course c where c.code='CLIP101';
insert into question (question_id, source_material_id, question_text, question_type, status, options, correct_option, source_slide, topic)
select gen_random_uuid(), m.id, q.t, 'mcq', 'staged', q.o, q.c, q.s, q.topic
from source_material m, (values
 ('Which planet is the largest in our solar system?', ARRAY['Mars','Jupiter','Venus'], 1, 3, 'Planets'),
 ('What is the capital of France?', ARRAY['Paris','Rome','Madrid'], 0, 5, 'Capitals')
) as q(t,o,c,s,topic) where m.filename='demo-lecture.pdf';
"@
$sql | docker exec -i (docker ps -qf "name=clip-demo-db") psql -U clip -d clip
```

It prints `INSERT 0 1` then `INSERT 0 2`.

```
$sid = (Invoke-RestMethod -Method Post -Uri "$B/sessions" -Headers @{Authorization="Bearer $L"} -ContentType application/json -Body '{"course_code":"CLIP101","title":"Paperclip demo"}').id
Invoke-RestMethod -Method Put  -Uri "$B/meetings/test-meeting" -Headers @{Authorization="Bearer $L"} -ContentType application/json -Body (@{session_id=$sid}|ConvertTo-Json) | Out-Null
Invoke-RestMethod -Method Post -Uri "$B/sessions/$sid/start" -Headers @{Authorization="Bearer $L"} | Out-Null
"Session: $sid"
```

## 4. Start the frontend

In a second PowerShell window, from the repo folder:

```
cd frontend
@"
VITE_TEAMS_MOCK_ENABLED=true
VITE_LIVE_SESSIONS_ENABLED=true
VITE_SOCRATIC_CHAT_ENABLED=true
VITE_MATERIAL_PIPELINE_ENABLED=true
CLIP_BACKEND_URL=http://127.0.0.1:8088
"@ | Set-Content -Encoding ascii .env.local
npm ci
npm run dev
```

Wait for `Local: http://localhost:5173/`. All four `VITE_` switches matter: without
`VITE_LIVE_SESSIONS_ENABLED`, the student panel stays on "Waiting for your
lecturer".

## 5. Look at it

Use two browser windows. Log in to each at `http://localhost:5173/login`.

- **Student** (incognito): `student@clip.example.com` / `StudentPass123!`, then open
  `http://localhost:5173/teams/meeting?teamsMock=1&meetingId=test-meeting`.
  You see only a small paperclip with the student's checkpoint count.
- **Lecturer** (normal window): `lecturer@clip.example.com` / `LecturerPass123!`, then open
  the same address. Click **Send a checkpoint now**.
- Back in the student window the paperclip opens by itself with the
  question. Answer it, then **Minimise**: the count updates (`1/1`).
- In the lecturer window, **Share to the meeting stage** opens the stage
  view in a new window. To open that view yourself as a student:
  `http://localhost:5173/teams/meeting?teamsMock=1&meetingId=test-meeting&frame=content`.

The lecturer can send two checkpoints (there are two questions). To start
again with a fresh class, repeat the last block of step 3.

## If something goes wrong

| What you see | Why, and what to do |
|---|---|
| Docker says "unable to start", or `docker ps` errors | Open Docker Desktop and wait for "Engine running". On Windows it may need `wsl --update`. |
| `couldn't find env file ... demo.env` | Do the config step (step 2) on this PC. The file is not in git. |
| The backend keeps restarting with `Can't locate revision identified by ...` | The database volume came from a different version of the code. Wipe that stack's data: `docker compose -p <project name> down -v --remove-orphans`, then start again. |
| Port 5173, 8000 or 5432 is in use | Another stack is running. `docker ps` shows it; stop it. Find a process with `netstat -ano \| findstr :5173`. |
| The student panel says "Waiting for your lecturer" | The `VITE_LIVE_SESSIONS_ENABLED=true` switch is missing from `frontend\.env.local`, or the class was not started (step 3, last block). |
| `Proxy error ... ECONNREFUSED` in the Vite window | The backend is not running. Check `docker ps`; use `127.0.0.1` in `CLIP_BACKEND_URL`, not `localhost`. |
| The Docker web image on port 8088 does not show the mock | Correct: the mock is never in a production build. Use the Vite dev server on 5173. |
| `python` or `pip` is "blocked" by a policy | Not needed here. Everything runs in Docker and Node. |

## What this does not test

Real Teams: the stage sharing itself, the manifest permission, the bot and
notifications need a Teams tenant and the packaged app. See
`teams-app/README.md`.
