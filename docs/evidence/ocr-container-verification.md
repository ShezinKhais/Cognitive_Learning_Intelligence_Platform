# OCR in the deployed container — verification (#238)

**Date:** 21 November 2026
**Tester:** Nour
**Release:** `d445c15f76bf2d4328ada9c7a878bd7460a617ca` (from `GET /api/v1/health`)
**Environment:** `docker-compose.demo.yml` on macOS (Apple Silicon, Docker 29.6.2), `CLIP_ENV=development`, `OCR_IN_IMAGE=true`, no Ollama running.

## Supported scope

As documented in `deploy/demo.env.example`: OCR covers **English scanned PDFs** only. The image does not install LibreOffice, so it adds no conversion for other formats. Pages with no readable text are reported as unreadable, not silently dropped.

## Results

| # | Check | How | Result |
|---|---|---|---|
| 1 | Tesseract present in the backend image | `docker compose ... exec -T backend tesseract --version` | **Passed**: tesseract 5.5.0, leptonica 1.84.1 |
| 2 | Clean scanned page | `backend/scripts/check_deployed_ocr.py` inside the container | **Passed**: expected text recovered |
| 3 | Low-contrast scanned page | same script | Observation: read correctly ("logistic regression predicts a binary outcome.") |
| 4 | Formula scanned page | same script | Observation: read correctly ("the line equation is y = 2x + 3.") |
| 5 | Blank / image-only page | same script | **Passed**: identified as unreadable, with a warning |
| 6 | Real scanned lecture uploaded through the web UI (`backend/tests/eval/ocr/lecture_scanned.pdf`, 847 KB) as `lecturer@clip.example.com` | Materials → Upload | **Blocked**: processing failed at the AI step because no Ollama server was reachable (`httpcore.ConnectError` in the backend log, raised by the OpenAI-compatible client the backend uses to call Ollama). OCR itself did not raise an error. |

## Finding

When the AI model server is unreachable, the lecturer sees only **"Processing failed unexpectedly."** (`UNEXPECTED_FAILURE_MESSAGE` in `backend/app/services/jobs.py`). The cause is logged, but the message gives the lecturer no hint that the model server is down. #238 asks for clear failed states, so this should become a specific message, e.g. "The AI model server is unavailable; try again later."

## Not yet verified

- End-to-end upload of real scans (clean and poor) with Ollama running and `qwen2.5` + `nomic-embed-text` pulled.
- That unrelated live sessions stay responsive while a large scan is processed.

## Reproduce

```sh
cp deploy/demo.env.example deploy/demo.env   # set secrets, OCR_IN_IMAGE=true, CLIP_RELEASE_SHA=$(git rev-parse HEAD)
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend tesseract --version
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend python - < backend/scripts/check_deployed_ocr.py
curl -s http://localhost:8088/api/v1/health
```