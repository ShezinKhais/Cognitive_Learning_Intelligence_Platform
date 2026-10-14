"""Which breakout room each student is in, and how each room is doing.

Owner: General CS, Phase 6.

A student says which room they are in with `room.confirm`, and that is the
mapping: nothing here guesses it from Teams. A room's status is worked out
from two things its members' devices already send, whether there is voice
activity and whether they are doing the task, and from nothing else. No audio
or transcript exists anywhere to work it out from.

A room nobody has been heard from is `unknown`, not `quiet`: a room where
every member declined the microphone, or has not turned it on, has not been
silent. Silence is counted only from the moment the room was first heard.

Kept in memory with the session, like everything else about a running class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.schemas.events import MAX_ROOM_LABEL_LENGTH, RoomStatus, RoomStatusPayload


class Refusal(StrEnum):
    """Why a room.confirm was not accepted."""

    BLANK = "blank"
    FULL = "full"


def room_key(label: str) -> str:
    """How a label is matched: "Room 1", "room 1" and " ROOM  1 " are one room."""
    return " ".join(label.split()).casefold()


def shown_label(label: str) -> str:
    """The label as it is shown: trimmed, inner whitespace collapsed, and
    free of characters that are not printed."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in label)
    return " ".join(cleaned.split())[:MAX_ROOM_LABEL_LENGTH]


@dataclass(slots=True)
class _Member:
    # When this member's device last reported on voice activity at all.
    heard_at: datetime | None = None
    speaking: bool = False


@dataclass(slots=True)
class _Room:
    label: str
    members: dict[UUID, _Member] = field(default_factory=dict)
    # When anyone in the room last had voice activity.
    spoke_at: datetime | None = None
    # When the room started being heard, after not being heard at all.
    # Silence is counted from here, never from before anyone was listening.
    listening_since: datetime | None = None
    interactions: int = 0


@dataclass(frozen=True)
class RoomLimits:
    # How long one voice reading describes a member.
    fresh: timedelta
    # Silence before a room is quiet, and before it needs attention.
    quiet_after: timedelta
    needs_attention_after: timedelta
    max_rooms: int


class Rooms:
    """The breakout rooms of one live session."""

    def __init__(self) -> None:
        self._rooms: dict[str, _Room] = {}
        self._where: dict[UUID, str] = {}

    def __bool__(self) -> bool:
        return bool(self._rooms)

    def room_of(self, user_id: UUID) -> str | None:
        """The label of the room this student confirmed, if any."""
        key = self._where.get(user_id)
        return self._rooms[key].label if key is not None else None

    def confirm(self, user_id: UUID, label: str, max_rooms: int) -> Refusal | None:
        """Put the student in the room they say they are in, out of any other.

        Refused when the label is blank once cleaned, or it would be a new
        room in a session that already has max_rooms of them: a student
        cannot fill the lecturer's panel with rooms.
        """
        label = shown_label(label)
        key = room_key(label)
        if not key:
            return Refusal.BLANK
        if self._where.get(user_id) == key:
            return None
        # Moving out of a room of one frees its place, so it is not counted.
        alone = self._where.get(user_id)
        frees = alone is not None and len(self._rooms[alone].members) == 1
        if key not in self._rooms and len(self._rooms) - frees >= max_rooms:
            return Refusal.FULL
        self.leave(user_id)
        room = self._rooms.setdefault(key, _Room(label))
        room.members[user_id] = _Member()
        self._where[user_id] = key
        return None

    def leave(self, user_id: UUID) -> str | None:
        """Take the student out of their room. Returns its label. A room
        left empty is dropped, so the panel shows only rooms with someone in."""
        key = self._where.pop(user_id, None)
        if key is None:
            return None
        room = self._rooms[key]
        room.members.pop(user_id, None)
        if not room.members:
            del self._rooms[key]
        return room.label

    def heard(self, user_id: UUID, speaking: bool | None, now: datetime, fresh: timedelta) -> None:
        """Count a member's voice reading towards their room. None is a
        device that did not report on voice at all, and changes nothing."""
        key = self._where.get(user_id)
        if key is None or speaking is None:
            return
        room = self._rooms[key]
        if not _listening(room, now, fresh):
            room.listening_since = now
        member = room.members[user_id]
        member.heard_at = now
        member.speaking = speaking
        if speaking:
            room.spoke_at = now

    def unhear(self, user_id: UUID) -> None:
        """Forget what was heard from a member, as when they withdraw
        microphone consent. They stay in the room."""
        key = self._where.get(user_id)
        if key is not None:
            self._rooms[key].members[user_id] = _Member()

    def interacted(self, user_id: UUID) -> None:
        """Count a member doing the task: answering a question."""
        key = self._where.get(user_id)
        if key is not None:
            self._rooms[key].interactions += 1

    def reporting(self, now: datetime, connected: set[UUID], fresh: timedelta) -> dict[str, int]:
        """For each room, by label, how many of its connected members'
        devices are reporting on voice. A room's status rests on these
        members alone, which is how far it can be trusted."""
        return {
            room.label: len(_heard(room, now, connected, fresh)) for room in self._rooms.values()
        }

    def statuses(
        self, now: datetime, connected: set[UUID], limits: RoomLimits
    ) -> list[RoomStatusPayload]:
        """Every room's status now, in label order. Only members who are
        connected count: one who has left the class is not a silent member."""
        return [
            _status(room, now, connected, limits)
            for _, room in sorted(self._rooms.items(), key=lambda item: item[0])
        ]


def _heard(room: _Room, now: datetime, connected: set[UUID], fresh: timedelta) -> list[_Member]:
    """The connected members whose devices have reported on voice recently."""
    return [
        m
        for u, m in room.members.items()
        if u in connected and m.heard_at is not None and now - m.heard_at <= fresh
    ]


def _listening(room: _Room, now: datetime, fresh: timedelta) -> bool:
    """Whether any member's device has reported on voice recently enough for
    the room to count as heard."""
    return any(m.heard_at is not None and now - m.heard_at <= fresh for m in room.members.values())


def _status(
    room: _Room, now: datetime, connected: set[UUID], limits: RoomLimits
) -> RoomStatusPayload:
    present = {u: m for u, m in room.members.items() if u in connected}
    heard = _heard(room, now, connected, limits.fresh)
    speaking_now = sum(1 for m in heard if m.speaking)
    if not heard or room.listening_since is None:
        status, silence = RoomStatus.UNKNOWN, 0
    elif speaking_now:
        status, silence = RoomStatus.ACTIVE, 0
    else:
        since = max(room.listening_since, room.spoke_at or room.listening_since)
        quiet_for = max(now - since, timedelta(0))
        silence = int(quiet_for.total_seconds())
        if quiet_for >= limits.needs_attention_after:
            status = RoomStatus.NEEDS_ATTENTION
        elif quiet_for >= limits.quiet_after:
            status = RoomStatus.QUIET
        else:
            status = RoomStatus.ACTIVE
    return RoomStatusPayload(
        room_label=room.label,
        status=status,
        members=len(present),
        speaking_now=speaking_now,
        silence_seconds=silence,
        task_interactions=room.interactions,
    )
