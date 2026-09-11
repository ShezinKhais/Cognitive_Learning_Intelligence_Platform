"""Connection registry and fan-out for live sessions.

Phase 1 provides the registry, sequencing and session broadcast paths. Phase 2
adds per-user channels and bounded progress replay so material updates can
reach the lecturer who uploaded a file even when no live class session exists.

Sequence numbers are assigned here, so every client can detect a gap by
comparing the seq it receives against the last one it saw.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket

from app.schemas.events import ServerEvent, ServerEventType

log = logging.getLogger("clip.realtime")

# One small int per session, held so a reconnecting client can be told whether
# it missed anything. forget_session is the intended way to drop an entry, but
# nothing calls it until the session lifecycle lands in Phase 3, so the map
# needs a ceiling of its own rather than trusting a caller that does not exist.
# A single lecturer never approaches this; reaching it means something is
# creating sessions that never end, which is worth a log line.
MAX_TRACKED_SESSIONS = 1024

# Progress updates are small and only the latest part of the pipeline is useful
# after a long disconnect. Bound every user independently so an abandoned
# account cannot retain events forever.
MAX_REPLAY_EVENTS_PER_CHANNEL = 128


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
        self._by_user: dict[UUID, set[Connection]] = defaultdict(set)
        # Ordered so the least recently used counter is the first eviction
        # candidate once the map reaches MAX_TRACKED_SESSIONS.
        self._seq: OrderedDict[UUID, int] = OrderedDict()
        self._user_seq: OrderedDict[UUID, int] = OrderedDict()
        self._user_replay: dict[UUID, deque[ServerEvent]] = defaultdict(
            lambda: deque(maxlen=MAX_REPLAY_EVENTS_PER_CHANNEL)
        )
        self._lock = asyncio.Lock()
        # Serialising user-channel replay with publication closes the gap where
        # an event could otherwise be emitted after a reconnect joins but
        # before its replay snapshot is taken.
        self._user_delivery_lock = asyncio.Lock()

    async def join(self, connection: Connection) -> None:
        async with self._lock:
            if connection.session_id is None:
                self._by_user[connection.user_id].add(connection)
            else:
                self._rooms[connection.session_id].add(connection)

        if connection.session_id is None:
            log.info("user %s joined their user channel", connection.user_id)
        else:
            log.info("user %s joined session %s", connection.user_id, connection.session_id)

    async def leave(self, connection: Connection) -> None:
        async with self._lock:
            if connection.session_id is None:
                user_connections = self._by_user.get(connection.user_id)
                if user_connections:
                    user_connections.discard(connection)
                    if not user_connections:
                        del self._by_user[connection.user_id]
            else:
                room = self._rooms.get(connection.session_id)
                if room:
                    room.discard(connection)
                    if not room:
                        del self._rooms[connection.session_id]

        if connection.session_id is None:
            log.info("user %s left their user channel", connection.user_id)
        else:
            log.info("user %s left session %s", connection.user_id, connection.session_id)

    def forget_session(self, session_id: UUID) -> None:
        """Drop a finished session's room and sequence counter.

        Owner: General CS, Phase 3. Nothing calls this yet because the session
        lifecycle arrives with the scheduler, which is why `next_seq` enforces
        a ceiling instead of relying on it.

        Call it only once a session has genuinely ended. `leave` already drops
        an empty room, and clearing the counter while a session is still
        running restarts seq at 1, which clients read as a gap.
        """
        self._rooms.pop(session_id, None)
        self._seq.pop(session_id, None)

    def participant_count(self, session_id: UUID) -> int:
        return len(self._rooms.get(session_id, ()))

    def tracked_session_count(self) -> int:
        """How many sequence counters are held. Exposed so the ceiling is
        observable rather than something only the logs know about."""
        return len(self._seq)

    def next_seq(self, session_id: UUID) -> int:
        counter = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = counter
        self._seq.move_to_end(session_id)
        if len(self._seq) > MAX_TRACKED_SESSIONS:
            self._evict_idle_counter()
        return counter

    def _evict_idle_counter(self) -> None:
        """Drop the counter of the session that has been quiet longest.

        Only sessions with nobody connected are eligible. Evicting a live one
        would restart its seq at 1, and every client watching that stream would
        read the restart as a gap, so an oversized map is the better failure.
        """
        idle = next((session for session in self._seq if not self._rooms.get(session)), None)
        if idle is not None:
            del self._seq[idle]
            log.info("dropped the sequence counter for idle session %s", idle)
            return

        log.warning(
            "%d sessions are tracked and every one has live connections, so the %d ceiling "
            "cannot be enforced; sessions are being created faster than they end",
            len(self._seq),
            MAX_TRACKED_SESSIONS,
        )

    def build(self, session_id: UUID, event_type: ServerEventType, data: dict) -> ServerEvent:
        return ServerEvent(
            type=event_type,
            seq=self.next_seq(session_id),
            ts=datetime.now(UTC),
            data=data,
        )

    def _next_user_seq(self, user_id: UUID) -> int:
        counter = self._user_seq.get(user_id, 0) + 1
        self._user_seq[user_id] = counter
        self._user_seq.move_to_end(user_id)

        if len(self._user_seq) > MAX_TRACKED_SESSIONS:
            idle = next(
                (
                    user
                    for user in self._user_seq
                    if user != user_id and not self._by_user.get(user)
                ),
                None,
            )
            if idle is not None:
                del self._user_seq[idle]
                self._user_replay.pop(idle, None)
            else:
                log.warning(
                    "%d user channels are tracked and every one has live connections",
                    len(self._user_seq),
                )

        return counter

    def _build_user_event(
        self,
        user_id: UUID,
        event_type: ServerEventType,
        data: dict,
    ) -> ServerEvent:
        event = ServerEvent(
            type=event_type,
            seq=self._next_user_seq(user_id),
            ts=datetime.now(UTC),
            data=data,
        )
        self._user_replay[user_id].append(event)
        return event

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

    async def send_to_user_channel(
        self,
        user_id: UUID,
        event_type: ServerEventType,
        data: dict,
    ) -> int:
        """Deliver an event to a user's personal WebSocket connections.

        Material preparation has no live session id, so the authenticated user
        id is the only safe address for its progress events. A caller can only
        join the channel derived from their signed token in the WebSocket
        endpoint; no client-supplied user id is trusted.
        """
        async with self._user_delivery_lock:
            event = self._build_user_event(user_id, event_type, data)
            payload = event.model_dump(mode="json")

            async with self._lock:
                targets = list(self._by_user.get(user_id, ()))

            delivered = 0
            for connection in targets:
                try:
                    await connection.websocket.send_json(payload)
                    delivered += 1
                except Exception:
                    log.warning("user-channel send failed for user %s, dropping", user_id)
                    await self.leave(connection)
            return delivered

    async def join_and_replay(
        self,
        connection: Connection,
        last_seq: int | None,
    ) -> tuple[int, int | None]:
        """Authorize the user channel handoff and replay missed progress.

        The returned cursor is null when the server cannot resume the client's
        sequence (for example after a backend restart), allowing the client to
        reset its local cursor before accepting the new stream.
        """
        async with self._user_delivery_lock:
            await self.join(connection)
            return await self._replay_user_events(connection, last_seq)

    async def replay(
        self,
        connection: Connection,
        last_seq: int | None,
    ) -> tuple[int, int | None]:
        """Replay missed progress on an already joined user connection."""
        async with self._user_delivery_lock:
            return await self._replay_user_events(connection, last_seq)

    async def _replay_user_events(
        self,
        connection: Connection,
        last_seq: int | None,
    ) -> tuple[int, int | None]:
        if connection.session_id is not None or last_seq is None:
            return 0, None

        current_seq = self._user_seq.get(connection.user_id, 0)
        if last_seq > current_seq:
            return 0, None

        events = [
            event
            for event in self._user_replay.get(connection.user_id, ())
            if event.seq > last_seq
        ]

        delivered = 0
        for event in events:
            try:
                await connection.websocket.send_json(event.model_dump(mode="json"))
                delivered += 1
            except Exception:
                log.warning("replay failed for user %s, dropping", connection.user_id)
                await self.leave(connection)
                break

        return delivered, last_seq

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
