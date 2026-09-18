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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

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

# A socket that has stopped reading must not hold a user's delivery lock
# forever. One second is long enough for an in-process WebSocket send while
# keeping a dead tab from stalling the material pipeline and every reconnect.
SEND_TIMEOUT_SECONDS = 1.0
SEND_TIMEOUT_CLOSE_CODE = 1011

# RFC 6455: reconnect and retry after the server drops a stale socket.
CLOSE_TRY_AGAIN_LATER = 1013


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
        # A sequence alone cannot identify a stream after a process restart or
        # an idle-user eviction: a new counter eventually reaches old values.
        # The generation id travels in READY and the next auth handshake.
        self._user_stream_ids: dict[UUID, UUID] = {}
        self._user_replay: dict[UUID, deque[ServerEvent]] = defaultdict(
            lambda: deque(maxlen=MAX_REPLAY_EVENTS_PER_CHANNEL)
        )
        self._lock = asyncio.Lock()
        # Publication and replay must be ordered for one user, but a slow
        # lecturer connection must never hold up every other lecturer. Weak
        # values keep this per-user lock registry bounded once a channel is no
        # longer active.
        self._user_delivery_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()

    def _user_delivery_lock(self, user_id: UUID) -> asyncio.Lock:
        lock = self._user_delivery_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_delivery_locks[user_id] = lock
        return lock

    async def join(self, connection: Connection) -> None:
        async with self._lock:
            # One socket carries one ordered stream. Material-workspace sockets
            # have no session id and join the private user channel; live-class
            # sockets join only their session room. Mixing both indexes gives a
            # single last_seq cursor two unrelated sequence namespaces.
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
        self._ensure_user_stream(user_id)
        counter = self._user_seq.get(user_id, 0) + 1
        self._user_seq[user_id] = counter
        self._user_seq.move_to_end(user_id)

        return counter

    def _ensure_user_stream(self, user_id: UUID) -> UUID:
        stream_id = self._user_stream_ids.get(user_id)
        if stream_id is None:
            stream_id = uuid4()
            self._user_stream_ids[user_id] = stream_id
            self._user_seq[user_id] = 0

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
                self._user_stream_ids.pop(idle, None)
                self._user_replay.pop(idle, None)
            else:
                log.warning(
                    "%d user channels are tracked and every one has live connections",
                    len(self._user_seq),
                )

        return stream_id

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
            if await self._send(connection, payload, "session broadcast"):
                delivered += 1
        return delivered

    async def _send(self, connection: Connection, payload: dict, context: str) -> bool:
        """Bound one WebSocket send and discard a connection that stops reading."""
        try:
            await asyncio.wait_for(
                connection.websocket.send_json(payload),
                timeout=SEND_TIMEOUT_SECONDS,
            )
            return True
        except TimeoutError:
            log.warning("%s timed out for user %s, dropping", context, connection.user_id)
        except Exception:
            log.warning("%s failed for user %s, dropping", context, connection.user_id)

        await self.leave(connection)
        try:
            await asyncio.wait_for(
                connection.websocket.close(
                    code=SEND_TIMEOUT_CLOSE_CODE,
                    reason="client stopped receiving events",
                ),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            # The send often failed because the peer was already gone. Closing
            # is best-effort after the connection has left both indexes.
            pass
        return False

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
        async with self._user_delivery_lock(user_id):
            event = self._build_user_event(user_id, event_type, data)
            payload = event.model_dump(mode="json")

            async with self._lock:
                targets = list(self._by_user.get(user_id, ()))

            delivered = 0
            for connection in targets:
                if await self._send(connection, payload, "user-channel send"):
                    delivered += 1
            return delivered

    async def join_and_replay(
        self,
        connection: Connection,
        last_seq: int | None,
        stream_id: UUID | None,
        send_ready: Callable[[int | None, UUID | None], Awaitable[None]],
    ) -> tuple[int, int | None] | None:
        """Complete the handshake, join, and replay missed progress atomically.

        The returned cursor is null when the server cannot resume the client's
        sequence (for example after a backend restart), allowing the client to
        reset its local cursor before accepting the new stream.

        READY is sent before the connection joins either delivery index. The
        per-user lock prevents publication during that handoff, so no progress
        can slip between READY, joining, and replay.
        """
        # Session replay lands in Phase 3. Keeping a session socket out of the
        # user channel gives this connection exactly one sequence stream.
        if connection.session_id is not None:
            if not await self._send_ready(connection, send_ready, None, None):
                return None
            await self.join(connection)
            return 0, None

        async with self._user_delivery_lock(connection.user_id):
            current_stream_id = self._ensure_user_stream(connection.user_id)
            resumed_from_seq = self._resumable_cursor(
                connection.user_id,
                last_seq,
                stream_id,
                current_stream_id,
            )
            if not await self._send_ready(
                connection,
                send_ready,
                resumed_from_seq,
                current_stream_id,
            ):
                return None
            await self.join(connection)
            return await self._replay_user_events(connection, resumed_from_seq)

    async def _send_ready(
        self,
        connection: Connection,
        send_ready: Callable[[int | None, UUID | None], Awaitable[None]],
        resumed_from_seq: int | None,
        stream_id: UUID | None,
    ) -> bool:
        try:
            await asyncio.wait_for(
                send_ready(resumed_from_seq, stream_id),
                timeout=SEND_TIMEOUT_SECONDS,
            )
            return True
        except TimeoutError:
            log.warning("READY timed out for user %s, dropping", connection.user_id)
        except Exception:
            log.warning("READY failed for user %s, dropping", connection.user_id)

        await self.leave(connection)
        try:
            await asyncio.wait_for(
                connection.websocket.close(
                    code=SEND_TIMEOUT_CLOSE_CODE,
                    reason="client stopped receiving events",
                ),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            pass
        return False

    def _resumable_cursor(
        self,
        user_id: UUID,
        last_seq: int | None,
        stream_id: UUID | None,
        current_stream_id: UUID,
    ) -> int | None:
        if last_seq is None:
            return None

        # A brand-new workspace socket deliberately asks for sequence zero so
        # it can receive progress emitted before the 202 response arrived. It
        # has no stream id yet; every later reconnect must name the generation
        # learned from READY so a restarted counter cannot impersonate it.
        if stream_id is None:
            if last_seq != 0:
                return None
        elif stream_id != current_stream_id:
            return None

        current_seq = self._user_seq.get(user_id, 0)
        if last_seq > current_seq:
            return None

        if last_seq == current_seq:
            return last_seq

        replay = self._user_replay.get(user_id)
        if not replay or last_seq < replay[0].seq - 1:
            # The requested cursor predates the retained window. Replaying only
            # the tail would falsely claim there was no gap.
            return None

        return last_seq

    async def _replay_user_events(
        self,
        connection: Connection,
        last_seq: int | None,
    ) -> tuple[int, int | None]:
        if last_seq is None:
            return 0, None

        events = [
            event for event in self._user_replay.get(connection.user_id, ()) if event.seq > last_seq
        ]

        delivered = 0
        for event in events:
            if await self._send(
                connection,
                event.model_dump(mode="json"),
                "user-channel replay",
            ):
                delivered += 1
                continue
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
            if await self._send(connection, payload, "targeted send"):
                delivered += 1
        return delivered > 0


hub = SessionHub()
