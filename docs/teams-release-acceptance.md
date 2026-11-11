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

Record the actual web and backend image IDs and architecture using
`docker image inspect --format '{{.Id}} {{.Architecture}}'`, the database
image digest, migration via `alembic current` inside the backend, frontend
lockfile hash, and installed Python versions via `python -m pip list --format=freeze`
inside the backend. Record effective feature switches, exact model names/digests,
speech model hash/language, and the prompt/evaluation source commit. Copy only
these selected values. Do not export full environment files, image environment
fields, credentials or meeting identifiers into shared evidence.

Keep the tested images under their release tag or export them with `docker save`;
retaining the actual images allows re-use even if a base tag or package changes.
This does not make a clean rebuild from floating base tags/Python ranges bitwise
reproducible. For rollback, stop live classes, check migration compatibility with
the older images and follow the existing database backup/restore runbook if
needed. Select the previously recorded image tag and run Compose with
`--no-build`; verify both identities before resuming. Do not rebuild an older
tag from the current checkout or automatically downgrade a production database.

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

Set `OCR_IN_IMAGE=true` before building to install Tesseract and enable OCR for
scanned PDFs. The image ships English support; additional languages and
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
| TEAM-03 | End and open the student's review in the tested Teams client and supported web browser. Record any unsupported meeting/client types. | Not run |

Attach redacted observations to #239/#234 and link them in #175 with test date,
build/image identity, Teams app/client versions, browser/device, expected/actual
outcome and defect/retest link. Do not use screenshots that expose participant
identity, credentials, private draft text or sensitive live speech.
