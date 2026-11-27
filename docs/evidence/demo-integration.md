# Demo integration evidence

Use [PR #333](https://github.com/ShezinKhais/Cognitive_Learning_Intelligence_Platform/pull/333)
to identify the reviewed revision and its automated check results. Record
the deployed revision separately because a passing PR run does not identify
the running test environment.

| Workflow | Requirement tracker | Automated evidence in the repository | Target deployment evidence |
| --- | --- | --- | --- |
| Recap lecture notes, including a named topic and an Arabic request | #318 | `backend/tests/test_discussion.py` | Speech accuracy and latency pending |
| Use the same tutor controls in Teams and the web app | #319 | `frontend/tests/extensionChatParity.test.ts` | Tenant acceptance deferred |
| Prepare a pinned local speech model and report its checksum | #323, #255 | `backend/tests/test_prepare_multilingual_speech.py`, `backend/scripts/check_live_speech.py`, `backend/constraints.txt` | Record the actual model checksum and package versions |
| Restore private student chat history and retry a failed load | #328, #169 | `backend/tests/test_student_chat_history_database.py`, `frontend/tests/chatHistoryRestore.test.ts`, `frontend/e2e/my-data.spec.ts` | Confirm web/API revision, migration head and signed-in student access |
| Show the class average based on marked checkpoint answers | #329 | `frontend/tests/lecturerPerformance.test.ts` | Teams panel acceptance deferred |
| Detect service failure, spikes and recovery | #173 | `backend/tests/test_watch_alerts.py` | Responder assignment and external alert delivery pending |

When recording a run for #175, include the date, tested revision, environment,
workflow, expected result, actual result and any defect or retest link.
The [release checks](../teams-release-acceptance.md) cover build and Teams
package identity. Use redacted evidence and record deferred, blocked and
failed cases as such.
