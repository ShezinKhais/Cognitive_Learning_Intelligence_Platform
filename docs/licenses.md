# Third-party licences

What C.L.I.P uses that someone else made, and under which licence, for the
submission (#257). Entries marked **to confirm** need checking against the exact
version or file deployed before the final release. This is an inventory, not
legal advice.

## The project itself

No licence has been chosen for the C.L.I.P code. Until the team and the university
agree one, the repository is all rights reserved by its authors. Agreeing it is an
open item on #257.

## Models

| Model | Used for | Licence |
|---|---|---|
| Qwen2.5 (Ollama `qwen2.5`, 7B by default) | Question generation, marking, the tutor | Apache 2.0 for the 7B weights. **To confirm** if a 3B build is deployed: Qwen2.5-3B is under the Qwen Research Licence, which does not allow commercial use |
| nomic-embed-text | Embeddings for retrieval | Apache 2.0 |
| Whisper base.en via faster-whisper (CTranslate2) | Optional live lecturer transcription | MIT (Whisper weights and faster-whisper) |
| MediaPipe Face Landmarker | On-device camera indicators | Apache 2.0 |
| Silero VAD, through `@ricky0123/vad-web` | On-device speech detection for the microphone indicator | MIT (Silero VAD), ISC (vad-web) |
| Qwen2.5-VL 3B (Ollama `qwen2.5vl:3b`) | Describing images in uploaded material | **To confirm**: the 3B Qwen releases use the Qwen Research Licence rather than Apache 2.0 |
| Anti-spoofing model (#233, off by default) | On-device liveness check | **To confirm** before it is turned on |

## Data

| Data | Used for | Licence |
|---|---|---|
| MIT OpenCourseWare lecture files named in `backend/tests/eval/` | Evaluation only; the files are not committed | CC BY-NC-SA 4.0. Attribute MIT OCW in any report that quotes them |
| Participant recordings for camera and microphone evaluation | Evaluation only; not committed | Consent forms held by AI 1. No licence to reuse |

## Main software dependencies

| Software | Licence |
|---|---|
| FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic, uvicorn | MIT or BSD |
| PostgreSQL, pgvector | PostgreSQL Licence |
| React, React Router, Vite, Tailwind CSS, lucide-react, motion | MIT (lucide-react is ISC) |
| python-pptx, pypdf, python-docx, openpyxl | MIT or BSD |
| reportlab (PDF reports) | BSD |
| Tesseract OCR (optional in the image) | Apache 2.0 |
| Microsoft Teams JavaScript client library | MIT |
| Ollama | MIT |

The full dependency lists are `backend/pyproject.toml` and `frontend/package-lock.json`.
A complete list with every transitive package can be produced with `pip-licenses` and
`npx license-checker`; running both before submission is **to confirm**.
