"""Connection registry and fan-out for live sessions and per-user channels.

Every socket carries exactly one ordered stream of events, its channel: the
room of the live session it joined, or, with no session, the user's own
channel, which is how material progress reaches the lecturer who uploaded a
file when no class is running. Both are the same thing here, a `_Stream` keyed
by the channel id, so sequencing, replay, eviction and delivery are written
once.

Sequence numbers are assigned here, so every client can detect a gap by
comparing the seq it receives against the last one it saw.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from fastapi import WebSocket

from app.schemas.events import ReadyPayload, ServerEvent, ServerEventType

log = logging.getLogger("clip.realtime")

# One stream per session and per user who has had progress, held so a
# reconnecting client can be told whether it missed anything. forget_session
# is the intended way to drop a session's, but nothing calls it until the
# session lifecycle lands in Phase 3, so the map needs a ceiling of its own
# rather than trusting a caller that does not exist.
MAX_TRACKED_STREAMS = 2048

# Progress updates are small and only the latest part of the pipeline is useful
# after a long disconnect. Bound every stream independently so an abandoned
# account cannot retain events forever.
MAX_REPLAY_EVENTS_PER_CHANNEL = 128

# A socket that has stopped reading must not hold its channel's delivery lock
# forever. One second is long enough for an in-process WebSocket send while
# keeping a dead tab from stalling the material pipeline and every reconnect.
SEND_TIMEOUT_SECONDS = 1.0

# RFC 6455's "try again later" code tells a client whose socket stopped
# receiving to reconnect and resume from its last cursor.
CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_TIMEOUT_SECONDS = 5.0


class Connection:
    def __init__(self, websocket: WebSocket, user_id: UUID, session_id: UUID | None) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.session_id = session_id
        self.connected_at = datetime.now(UTC)

    @property
    def channel(self) -> UUID:
        """The connection's single ordered event stream."""
        return self.session_id if self.session_id is not None else self.user_id

    @property
    def resumable(self) -> bool:
        """Whether a reconnect may continue where it left off.

        Only user channels, for now. Session-wide replay lands in Phase 3.
        """
        return self.session_id is None

    def describe(self) -> str:
        """Which stream this is, for log lines: "user X (user channel)"."""
        where = "user channel" if self.session_id is None else f"session {self.session_id}"
        return f"user {self.user_id} ({where})"


class _Stream:
    """One ordered stream of events and the connections that receive it."""

    def __init__(self) -> None:
        # A sequence alone cannot identify a stream after a process restart or
        # an eviction, because a new counter eventually reaches old values. The
        # generation travels in READY and comes back in the next handshake.
        self.generation = uuid4()
        self.seq = 0
        self.members: set[Connection] = set()
        self.recent: deque[ServerEvent] = deque(maxlen=MAX_REPLAY_EVENTS_PER_CHANNEL)

    def next_event(
        self, event_type: ServerEventType, data: dict, *, replayable: bool
    ) -> ServerEvent:
        self.seq += 1
        event = ServerEvent(type=event_type, seq=self.seq, ts=datetime.now(UTC), data=data)
        if replayable:
            self.recent.append(event)
        return event

    def resume_point(self, last_seq: int | None, generation: UUID | None) -> int | None:
        """The cursor this stream can continue from, or None to start afresh.

        None tells the client its cursor could not be honoured, so it resets
        rather than reading a restarted counter as a continuation.
        """
        if last_seq is None:
            return None
        # A brand-new workspace socket asks for sequence zero so it receives
        # progress emitted before the 202 arrived. It has no generation yet;
        # every later reconnect must name the one learned from READY, so a
        # restarted counter cannot impersonate it.
        if generation is None:
            if last_seq != 0:
                return None
        elif generation != self.generation:
            return None

        if last_seq > self.seq:
            return None
        if last_seq == self.seq:
            return last_seq
        # A cursor older than the retained window cannot be served. Replaying
        # only the tail would falsely claim there was no gap.
        if not self.recent or last_seq < self.recent[0].seq - 1:
            return None
        return last_seq

    def missed_since(self, last_seq: int) -> list[ServerEvent]:
        return [event for event in self.recent if event.seq > last_seq]


