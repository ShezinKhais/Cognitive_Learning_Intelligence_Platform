"""The admin's view of recent errors."""

import logging

from app.api.v1 import monitoring
from app.core.error_log import ErrorLog, ErrorLogHandler


def _logger(log: ErrorLog) -> logging.Logger:
    logger = logging.getLogger("clip.test.error_log")
    logger.handlers = [ErrorLogHandler(log)]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger


def test_errors_and_security_events_are_kept_and_the_rest_ignored() -> None:
    log = ErrorLog()
    logger = _logger(log)
    logger.info("fine")
    logger.warning("just a warning")
    logger.warning("security_event=BOT_TOKEN_REJECTED reason=x")
    logger.error("the store is down")
    assert [g.message for g in log.recent()] == [
        "the store is down",
        "security_event=BOT_TOKEN_REJECTED reason=x",
    ]


def test_repeats_are_one_group_with_a_count_and_move_to_the_top() -> None:
    log = ErrorLog()
    logger = _logger(log)
    logger.error("A")
    logger.error("B")
    logger.error("A")
    first, second = log.recent()
    assert (first.message, first.count) == ("A", 2)
    assert (second.message, second.count) == ("B", 1)
    assert log.total == 3


def test_an_exception_names_its_type_but_not_its_trace() -> None:
    log = ErrorLog()
    logger = _logger(log)
    try:
        raise KeyError("secret-ish")
    except KeyError:
        logger.exception("Unhandled error on GET /x")
    [group] = log.recent()
    assert group.message == "Unhandled error on GET /x (KeyError)"


def test_the_log_is_bounded_and_messages_are_cut_short() -> None:
    log = ErrorLog(max_groups=3)
    for number in range(5):
        log.add(source="server", level="ERROR", where="w", message=f"m{number} " + "x" * 400)
    groups = log.recent()
    assert len(groups) == 3 and groups[0].message.startswith("m4")
    assert len(groups[0].message) == 300


def test_a_user_can_report_only_a_few_crashes_a_minute() -> None:
    limiter = monitoring._Limiter()
    user = object()
    allowed = [limiter.allow(user, 0.0) for _ in range(monitoring.REPORTS_PER_WINDOW + 2)]
    assert allowed.count(True) == monitoring.REPORTS_PER_WINDOW
    assert limiter.allow(user, monitoring.WINDOW_SECONDS + 1)


def test_a_crash_report_reaches_the_admin_view(as_admin) -> None:
    from app.core.error_log import error_log

    error_log.clear()
    response = as_admin.post(
        "/api/v1/client-errors",
        json={"kind": "render", "message": "x is undefined", "page": "/admin?x=1"},
    )
    assert response.status_code == 204
    body = as_admin.get("/api/v1/admin/errors").json()
    [group] = [g for g in body["groups"] if g["source"] == "client"]
    assert group["where"] == "/admin (render, admin)"
    assert group["message"] == "x is undefined"
