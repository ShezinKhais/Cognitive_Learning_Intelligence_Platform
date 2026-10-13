from app.realtime.classroom import Classroom
from app.repositories.comprehension_repository import DatabaseComprehensionSource
from app.services.live_recorder import LiveCloseRecorder, LiveResponseRecorder
from app.services.live_wiring import install_live_store


def test_the_live_store_fills_every_seam_the_classroom_checks(monkeypatch):
    """check_wiring refuses to start production with a seam empty, so the
    one install call has to fill them all."""
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    room = Classroom(settings=lambda: type("S", (), {"is_production": True})())

    install_live_store(room)

    assert isinstance(room.recorder, LiveResponseRecorder)
    assert isinstance(room.close_recorder, LiveCloseRecorder)
    assert isinstance(room.comprehension_source, DatabaseComprehensionSource)
    assert room.prompt_recorder is not None
    assert room.participant_recorder is not None
    assert room.alert_recorder is not None
    room.check_wiring()


async def test_the_startup_alert_recorder_stores_the_alert(monkeypatch):
    """Registering a recorder is not enough: what it is handed has to reach the store."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.schemas.session import ClassComprehensionAlert
    from app.services import live_wiring

    stored = []

    async def store(alert):
        stored.append(alert)

    monkeypatch.setattr(live_wiring, "store_comprehension_alert", store)
    room = Classroom(settings=lambda: type("S", (), {"is_production": False})())
    install_live_store(room)
    alert = ClassComprehensionAlert(
        alert_id=uuid4(),
        session_id=uuid4(),
        question_id=uuid4(),
        topic=None,
        correct_ratio=0.2,
        respondents=6,
        threshold=0.5,
        raised_at=datetime.now(UTC),
        message="m",
        reason="r",
        confidence=0.5,
        explanation="e",
        explanation_source="fallback",
        confidence_reasons=["c"],
        recommendation="do",
    )

    await room.alert_recorder.record_alert(alert)

    assert stored == [alert]
