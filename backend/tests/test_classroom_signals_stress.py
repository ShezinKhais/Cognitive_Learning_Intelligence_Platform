"""The watch, the rooms and the question cycle, all at once and in any order.

Owner: General CS, Phase 6.

Each part of a live session is tested on its own elsewhere. This runs them
against each other: students send signals, move between rooms, answer, drop
and return and withdraw consent while questions open and close and the watch
makes its passes, in an order drawn from a seed. Nothing here says what the
right answer to any one step is. It says what must hold whatever the order:

- a prompt, a receipt and a result reach only the student they are for;
- a room's status and its alerts reach only staff;
- no student is sent more prompts than the cap;
- no prompt is sent to a student once they have withdrawn engagement
  monitoring, and the attention minutes stored as the session ends hold
  nothing of theirs;
- a room never reports more members than are connected, or more speaking
  than it has members;
- when the session ends, every timer it started has stopped.

A failure prints its seed, which reproduces it.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

import pytest

from app.realtime import attention_windows
from app.realtime.classroom import Classroom
from app.realtime.hub import Connection
from app.realtime.recorders import AttentionWindow, RoomAlert
from app.schemas.events import (
    AttentionSignalPayload,
    PromptAckPayload,
    RoomConfirmPayload,
    ServerEventType,
)
from app.schemas.identity import ConsentType, Role
from app.schemas.session import SessionStatus

from .classroom_support import (
    FakeDb,
    FakeRepository,
    FakeSocket,
    StagedQuestion,
    answer_to,
    join_as,
    make_room,
    make_row,
)

pytestmark = pytest.mark.usefixtures("fake_session_repository")


@pytest.fixture(autouse=True)
def _no_signal_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run takes about a second, so with the server's spacing between a
    student's signals (attention_windows.py) each would be heard once and the
    rooms would pass through their statuses only by luck of timing. That
    rule has its own tests."""
    monkeypatch.setattr(attention_windows, "MIN_SIGNAL_INTERVAL", timedelta(0))


STUDENTS = 12
PROMPT_CAP = 2
STEPS = 400
STAFF_ONLY = {ServerEventType.ROOM_STATUS.value, ServerEventType.ALERT_RAISED.value}
PRIVATE = {
    ServerEventType.PROMPT_ATTENTION.value,
    ServerEventType.ANSWER_RECEIPT.value,
    ServerEventType.FEEDBACK_RESULT.value,
}


class _Recorder:
    """Keeps everything it is handed, and sometimes fails, as a store does."""

    def __init__(self, rng: random.Random, room: Classroom) -> None:
        self._rng = rng
        self._room = room
        self.windows: list[AttentionWindow] = []
        # Minutes handed over, stored or not.
        self.handed = 0
        self.unconsented: list[UUID] = []
        self.alerts: list[RoomAlert] = []
        # Set as the session ends. Every minute still open is handed over
        # then, so none may belong to a student who withdrew monitoring:
        # withdrawing drops the minute in progress.
        self.ending = False

    async def record_windows(self, windows: Sequence[AttentionWindow]) -> None:
        self.handed += len(windows)
        if self.ending:
            self.unconsented += [
                w.user_id for w in windows if not self._room.consents.monitored(w.user_id)
            ]
        await asyncio.sleep(0)
        if self._rng.random() < 0.2:
            raise RuntimeError("the store is down")
        self.windows += windows

    async def record_alert(self, alert: object) -> None:
        return None

    async def record_room_alert(self, alert: RoomAlert) -> None:
        await asyncio.sleep(0)
        if self._rng.random() < 0.2:
            raise RuntimeError("the store is down")
        self.alerts.append(alert)

    async def record_prompt(self, outcome: object) -> None:
        await asyncio.sleep(0)


