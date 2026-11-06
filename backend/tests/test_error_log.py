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


SENSITIVE = [
    (
        "a refresh token",
        "refresh failed for eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        "eyJ",
    ),
    ("a bearer header", "upstream said Authorization: Bearer abc.def-ghi", "abc.def"),
    ("a password value", "bad config password=hunter2 for clip", "hunter2"),
    ("a client secret", "CLIENT_SECRET='s3cr3t~value' rejected", "s3cr3t"),
    ("a database URL", "cannot reach postgresql+asyncpg://clip:pw123@db:5432/clip", "pw123"),
    ("a link with a query", "fetch https://example.test/cb?code=XYZ987 failed", "XYZ987"),
    ("a student email", "no account for student1@CLIP736.onmicrosoft.com", "student1@"),
    (
        "a hex key",
        "key 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 refused",
        "9f86d0",
    ),
    ("a random token", "token_urlsafe gave Zk3p9Qx2LmN8rT5vW1yB4cD7fG0hJ6kL3mP9sV2xA", "Zk3p9Q"),
    (
        "query values",
        "IntegrityError: duplicate key [SQL: INSERT INTO users (email, name) VALUES ($1, $2)]"
        " [parameters: ('ana@uni.test', 'Ana Student')]",
        "Ana Student",
    ),
]


def test_sensitive_values_never_reach_the_admin_view() -> None:
    """Exception messages can quote anything; none of it is shown as is."""
    log = ErrorLog()
    logger = _logger(log)
    for _, message, _ in SENSITIVE:
        logger.error(message)
    shown = " | ".join(f"{g.where} {g.message}" for g in log.recent())
    leaked = [label for label, _, secret in SENSITIVE if secret in shown]
    assert not leaked, f"shown to admins: {leaked}\n{shown}"


def test_redaction_keeps_what_an_admin_needs() -> None:
    from app.core.error_log import redact

    kept = [
        "security_event=ACCESS_DENIED user_id=3fa85f64-5717-4562-b3fc-2c963f66afa6"
        " actual_role=student",
        "Unhandled error on GET /api/v1/sessions/3fa85f64-5717-4562-b3fc-2c963f66afa6/rooms",
        "app.services.teams_notifications could not post (ServiceUnavailableError)",
        "test_a_service_commit_cannot_precede_its_audit_because_of_the_listener failed",
    ]
    for message in kept:
        assert redact(message) == message


def test_a_browser_report_is_redacted_on_the_server_too(as_admin) -> None:
    """The frontend removes links and emails first, but the server does not
    rely on it: a report sent by anything else is cleaned the same way."""
    from app.core.error_log import error_log

    error_log.clear()
    response = as_admin.post(
        "/api/v1/client-errors",
        json={
            "kind": "script",
            "message": "token=abc123secret leaked by a.b@c.de",
            "page": "/student",
        },
    )
    assert response.status_code == 204
    body = as_admin.get("/api/v1/admin/errors").json()
    [group] = [g for g in body["groups"] if g["source"] == "client"]
    assert "abc123secret" not in group["message"] and "a.b@c.de" not in group["message"]
