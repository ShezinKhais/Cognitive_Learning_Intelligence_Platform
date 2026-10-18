"""The tutor's chat request.

Owner: General CS, Phase 5.

The reply is a stream of events, one JSON object per line, and has no model
here: app/services/tutor_guardrails.py builds each event and the student
panel's chatProtocol.ts reads them. The request is the one part a caller
controls, so it is bounded here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.tutor_guardrails import (
    MAX_ANSWER_CHARS,
    MAX_EARLIER_TURNS,
    MAX_QUESTION_CHARS,
)


class ChatTurn(BaseModel):
    """An earlier exchange the panel sends back with a follow-up. The server
    keeps no conversation, so this is the client's word for it, and the guard
    screens it again before the model sees it."""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)


class ChatRequest(BaseModel):
    # Made by the client and echoed on every event of the reply, so a panel
    # can tell this reply from a stale one. It is written to the log, so it
    # is held to characters that cannot break a log line.
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=MAX_EARLIER_TURNS,
        description="The exchanges before this one, oldest first, so a follow-up can refer to "
        "them. Screened again on the server; never cited.",
    )
