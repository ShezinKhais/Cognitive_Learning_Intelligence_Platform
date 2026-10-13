# The tutor's chat route

Owner: General CS, Phase 5. Code: `backend/app/api/v1/chat.py` and
`backend/app/services/tutor_chat.py`.

`POST /api/v1/sessions/{session_id}/chat` lets a student in a session ask the
tutor a question and read the reply as it is written. It joins three pieces of
Phase 5: the student panel (AI 2), the guard that decides what a student may be
told (Cyber 1, `tutor_guardrails.py`), and the AI gateway (`docs/ai-gateway.md`).

## Request

```json
{ "request_id": "3f0c...", "question": "Why are the base layers frozen?" }
```

| Field | Rule |
|---|---|
| `request_id` | 1 to 64 characters from letters, digits, `.`, `_` and `-`. Made by the client and echoed on every event. |
| `question` | 1 to 2000 characters. |

Send it as the signed-in student, with `Accept: application/x-ndjson`.

## Reply

Status 200 with `Content-Type: application/x-ndjson`: one JSON object per line.
Every event has `type` and `request_id`.

| Event | Carries | Meaning |
|---|---|---|
| `accepted` | | Always first. |
| `delta` | `text` | The next piece of the reply. |
| `citation` | `citation` | A passage the reply cites. |
| `follow_up` | `prompt` | A question the student might ask next. |
| `completed` | | The reply is finished. |
| `unsupported` | `reason` | The guard declined the question or withheld the reply. `reason` is a fixed sentence. |
| `empty_retrieval` | | Nothing in the session's material is close enough to the question. |
| `error` | `detail` | The model could not answer. `detail` is a fixed sentence. |

A reply ends with exactly one of `completed`, `unsupported`, `empty_retrieval`
and `error`.

A citation is:

```json
{
  "id": "the excerpt's id",
  "material_title": "week1.pdf",
  "source_page": 3,
  "source_slide": null,
  "excerpt": "Up to 240 characters of the passage."
}
```

Slide decks (`.pptx`, `.ppt`) are cited by `source_slide` and everything else by
`source_page`. The other of the two is null.

To stop a reply, close the connection. The server notices and stops the model.

## Refusals before the reply starts

These are ordinary error responses in the API's usual envelope.

| Status | Code | When |
|---|---|---|
| 401 | `UNAUTHENTICATED` | Not signed in. |
| 403 | `FORBIDDEN` | Signed in, but not as a student. |
| 403 | `CONSENT_REQUIRED` | The student has not agreed to the terms. |
| 404 | `NOT_FOUND` | No such session, the student is not enrolled on its course, or it is over. These are deliberately the same. |
| 409 | `CONFLICT` | The tutor is still answering this student's last question. |
| 422 | `VALIDATION_ERROR` | The body is out of bounds. |
| 429 | `RATE_LIMITED` | More than `CHAT_QUESTIONS_PER_MINUTE` questions in a minute. `detail.retry_after_seconds` says when to try again. |

A request refused for any of the first six does not count against the limit.

## What it searches

Only the material this session draws its questions from: uploaded by the
session's lecturer, for its course or for no course, and finished processing.
Another lecturer's material is never searched, and excerpts embedded by a model
other than `EMBEDDING_MODEL` are left out.

The `CHAT_RETRIEVED_CHUNKS` nearest excerpts are passed to the guard, which
drops any too far from the question.

## The open question

If a question is open in the session, the guard is given its prompt, its
options and its correct option, read from the stored question, so it can refuse
to help with it and can tell when a reply would give the answer away.

## What it costs the live session

Both model calls, embedding the question and writing the reply, go through the
AI gateway at live priority. They wait their turn with every other model call
and are bounded by the gateway's deadlines, so a slow model cannot hold up the
class. No database connection is held while the model writes.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `CHAT_QUESTIONS_PER_MINUTE` | 6 | Questions one student may ask in a minute. |
| `CHAT_RETRIEVED_CHUNKS` | 5 | Excerpts put to the model with a question. |

## Not done here

- Follow-up prompts come from the guard's own safe set. Asking the model to
  suggest them is a second model call for every question and is left out.
- Exchanges are not stored.
- The limits are kept in memory, like the hub and the classroom, so they are
  per process.
