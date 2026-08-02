# C.L.I.P

Cognitive Learning Intelligence Platform. An AI engagement assistant for live online
classes, built as a Microsoft Teams app.

During an online lecture a student can join, turn their camera off, and disengage without
anyone noticing until an assessment weeks later. C.L.I.P generates comprehension
checkpoints from the lecturer's own slides, tracks engagement in real time, and shows the
lecturer who is following and who is lost while there is still time to act.

It is **not** a grading system, a proctoring tool, or a replacement for the lecturer.
The AI suggests; the lecturer decides.

CSIT321 Capstone Project, Team 4, University of Wollongong in Dubai.
Supervisor: Dr. Farhad Orumchian.

---

## Stack

| Layer | Choice |
|---|---|
| Client | Microsoft Teams app: meeting side panel and personal tabs |
| Frontend | React, Vite, Tailwind |
| Backend | FastAPI, serving REST, WebSockets and the Teams bot from one process |
| Database | PostgreSQL with pgVector |
| AI | Qwen via Ollama, running locally |

Everything is open source and runs on our own hardware. No student data is sent to a
third-party AI service.

---

## Running it locally

Requires Python 3.11 to 3.13, Node LTS, Docker and Ollama. CI runs 3.12.

```bash
# database
docker compose up -d

# models
ollama pull qwen2.5
ollama pull nomic-embed-text

# backend, on http://localhost:8000
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload

# frontend, on http://localhost:5173
cd frontend && npm install && npm run dev
```

Check it came up:

```bash
curl http://localhost:8000/api/v1/ready
```

That reports whether Postgres and Ollama are actually reachable, and names what is wrong
when they are not. Interactive API docs are at `/docs` in development.

The Teams integration stays dormant until a tenant is available. `/health` reports
`teams_configured: false` and the app runs standalone in the meantime.

---

## Layout

```
backend/
  app/api/v1        routes, versioned
  app/schemas       request, response and event contracts
  app/core          config, database, errors, logging
  app/realtime      WebSocket connections and fan-out
  openapi.json      REST contract, generated
  events.schema.json  WebSocket contract, generated

frontend/           React, student and staff interfaces
teams-app/          Teams manifest and app package
```

---

## The API contract

`backend/openapi.json` and `backend/events.schema.json` describe every endpoint and every
live event. Both are generated from the code and committed, and CI fails if they drift out
of date, so they can be trusted as the interface between workstreams.

Regenerate after changing any schema:

```bash
python scripts/export_contract.py
```

Routes that return 501 have an agreed contract but no implementation yet. The response
names the workstream that owns them.

---

## Privacy

These are enforced in code, not promised in documentation.

- No raw video, audio, screenshots or transcripts are ever stored.
- Camera and microphone processing happens on the student's own device. Only numeric
  indicators leave it, and no event type can carry anything else.
- Engagement and comprehension are measured separately, and neither is an assessment.
- Declining consent never lowers a student's score.
- Session data is deleted after 90 days, per UAE Federal Decree-Law No. 45 of 2021.