class _Class:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        # Short limits, so rooms pass through every status inside the run.
        self.room, self.events = make_room(
            window=0.03,
            prompts=PROMPT_CAP,
            prompt_ttl=0.05,
            missed=1,
            refocus_after=5.0,
            refocus_cooldown=0.0,
            voice_fresh=0.05,
            quiet_after=0.02,
            needs_attention_after=0.04,
            max_rooms=4,
        )
        self.row = make_row()
        self.recorder = _Recorder(self.rng, self.room)
        self.room.attention_recorder = self.recorder
        self.room.alert_recorder = self.recorder
        self.room.prompt_recorder = self.recorder  # type: ignore[assignment]
        self.sockets: dict[UUID, list[FakeSocket]] = {}
        self.connections: dict[UUID, list[Connection]] = {}
        self.students: list[UUID] = []
        self.withdrew: set[UUID] = set()
        self.staff: list[FakeSocket] = []
        self.problems: list[str] = []

    @property
    def session_id(self) -> UUID:
        return self.row.session_id

    async def open(self) -> None:
        self.room.activate(self.session_id)
        for role in (Role.LECTURER, Role.ADMIN):
            socket, _ = await join_as(self.events, self.session_id, role)
            self.staff.append(socket)
        for _ in range(STUDENTS):
            socket, student = await join_as(self.events, self.session_id, Role.STUDENT)
            self.students.append(student)
            self.sockets[student] = [socket]
        self._index_connections()

    def _index_connections(self) -> None:
        stream = self.events._streams[self.session_id]
        self.connections = {}
        for connection in stream.members:
            self.connections.setdefault(connection.user_id, []).append(connection)

    # -- what students and the lecturer do ------------------------------------------

    async def signal(self, student: UUID) -> None:
        rng = self.rng
        await self.room.record_attention(
            self.session_id,
            student,
            AttentionSignalPayload(
                gaze_on_screen_ratio=rng.choice([None, 0.0, 0.1, 0.9, 1.0]),
                face_present=rng.choice([None, False, True]),
                speaking=rng.choice([None, False, False, True]),
                window_seconds=rng.choice([0.5, 5.0, 30.0, 3600.0]),
            ),
        )

    async def confirm(self, student: UUID) -> None:
        label = self.rng.choice(["Room 1", "room  1", "Room 2", "Room 3", "Room 4", "Room 5", " "])
        await self.room.confirm_room(self.session_id, student, RoomConfirmPayload(room_label=label))

    async def question(self) -> None:
        live = self.room.get_running(self.session_id)
        if live is None or live.open is not None or live.countdown.paused:
            return
        FakeRepository.staged.append(StagedQuestion())
        delivered = await self.room.deliver(FakeDb(), self.row)  # type: ignore[arg-type]
        if delivered is None:
            return
        for student in self.rng.sample(self.students, self.rng.randint(0, STUDENTS)):
            await self.room.submit(
                self.session_id, student, Role.STUDENT, answer_to(delivered.question_id)
            )

    async def acknowledge(self, student: UUID) -> None:
        for socket in self.sockets[student]:
            prompts = socket.of(ServerEventType.PROMPT_ATTENTION)
            if prompts:
                await self.room.acknowledge_prompt(
                    self.session_id,
                    student,
                    PromptAckPayload(
                        prompt_id=prompts[-1]["data"]["prompt_id"],
                        dismissed=self.rng.random() < 0.5,
                    ),
                )
                return

    async def withdraw(self, student: UUID) -> None:
        consent = self.rng.choice(
            [ConsentType.ENGAGEMENT_MONITORING, ConsentType.CAMERA, ConsentType.MICROPHONE]
        )
        if consent is ConsentType.ENGAGEMENT_MONITORING:
            self.withdrew.add(student)
            # Whatever they are sent from here on is counted separately.
            for socket in self.sockets[student]:
                socket.sent.append({"type": "__withdrew__"})
        await self.room.withdraw_consent(student, consent)

    async def drop_and_return(self, student: UUID) -> None:
        for connection in self.connections.get(student, []):
            await self.events.leave(connection)
        await self.room.departed(self.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)
        await asyncio.sleep(0)
        socket, _ = await join_as(self.events, self.session_id, Role.STUDENT, student)
        self.sockets[student].append(socket)
        self._index_connections()
        await self.room.arrived(self.session_id, student, Role.STUDENT, SessionStatus.ACTIVE)

    async def watch(self) -> None:
        live = self.room.get_running(self.session_id)
        if live is not None:
            await self.room.watch_once(live)
            self.check_rooms()

    async def pause_or_resume(self) -> None:
        live = self.room.get_running(self.session_id)
        if live is None:
            return
        if live.countdown.paused:
            await self.room.resume(FakeDb(), self.row)  # type: ignore[arg-type]
        else:
            await self.room.pause(FakeDb(), self.row)  # type: ignore[arg-type]

    # -- what must hold ------------------------------------------------------------

    def check_rooms(self) -> None:
        connected = len(self.events.student_ids(self.session_id))
        rooms = self.room.rooms(self.session_id)
        if sum(r.members for r in rooms) > connected:
            self.problems.append(f"rooms hold {sum(r.members for r in rooms)} of {connected}")
        for room in rooms:
            if room.speaking_now > room.members or room.silence_seconds < 0:
                self.problems.append(f"impossible room {room}")
            if room.status.value == "unknown" and room.silence_seconds:
                self.problems.append(f"an unheard room is counting silence: {room}")
        if len(rooms) > 4:
            self.problems.append(f"{len(rooms)} rooms in a session limited to 4")
        if [r.room_label for r in rooms] != sorted(
            (r.room_label for r in rooms), key=lambda label: " ".join(label.split()).casefold()
        ):
            self.problems.append("rooms out of label order")

    def check_delivery(self) -> None:
        for sockets in self.sockets.values():
            sent = [message for socket in sockets for message in socket.sent]
            leaked = [m["type"] for m in sent if m["type"] in STAFF_ONLY]
            if leaked:
                self.problems.append(f"a student was sent {sorted(set(leaked))}")
            prompts = {
                m["data"]["prompt_id"]
                for m in sent
                if m["type"] == ServerEventType.PROMPT_ATTENTION.value
            }
            # One prompt may be restated to a reconnecting tab, so prompts are
            # counted by id, not by message.
            if len(prompts) > PROMPT_CAP:
                self.problems.append(f"{len(prompts)} prompts to one student, cap {PROMPT_CAP}")
            for socket in sockets:
                types = [m["type"] for m in socket.sent]
                if "__withdrew__" in types:
                    after = types[types.index("__withdrew__") + 1 :]
                    if ServerEventType.PROMPT_ATTENTION.value in after:
                        self.problems.append("a prompt after monitoring was withdrawn")
        for socket in self.staff:
            private = [m["type"] for m in socket.sent if m["type"] in PRIVATE]
            if private:
                self.problems.append(f"staff were sent {sorted(set(private))}")
        if self.recorder.unconsented:
            self.problems.append("a withdrawn student's open minute was stored at the end")


