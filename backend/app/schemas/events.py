"""WebSocket event contract.

Every live message is a JSON object with a `type` discriminator and a `data`
payload. Both directions are versioned together with the REST API.

Ordering and replay
-------------------
Server events carry a monotonically increasing `seq` per session or user
channel. A client that reconnects sends `last_seq` so the server can replay
missed material-progress events. Session-wide replay lands in Phase 3.

Privacy
-------
`signal.attention` carries derived numbers only: a gaze ratio and a speaking
boolean. Raw frames and audio never leave the student's device, and no event
type is capable of carrying them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.session import EngagementStatus, SessionStatus

# Client to server fields are the one part of this contract an unauthenticated
# or hostile caller controls, so the string ones are bounded here. Without a
# limit a single frame can carry megabytes into whatever stores it in Phase 3.
MAX_TOKEN_LENGTH = 4096
MAX_FREE_TEXT_LENGTH = 4000
MAX_ROOM_LABEL_LENGTH = 100

# An attention window is a summary of the last few seconds. An hour is already
# far past anything the client sends and rules out a value that would swamp a
# per-second average.
MAX_ATTENTION_WINDOW_SECONDS = 3600.0


class QuestionCloseReason(StrEnum):
    WINDOW_ELAPSED = "window_elapsed"
    LECTURER_CLOSED = "lecturer_closed"
    SESSION_ENDED = "session_ended"


class AlertKind(StrEnum):
    TOPIC_DIFFICULTY = "topic_difficulty"
    STUDENT_DISENGAGEMENT = "student_disengagement"
    BREAKOUT_INACTIVE = "breakout_inactive"


class MaterialStage(StrEnum):
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class RoomStatus(StrEnum):
    """UNKNOWN is distinct from QUIET: absent data is not evidence of silence."""

    ACTIVE = "active"
    QUIET = "quiet"
    NEEDS_ATTENTION = "needs_attention"
    UNKNOWN = "unknown"


class ClientEventType(StrEnum):
    AUTH = "auth"
    PING = "ping"
    ANSWER_SUBMIT = "answer.submit"
    PROMPT_ACK = "prompt.ack"
    SIGNAL_ATTENTION = "signal.attention"
    ROOM_CONFIRM = "room.confirm"


class ServerEventType(StrEnum):
    READY = "ready"
    PONG = "pong"
    SESSION_STATE = "session.state"
    QUESTION_DELIVERED = "question.delivered"
    QUESTION_CLOSED = "question.closed"
    ANSWER_RECEIPT = "answer.receipt"
    FEEDBACK_RESULT = "feedback.result"
    PROMPT_ATTENTION = "prompt.attention"
    ENGAGEMENT_UPDATE = "engagement.update"
    ALERT_RAISED = "alert.raised"
    MATERIAL_PROGRESS = "material.progress"
    ROOM_STATUS = "room.status"
    ERROR = "error"


# --------------------------------------------------------------------------
# Client to server
# --------------------------------------------------------------------------


class AuthPayload(BaseModel):
    # The first frame an unauthenticated socket sends, so both fields are
    # bounded before anything reads them.
    token: str = Field(max_length=MAX_TOKEN_LENGTH)
    session_id: UUID | None = None
    last_seq: int | None = Field(
        default=None,
        ge=0,
        description="Highest seq already received. Triggers replay on reconnect.",
    )


class AnswerSubmitPayload(BaseModel):
    question_id: UUID
    # Exactly one is set, enforced below. MCQ ships first; free text is added
    # over the same path.
    selected_option: int | None = Field(default=None, ge=0)
    # min_length matters as much as max: an empty string satisfies "exactly one
    # is set" while carrying no answer at all.
    free_text: str | None = Field(default=None, min_length=1, max_length=MAX_FREE_TEXT_LENGTH)
    client_elapsed_ms: int = Field(
        ge=0, description="Time from delivery to submit, measured on the client."
    )

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> AnswerSubmitPayload:
        """A submission with neither field is not an answer, and one with both
        has no defined meaning.

        The comment above claimed this invariant without enforcing it, which
        left the Phase 3 handler to discover an empty submission at scoring
        time and decide what a half-answered question counts as.
        """
        answered = (self.selected_option is not None) + (self.free_text is not None)
        if answered != 1:
            raise ValueError("set exactly one of selected_option or free_text")
        return self


class PromptAckPayload(BaseModel):
    prompt_id: UUID
    dismissed: bool = False


class AttentionSignalPayload(BaseModel):
    """Derived indicators only. Computed on the student's device."""

    gaze_on_screen_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    face_present: bool | None = None
    speaking: bool | None = Field(default=None, description="Voice activity, not speech content.")
    window_seconds: float = Field(
        gt=0.0,
        le=MAX_ATTENTION_WINDOW_SECONDS,
        description="Period these values summarise.",
    )


class RoomConfirmPayload(BaseModel):
    """Student's one-tap confirmation of which breakout room they are in.

    This is the authoritative mapping, not a correction to one.
    """

    room_label: str = Field(min_length=1, max_length=MAX_ROOM_LABEL_LENGTH)


class ClientEvent(BaseModel):
    type: ClientEventType
    data: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Server to client
# --------------------------------------------------------------------------


