"""Connection registry and fan-out for live sessions.

Phase 1 provides the registry, sequencing and broadcast paths. Phase 3 adds the
replay buffer, so that a student who loses wifi mid-question receives what they
missed rather than a blank panel.

Events are addressed to a channel, and every connection belongs to exactly one:
the session it named, or, when it named none, its user's own channel. Sequence
numbers are assigned per channel, so every client can detect a gap by comparing
the seq it receives against the last one it saw.

The user channel exists because not every event belongs to a class.
`material.progress` reports on a file a lecturer uploaded, which happens while
they are preparing, not while they are teaching. Before Phase 2 a connection
that named no session joined nothing, so it could be sent nothing at all.

One channel per connection, not both. A session connection that also sat on its
user's channel received two independently numbered streams on one socket, and
the single last_seq a client reconnects with cannot describe two streams.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket

from app.schemas.events import ServerEvent, ServerEventType

log = logging.getLogger("clip.realtime")

# One small int per channel, held so a reconnecting client can be told whether
# it missed anything. forget_session is the intended way to drop an entry, but
# nothing calls it until the session lifecycle lands in Phase 3, so the map
# needs a ceiling of its own rather than trusting a caller that does not exist.
# A single lecturer never approaches this; reaching it means something is
# creating sessions that never end, which is worth a log line.
MAX_TRACKED_SESSIONS = 1024

# How long one socket write may take before the connection is treated as dead.
# A client on a train in a tunnel stops acknowledging without closing, and a
# write to it waits on TCP backpressure indefinitely. Delivery loops over its
# recipients one at a time, so without a bound that one socket holds up
# everyone after it. Five seconds is far past any healthy write of a few
# hundred bytes.
SEND_TIMEOUT_SECONDS = 5.0

# Sent when the hub gives up on a connection. RFC 6455 registers 1013 as
# "try again later", which is the instruction: reconnect and resume.
CLOSE_TRY_AGAIN_LATER = 1013

# Closing writes a frame to a socket that has just failed a write, so it is
# bounded as well. It runs in the background, so this limit holds up nobody.
CLOSE_TIMEOUT_SECONDS = 5.0


class Connection:
    def __init__(self, websocket: WebSocket, user_id: UUID, session_id: UUID | None) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.session_id = session_id
        self.connected_at = datetime.now(UTC)

    @property
    def channel(self) -> UUID:
        return self.session_id if self.session_id is not None else self.user_id


class SessionHub:
    """Tracks which channel each connection is on and delivers events to them.

    One instance per process. With a single backend host that is sufficient; a
    multi-host deployment would need the registry moved to Redis, which is out
    of scope for a prototype serving one lecturer at a time.
    """

    def __init__(self) -> None:
        self._channels: dict[UUID, set[Connection]] = defaultdict(set)
        # Ordered so the least recently used counter is the first eviction
        # candidate once the map reaches MAX_TRACKED_SESSIONS.
        self._seq: OrderedDict[UUID, int] = OrderedDict()
        self._lock = asyncio.Lock()
        # Strong references to closes in progress, which run detached from
        # the delivery that found the dead socket.
        self._closing: set[asyncio.Task[None]] = set()
        # Assigning a seq and writing it to the sockets are one step per
        # channel. Two events published at once otherwise take numbers 1 and 2
        # and race to the socket, so a client tracking last_seq sees 2 followed
        # by 1 and reads a gap where nothing was lost. A lecturer processing two
        # uploads reports on one channel concurrently, and so will the prompt
        # scheduler alongside question delivery in a session (#41).
        #
        # One lock per channel, not one for the hub, so one stalled socket never
        # holds up delivery anywhere else. Entries exist only while a delivery
        # is in flight, counted in _delivery_waiters, so the map cannot grow
        # with the number of channels. Separate from _lock, so delivery never
        # blocks a connection joining or leaving.
        self._delivery_locks: dict[UUID, asyncio.Lock] = {}
        self._delivery_waiters: dict[UUID, int] = {}

    async def join(self, connection: Connection) -> None:
        async with self._lock:
            self._channels[connection.channel].add(connection)
        log.info("user %s joined channel %s", connection.user_id, connection.channel)

    async def join_after(
        self, connection: Connection, send_ready: Callable[[], Awaitable[None]]
    ) -> None:
        """Send ready, then join, with nothing published on the channel in between.

        Joining first let an event reach the socket ahead of ready. Sending
        ready and then joining left a gap: an event published between the two
        went to no socket, and if it was the final done frame nothing later
        would replace it, so the tab waited forever. Holding the channel's
        delivery lock across both makes delivery wait for the join instead.

        The ready write is bounded like any other, since the lock is held
        while it runs.
        """
        async with self._delivery_lock_for(connection.channel):
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await send_ready()
            await self.join(connection)

    async def leave(self, connection: Connection) -> None:
        async with self._lock:
            members = self._channels.get(connection.channel)
            if members:
                members.discard(connection)
                if not members:
                    del self._channels[connection.channel]
        log.info("user %s left channel %s", connection.user_id, connection.channel)

    def forget_session(self, session_id: UUID) -> None:
        """Drop a finished session's room and sequence counter.

        Owner: General CS, Phase 3. Nothing calls this yet because the session
        lifecycle arrives with the scheduler, which is why `next_seq` enforces
        a ceiling instead of relying on it.

        Call it only once a session has genuinely ended. `leave` already drops
        an empty room, and clearing the counter while a session is still
        running restarts seq at 1, which clients read as a gap.
        """
        self._channels.pop(session_id, None)
        self._seq.pop(session_id, None)

    def participant_count(self, session_id: UUID) -> int:
        return len(self._channels.get(session_id, ()))

    def tracked_session_count(self) -> int:
        """How many sequence counters are held. Exposed so the ceiling is
        observable rather than something only the logs know about."""
        return len(self._seq)

    def next_seq(self, channel: UUID) -> int:
        counter = self._seq.get(channel, 0) + 1
        self._seq[channel] = counter
        self._seq.move_to_end(channel)
        if len(self._seq) > MAX_TRACKED_SESSIONS:
            self._evict_idle_counter()
        return counter

    def _evict_idle_counter(self) -> None:
        """Drop the counter of the channel that has been quiet longest.

        Only channels with nobody connected are eligible. Evicting a live one
        would restart its seq at 1, and every client watching that stream would
        read the restart as a gap, so an oversized map is the better failure.
        """
        idle = next((channel for channel in self._seq if not self._channels.get(channel)), None)
        if idle is not None:
            del self._seq[idle]
            log.info("dropped the sequence counter for idle channel %s", idle)
            return

        log.warning(
            "%d channels are tracked and every one has live connections, so the %d ceiling "
            "cannot be enforced; sessions are being created faster than they end",
            len(self._seq),
            MAX_TRACKED_SESSIONS,
        )

    def build(self, channel: UUID, event_type: ServerEventType, data: dict) -> ServerEvent:
        return ServerEvent(
            type=event_type,
            seq=self.next_seq(channel),
            ts=datetime.now(UTC),
            data=data,
        )

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
        """Deliver on a user's own channel, independent of any session.

        This is how `material.progress` reaches the lecturer who uploaded a
        file: processing runs while they are preparing, so there is no class to
        broadcast to. Returns the number of connections written to, which is
        zero when the lecturer has closed the tab. That is a normal outcome,
        not a failure; the material keeps processing regardless.
        """
        return await self._publish(user_id, event_type, data)

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
        delivered = await self._publish(
            session_id, event_type, data, only=lambda connection: connection.user_id == user_id
        )
        return delivered > 0

    async def _publish(
        self,
        channel: UUID,
        event_type: ServerEventType,
        data: dict,
        only: Callable[[Connection], bool] | None = None,
    ) -> int:
        """Number one event and write it to the channel's connections.

        Dead connections are forgotten before the channel's lock is released.
        Dropped after it, a delivery waiting on the lock could snapshot the same
        dead socket and spend another full send timeout on it.
        """
        async with self._delivery_lock_for(channel):
            payload = self.build(channel, event_type, data).model_dump(mode="json")

            async with self._lock:
                targets = [c for c in self._channels.get(channel, ()) if only is None or only(c)]

            delivered = 0
            for connection in targets:
                if await self._deliver(connection, payload):
                    delivered += 1
                else:
                    log.warning("send failed for user %s, dropping", connection.user_id)
                    await self._drop(connection)
            return delivered

    async def _deliver(self, connection: Connection, payload: dict) -> bool:
        """Write one frame, reporting whether it arrived rather than raising.

        A write that outlasts SEND_TIMEOUT_SECONDS counts as a failure, so the
        caller drops the connection exactly as it would a closed one.
        """
        try:
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await connection.websocket.send_json(payload)
        except Exception:
            return False
        return True

    async def _drop(self, connection: Connection) -> None:
        """Forget a failed connection now, and close it in the background.

        The close is another write to the same stalled socket. Awaited inline,
        under the channel's delivery lock, it held up the channel's healthy
        connections for a second timeout, and the pipeline awaiting the send
        waited too.

        Closed rather than only forgotten: a socket removed from the registry
        but left open kept answering pings with nothing to tell the client that
        no further event would arrive. Closed, the client reconnects.
        """
        await self.leave(connection)
        task = asyncio.create_task(self._close_quietly(connection))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close_quietly(self, connection: Connection) -> None:
        # A socket that is already gone raises, and there is nothing more to do.
        with contextlib.suppress(Exception):
            async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                await connection.websocket.close(code=CLOSE_TRY_AGAIN_LATER)

    @asynccontextmanager
    async def _delivery_lock_for(self, channel: UUID) -> AsyncIterator[None]:
        """Serialise delivery on one channel without touching any other.

        The waiter count is what lets the entry be removed. Nothing yields
        between creating the lock and counting this caller, so a concurrent
        caller either finds the lock already present or creates it, and the
        entry only disappears once the last caller for that channel has finished.
        """
        lock = self._delivery_locks.setdefault(channel, asyncio.Lock())
        self._delivery_waiters[channel] = self._delivery_waiters.get(channel, 0) + 1
        try:
            async with lock:
                yield
        finally:
            remaining = self._delivery_waiters[channel] - 1
            if remaining:
                self._delivery_waiters[channel] = remaining
            else:
                del self._delivery_waiters[channel]
                del self._delivery_locks[channel]


hub = SessionHub()
