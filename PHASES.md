\# CLIP (Cognitive Learning Intelligence Platform) — Full Project Phases



An AI-powered engagement assistant for live online classes. Provides real-time

attention tracking, RAG-based adaptive questions, and Socratic chatbot guidance

to combat student disengagement, using a privacy-first, human-in-the-loop approach.



Six roles work in parallel across phases: General CS, BBIS, AI 1, Cyber 2, AI 2, Cyber 1.



\---



\## Phase 1: Data and API spine

\*\*Weeks 2–3 — Critical path\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Build FastAPI application modules, dependency injection, central error handling, configuration management, service-health checks and API versioning. Define REST and WebSocket contracts with all members. | Working `/api/v1` backend and frozen API specification. |

| BBIS | Convert the ERD into SQLAlchemy models and Alembic migrations. Add approximately 20 core models, indexes, constraints and seed data for one course, one lecturer and 40 students. Build initial repository/query layer. | Reproducible database with migrations, rollback and seed script. |

| AI 1 | Build the file-processing service interface, upload processing contract and extraction-router skeleton. Define common extracted-element and content-chunk schemas. | Extraction API contract and test output for each supported format. |

| Cyber 2 | Build the secure administrator console for timetable CSV/XLSX upload, roster preview, conflict display and lecturer assignment. Implement protected staff routes. | Functional timetable and roster interface using mocked or real APIs. |

| AI 2 | Port the student prototype into the actual frontend. Remove duplicate components, add routing, typed API client, authentication state and shared state management. | Student app connected to API mocks or initial backend endpoints. |

| Cyber 1 | Implement password hashing, login, token validation, RBAC middleware, ownership checks, consent gate and audit decorator for state-changing endpoints. | Authentication, RBAC and consent tests passing. |



\---



\## Phase 2: Content and question pipeline

\*\*Weeks 3–5 — Runs partly alongside Phase 1\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Implement background-processing coordination, job status, file-storage interface and WebSocket processing-progress events. Connect upload, parser, chunker and embedding services. | Upload triggers processing and reports progress without blocking the API. |

| BBIS | Implement material, extraction-element, chunk, embedding, processing-status and AI-model-run tables. Build materials API persistence and status queries. | Every processing step stored and traceable by material ID. |

| AI 1 | Implement extraction router, structure-preserving hybrid chunking, batched embeddings, pgVector retrieval, MCQ generation, source citations and generation validation. | Lecturer material produces grounded draft questions with page or slide references. |

| Cyber 2 | Build the lecturer question-review interface: approve, edit, reject, approve all, regenerate and stage for delivery. Protect review operations by lecturer and session ownership. | Fully functional human-in-the-loop review screen. |

| AI 2 | Build lecturer upload and progress components, extracted-content preview, source-reference display and processing-error states. Assist with identification of thin or image-heavy pages. | Upload UI displays status, warnings and extracted source information. |

| Cyber 1 | Implement secure upload rules, file validation, MIME checks, filename handling and processing limits. Test prompt injection, malicious document instructions and unsupported question generation. | Upload-security and AI-grounding test report. |



\---



\## Phase 3: Live session core

\*\*Weeks 5–8 — Critical path\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Build WebSocket hub, per-session rooms, per-user channels, reconnect handling, buffered event replay, prompt scheduler, configurable question cycle, manual trigger, 30-second response window and session lifecycle. | Reliable live event system with start, pause, reconnect and end behaviour. |

| BBIS | Implement session, participant, delivered-question, response, missed-response, prompt-response and activity persistence. Build dashboard query layer. | All live events stored correctly and retrievable by session. |

| AI 1 | Implement MCQ scoring, answer validation, instant feedback and source-slide/page reference. Prepare the interface for later free-text classification. | Submitted MCQ receives correct scoring and source-grounded feedback. |

| Cyber 2 | Build lecturer live panel, participant view, manual question trigger, live result distribution, alert area and session controls. | Lecturer can operate a complete live session from the staff interface. |

| AI 2 | Build student in-meeting panel, checkpoint card, timer, response submission, missed-response state, reconnect state and private attention-prompt interface. | Student can join, answer and recover after disconnection. |

| Cyber 1 | Implement camera-free engagement scoring v1, dynamic attention prompts, minimum-respondent guard and class comprehension alert. Validate event permissions and session ownership. | Separate engagement and comprehension results with explainable alerts. |



\---



\## Phase 4: Microsoft Teams integration

\*\*Weeks 7–10 — Gated by IT approval\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Run Teams iframe and background-tab spikes. Build Teams app configuration, manifest, bot/meeting adapter, development tunnel, meeting-event handling, automatic session creation and archival. Maintain mock Teams fallback. | Teams meeting events reach C.L.I.P, or equivalent events work through the fallback adapter. |

| BBIS | Store meeting IDs, Teams user mappings, roster-sync events and participant mappings. Handle duplicate, missing and unmatched participant records. | Teams meeting and roster data reliably linked to C.L.I.P sessions. |

| AI 1 | Build pre-session content-readiness gate. Prevent a session from beginning until required material has processed and approved questions are available. | Clear readiness status and blocked-start response when content is incomplete. |

| Cyber 2 | Build secure pre-meeting lecturer tab and staff personal-app pages. Configure frontend CSP, environment separation and Teams staff routes. | Staff Teams surfaces load securely and respect role permissions. |

| AI 2 | Implement TeamsJS, `getContext()`, student identity/meeting context, in-meeting panel, notification card and Teams light, dark and high-contrast handling. | Student panel works in the Teams context or simulated Teams shell. |

| Cyber 1 | Review Teams permissions, validate mapped identities, apply least privilege, enforce consent across Teams surfaces and test unauthorised meeting access. | Teams permission and security review completed. |



