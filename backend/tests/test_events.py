"""The WebSocket contract must be complete, single-sourced and free of raw media.

Five workstreams build against these shapes, so an event declared without a
payload is a hole someone falls into weeks later.
"""

import pytest
from pydantic import BaseModel

from app.schemas.events import (
    CLIENT_PAYLOADS,
    SERVER_PAYLOADS,
    AttentionSignalPayload,
    ClientEventType,
    EngagementUpdatePayload,
    RoomStatusPayload,
    ServerEventType,
    SessionStatePayload,
)
from app.schemas.session import EngagementStatus, SessionStatus


def test_every_client_event_declares_a_payload() -> None:
    assert set(CLIENT_PAYLOADS) == set(ClientEventType), (
        "an event type exists with no entry in CLIENT_PAYLOADS"
    )


def test_every_server_event_declares_a_payload() -> None:
    assert set(SERVER_PAYLOADS) == set(ServerEventType), (
        "an event type exists with no entry in SERVER_PAYLOADS"
    )


@pytest.mark.parametrize("model", [m for m in SERVER_PAYLOADS.values() if m is not None])
def test_server_payloads_are_models(model: type[BaseModel]) -> None:
    assert issubclass(model, BaseModel)
    assert model.model_fields, f"{model.__name__} has no fields"


def test_status_values_come_from_the_shared_enums() -> None:
    """Inline string literals would let the REST and WebSocket contracts drift
    apart when someone adds a status."""
    assert SessionStatePayload.model_fields["status"].annotation is SessionStatus
    assert EngagementUpdatePayload.model_fields["status"].annotation is EngagementStatus


def test_attention_signal_carries_indicators_not_media() -> None:
    """Gaze and voice activity are reduced to numbers on the student's device.

    If this ever gains a field holding frames or samples, the privacy claim in
    the README stops being true.
    """
    fields = set(AttentionSignalPayload.model_fields)
    assert fields == {
        "gaze_on_screen_ratio",
        "face_present",
        "speaking",
        "window_seconds",
    }


def test_room_status_reports_activity_not_content() -> None:
    """Breakout monitoring measures whether people are speaking, never what
    they said."""
    fields = set(RoomStatusPayload.model_fields)
    assert "speaking_now" in fields
    assert not any(w in f for f in fields for w in ("transcript", "text", "audio", "content"))


def test_payloads_are_validated_not_just_the_envelope() -> None:
    """Envelope validation only proves `type` is known. Without payload checking
    a malformed answer reaches a handler and fails there instead of at the edge.
    """
    from pydantic import ValidationError

    from app.schemas.events import parse_client_event

    good = {
        "type": "answer.submit",
        "data": {
            "question_id": "11111111-1111-1111-1111-111111111111",
            "selected_option": 2,
            "client_elapsed_ms": 4200,
        },
    }
    event_type, payload = parse_client_event(good)
    assert event_type is ClientEventType.ANSWER_SUBMIT
    assert payload.selected_option == 2

    with pytest.raises(ValidationError):
        parse_client_event({"type": "answer.submit", "data": {"question_id": "not-a-uuid"}})

    with pytest.raises(ValidationError):
        parse_client_event({"type": "definitely.not.an.event", "data": {}})


def test_events_without_a_payload_parse_cleanly() -> None:
    from app.schemas.events import parse_client_event

    event_type, payload = parse_client_event({"type": "ping", "data": {}})
    assert event_type is ClientEventType.PING
    assert payload is None


def test_answer_receipt_is_separate_from_the_result() -> None:
    """Classification takes about 11 seconds for a full cohort, so submission
    must be acknowledged before scoring completes."""
    receipt = SERVER_PAYLOADS[ServerEventType.ANSWER_RECEIPT]
    result = SERVER_PAYLOADS[ServerEventType.FEEDBACK_RESULT]

    assert receipt is not result
    assert "accepted" in receipt.model_fields
    assert "correct" not in receipt.model_fields, "a receipt must not imply a grade"
