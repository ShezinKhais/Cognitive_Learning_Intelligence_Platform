# OCR in the deployed container — verification (#238)

**Date:** 21–22 November 2026
**Tester:** Nour
**Release:** `d445c15f76bf2d4328ada9c7a878bd7460a617ca` plus the fix in this PR
**Environment:** `docker-compose.demo.yml` on macOS (Apple Silicon, Docker 29.6.2), `CLIP_ENV=development`, `OCR_IN_IMAGE=true`. Ollama on the host with `nomic-embed-text` and `qwen2.5:0.5b` (a smaller model than the default `qwen2.5`, used to save download time).

## Supported scope

As documented in `deploy/demo.env.example`: OCR covers **English scanned PDFs** only. The image does not install LibreOffice, so it adds no conversion for other formats. Pages with little or no readable text are flagged to the lecturer, not silently dropped.

## Results

| # | Check | How | Result |
|---|---|---|---|
| 1 | Tesseract present in the backend image | `docker compose ... exec -T backend tesseract --version` | **Passed**: tesseract 5.5.0, leptonica 1.84.1 |
| 2 | Clean scanned page | `backend/scripts/check_deployed_ocr.py` inside the container | **Passed**: expected text recovered |
| 3 | Low-contrast scanned page | same script | Observation: read correctly |
| 4 | Formula scanned page | same script | Observation: read correctly ("y = 2x + 3") |
| 5 | Blank / image-only page | same script | **Passed**: identified as unreadable, with a warning |
| 6 | Real clean scan through the web UI (`backend/tests/eval/ocr/lecture_scanned.pdf`, 847 KB) | Materials → Upload as `lecturer@clip.example.com` | **Passed**: 21 pages, status Ready |
| 7 | Real poor scan through the web UI (`backend/tests/eval/ocr/lecture_pptx_as_pdf_scanned.pdf`, 2.4 MB) | same | **Passed**: 18 pages read with OCR, 31 sections, status Ready. Lecturer warned to check for misread words and that pages 1 and 18 have very little readable text. No questions were drafted (see limitations). |
| 8 | Model server unreachable (Ollama stopped) | Upload `lecture_scanned.pdf` | **Passed after fix**: before, the lecturer saw "Processing failed unexpectedly."; now "The AI model server is unavailable, so this material could not be indexed. Try uploading it again later." The uploaded file is kept for a retry. |
| 9 | Server stays responsive while a scan is processed | `GET /api/v1/health` once a second for 90 s during upload of the 2.4 MB scan | **Passed**: 90/90 answered; median 0.006 s, slowest 0.020 s |

## Fix included

`backend/app/services/pipeline.py`: an `AiUnavailableError` from the model gateway is now reported with a specific message and the gateway's error code (`AI_UNAVAILABLE` / `AI_BUSY`) instead of `INTERNAL_ERROR`, and is not logged as a crash. Test: `test_an_unreachable_model_server_is_reported_clearly` in `backend/tests/test_pipeline.py`.

## Limitations

- Question drafting used `qwen2.5:0.5b`. The poor scan produced no questions; this is likely the small model rather than OCR, since the text was extracted and indexed. Re-check with the default `qwen2.5` on the target machine.
- Responsiveness was measured with the health endpoint, not a live class with connected students.
- Tested on a developer laptop, not the university host.

## Reproduce

```sh
cp deploy/demo.env.example deploy/demo.env   # set secrets, OCR_IN_IMAGE=true, CLIP_RELEASE_SHA=$(git rev-parse HEAD)
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend tesseract --version
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend python - < backend/scripts/check_deployed_ocr.py
ollama pull nomic-embed-text && ollama pull qwen2.5   # then upload the two PDFs in backend/tests/eval/ocr/
```