# Cyber 1 Phase 1 — Run and Test Guide

This snapshot combines:

- General CS Phase 1 API foundation and error handling
- Hunain's Cyber 2 administrator timetable/roster console
- Aliyeh's Cyber 1 authentication, consent, JWT and RBAC work

BBIS is not required for this prototype. Users, consent decisions and failed-login counts are held in memory and reset when the backend restarts.

## Development accounts

| Role | Email | Password |
|---|---|---|
| Student | `student@clip.example.com` | `StudentPass123!` |
| Lecturer | `lecturer@clip.example.com` | `LecturerPass123!` |
| Admin | `admin@clip.example.com` | `AdminPass123!` |

These accounts are disabled automatically when `CLIP_ENV=production`.

## 1. Put the code into the cloned GitHub repository

Extract this ZIP into a temporary folder. Copy everything inside it into the root of the cloned repository, where `backend`, `frontend`, and `docker-compose.yml` are visible. Choose **Replace files** when Windows asks.

Do not delete or replace the hidden `.git` folder in the cloned repository. This ZIP does not contain one.

## 2. Run the backend on Windows

Open the repository in VS Code. Open a terminal and run:

```powershell
cd backend
py -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

The backend should start at:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

PostgreSQL is not needed for the Cyber 1 authentication and Cyber 2 import demo. `/ready` may report unavailable dependencies until BBIS/PostgreSQL and Ollama are running.

## 3. Run the frontend

Open a second VS Code terminal from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the address printed by Vite, normally:

`http://localhost:5173/login`

Log in using the admin development account. On first access, accept the terms. You can then open the administrator console and upload the sample CSV files in the `samples` folder.

## 4. Run Cyber 1 and Cyber 2 tests

With the backend virtual environment active:

```powershell
cd backend
pytest -q tests/test_auth.py tests/test_consent.py tests/test_rbac.py tests/test_ws.py tests/test_contract.py tests/test_admin_routes.py tests/test_timetable_import.py
```

Optional checks:

```powershell
ruff check app tests
python scripts/export_contract.py --check
```

## 5. Save the work to Aliyeh's branch

From the repository root:

```powershell
git branch --show-current
git status
git add .
git commit -m "Phase 1: implement authentication consent and RBAC"
git push origin Aliyeh-Phase-1
```

Before committing, confirm the current branch is `Aliyeh-Phase-1`.

## What Cyber 1 now implements

- Password hashing and verification
- Signed JWT access tokens with expiry
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- Granular and revocable consent
- Real `get_principal(request)` bearer-token validation
- Role-based access checks
- Terms requirement for administrator actions
- Protected timetable and roster uploads
- WebSocket token authentication
- Structured security-event logging
- Frontend login, token storage, consent screen and protected admin route
- Authentication, consent, RBAC and WebSocket tests

## Temporary Phase 1 limitations

- Users and consent decisions are in memory, not PostgreSQL.
- Account locks reset when the backend restarts.
- The five-failed-attempt lock does not send an email yet.
- Microsoft Entra ID / Teams SSO is not connected yet.
- BBIS should later replace the in-memory repositories without changing route contracts or JWT/RBAC logic.
