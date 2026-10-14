"""Session reports: the background queue and the PDF.

Owner: General CS, Phase 7 (#65). The queue is tested with a scripted builder;
the database builder and the routes are in test_report_routes.py.
"""

from __future__ import annotations

import asyncio
import io
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader

from app.core.errors import ServiceUnavailableError
from app.schemas.content import Difficulty
from app.schemas.report import ReportParticipation, ReportStatus, SessionReport
from app.schemas.session import AlertOut, SessionStatus, TopicDifficultyOut
from app.services import reports as reports_module
from app.services.report_pdf import render_pdf
from app.services.reports import REPORT_TTL, ReportQueue

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def a_report(session_id: UUID | None = None, **overrides: object) -> SessionReport:
    fields: dict[str, object] = {
        "session_id": session_id or uuid4(),
        "course_code": "CS101",
        "title": "Week 3: Neural networks",
        "status": SessionStatus.ENDED,
        "starts_at": NOW - timedelta(hours=1),
        "ended_at": NOW,
        "generated_at": NOW,
        "participation": ReportParticipation(
            students=12, questions_delivered=4, answers=40, missed_answers=8, attention_prompts=3
        ),
        "topics": [
            TopicDifficultyOut(
                topic="Backpropagation",
                questions=2,
                answers=20,
                mastered=4,
                partial=6,
                struggling=10,
                uncertain=1,
                score=0.7,
                level=Difficulty.HARD,
                expected=Difficulty.MEDIUM,
            )
        ],
        "alerts": [],
    }
    fields.update(overrides)
    return SessionReport(**fields)  # type: ignore[arg-type]


class Builder:
    def __init__(self, *, fail: Exception | None = None, gate: asyncio.Event | None = None):
        self.fail, self.gate = fail, gate
        self.built: list[UUID] = []
        self.running = 0
        self.most = 0

    async def build(self, session_id: UUID) -> SessionReport:
        self.running += 1
        self.most = max(self.most, self.running)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.fail is not None:
                raise self.fail
            self.built.append(session_id)
            return a_report(session_id)
        finally:
            self.running -= 1


async def settle(queue: ReportQueue) -> None:
    await asyncio.gather(*queue._tasks.values(), return_exceptions=True)  # noqa: SLF001


# -- the queue --------------------------------------------------------------------


async def test_a_report_is_queued_at_once_and_ready_later() -> None:
    queue = ReportQueue(Builder(), render=lambda report: b"%PDF-fake")
    session, lecturer = uuid4(), uuid4()

    job = queue.submit(session, lecturer)
    assert job.status is ReportStatus.QUEUED and job.report is None

    await settle(queue)
    assert job.status is ReportStatus.READY
    assert job.report is not None and job.report.session_id == session
    assert job.pdf == b"%PDF-fake"
    assert job.finished_at is not None
    out = job.out()
    assert out.report == job.report and out.error is None


async def test_asking_again_while_one_is_on_the_way_returns_it() -> None:
    gate = asyncio.Event()
    queue = ReportQueue(Builder(gate=gate), render=lambda report: b"%PDF")
    session, lecturer = uuid4(), uuid4()

    first = queue.submit(session, lecturer)
    again = queue.submit(session, lecturer)
    someone_else = queue.submit(session, uuid4())
    gate.set()
    await settle(queue)

    assert again is first
    assert someone_else is not first
    later = queue.submit(session, lecturer)
    assert later is not first, "a finished report is not reused: asking again rebuilds it"
    await settle(queue)


async def test_one_report_is_built_at_a_time() -> None:
    gate = asyncio.Event()
    builder = Builder(gate=gate)
    queue = ReportQueue(builder, render=lambda report: b"%PDF")
    jobs = [queue.submit(uuid4(), uuid4()) for _ in range(3)]
    await asyncio.sleep(0.01)

    assert [j.status for j in jobs].count(ReportStatus.RUNNING) == 1
    gate.set()
    await settle(queue)
    assert builder.most == 1
    assert all(j.status is ReportStatus.READY for j in jobs)


async def test_the_pdf_is_rendered_off_the_event_loop() -> None:
    """Rendering holds a CPU, and every live class on this process shares the loop."""
    loop_thread = threading.get_ident()
    rendered_on: list[int] = []

    def render(report: SessionReport) -> bytes:
        rendered_on.append(threading.get_ident())
        return b"%PDF"

    queue = ReportQueue(Builder(), render=render)
    queue.submit(uuid4(), uuid4())
    await settle(queue)

    assert rendered_on and rendered_on[0] != loop_thread


async def test_a_report_that_cannot_be_built_says_so(caplog: pytest.LogCaptureFixture) -> None:
    queue = ReportQueue(Builder(fail=RuntimeError("database is down")), render=lambda r: b"")
    with caplog.at_level("ERROR", logger="clip.reports"):
        job = queue.submit(uuid4(), uuid4())
        await settle(queue)

    assert job.status is ReportStatus.FAILED
    assert (job.error, job.message) == ("INTERNAL_ERROR", reports_module.FAILED_MESSAGE)
    assert job.report is None and job.pdf is None
    assert "could not build report" in caplog.text


async def test_a_report_that_cannot_be_rendered_is_not_half_ready() -> None:
    def render(report: SessionReport) -> bytes:
        raise ValueError("bad page")

    queue = ReportQueue(Builder(), render=render)
    job = queue.submit(uuid4(), uuid4())
    await settle(queue)

    assert job.status is ReportStatus.FAILED
    assert job.report is None and job.pdf is None


