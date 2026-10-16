"""A student, or a lecturer's panel, as one WebSocket the way the frontend holds it.

Each client keeps what the real one keeps: the highest seq it has seen and
the stream it belongs to, which it hands back when it reconnects. It records
when every event arrived, which is where the latencies in the report come
from, and every seq, which is how a gap or a repeat is found.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from scripts.loadtest.environment import Person

OPEN_TIMEOUT_SECONDS = 20.0


@dataclass
class Received:
    type: str
    seq: int
    data: dict[str, Any]
    at: float  # time.perf_counter() when it arrived
    # Seconds between the server stamping the event and it arriving here.
    # Both clocks are this machine's, so the difference is the journey.
    transit: float = 0.0


@dataclass
class Client:
    person: Person
    url: str
    session_id: UUID | None
    events: list[Received] = field(default_factory=list)
    last_seq: int = 0
    stream_id: str | None = None
    # What the last READY said about the cursor this client offered.
    resumed_from: int | None = None
    ready_seconds: float | None = None
    close_code: int | None = None
    # Sequenced events seen out of order, twice, or with one missing before them.
    gaps: list[str] = field(default_factory=list)
    _socket: ClientConnection | None = None
    _reader: asyncio.Task[None] | None = None
    _waiters: list[tuple[Any, asyncio.Future[Received]]] = field(default_factory=list)
    # Joined a stream part way through, so the first seq seen is where this
    # client starts counting and is not checked against anything.
    _joining: bool = True

    @property
    def connected(self) -> bool:
        return self._socket is not None and self._reader is not None and not self._reader.done()

    async def connect(self, *, resume: bool = False, forget_stream: bool = False) -> None:
        """Open the socket, authenticate and wait for READY. With resume, the
        cursor from the last connection is offered, as a real client does."""
        began = time.perf_counter()
        self.close_code = None
        self._socket = await websockets.connect(
            self.url, open_timeout=OPEN_TIMEOUT_SECONDS, ping_interval=None, max_queue=None
        )
        auth: dict[str, Any] = {"token": self.person.token}
        if self.session_id is not None:
            auth["session_id"] = str(self.session_id)
        if resume:
            auth["last_seq"] = self.last_seq
            if self.stream_id is not None and not forget_stream:
                auth["stream_id"] = self.stream_id
        await self._socket.send(json.dumps({"type": "auth", "data": auth}))
        ready = json.loads(await asyncio.wait_for(self._socket.recv(), OPEN_TIMEOUT_SECONDS))
        if ready.get("type") != "ready":
            raise RuntimeError(f"expected ready, got {ready}")
        self.ready_seconds = time.perf_counter() - began
        self.resumed_from = ready["data"].get("resumed_from_seq")
        if ready["data"].get("stream_id") != self.stream_id or self.resumed_from is None:
            # A stream this client has not seen, or a cursor that could not be
            # honoured: it starts counting afresh, as the frontend does.
            self.last_seq = 0
            self._joining = True
        self.stream_id = ready["data"].get("stream_id")
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        socket = self._socket
        assert socket is not None
        try:
            async for raw in socket:
                at, wall = time.perf_counter(), time.time()
                message = json.loads(raw)
                stamped = datetime.fromisoformat(message["ts"]).timestamp()
                event = Received(
                    message["type"],
                    message.get("seq", 0),
                    message.get("data", {}),
                    at,
                    max(wall - stamped, 0.0),
                )
                if event.seq:
                    if self._joining:
                        self._joining = False
                    elif event.seq != self.last_seq + 1:
                        self.gaps.append(f"seq {event.seq} after {self.last_seq} ({event.type})")
                    self.last_seq = max(self.last_seq, event.seq)
                self.events.append(event)
                for want, future in list(self._waiters):
                    if not future.done() and want(event):
                        future.set_result(event)
                        self._waiters.remove((want, future))
        except ConnectionClosed as closed:
            self.close_code = closed.rcvd.code if closed.rcvd else 1006
        finally:
            for _, future in self._waiters:
                if not future.done():
                    future.cancel()
            self._waiters.clear()

    async def send(self, event_type: str, data: dict[str, Any] | None = None) -> float:
        """Send one event. Returns when it was sent."""
        assert self._socket is not None
        await self._socket.send(json.dumps({"type": event_type, "data": data or {}}))
        return time.perf_counter()

    async def wait_for(self, want: Any, timeout: float = 15.0) -> Received:  # noqa: ASYNC109
        """The next event `want` accepts, which may already have arrived."""
        for event in self.events:
            if want(event):
                return event
        future: asyncio.Future[Received] = asyncio.get_running_loop().create_future()
        self._waiters.append((want, future))
        return await asyncio.wait_for(future, timeout)

    def of(self, event_type: str) -> list[Received]:
        return [e for e in self.events if e.type == event_type]

    async def drop(self) -> None:
        """Lose the connection with no goodbye, as a laptop lid or a dead
        network does."""
        socket, self._socket = self._socket, None
        if socket is not None:
            socket.transport.abort()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader

    async def close(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader

    async def answer(self, question_id: str, option: int = 1) -> float | None:
        """Answer a question and wait for the receipt. Returns the seconds
        from sending to an accepting receipt, or None if it was refused."""
        seen = len(self.events)
        sent = await self.send(
            "answer.submit",
            {"question_id": question_id, "selected_option": option, "client_elapsed_ms": 500},
        )

        def mine(event: Received) -> bool:
            return event.type == "answer.receipt" and event.data.get("question_id") == question_id

        future: asyncio.Future[Received] = asyncio.get_running_loop().create_future()
        for event in self.events[seen:]:
            if mine(event):
                future.set_result(event)
                break
        else:
            self._waiters.append((mine, future))
        receipt = await asyncio.wait_for(future, 20.0)
        return receipt.at - sent if receipt.data.get("accepted") else None


def is_type(event_type: str, **data: Any) -> Any:
    """A matcher for wait_for: this type, with these values in its data."""

    def want(event: Received) -> bool:
        return event.type == event_type and all(event.data.get(k) == v for k, v in data.items())

    return want
