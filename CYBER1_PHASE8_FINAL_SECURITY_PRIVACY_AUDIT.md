# Cyber 1, Phase 8: final security and privacy audit

Issue #76. Evidence: *final security and privacy audit*.
Branch `hunain-phase-8`, built on `main`. It audits the application as it stands on `main`, plus
the Phase 6 (#143) and Phase 7 (#144) work, which are separate PRs; where an item depends on
them it says so. The audit is executable: `tests/test_security_audit.py` and
`tests/test_llm_attack_corpus.py` fail when a route is added without an audience, or when an
attack gets through, so it does not go stale.

## 1. Scope and method

Authentication, RBAC, consent, API surface, prompt injection, OWASP LLM Top 10, and the
no-raw-media promise. Method: read every security-relevant module, then test black-box
against the published OpenAPI document and the WebSocket, then try to break each control.
Where the controls held, tests now pin them. Where they did not, the finding is below.

## 2. Findings

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | High | `CLIP_ENV` failed open. Any value other than `production`/`prod` (`"staging"`, `"prod-eu"`, `"Production "` with a stray space) counted as development: interactive docs and OpenAPI exposed, dev CORS on, the well-known development accounts enabled, production safety checks (secret key, database password) skipped | `CLIP_ENV` is normalised (trim, lower case) and anything not in the known list is refused at startup |
| F2 | Medium | No limit on how fast one WebSocket may send events, or how many sockets one user may hold open. Every event takes the session lock, so one student could slow a class | Sliding-window limit (100 events / 10 s) closes the socket with 4429; at most 10 sockets per user per class |
| F3 | Medium | The tutor's input screen missed paraphrased overrides ("Pretend you have no guidelines", "Override your safety settings", "Stop being a tutor"), prompt extraction by count or summary ("first 50 words of your instructions", "the rules you were told"), chat-template markers (`<\|im_start\|>`, `</s><s>`, `### SYSTEM`), and "ignore previous instructions" in Spanish, French, German, Chinese, Arabic and Russian | Patterns added; ordinary study questions in the same languages are tested to still pass |
| F4 | Medium | Indirect injection: a lecture excerpt or topic name carrying the same attack disguised as rot13, base64, or dotted letters (`i.g.n.o.r.e`), or in another language, reached the model / the lecturer's screen | The shared screening variants (`text_variants.py`, used by question generation, the tutor's context filter and every `safe_display_text`) now also read rot13, base64 runs and dotted letters, and one shared pattern covers the other languages and template markers |
| F5 | Low | API responses carried no `X-Content-Type-Options`, `Referrer-Policy` or cache directive, though they hold student data | Added to every response; `Cache-Control: no-store` on `/api/v1` unless a route sets its own. No `X-Frame-Options`: a Teams tab frames this app by design |

## 3. Controls that held (pinned by tests, no change needed)

| Area | Evidence |
|---|---|
| Authentication | 31 of 35 published routes reject an anonymous caller with 401 (the other four are the named public list: login, health, ready, Teams bot); bad schemes, `alg: none`, a token signed with another key, an expired token, and a token whose role claim no longer matches the user are all refused |
| RBAC | Every route has a declared audience (`AUDIENCE` table). A student reaches no staff route (403 on all of them); a lecturer reaches no admin route; staff do not use the tutor; another lecturer gets a 404 on every session-scoped route of a session they do not run |
| Consent | Every route except the consent route and `/auth/me` refuses a user without terms consent (403) |
| Error handling | No response in the matrix contains a traceback, file path, SQL, driver name or secret |
| IDOR | Materials and questions are scoped to the uploader; sessions, alerts and summaries to the running lecturer; covered by the matrix and by earlier phases' tests |
| Production config | Secret key length and default, database host and password strength refused at startup; docs, OpenAPI and dev CORS off in production |
| Tutor output | Answer-leak, citation and link checks on the model's reply (Phase 5) |

## 4. OWASP Top 10 for LLM Applications (2025)

| # | Risk | Where it is handled | Status |
|---|---|---|---|
| LLM01 | Prompt injection | Direct: `screen_question`. Indirect: `screen_context`, `generation.screened`, `safe_display_text`, report validation. One shared set of screening variants. Corpus of 41 attacks run through every surface | Covered (F3, F4) |
| LLM02 | Sensitive information disclosure | Tutor sees only excerpts and a question; the correct option is never sent to the model; answers checked on the way out; reports refuse accommodations and raw readings (#144) | Covered |
| LLM03 | Supply chain | Models run locally via Ollama; dependencies pinned in `pyproject.toml`; no model weights or code fetched at runtime | Residual: R23 |
| LLM04 | Data and model poisoning | Lecturer material is screened before it reaches generation; generated questions need lecturer approval before any student sees them | Covered |
| LLM05 | Improper output handling | Model text is never rendered as markup (markup and links refused), never executed, and shown as text; alert and report text built from templates | Covered |
| LLM06 | Excessive agency | The model has no tools: it cannot call routes, write data or send messages. It returns text that code validates | Covered |
| LLM07 | System prompt leakage | Extraction attempts refused (F3); the prompt holds no secrets, only behaviour rules; replies echoing it are refused | Covered |
| LLM08 | Vector and embedding weaknesses | Retrieval is scoped to the session's course material; a distance floor drops irrelevant excerpts; excerpts carrying instructions are dropped | Covered |
| LLM09 | Misinformation | Tutor answers must be grounded in cited excerpts or say so; summaries are templates over counted values; uncertain classifications are not reported as fact | Covered |
| LLM10 | Unbounded consumption | Per-student tutor rate limit, global AI queue and concurrency limits, request and stream timeouts, circuit breaker, question length cap, upload limits, and (F2) the socket event limit | Covered |

## 5. No raw media

Derived numbers only cross the wire. Evidence: `AttentionSignalPayload` is closed to unknown
fields and holds only numbers and flags; frames over 64 KiB close the socket; no table has a
binary column or a raw gaze/face/audio column; no log line carries a reading; the frontend has
no way to record or serialise media (all in #143's `test_privacy_verification.py`). With this
branch, the whole path was exercised together (section 7).

## 6. Verification

ruff, format, contract check, single alembic head, full pytest on Postgres (1827 passed).
Mutation pass over every control added in this phase: 35 deliberate breaks, 32 caught; the other 3 are equivalent (a no-op rewrite, a branch the earlier check already makes unreachable, and a redundant second pattern check that was removed as a result).

## 7. Integration check

main + #143 + #144 + this branch merged in a scratch worktree and the full suite run on the
result: 1995 passed, ruff and the contract check clean, and the three branches merge without conflicts.
The audit matrix also checks #144's summary route (404 for another lecturer) once it is present.

## 8. Residual risks

| # | Risk |
|---|---|
| R23 | Dependencies are not scanned for known vulnerabilities in CI; recommend `pip-audit` as a CI step |
| R24 | `/health` still returns the environment name and whether Teams is configured, to anyone. The response shape is frozen; harmless but avoidable |
| R25 | Tutor screening is pattern-based. It raises the cost of an attack and is backed by output checks, but a novel phrasing in a language not listed can pass the input screen; the output checks and the model having no tools are what bound the harm |
| R26 | `GET /sessions`, `GET /sessions/{id}` and `GET /sessions/{id}/responses` are still 501 stubs. `test_unimplemented_routes_are_known` fails when one is implemented, so its audience gets checked then |
| R27 | In-memory state (rate limits, engagement scores, consent registry) is per process; a multi-instance deployment needs sticky sessions or a shared store |
| R28 | `audit_log` records who and when but not the target of a staff view (see #144 R20) |