\---



\## Phase 5: AI intelligence layer

\*\*Weeks 8–12\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Add AI request queue, streaming model responses, cancellation, model warm-up, timeout, retry and failure fallback. | AI operations do not block the live-session service. |

| BBIS | Implement classification, confidence, alert, explanation and recommendation persistence. Maintain hand-labelled evaluation data and model-version statistics. | AI results are stored, comparable and traceable to model and prompt versions. |

| AI 1 | Implement free-text classification into Mastered, Partial and Struggling; semantic answer comparison; confidence calculation; topic-level difficulty analysis and accuracy baseline. | Classification tested against a labelled answer set. |

| Cyber 2 | Build topic-recovery dashboard, classification details, confidence display, source citations, AI recommendation view and lecturer acknowledgement. | Lecturer sees why a topic or student was flagged. |

| AI 2 | Build Socratic chatbot UI, streaming text, citations, follow-up prompts, unsupported-query state, empty-retrieval state and response cancellation. | Student receives guided, source-linked help without direct final answers. |

| Cyber 1 | Implement chatbot guardrails, prompt-injection defence, direct-answer restriction, explainability rules, confidence reasons and lecturer recommendation logic. | Every AI alert and recommendation has a safe reason and fallback explanation. |



\---



\## Phase 6: Attention and breakout groups

\*\*Weeks 10–13 — Optional/advanced phase\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Implement lightweight signal transport, aggregation, room-level status events and private refocus-prompt delivery. | Attention indicators reach the analytics layer without transmitting raw media. |

| BBIS | Create breakout-room, group-membership, group-status, signal-summary and student-confirmation tables and APIs. | Group activity records stored and linked to the correct session. |

| AI 1 | Implement breakout-room OCR and roster fuzzy matching where needed. Build balanced-group recommendation using comprehension data. | Proposed groups are explainable and can be manually changed by the lecturer. |

| Cyber 2 | Build group-formation UI, recommendation review, manual editing and live breakout-room status display. | Lecturer controls final grouping and can view room-level indicators. |

| AI 2 | Implement MediaPipe gaze, local face/head-direction indicators, microphone VAD, self-hosted WASM, permission flow, privacy indicator and one-click disable. | Local indicators work without raw image or audio transmission. |

| Cyber 1 | Implement personal baselines, signal renormalisation, availability handling, accessibility threshold rules and privacy verification. | Engagement remains usable and fair when signals are missing. |



\---



\## Phase 7: Reporting and governance

\*\*Weeks 12–15\*\*



| Member | Exact work | Required deliverable |

|---|---|---|

| General CS | Build report-generation queue, export orchestration, scheduled jobs and scheduled purge runner integration. | Reports and governance jobs run without blocking normal sessions. |

| BBIS | Implement 90-day retention rules, student deletion, cascading-deletion checks, backup, restoration and report-data validation. | Retention, deletion and recovery tests pass. |

| AI 1 | Implement summary/reporting agent using structured session data. Generate student and lecturer summaries with source-grounded topic information. | AI summaries generated from verified database values. |

| Cyber 2 | Build report interface, PDF export, audit-log viewer, governance panel, retention controls and authorised deletion-request interface. | Staff can securely review reports and governance events. |

| AI 2 | Build student review-session interface, separate engagement/comprehension view and wrong-answer links to relevant source chunks. | Student receives understandable, source-linked post-session feedback. |

| Cyber 1 | Validate summaries, ensure engagement and comprehension remain separate, generate action items, review explanations and verify audit/privacy rules. | Reports meet responsible-AI and privacy requirements. |



\---



\## Phase 8: Hardening and delivery

\*\*Weeks 15–16 — All hands\*\*



| Member | Exact work | Required evidence |

|---|---|---|

| General CS | Test 40 concurrent student connections, WebSocket reconnect, scheduler load, service failures, Teams/mock adapter and demo deployment. | Load-test and failure-recovery report. |

| BBIS | Run database integrity tests, performance queries, migration rollback, purge simulation, deletion test and backup restoration. | Database integrity and recovery evidence. |

| AI 1 | Test parser coverage, retrieval precision, question grounding and classification accuracy against labelled examples. | AI evaluation report with baseline metrics. |

| Cyber 2 | Test staff permissions, insecure object access, report downloads, deployment security headers, frontend accessibility and demo workflow. Coordinate poster and interface screenshots. | Staff-interface, deployment and accessibility test evidence. |

| AI 2 | Test Chrome, Edge, Teams web view, weaker devices, camera/microphone denial, gaze/VAD performance, keyboard access and reduced-motion behaviour. | Student-interface and client-AI test report. |

| Cyber 1 | Conduct authentication, RBAC, consent, API, prompt-injection, OWASP LLM and no-raw-media privacy review. | Final security and privacy audit. |



\---



\## Notes for autonomous implementation



\- Phases 1 and 2 are already implemented on `main` in this repository — treat that code as the ground truth for existing patterns (auth via `app/api/deps.py`, error handling via `app/core/errors.py`, the review-router + ownership-guard pattern in `app/api/v1/content.py`, repository pattern in `app/repositories/`).

\- The API contract is frozen and tracked in `backend/openapi.json` and `backend/events.schema.json`, regenerated via `backend/scripts/export\_contract.py`.

\- Where a phase's spec is ambiguous or requires a judgment call another team member would normally make, make a reasonable decision and document it clearly in code comments and commit messages rather than stopping.

\- Run `ruff check`, `ruff format --check`, and the full `pytest` suite after each phase before moving to the next. Regenerate the API contract whenever routes or schemas change.