class SessionStatePayload(BaseModel):
    """Sent on join and whenever the session changes state, so a client that
    connects late renders the right thing without polling."""

    session_id: UUID
    status: SessionStatus
    participant_count: int
    active_question_id: UUID | None = None
    questions_delivered: int = 0


class QuestionDeliveredPayload(BaseModel):
    question_id: UUID
    prompt: str
    options: list[str] | None = Field(default=None, description="Null for free-text questions.")
    closes_at: datetime
    window_seconds: int
    source_slide: int | None = None


class QuestionClosedPayload(BaseModel):
    """The response window has shut. Students stop being able to answer; the
    lecturer panel switches from a countdown to results."""

    question_id: UUID
    reason: QuestionCloseReason
    respondents: int
    eligible: int


class AnswerReceiptPayload(BaseModel):
    """Immediate acknowledgement that a submission was stored.

    Sent before any scoring. Free-text classification takes around 11 seconds
    for a full cohort, so the student must see confirmation now rather than
    waiting for a result.
    """

    question_id: UUID
    accepted: bool
    received_at: datetime
    reason: str | None = Field(default=None, description="Set when accepted is false.")


class FeedbackResultPayload(BaseModel):
    question_id: UUID
    correct: bool | None = Field(default=None, description="Null while free text is classifying.")
    explanation: str | None = None
    source_slide: int | None = None


class AttentionPromptPayload(BaseModel):
    """A private nudge to one student. Never visible to the class, and it does
    not contribute to comprehension, only to engagement and presence."""

    prompt_id: UUID
    message: str
    expires_at: datetime
    escalation: int = Field(
        default=1, ge=1, description="Which consecutive prompt this is for the student."
    )


class EngagementUpdatePayload(BaseModel):
    """Engagement only. Comprehension is a separate concept and is never merged
    into this number."""

    score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: EngagementStatus
    confidence: float = Field(ge=0.0, le=1.0)


class AlertRaisedPayload(BaseModel):
    alert_id: UUID
    kind: AlertKind
    message: str
    reason: str = Field(description="Plain-language justification. Required, never empty.")
    confidence: float = Field(ge=0.0, le=1.0)


class MaterialProgressPayload(BaseModel):
    material_id: UUID
    stage: MaterialStage
    percent: int = Field(ge=0, le=100)
    message: str | None = None


class RoomStatusPayload(BaseModel):
    """Breakout room activity, derived from voice-activity detection and task
    interaction. Carries no audio, no transcript and no speech content."""

    room_label: str
    status: RoomStatus
    members: int
    speaking_now: int = Field(description="How many members are currently speaking.")
    silence_seconds: int
    task_interactions: int = 0


class ReadyPayload(BaseModel):
    """Handshake complete. The client may start sending events."""

    user_id: UUID
    session_id: UUID | None = None
    resumed_from_seq: int | None = Field(
        default=None, description="Set when the server continued the requested sequence stream."
    )


class ErrorPayload(BaseModel):
    code: str
    detail: str | None = None


class ServerEvent(BaseModel):
    type: ServerEventType
    seq: int = Field(description="Monotonic per channel. Clients use it to detect gaps.")
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)


# Every event type maps to the model describing its `data`. None means the event
# carries no payload. A test asserts this covers both enums, so an event cannot
# be declared without also declaring its shape.
CLIENT_PAYLOADS: dict[ClientEventType, type[BaseModel] | None] = {
    ClientEventType.AUTH: AuthPayload,
    ClientEventType.PING: None,
    ClientEventType.ANSWER_SUBMIT: AnswerSubmitPayload,
    ClientEventType.PROMPT_ACK: PromptAckPayload,
    ClientEventType.SIGNAL_ATTENTION: AttentionSignalPayload,
    ClientEventType.ROOM_CONFIRM: RoomConfirmPayload,
}


def parse_client_event(raw: dict[str, Any]) -> tuple[ClientEventType, BaseModel | None]:
    """Validate an inbound message and its payload against the registry.

    Envelope validation alone only proves `type` is known, so without this a
    malformed `answer.submit` reaches a handler and fails there instead of at
    the boundary. Raises pydantic.ValidationError for the caller to translate
    into a close code or an error event.
    """
    event = ClientEvent.model_validate(raw)
    model = CLIENT_PAYLOADS[event.type]
    return event.type, model.model_validate(event.data) if model else None


SERVER_PAYLOADS: dict[ServerEventType, type[BaseModel] | None] = {
    ServerEventType.READY: ReadyPayload,
    ServerEventType.PONG: None,
    ServerEventType.SESSION_STATE: SessionStatePayload,
    ServerEventType.QUESTION_DELIVERED: QuestionDeliveredPayload,
    ServerEventType.QUESTION_CLOSED: QuestionClosedPayload,
    ServerEventType.ANSWER_RECEIPT: AnswerReceiptPayload,
    ServerEventType.FEEDBACK_RESULT: FeedbackResultPayload,
    ServerEventType.PROMPT_ATTENTION: AttentionPromptPayload,
    ServerEventType.ENGAGEMENT_UPDATE: EngagementUpdatePayload,
    ServerEventType.ALERT_RAISED: AlertRaisedPayload,
    ServerEventType.MATERIAL_PROGRESS: MaterialProgressPayload,
    ServerEventType.ROOM_STATUS: RoomStatusPayload,
    ServerEventType.ERROR: ErrorPayload,
}
