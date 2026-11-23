"""Short-lived capture leases and automatic, explicitly labelled transcript text."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationError
from app.models.discussion_note import DiscussionNote
from app.services import discussion
from app.services.text_screening import safe_display_text

LEASE_SECONDS = 90
MAX_LIVE_SEGMENTS = 1200


@dataclass
class Capture:
    id: UUID
    session_id: UUID
    user_id: UUID
    expires: float
    last_sequence: int = -1
    busy: bool = False
    next_allowed: float = 0


class Captures:
    def __init__(self):
        self.items: dict[UUID, Capture] = {}

    def active(self, session_id: UUID) -> Capture | None:
        now = time.monotonic()
        self.items = {key: value for key, value in self.items.items() if value.expires > now}
        return next((item for item in self.items.values() if item.session_id == session_id), None)

    def start(self, session_id: UUID, user_id: UUID) -> Capture:
        if self.active(session_id):
            raise ConflictError(
                "Live transcription is already running for this class. Stop it first."
            )
        if len(self.items) >= 20:
            raise ConflictError("Live transcription capacity is full. Try again later.")
        item = Capture(uuid4(), session_id, user_id, time.monotonic() + LEASE_SECONDS)
        self.items[item.id] = item
        return item

    def require(self, session_id: UUID, capture_id: UUID, user_id: UUID) -> Capture:
        item = self.active(session_id)
        if item is None or item.id != capture_id or item.user_id != user_id:
            raise ConflictError("This live capture is no longer active. Start it again explicitly.")
        return item

    def stop(self, session_id: UUID, capture_id: UUID) -> None:
        item = self.items.get(capture_id)
        if item is not None and item.session_id == session_id:
            self.items.pop(capture_id, None)


captures = Captures()


async def running_session(db, session_id, principal, *, lock=False):
    row = await discussion.accessible_session(
        db, session_id, principal.user_id, principal.role, write=lock
    )
    if row.status != "active" or row.paused_at is not None:
        raise ConflictError("Live transcription requires a running, unpaused class.")
    return row


def clean_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|https?://\S+", "[removed]", text)
    if not text:
        return ""
    if len(text) > 2000 or safe_display_text(text, limit=len(text)) is None:
        raise ValidationError(
            "This speech segment could not be shared safely. Capture stopped; review manually."
        )
    return text


async def publish(
    db, principal, item: Capture, sequence: int, started_at: datetime, duration: float, text: str
) -> DiscussionNote | None:
    if started_at + timedelta(seconds=duration) > datetime.now(UTC) + timedelta(seconds=2):
        raise ValidationError("The capture timestamp is in the future. Check the lecturer's clock.")
    row = await running_session(db, item.session_id, principal, lock=True)
    if started_at < row.start_time - timedelta(minutes=30):
        raise ValidationError("The capture timestamp is outside this class.")
    captures.require(item.session_id, item.id, principal.user_id)
    note_id = uuid5(item.id, str(sequence))
    if sequence <= item.last_sequence:
        # A lost response retried after lecturer removal must not recreate text.
        return await db.get(DiscussionNote, note_id)
    text = clean_text(text)
    if not text:
        item.last_sequence = sequence
        return None
    if (
        await db.scalar(
            select(func.count())
            .select_from(DiscussionNote)
            .where(
                DiscussionNote.session_id == item.session_id,
            )
        )
        >= discussion.MAX_NOTES
    ):
        raise ConflictError("This class has reached the live transcript limit. Capture stopped.")
    note = DiscussionNote(
        note_id=note_id,
        session_id=item.session_id,
        occurred_at=started_at,
        text=text,
        origin="live_transcript",
    )
    db.add(note)
    await db.commit()
    item.last_sequence = sequence
    await db.refresh(note)
    return note
