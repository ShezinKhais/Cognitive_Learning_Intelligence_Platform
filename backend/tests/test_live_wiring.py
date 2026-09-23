from app.realtime.classroom import classroom
from app.services.live_recorder import LiveResponseRecorder


def test_importing_live_wiring_registers_the_response_recorder():
    import app.services.live_wiring  # noqa: F401

    assert isinstance(classroom.recorder, LiveResponseRecorder)
