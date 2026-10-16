"""Cyber 1, Phase 6: privacy verification for attention data.

The promise: the server receives derived numbers about a student's attention,
never the media they came from, keeps no media, and logs no readings. Each
test here is a way that promise could quietly stop being true.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import Float, LargeBinary

import app.models  # noqa: F401  (registers every table on Base)
from app.api.v1 import ws as ws_module
from app.core.database import Base
from app.schemas.events import (
    CLIENT_PAYLOADS,
    MAX_FREE_TEXT_LENGTH,
    AttentionSignalPayload,
    ClientEventType,
    parse_client_event,
)

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
ALLOWED_SIGNAL_FIELDS = {"gaze_on_screen_ratio", "face_present", "speaking", "window_seconds"}


# -- what a client may send --------------------------------------------------------


def test_the_attention_payload_is_exactly_the_allowlist() -> None:
    assert set(AttentionSignalPayload.model_fields) == ALLOWED_SIGNAL_FIELDS


def test_the_attention_payload_holds_only_numbers_and_flags() -> None:
    for name, field in AttentionSignalPayload.model_fields.items():
        annotation = str(field.annotation)
        assert "str" not in annotation and "bytes" not in annotation, name


@pytest.mark.parametrize(
    "extra",
    [
        {"frame": "data:image/jpeg;base64,/9j/4AAQ"},
        {"image": "AAAA"},
        {"landmarks": [[0.1, 0.2, 0.3]] * 468},
        {"audio": "AAAA"},
        {"transcript": "I do not understand"},
        {"user_id": "5b3c0a3e-0000-0000-0000-000000000000"},
        {"device_id": "abc"},
        {"nested": {"gaze_on_screen_ratio": 0.5}},
    ],
)
def test_a_field_outside_the_allowlist_is_refused_not_ignored(extra: dict) -> None:
    data = {"gaze_on_screen_ratio": 0.5, "window_seconds": 5, **extra}
    with pytest.raises(ValidationError):
        AttentionSignalPayload.model_validate(data)
    with pytest.raises(ValidationError):
        parse_client_event({"type": ClientEventType.SIGNAL_ATTENTION.value, "data": data})


def test_a_valid_signal_still_parses() -> None:
    event_type, payload = parse_client_event(
        {
            "type": ClientEventType.SIGNAL_ATTENTION.value,
            "data": {
                "gaze_on_screen_ratio": 0.5,
                "face_present": True,
                "speaking": False,
                "window_seconds": 5,
            },
        }
    )
    assert event_type is ClientEventType.SIGNAL_ATTENTION
    assert isinstance(payload, AttentionSignalPayload)


def test_no_client_event_accepts_a_binary_or_blob_field() -> None:
    for event_type, model in CLIENT_PAYLOADS.items():
        if model is None:
            continue
        for name, field in model.model_fields.items():
            assert "bytes" not in str(field.annotation), f"{event_type}.{name}"


# -- how much a client may send --------------------------------------------------------


def test_the_biggest_honest_event_fits_in_a_frame() -> None:
    free_text = "é" * MAX_FREE_TEXT_LENGTH  # two bytes each
    answer = (
        '{"type":"answer.submit","data":{"question_id":"'
        + "0" * 36
        + '","free_text":"'
        + free_text
        + '"}}'
    )
    assert len(answer.encode()) < ws_module.MAX_FRAME_BYTES


def test_a_frame_of_video_does_not_fit_in_a_frame() -> None:
    assert ws_module.MAX_FRAME_BYTES < 100 * 1024  # a small JPEG is already larger


def test_an_oversized_text_frame_closes_the_socket(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_text("x" * (ws_module.MAX_FRAME_BYTES + 1))
            ws.receive_json()
    assert closed.value.code == ws_module.CLOSE_TOO_BIG


def test_an_oversized_binary_frame_closes_the_socket(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_bytes(b"\xff\xd8\xff" + b"\0" * ws_module.MAX_FRAME_BYTES)
            ws.receive_json()
    assert closed.value.code == ws_module.CLOSE_TOO_BIG


def test_a_small_binary_frame_is_a_malformed_event_not_a_crash(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_bytes(b"\xff\xd8\xff")
            ws.receive_json()
    assert closed.value.code == 4400


def test_a_frame_at_the_limit_is_still_read(client: TestClient) -> None:
    padding = "a" * (ws_module.MAX_FRAME_BYTES - 40)
    text = '{"type":"ping","data":{"pad":"' + padding + '"}}'
    assert len(text) <= ws_module.MAX_FRAME_BYTES
    with pytest.raises(WebSocketDisconnect) as closed:  # noqa: PT012
        with client.websocket_connect("/ws/session") as ws:
            ws.send_text(text)
            ws.receive_json()
    # Read and refused as "not auth" (4001), not cut off for its size.
    assert closed.value.code == 4001


# -- what is kept ------------------------------------------------------------------------


def test_no_table_has_a_binary_column() -> None:
    """Nothing in the schema can hold an image, a frame or audio."""
    binary = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, LargeBinary) or column.type.__class__.__name__ in {"BYTEA"}
    ]
    assert binary == []


def test_no_table_stores_a_raw_attention_reading() -> None:
    """Only the explicitly approved minute aggregates may use visual names.

    These derived ratios are not raw frames, landmarks or per-frame readings.
    No other table (or newly added column) receives a blanket exemption.
    """
    aggregates = {
        "attention_signal_summary.gaze_on_screen_ratio",
        "attention_signal_summary.face_present_ratio",
    }
    names = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    assert aggregates <= names
    for forbidden in ("gaze", "face_present", "landmark", "frame", "audio", "transcript_audio"):
        assert not [n for n in names - aggregates if forbidden in n.split(".")[1]], forbidden


def test_attention_summary_is_a_bounded_schema_of_derived_scalars() -> None:
    from app.models.attention_signal_summary import AttentionSignalSummary

    columns = AttentionSignalSummary.__table__.columns
    assert set(columns.keys()) == {
        "summary_id",
        "session_id",
        "student_id",
        "window_start",
        "window_seconds",
        "sample_count",
        "gaze_on_screen_ratio",
        "face_present_ratio",
        "speaking_ratio",
        "recorded_at",
    }
    for name in ("gaze_on_screen_ratio", "face_present_ratio", "speaking_ratio"):
        assert isinstance(columns[name].type, Float)
        assert columns[name].nullable  # Unavailable signals are not forced to zero.


def test_the_stored_engagement_record_is_derived_data_only() -> None:
    from app.models.engagement_record import EngagementRecord

    columns = set(EngagementRecord.__table__.columns.keys())
    assert {"attempt_rate", "attention_signal", "engagement_score"} <= columns
    assert not {c for c in columns if "gaze" in c or "face" in c or "image" in c}


# -- what is logged ------------------------------------------------------------------------


@pytest.mark.usefixtures("fake_session_repository")
async def test_attention_readings_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    from types import SimpleNamespace  # noqa: F401

    from app.realtime.consent import ConsentRegistry
    from app.schemas.identity import ConsentType, Role

    from .classroom_support import deliver_next, join_as, make_room, make_row

    room, events = make_room(window=0.05, consents=ConsentRegistry())
    row = make_row()
    room.activate(row.session_id)
    _, student = await join_as(events, row.session_id, Role.STUDENT)
    room.admit_consents(
        student,
        {ConsentType.TERMS, ConsentType.ENGAGEMENT_MONITORING, ConsentType.CAMERA},
        room.consents.version(student),
    )
    marker = 0.41373
    with caplog.at_level(logging.DEBUG):
        await room.record_attention(
            row.session_id,
            student,
            AttentionSignalPayload(
                gaze_on_screen_ratio=marker, face_present=True, window_seconds=5
            ),
        )
        await deliver_next(room, row)
        await asyncio.sleep(0.15)
        await room.withdraw_consent(student, ConsentType.CAMERA)
    await room.shutdown()
    assert "41373" not in caplog.text
    assert "gaze_on_screen_ratio" not in caplog.text


def test_no_module_that_handles_attention_logs_a_reading() -> None:
    """A tripwire for the cheap mistake: a log call that names a reading."""
    root = Path(inspect.getfile(ws_module)).parents[2]
    handling = [
        root / "realtime" / "attention.py",
        root / "realtime" / "classroom.py",
        root / "realtime" / "accommodations.py",
        root / "services" / "engagement.py",
        root / "services" / "engagement_baseline.py",
    ]
    pattern = re.compile(
        r"log(?:ger)?\.\w+\([^)]*(gaze|face_present|signal\b|accessibility_need|\.speaking)",
        re.S,
    )
    for path in handling:
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_the_accessibility_need_is_read_in_one_place_only() -> None:
    root = Path(inspect.getfile(ws_module)).parents[2]
    users = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "accessibility_need" in p.read_text(encoding="utf-8")
    )
    assert users == [
        "models/student.py",
        "realtime/accommodations.py",
        "repositories/student_repository.py",
    ]


# -- the browser ------------------------------------------------------------------------------

MEDIA_EGRESS = (
    "MediaRecorder",
    "toDataURL",
    "toBlob(",
    "captureStream",
    "getImageData",
    "readAsDataURL",
    "RTCPeerConnection",
)


@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="frontend not present")
def test_the_frontend_has_no_way_to_record_or_serialise_media() -> None:
    """Camera frames may be read on the device to derive numbers. Nothing in
    the app records, encodes or streams them, so there is nothing to send."""
    found = []
    for path in FRONTEND_SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        found += [f"{path.name}: {api}" for api in MEDIA_EGRESS if api in text]
    assert found == []


@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="frontend not present")
def test_the_frontend_sends_only_json_down_the_socket() -> None:
    offenders = []
    for path in FRONTEND_SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"[sS]ocket\.send\(\s*(\S+)", text):
            if not match.group(1).startswith("JSON.stringify"):
                offenders.append(f"{path.name}: {match.group(0)[:60]}")
    assert offenders == []