@pytest.mark.parametrize("seed", range(12))
async def test_nothing_private_leaks_and_nothing_is_left_running_whatever_the_order(
    seed: int,
) -> None:
    lesson = _Class(seed)
    await lesson.open()
    rng = lesson.rng
    steps = [
        (lesson.signal, 40, True),
        (lesson.confirm, 12, True),
        (lesson.acknowledge, 6, True),
        (lesson.withdraw, 1, True),
        (lesson.drop_and_return, 3, True),
        (lesson.watch, 14, False),
        (lesson.question, 6, False),
        (lesson.pause_or_resume, 2, False),
    ]
    actions = [step for step, weight, _ in steps for _ in range(weight)]
    per_student = {step for step, _, takes_student in steps if takes_student}

    async def one(action) -> None:  # noqa: ANN001
        if action in per_student:
            await action(rng.choice(lesson.students))
        else:
            await action()

    # In bursts, so steps overlap: several run at once between pauses long
    # enough for windows, prompts and voice readings to run out.
    for _ in range(STEPS // 8):
        burst = [asyncio.create_task(one(rng.choice(actions))) for _ in range(8)]
        results = await asyncio.gather(*burst, return_exceptions=True)
        lesson.problems += [f"{type(r).__name__}: {r}" for r in results if isinstance(r, Exception)]
        await asyncio.sleep(rng.choice([0, 0, 0.005, 0.03]))

    lesson.check_rooms()
    live = lesson.room.get_running(lesson.session_id)
    assert live is not None
    watch = live.watch
    timers = [live.cycle, watch, *(p.expiry for p in live.attention.pending())]
    if live.open is not None:
        timers.append(live.open.closer)

    lesson.recorder.ending = True
    await lesson.room.end(lesson.session_id, SessionStatus.ENDED, live.delivered)
    await asyncio.sleep(0.1)
    lesson.check_delivery()

    assert lesson.problems == [], f"seed {seed}: {lesson.problems[:5]}"
    assert lesson.room.get_running(lesson.session_id) is None
    assert lesson.room.rooms(lesson.session_id) == []
    still_running = [t.get_name() for t in timers if t is not None and not t.done()]
    assert still_running == [], f"seed {seed}: left running {still_running}"
    await lesson.room.shutdown()


async def test_the_stress_run_does_reach_prompts_rooms_and_the_recorder() -> None:
    """The test above passes trivially if nothing ever happens. This is the
    same run for one seed, checked for having exercised what it claims to."""
    lesson = _Class(seed=3)
    await lesson.open()
    rng = lesson.rng
    for _ in range(150):
        student = rng.choice(lesson.students)
        await rng.choice([lesson.signal, lesson.signal, lesson.confirm])(student)
        if rng.random() < 0.3:
            await lesson.watch()
        if rng.random() < 0.1:
            await lesson.question()
            await asyncio.sleep(0.04)

    sent = [m["type"] for sockets in lesson.sockets.values() for s in sockets for m in s.sent]
    staff = [m["type"] for s in lesson.staff for m in s.sent]
    assert ServerEventType.PROMPT_ATTENTION.value in sent
    assert ServerEventType.ROOM_STATUS.value in staff
    assert ServerEventType.ALERT_RAISED.value in staff
    live = lesson.room.get_running(lesson.session_id)
    assert live is not None
    lesson.recorder.ending = True
    await lesson.room.end(lesson.session_id, SessionStatus.ENDED, live.delivered)
    assert lesson.recorder.handed
    assert lesson.problems == []
    await lesson.room.shutdown()
