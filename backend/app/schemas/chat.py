"""The tutor's chat request.

Owner: General CS, Phase 5.

The reply is a stream of events, one JSON object per line, and has no model
here: app/services/tutor_guardrails.py builds each event and the student
panel's chatProtocol.ts reads them. The request is the one part a caller
controls, so it is bounded here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.tutor_guardrails import MAX_QUESTION_CHARS


class ChatRequest(BaseModel):
    # Made by the client and echoed on every event of the reply, so a panel
    # can tell this reply from a stale one. It is written to the log, so it
    # is held to characters that cannot break a log line.
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
