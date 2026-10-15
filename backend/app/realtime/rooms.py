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
from uuid import UUID, uuid4

from app.core.config import Settings
from app.realtime.recorders import RoomAlert
from app.schemas.events import MAX_ROOM_LABEL_LENGTH, AlertKind, RoomStatus, RoomStatusPayload
from app.services.ai_explainability import fallback_explanation


class Refusal(StrEnum):
    """Why a room.confirm was not accepted, as the error code the student's
    client is sent."""

    NOT_IN_SESSION = "NOT_IN_SESSION"
    FULL = "ROOM_LIMIT"
    BLANK = "ROOM_LABEL_INVALID"

    @property
    def detail(self) -> str:
        return _REFUSAL_DETAIL[self]


_REFUSAL_DETAIL = {
    Refusal.NOT_IN_SESSION: "only a student in a running session sends room.confirm",
    Refusal.FULL: "this session already has as many rooms as it may",
    Refusal.BLANK: "that room label has nothing in it to show",
}


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

    @classmethod
    def from_settings(cls, settings: Settings) -> RoomLimits:
        return cls(
            fresh=timedelta(seconds=settings.room_voice_fresh_seconds),
            quiet_after=timedelta(seconds=settings.room_quiet_after_seconds),
            needs_attention_after=timedelta(seconds=settings.room_needs_attention_after_seconds),
            max_rooms=settings.max_rooms_per_session,
        )


@dataclass(frozen=True)
class RoomNews:
    """What the lecturer is to be told about the rooms since last time."""

    # Every room whose status changed, including one that has emptied, sent
    # once more with nobody in it so a panel can take it down.
    changed: list[RoomStatusPayload]
    # An alert for each room that has just come to need attention.
    alerts: list[RoomAlert]


class Rooms:
    """The breakout rooms of one live session, and what the lecturer has
    been told about them."""

    def __init__(self, limits: RoomLimits) -> None:
        self.limits = limits
        self._rooms: dict[str, _Room] = {}
        self._where: dict[UUID, str] = {}
        # What staff were last told about each room, by label, so only a
        # change is sent; and the rooms already reported as needing attention.
        self._told: dict[str, RoomStatusPayload] = {}
        self._alerted: set[str] = set()

    def __bool__(self) -> bool:
        return bool(self._rooms)

    def room_of(self, user_id: UUID) -> str | None:
        """The label of the room this student confirmed, if any."""
        key = self._where.get(user_id)
        return self._rooms[key].label if key is not None else None

    def confirm(self, user_id: UUID, label: str) -> Refusal | None:
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
        if key not in self._rooms and len(self._rooms) - frees >= self.limits.max_rooms:
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

    def heard(self, user_id: UUID, speaking: bool | None, now: datetime) -> None:
        """Count a member's voice reading towards their room. None is a
        device that did not report on voice at all, and changes nothing."""
        key = self._where.get(user_id)
        if key is None or speaking is None:
            return
        room = self._rooms[key]
        if not _listening(room, now, self.limits.fresh):
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

    def statuses(self, now: datetime, connected: set[UUID]) -> list[RoomStatusPayload]:
        """Every room's status now, in label order. Only members who are
        connected count: one who has left the class is not a silent member."""
        return [
            _status(room, now, connected, self.limits)
            for _, room in sorted(self._rooms.items(), key=lambda item: item[0])
        ]

    def news(self, session_id: UUID, now: datetime, connected: set[UUID]) -> RoomNews:
        """What has changed since the last call, and the alerts now due,
        remembered as told. A room is alerted once per silence: heard from
        again, its next long silence is alerted too."""
        statuses = {room.room_label: room for room in self.statuses(now, connected)}
        changed = [room for label, room in statuses.items() if self._told.get(label) != room]
        changed += [
            RoomStatusPayload(
                room_label=label,
                status=RoomStatus.UNKNOWN,
                members=0,
                speaking_now=0,
                silence_seconds=0,
                task_interactions=told.task_interactions,
            )
            for label, told in self._told.items()
            if label not in statuses and told.members
        ]
        self._told = statuses

        alerts = []
        for _, room in sorted(self._rooms.items(), key=lambda item: item[0]):
            status = statuses[room.label]
            if status.status is RoomStatus.NEEDS_ATTENTION and room.label not in self._alerted:
                self._alerted.add(room.label)
                reporting = len(_heard(room, now, connected, self.limits.fresh))
                alerts.append(room_alert(session_id, status, reporting, now))
            elif status.status is RoomStatus.ACTIVE:
                self._alerted.discard(room.label)
        self._alerted &= set(statuses)
        return RoomNews(changed, alerts)


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


ROOM_ALERT_EXPLANATION = (
    "Nobody in this room has had voice activity for that long. This is worked out from "
    "whether each member's own device detects a voice. Nothing is recorded or listened "
    "to, and members who have not allowed the microphone are not heard at all, so a room "
    "working quietly looks the same as one that has stopped."
)


def room_alert(
    session_id: UUID, room: RoomStatusPayload, reporting: int, now: datetime
) -> RoomAlert:
    """The alert for a room that has been silent too long. All of it is
    built from the counts, since no model is asked about a room: what was
    measured, how, and how far to trust it. The confidence is the share of
    the room's members whose devices are reporting on voice, because a room
    heard through one member of five is known far less well than one heard
    through all of them."""
    fallback = fallback_explanation(AlertKind.BREAKOUT_INACTIVE)
    reporting = min(reporting, room.members)
    confidence = reporting / room.members if room.members else 0.0
    # In whole minutes once there is one, since that is how a lecturer
    # thinks of it. A deployment with a short limit is told in seconds.
    minutes = room.silence_seconds // 60
    quiet_for = (
        f"{minutes} minute{'' if minutes == 1 else 's'}"
        if minutes
        else f"{room.silence_seconds} seconds"
    )
    members = f"{room.members} member{'' if room.members == 1 else 's'}"
    return RoomAlert(
        alert_id=uuid4(),
        session_id=session_id,
        room_label=room.room_label,
        members=room.members,
        silence_seconds=room.silence_seconds,
        raised_at=now,
        message=f"{room.room_label} has been quiet for {quiet_for}.",
        reason=f"No voice activity from {members} for {room.silence_seconds} seconds.",
        confidence=confidence,
        explanation=ROOM_ALERT_EXPLANATION,
        # Written here and not by a model, which is what "fallback" says.
        explanation_source="fallback",
        confidence_reasons=[
            f"{reporting} of the room's {members} "
            f"{'is' if reporting == 1 else 'are'} reporting voice activity.",
            "Silence is counted only from when the room was first heard.",
        ],
        recommendation=fallback.recommendation,
    )
