# Teams release and catch-up acceptance

Tracks #239, #234, #255 and #238. This complements the existing
[live speech setup](live-transcription.md) and [Teams tenant setup](teams-tenant-setup.md).
Do not mark a tenant or hardware check passed based on mock or container results.

## Identify the build before testing

Use a clean checkout of the intended release. From the repository root:

```sh
export CLIP_RELEASE_SHA="$(git rev-parse HEAD)"
export CLIP_IMAGE_TAG="$CLIP_RELEASE_SHA"
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env up -d --build --wait
python backend/scripts/check_deployed_release.py --base https://your-app.example --revision "$CLIP_RELEASE_SHA"
```

The web's `/release.json` and API's `/api/v1/health` return the build revision
without caching. The web file also contains the built frontend switches.
An unstamped image says `unknown`; it cannot pass the comparison. These stamps
help identify a build; they are not a cryptographic attestation of its contents.

Then record what the backend is running. This prints JSON with the commit,
the database migration against the code's head, every true/false switch, the
chat and embedding models with their Ollama digests, the prompt versions, and
a hash of the installed Python packages. It prints no URL, key, secret or
account id, so the output can go into shared evidence as it is:

```sh
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env \
  exec -T backend python - < backend/scripts/record_release.py
docker image inspect --format '{{.Id}} {{.Architecture}}' \
  clip-demo-backend:"$CLIP_IMAGE_TAG" clip-demo-web:"$CLIP_IMAGE_TAG"
```

Add the frontend lockfile hash (`sha256sum frontend/package-lock.json`), the
Teams package version and ZIP hash, and the speech model hash and language when
speech is on (`python scripts/check_live_speech.py` in the backend). Copy only
these values. Do not export full environment files, image environment fields,
credentials or meeting identifiers into shared evidence.

The package hash covers every installed distribution, pip and setuptools
included, so it changes with the base image's tooling even when the app's own
pins are the same. Equal hashes mean the same packages; different hashes mean
compare the package lists before calling it an app difference. A model shown
as `(could not reach Ollama)` means the record could not ask Ollama, not that
the model is missing; `(not pulled)` means Ollama answered without it.

### If saved conversations fail to load

Run the revision comparison above before investigating the student account.
A frontend with the history panel needs a backend from the same build and the
chat-history migration applied. If the revisions differ, rebuild and deploy
both services from the same commit, then run the comparison again. If they
match, use `record_release.py` to compare the database revision with the code
head and check the backend error for the failed request.

In the browser Network panel, record the status for
`GET /api/v1/me/chat-history`. A 404 indicates the route was unavailable at
that origin, a 401 or 403 points to authentication or role access, and a 5xx
requires the backend error to diagnose. Share the status, build and time.
Keep private chat content and credentials out of shared evidence.

### What makes a rebuild the same

- Base images are pinned by digest: `python:3.12.16-slim`, `node:24.22.3-alpine`,
  `nginx:1.31.7-alpine` and `pgvector/pgvector:pg16` (PostgreSQL 16.14), each
  the version the demo ran when the pins were taken.
- Backend packages install from `backend/constraints.txt`, the exact versions of
  that image plus the optional speech pins. `pyproject.toml` keeps the ranges
  for development. Frontend packages install with `npm ci` from
  `package-lock.json`.
- Builds with `ENABLE_LIVE_TRANSCRIPTION=true` use the same constraints for
  the local speech runtime, including faster-whisper and its dependencies.
  Resolve updates for both Linux amd64 and arm64. Record the prepared model
  checksum separately with `scripts/check_live_speech.py`.
- Ollama models are named by tag; the record above captures the digest that
  answered, which is what to compare between machines.

To move a pin, change it, rebuild, run the suite and the checks on this page,
and commit the new pin with the result. A stamp identifies a build; it is not a
cryptographic attestation of its contents.

### Known-good release and rollback

Keep the tested images under their release tag (`CLIP_IMAGE_TAG`) or export them
with `docker save`. For rollback, stop live classes, check migration
compatibility with the older images and follow the existing database
backup/restore runbook if needed. Select the previously recorded image tag and
run Compose with `--no-build`; verify both identities with
`check_deployed_release.py` before resuming. Do not rebuild an older tag from
the current checkout or automatically downgrade a production database.

## Validate the package

