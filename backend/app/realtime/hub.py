"""Connection registry and fan-out for live sessions.

Phase 1 provides the registry, sequencing and broadcast paths. Phase 3 adds the
replay buffer, so that a student who loses wifi mid-question receives what they
missed rather than a blank panel.

Sequence numbers are per session and assigned here, so every client can detect
a gap by comparing the seq it receives against the last one it saw.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket

from app.schemas.events import ServerEvent, ServerEventType

log = logging.getLogger("clip.realtime")


class Connection:
    def __init__(self, websocket: WebSocket, user_id: UUID, session_id: UUID | None) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.session_id = session_id
        self.connected_at = datetime.now(UTC)


class SessionHub:
    """Tracks who is connected to which session and delivers events to them.

    One instance per process. With a single backend host that is sufficient; a
    multi-host deployment would need the registry moved to Redis, which is out
    of scope for a prototype serving one lecturer at a time.
    """

    def __init__(self) -> None:
        self._rooms: dict[UUID, set[Connection]] = defaultdict(set)
        self._seq: dict[UUID, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def join(self, connection: Connection) -> None:
        if connection.session_id is None:
            return
        async with self._lock:
            self._rooms[connection.session_id].add(connection)
        log.info("user %s joined session %s", connection.user_id, connection.session_id)

    async def leave(self, connection: Connection) -> None:
        if connection.session_id is None:
            return
        async with self._lock:
            room = self._rooms.get(connection.session_id)
            if room:
                room.discard(connection)
                if not room:
                    del self._rooms[connection.session_id]
        log.info("user %s left session %s", connection.user_id, connection.session_id)

    def forget_session(self, session_id: UUID) -> None:
        """Drop a finished session's room and sequence counter.

        Owner: General CS, Phase 3. Nothing calls this yet because the session
        lifecycle arrives with the scheduler. Until then `_seq` keeps one entry
        per session for the life of the process, which is a slow leak rather
        than a correctness problem.

        Call it only once a session has genuinely ended. `leave` already drops
        an empty room, and clearing the counter while a session is still
        running restarts seq at 1, which clients read as a gap.
        """
        self._rooms.pop(session_id, None)
        self._seq.pop(session_id, None)

    def participant_count(self, session_id: UUID) -> int:
        return len(self._rooms.get(session_id, ()))

    def next_seq(self, session_id: UUID) -> int:
        self._seq[session_id] += 1
        return self._seq[session_id]

    def build(self, session_id: UUID, event_type: ServerEventType, data: dict) -> ServerEvent:
        return ServerEvent(
            type=event_type,
            seq=self.next_seq(session_id),
            ts=datetime.now(UTC),
            data=data,
        )

    async def broadcast(self, session_id: UUID, event_type: ServerEventType, data: dict) -> int:
        """Send to everyone in a session. Returns the number of recipients.

        A send failure removes the connection rather than aborting the
        broadcast: one student's dropped socket must not stop the other 39
        receiving a question.
        """
        event = self.build(session_id, event_type, data)
        payload = event.model_dump(mode="json")

        async with self._lock:
            targets = list(self._rooms.get(session_id, ()))

        delivered = 0
        for connection in targets:
            try:
                await connection.websocket.send_json(payload)
                delivered += 1
            except Exception:
                log.warning("send failed for user %s, dropping", connection.user_id)
                await self.leave(connection)
        return delivered

    async def send_to_user(
        self, session_id: UUID, user_id: UUID, event_type: ServerEventType, data: dict
    ) -> bool:
        """Targeted delivery, used for private attention prompts and per-student
        feedback. Nothing here is visible to other students.

        A student can hold more than one connection at once: Teams open in the
        desktop app and in a browser tab, or a reconnect whose predecessor has
        not been evicted yet. All of them receive the event. Stopping at the
        first would send an attention prompt to whichever socket the set
        happened to yield first, which may be the stale one, and report success.
        """
        event = self.build(session_id, event_type, data)
        payload = event.model_dump(mode="json")

        async with self._lock:
            targets = [c for c in self._rooms.get(session_id, ()) if c.user_id == user_id]

        delivered = 0
        for connection in targets:
            try:
                await connection.websocket.send_json(payload)
                delivered += 1
            except Exception:
                log.warning("targeted send failed for user %s, dropping", user_id)
                await self.leave(connection)
        return delivered > 0


hub = SessionHub()
