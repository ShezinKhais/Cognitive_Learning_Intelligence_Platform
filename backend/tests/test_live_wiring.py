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
    room.check_wiring()