Generate the package from the same checkout as the images, with the approved
test app/bot IDs and HTTPS app origin in the private Teams configuration. CI
validates the filled template against the pinned Microsoft 1.17 schema and the
CLIP meeting, SSO, privacy URL and RSC rules using synthetic values. For the
actual package, run from the root:

```sh
python backend/scripts/package_teams_app.py --schema /path/to/MicrosoftTeams.schema.json
shasum -a 256 teams-app/build/clip.zip
```

For an update, add `--previous /path/to/installed/manifest.json` to check the
same app ID and an increased version before replacing the package. Keep the
existing bot registration, compare its registered endpoint with
`https://your-app.example/api/v1/teams/messages`, and record the installed
version and ZIP hash. Use the team's approved tenant installation workflow.
Local validation cannot prove installation rights, consent or callback delivery.
See [Microsoft's package update guidance](https://learn.microsoft.com/en-us/microsoftteams/platform/publishing/office-store-approval).

## OCR in the demo image

`OCR_IN_IMAGE` is `true` in the demo example and the Compose default, which
installs Tesseract and enables OCR for scanned PDFs. Set it to `false` for a
smaller image; scanned pages are then reported as unreadable rather than
silently empty. The image ships English support; additional languages and
LibreOffice vector conversion are outside this image option. A clean synthetic
scan must yield expected text and a blank scan must be labelled unreadable.
Low-contrast and formula samples are observations: OCR text, especially equations,
still needs lecturer review. CI runs the actual extractor and Tesseract inside
the image while the HTTP/database/WebSocket smoke suite runs. This is a short
smoke check, not evidence of capacity under a full classroom load.

To repeat against the selected Compose stack:

```sh
docker compose -p clip-demo -f docker-compose.demo.yml --env-file deploy/demo.env exec -T backend python - < backend/scripts/check_deployed_ocr.py
```

## Real Teams execution record

On an approved test deployment, follow the existing speech-model setup and run
`python scripts/check_live_speech.py` inside the backend container. This loads
the prepared model locally without requesting a microphone, and prints the model
hash and language. Enable Graph automatic drafts only after the tenant owner
verifies permissions, transcript policy and callback setup. Keep the
lecture microphone in a separate visible window and use consented synthetic
teaching phrases. Do not upload speech recordings or raw transcripts as evidence.

Use this list with actual results, per client and release:

| ID | Expected outcome | Actual / evidence |
|---|---|---|
| TEAM-01 | Update/install the validated ZIP, sign in as lecturer and student, link a fresh meeting and start the class. | Not run |
| TEAM-02 | Deliver a checkpoint, verify the targeted notification, answer and view feedback, check bot help/status, reconnect and use the panel after Teams room assignment. | Not run |
| SPEECH-01 | With notice and consent, start lecturer capture; verify the unreviewed timestamped note and the student's cited catch-up answer. | Not run |
| SPEECH-02 | Repeat with domain terminology, varied delivery and background noise. Record utterance end, first visible note and first usable citation; note omissions and wrong terms. | Not run |
| SPEECH-03 | In separate trials stop, hide the page, lose the microphone, pause and end. Check track shutdown, publication stops, and no restart without explicit action. Check any already-committing final segment. | Not run |
| GRAPH-01 | End the meeting; record notification and draft arrival times. Before publishing, confirm the student cannot see or retrieve the draft. Publish, correct and remove a note and recheck student retrieval. | Not run |
| GRAPH-02 | Exercise the existing manual-import fallback and confirm only transcript text is imported. Verify no Teams recording download or persisted lecturer audio. | Not run |
| TEAM-04 | With automatic installation enabled, create a meeting as a linked lecturer and include one of their course codes in the title. After the configured sweep, verify that exactly one C.L.I.P tab opens the class. Repeat with a tab already added manually. | Not run |
| TEAM-05 | Paste the organiser's short Teams link into a prepared class. Verify that it resolves with the tenant's Graph application access policy, then repeat with the full link. Use a student and lecturer to check the side-panel back buttons and lecturer class tools. | Not run |
| TEAM-03 | End and open the student's review in the tested Teams client and supported web browser. Record any unsupported meeting/client types. | Not run |

Attach redacted observations to #239/#234 and link them in #175 with test date,
build/image identity, Teams app/client versions, browser/device, expected/actual
outcome and defect/retest link. Do not use screenshots that expose participant
identity, credentials, private draft text or sensitive live speech.
