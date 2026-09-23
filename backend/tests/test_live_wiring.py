from app.realtime.classroom import classroom
from app.services.live_recorder import LiveCloseRecorder, LivePromptRecorder, LiveResponseRecorder


def test_importing_live_wiring_registers_the_response_recorder():
    import app.services.live_wiring  # noqa: F401

    assert isinstance(classroom.recorder, LiveResponseRecorder)


def test_importing_live_wiring_registers_the_close_recorder():
    import app.services.live_wiring  # noqa: F401

    assert isinstance(classroom.close_recorder, LiveCloseRecorder)


def test_importing_live_wiring_registers_the_prompt_recorder():
    import app.services.live_wiring  # noqa: F401

    assert isinstance(classroom.prompt_recorder, LivePromptRecorder)
