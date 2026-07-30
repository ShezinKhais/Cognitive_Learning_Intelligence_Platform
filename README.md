# C.L.I.P — Cognitive Learning Intelligence Platform

An AI engagement assistant for live online classes, built as a Microsoft Teams app.

During an online lecture a student can join, turn their camera off, and disengage without
anyone noticing until an assessment weeks later. C.L.I.P closes that gap: it generates
comprehension checkpoints from the lecturer's own slides, tracks engagement in real time,
and gives the lecturer a live view of who is following and who is lost — in time to do
something about it.

It is **not** a grading system, a proctoring tool, or a replacement for the lecturer.
The AI suggests; the lecturer decides.

**CSIT321 Capstone Project · Team 4 · University of Wollongong in Dubai**
Supervisor: Dr. Farhad Orumchian

---

## Stack

| Layer | Choice |
|---|---|
| Client | Microsoft Teams app — meeting side panel and personal tabs |
| Frontend | React, Vite, Tailwind |
| Backend | FastAPI — REST, WebSockets and the Teams bot in one process |
| Database | PostgreSQL + pgVector |
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

# backend  ->  http://localhost:8000
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload

# frontend ->  http://localhost:5173
cd frontend && npm install && npm run dev
```

The Teams integration stays dormant until a tenant is available — `/health` reports
`teams_configured: false` and the app runs standalone in the meantime.

---

## Layout

```
backend/     FastAPI — API, WebSockets, Teams bot, AI agents
frontend/    React — student, lecturer and admin interfaces
teams-app/   Teams manifest and app package
```

---

## Privacy

These are architectural constraints, not aspirations.

- No raw video, audio, screenshots or transcripts are ever stored.
- Camera and microphone processing happens on the student's own device; only numeric
  indicators leave it.
- Engagement and comprehension are measured separately, and neither is an assessment.
- Declining consent never lowers a student's score.
- Session data is deleted after 90 days, per UAE Federal Decree-Law No. 45 of 2021.
