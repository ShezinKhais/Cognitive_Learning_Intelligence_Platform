"""Privacy, access and alert behavior of the administrator diagnostics."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.api.v1 import monitoring
from app.core.error_log import SPIKE_THRESHOLD, ErrorLog, ErrorLogHandler, error_log
from app.core.logging import monitoring_request_id_var


def _logger(log: ErrorLog) -> logging.Logger:
    logger = logging.Logger("clip.test.error_log")
    logger.addHandler(ErrorLogHandler(log))
    return logger


def test_server_reports_keep_location_and_generated_id_without_raw_content() -> None:
    log = ErrorLog()
    logger = _logger(log)
    request_id = str(uuid4())
    context = monitoring_request_id_var.set(request_id)
    try:
        logger.warning("just a warning")
        logger.warning("security_event=ACCESS_DENIED user=Private Student")
        try:
            raise ValueError("private student answer")
        except ValueError:
            logger.exception("body=%s", "private unlabelled answer")
    finally:
        monitoring_request_id_var.reset(context)

    error, warning = log.recent()
    assert error.message == "Server exception (ValueError)"
    assert "test_error_log.py:" in error.where
    assert error.request_id == request_id
    assert warning.message == "Security check refused a request"
    assert "private" not in repr(log.recent()).lower()


def test_groups_are_bounded_and_expire_after_24_hours_without_a_repeat() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    log = ErrorLog(max_groups=2, clock=lambda: now)

    for location in ("first", "second", "third", "second"):
        log.add(source="server", level="ERROR", where=location, message="Server error")
    assert [(group.where, group.count) for group in log.recent()] == [("second", 2), ("third", 1)]
    now += timedelta(hours=24)
    assert log.recent() == []


def test_spike_requires_two_completed_minutes_of_server_errors() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    log = ErrorLog(clock=lambda: now)

    for _ in range(SPIKE_THRESHOLD):
        log.add(source="server", level="WARNING", where="guard", message="Refused")
        log.add(source="client", level="ERROR", where="/student", message="Crash")
    now += timedelta(minutes=1)
    for _ in range(2):
        for _ in range(SPIKE_THRESHOLD):
            log.add(source="server", level="ERROR", where="api", message="Server error")
        assert not log.server_error_spike()
        now += timedelta(minutes=1)

    assert log.server_error_spike()
    now += timedelta(minutes=1)
    assert not log.server_error_spike()


def test_a_user_can_report_only_a_few_crashes_a_minute() -> None:
    limiter = monitoring._Limiter()
    user = uuid4()
    allowed = [limiter.allow(user, 0.0) for _ in range(monitoring.REPORTS_PER_WINDOW + 2)]
    assert allowed.count(True) == monitoring.REPORTS_PER_WINDOW
    assert limiter.allow(user, monitoring.WINDOW_SECONDS + 1)


def test_legacy_report_cannot_expose_private_message_or_route_in_dashboard(as_admin) -> None:
    error_log.clear()
    response = as_admin.post(
        "/api/v1/client-errors",
        json={
            "kind": "render",
            "message": "private student answer and password=example",
            "page": "/student/private-student-id?secret=private",
        },
        headers={"X-Request-ID": "private-caller-id"},
    )
    assert response.status_code == 204
    dashboard = as_admin.get("/api/v1/admin/errors")
    assert dashboard.status_code == 200
    [group] = [g for g in dashboard.json()["groups"] if g["source"] == "client"]
    assert group["where"] == "/student (render, admin)"
    assert group["message"] == "Page failed to render"
    assert "private" not in dashboard.text


def test_student_cannot_read_diagnostics(as_student) -> None:
    assert as_student.get("/api/v1/admin/errors").status_code == 403


def test_an_admin_can_record_synthetic_errors_that_trip_the_spike(as_admin) -> None:
    error_log.clear()
    response = as_admin.post("/api/v1/admin/errors/synthetic?count=3")
    assert response.status_code == 204
    groups = as_admin.get("/api/v1/admin/errors").json()["groups"]
    [synthetic] = [g for g in groups if "SyntheticMonitoringFailure" in g["message"]]
    assert synthetic["count"] == 3
    assert as_admin.post("/api/v1/admin/errors/synthetic?count=31").status_code == 422
    # Readiness carries only a yes or no, for the outside watcher.
    assert as_admin.get("/api/v1/ready").json()["server_error_spike"] in (True, False)


def test_a_student_cannot_record_synthetic_errors(as_student) -> None:
    assert as_student.post("/api/v1/admin/errors/synthetic").status_code == 403