class SessionHub:
    """Tracks who is connected to which channel and delivers events to them.

    One instance per process. With a single backend host that is sufficient; a
    multi-host deployment would need the registry moved to Redis, which is out
    of scope for a prototype serving one lecturer at a time.
    """

    def __init__(self) -> None:
        # Ordered so the least recently used stream is the first eviction
        # candidate once the map reaches MAX_TRACKED_STREAMS.
        self._streams: OrderedDict[UUID, _Stream] = OrderedDict()
        # Guards membership. Delivery snapshots members under it and then
        # writes outside it, so a slow socket never blocks joins and leaves.
        self._lock = asyncio.Lock()
        # Publication, the handshake and replay must be ordered within one
        # channel, but a slow lecturer's socket must never hold up any other
        # channel. Weak values let a lock disappear once no delivery holds it.
        self._delivery_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
        self._closing: set[asyncio.Task[None]] = set()

    # -- the handshake ------------------------------------------------------

    async def connect(
        self,
        connection: Connection,
        last_seq: int | None = None,
        generation: UUID | None = None,
    ) -> bool:
        """Send READY, join, and replay what the client missed, as one step.

        Delivery on the connection's channel is held for the whole of it, so
        no event can arrive before READY, slip between READY and the join, or
        be skipped between the replay and the next live event. Returns False
        when READY could not be delivered, in which case the socket has been
        closed and nothing was joined.
        """
        async with self._delivering(connection.channel):
            stream = self._stream(connection.channel)
            resumed = stream.resume_point(last_seq, generation) if connection.resumable else None
            ready = ServerEvent(
                type=ServerEventType.READY,
                seq=0,
                ts=datetime.now(UTC),
                data=ReadyPayload(
                    user_id=connection.user_id,
                    session_id=connection.session_id,
                    resumed_from_seq=resumed,
                    stream_id=stream.generation if connection.resumable else None,
                ).model_dump(mode="json"),
            )
            if not await self._send(connection, ready.model_dump(mode="json"), "ready"):
                return False
            await self.join(connection)
            if resumed is not None:
                for event in stream.missed_since(resumed):
                    if not await self._send(connection, event.model_dump(mode="json"), "replay"):
                        break
        return True

    async def join(self, connection: Connection) -> None:
        """Add a connection to its channel. connect() is the handshake around it."""
        async with self._lock:
            self._stream(connection.channel).members.add(connection)
        log.info("%s joined", connection.describe())

    async def leave(self, connection: Connection) -> None:
        async with self._lock:
            stream = self._streams.get(connection.channel)
            if stream is not None:
                stream.members.discard(connection)
        log.info("%s left", connection.describe())

    # -- delivery -----------------------------------------------------------

    async def broadcast(self, session_id: UUID, event_type: ServerEventType, data: dict) -> int:
        """Send to everyone in a session. Returns the number of recipients.

        A send failure removes the connection rather than aborting the
        broadcast: one student's dropped socket must not stop the other 39
        receiving a question.
        """
        return await self._publish(session_id, event_type, data)

    async def send_to_user_channel(
        self, user_id: UUID, event_type: ServerEventType, data: dict
    ) -> int:
        """Deliver an event to a user's own connections, the ones in no session.

        Material preparation has no live session, so the authenticated user id
        is the only safe address for its progress. A caller can only join the
        channel derived from their signed token in the WebSocket endpoint; no
        client-supplied user id is trusted.
        """
        return await self._publish(user_id, event_type, data)

    async def send_to_user(
        self, session_id: UUID, user_id: UUID, event_type: ServerEventType, data: dict
    ) -> bool:
        """Targeted delivery within a session, for private attention prompts and
        per-student feedback. Nothing here is visible to other students, and it
        is kept out of the session's replay for the same reason.

        A student can hold more than one connection at once: Teams open in the
        desktop app and in a browser tab, or a reconnect whose predecessor has
        not been evicted yet. All of them receive the event. Stopping at the
        first would send an attention prompt to whichever socket the set
        happened to yield first, which may be the stale one, and report success.
        """
        return await self._publish(session_id, event_type, data, only=user_id) > 0

    async def _publish(
        self,
        channel: UUID,
        event_type: ServerEventType,
        data: dict,
        only: UUID | None = None,
    ) -> int:
        """Number, record and deliver one event on a channel, in order.

        Numbering happens under the same lock as the writes. Numbered and then
        written separately, two concurrent events on one channel raced to the
        socket, and a client saw seq 2 before seq 1 and read a gap where
        nothing had been lost.
        """
        async with self._delivering(channel):
            stream = self._stream(channel)
            event = stream.next_event(event_type, data, replayable=only is None)
            payload = event.model_dump(mode="json")
            async with self._lock:
                targets = [c for c in stream.members if only is None or c.user_id == only]

            delivered = 0
            for connection in targets:
                if await self._send(connection, payload, event_type.value):
                    delivered += 1
            return delivered

    async def _send(self, connection: Connection, payload: dict, context: str) -> bool:
        """Bound one WebSocket send and discard a connection that stops reading."""
        try:
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await connection.websocket.send_json(payload)
            return True
        except TimeoutError:
            log.warning("%s send timed out for %s, dropping", context, connection.describe())
        except Exception:
            log.warning("%s send failed for %s, dropping", context, connection.describe())

        await self._drop(connection)
        return False

    async def _drop(self, connection: Connection) -> None:
        """Forget a dead socket now, and close it without blocking delivery."""
        await self.leave(connection)
        task = asyncio.create_task(self._close_quietly(connection))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close_quietly(self, connection: Connection) -> None:
        with contextlib.suppress(Exception):
            async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                await connection.websocket.close(
                    code=CLOSE_TRY_AGAIN_LATER,
                    reason="client stopped receiving events",
                )

    @contextlib.asynccontextmanager
    async def _delivering(self, channel: UUID) -> AsyncIterator[None]:
        lock = self._delivery_locks.get(channel)
        if lock is None:
            lock = asyncio.Lock()
            self._delivery_locks[channel] = lock
        async with lock:
            yield

    # -- streams ------------------------------------------------------------

    def _stream(self, channel: UUID) -> _Stream:
        """The channel's stream, created on first use and marked recently used."""
        stream = self._streams.get(channel)
        if stream is None:
            stream = self._streams[channel] = _Stream()
        self._streams.move_to_end(channel)
        if len(self._streams) > MAX_TRACKED_STREAMS:
            self._evict_idle_stream()
        return stream

    def _evict_idle_stream(self) -> None:
        """Drop the stream that has been quiet longest and has nobody connected.

        Evicting a live one would restart its seq at 1, and every client
        watching it would read the restart as a gap, so an oversized map is the
        better failure. The newest stream is the one just asked for, so it is
        never the candidate.
        """
        newest = next(reversed(self._streams))
        idle = next(
            (
                channel
                for channel, stream in self._streams.items()
                if channel != newest and not stream.members
            ),
            None,
        )
        if idle is not None:
            del self._streams[idle]
            log.info("dropped the idle stream for channel %s", idle)
            return

        log.warning(
            "%d streams are tracked and every one has live connections, so the %d ceiling "
            "cannot be enforced; sessions are being created faster than they end",
            len(self._streams),
            MAX_TRACKED_STREAMS,
        )

    def forget_session(self, session_id: UUID) -> None:
        """Drop a finished session's stream.

        Owner: General CS, Phase 3. Nothing calls this yet because the session
        lifecycle arrives with the scheduler, which is why streams have a
        ceiling instead of relying on it.

        Call it only once a session has genuinely ended. Clearing the stream
        while a session is still running restarts seq at 1, which clients read
        as a gap.
        """
        self._streams.pop(session_id, None)

    def participant_count(self, session_id: UUID) -> int:
        stream = self._streams.get(session_id)
        return len(stream.members) if stream is not None else 0

    def tracked_stream_count(self) -> int:
        """How many streams are held. Exposed so the ceiling is observable
        rather than something only the logs know about."""
        return len(self._streams)


hub = SessionHub()