async def test_a_shutdown_marks_unfinished_reports_interrupted() -> None:
    gate = asyncio.Event()
    queue = ReportQueue(Builder(gate=gate), render=lambda report: b"%PDF")
    running = queue.submit(uuid4(), uuid4())
    waiting = queue.submit(uuid4(), uuid4())
    await asyncio.sleep(0.01)

    async with asyncio.timeout(1):
        await queue.drain()

    for job in (running, waiting):
        assert job.status is ReportStatus.FAILED
        assert (job.error, job.message) == ("INTERRUPTED", reports_module.INTERRUPTED_MESSAGE)


async def test_finished_reports_are_dropped_after_a_while() -> None:
    queue = ReportQueue(Builder(), render=lambda report: b"%PDF")
    job = queue.submit(uuid4(), uuid4())
    await settle(queue)
    assert job.finished_at is not None

    assert queue.expire(job.finished_at + REPORT_TTL - timedelta(seconds=1)) == 0
    assert queue.get(job.report_id) is job
    assert queue.expire(job.finished_at + REPORT_TTL + timedelta(seconds=1)) == 1
    assert queue.get(job.report_id) is None


async def test_a_report_still_being_built_is_never_expired() -> None:
    gate = asyncio.Event()
    queue = ReportQueue(Builder(gate=gate), render=lambda report: b"%PDF")
    job = queue.submit(uuid4(), uuid4())

    assert queue.expire(datetime.now(UTC) + REPORT_TTL * 10) == 0
    assert queue.get(job.report_id) is job
    gate.set()
    await settle(queue)


async def test_a_full_queue_makes_room_from_the_oldest_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reports_module, "MAX_REPORTS", 2)
    queue = ReportQueue(Builder(), render=lambda report: b"%PDF")
    oldest = queue.submit(uuid4(), uuid4())
    await settle(queue)
    newer = queue.submit(uuid4(), uuid4())
    await settle(queue)

    newest = queue.submit(uuid4(), uuid4())
    await settle(queue)

    assert queue.get(oldest.report_id) is None
    assert queue.get(newer.report_id) is newer and queue.get(newest.report_id) is newest


async def test_a_queue_full_of_unfinished_reports_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reports_module, "MAX_REPORTS", 2)
    gate = asyncio.Event()
    queue = ReportQueue(Builder(gate=gate), render=lambda report: b"%PDF")
    queue.submit(uuid4(), uuid4())
    queue.submit(uuid4(), uuid4())

    with pytest.raises(ServiceUnavailableError):
        queue.submit(uuid4(), uuid4())
    gate.set()
    await settle(queue)


# -- the PDF ----------------------------------------------------------------------


def pdf_text(data: bytes) -> str:
    """The PDF's text with its line breaks folded, since table cells wrap."""
    pages = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    return " ".join(pages.split())


def an_alert(**overrides: object) -> AlertOut:
    fields: dict[str, object] = {
        "alert_id": uuid4(),
        "session_id": uuid4(),
        "question_id": None,
        "kind": "topic_difficulty",
        "topic": "Backpropagation",
        "message": "Much of the class may be struggling with Backpropagation.",
        "reason": "6 of 8 classified answers were partial or struggling.",
        "confidence": 0.7,
        "explanation": "e",
        "explanation_source": "fallback",
        "confidence_reasons": ["c"],
        "recommendation": "Ask a quick follow-up question.",
        "status": "open",
        "raised_at": NOW,
    }
    fields.update(overrides)
    return AlertOut(**fields)  # type: ignore[arg-type]


def test_the_pdf_shows_the_session_its_topics_and_its_alerts() -> None:
    text = pdf_text(render_pdf(a_report(alerts=[an_alert()])))

    assert "CS101: Week 3: Neural networks" in text
    assert "Backpropagation" in text and "hard" in text
    assert "Ask a quick follow-up question." in text
    assert "13 Oct 2026 12:00 UTC" in text


def test_the_pdf_says_when_there_is_nothing_to_show() -> None:
    text = pdf_text(render_pdf(a_report(topics=[], alerts=[])))

    assert "No answers were marked in this session." in text
    assert "No alerts were raised in this session." in text


def test_text_that_looks_like_markup_is_printed_as_written() -> None:
    """A topic comes from lecture material. Unescaped, `<b>` would be drawn
    as bold and `<a` would break the render."""
    topic = TopicDifficultyOut(
        topic="Tags <b>bold</b> & <a href",
        questions=1,
        answers=1,
        mastered=1,
        partial=0,
        struggling=0,
        uncertain=0,
        score=None,
        level=None,
        expected=None,
    )

    text = pdf_text(render_pdf(a_report(title="A & B <i>", topics=[topic])))

    assert "Tags <b>bold</b> & <a href" in text
    assert "A & B <i>" in text
    assert "too few answers" in text


def test_text_the_font_cannot_draw_does_not_stop_the_report() -> None:
    data = render_pdf(a_report(title="Übung 日本語"))

    assert data.startswith(b"%PDF")
    assert "Übung" in pdf_text(data)


def test_times_are_shown_in_utc() -> None:
    later_elsewhere = NOW.astimezone(ZoneInfo("Asia/Dubai"))

    text = pdf_text(
        render_pdf(a_report(generated_at=later_elsewhere, starts_at=None, ended_at=None))
    )

    assert "Report generated 13 Oct 2026 12:00 UTC" in text
    assert "16:00" not in text
