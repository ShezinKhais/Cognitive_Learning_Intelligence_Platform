"""A student's own engagement history (#243), against a real database. Each
test works inside one transaction that is never committed."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.consent import Consent
from app.models.delivered_question import DeliveredQuestion
from app.models.missed_response import MissedResponse
from app.models.session import Session
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.services import student_engagement
from tests.test_topic_difficulty import database, question  # noqa: F401

NOW = datetime.now(UTC)


async def _ended_class(db, ids):  # noqa: ANN001, ANN202
    session = await db.get(Session, ids.session)
    session.status = "ended"
    session.ended_at = NOW
    student = (await db.execute(select(Student).where(Student.user_id == ids.user))).scalar_one()
    return session, student


def _window(session_id, student_id, start, *, camera=False, microphone=False):  # noqa: ANN001, ANN202
    return AttentionSignalSummary(
        session_id=session_id,
        student_id=student_id,
        window_start=start,
        window_seconds=60.0,
        sample_count=12,
        gaze_on_screen_ratio=0.8 if camera else None,
        face_present_ratio=0.9 if camera else None,
        speaking_ratio=0.1 if microphone else None,
    )


def _consent(user_id, kind, granted, at):  # noqa: ANN001, ANN202
    return Consent(user_id=user_id, consent_type=kind, granted=granted, recorded_at=at)


async def test_a_class_reports_participation_and_only_consented_readings(database, question):  # noqa: F811
    async with database() as db:
        session, student = await _ended_class(db, question)
        delivery = DeliveredQuestion(
            session_id=session.session_id,
            question_id=question.question,
            delivered_at=NOW - timedelta(minutes=30),
            closes_at=NOW - timedelta(minutes=29),
            window_seconds=30,
        )
        db.add(delivery)
        await db.flush()
        db.add(MissedResponse(delivery_id=delivery.delivery_id, student_id=student.student_id))
        granted_at = NOW - timedelta(minutes=40)
        db.add_all(
            [
                _consent(question.user, "engagement_monitoring", True, granted_at),
                _consent(question.user, "camera", True, granted_at),
                # Before the grant: never counted.
                _window(
                    session.session_id,
                    student.student_id,
                    granted_at - timedelta(minutes=5),
                    camera=True,
                ),
                _window(
                    session.session_id,
                    student.student_id,
                    NOW - timedelta(minutes=20),
                    camera=True,
                    microphone=True,
                ),
                _window(
                    session.session_id, student.student_id, NOW - timedelta(minutes=19), camera=True
                ),
            ]
        )
        # Another student's readings in the same class are not this student's.
        other = User(name="Other", role="student", email=f"o-{session.session_id}@example.com")
        db.add(other)
        await db.flush()
        neighbour = Student(
            user_id=other.user_id,
            course_id=session.course_id,
            consent_status="granted",
            enrolled_at=NOW.date(),
        )
        db.add(neighbour)
        await db.flush()
        db.add(
            _window(
                session.session_id, neighbour.student_id, NOW - timedelta(minutes=18), camera=True
            )
        )
        await db.flush()

        result = await student_engagement.history(db, question.user, 20, 0)

        [one] = result.classes
        assert one.participation.checkpoints == 1
        assert (one.participation.answered, one.participation.missed) == (0, 1)
        assert (one.readings.camera, one.readings.camera_windows) == ("available", 2)
        # The microphone was never agreed to, so its reading is not shown.
        assert (one.readings.microphone, one.readings.microphone_windows) == ("not_consented", None)


async def test_withdrawn_monitoring_hides_every_reading(database, question):  # noqa: F811
    async with database() as db:
        session, student = await _ended_class(db, question)
        db.add_all(
            [
                _consent(question.user, "camera", True, NOW - timedelta(hours=2)),
                # Withdrawn after the class: one row per consent, now refused.
                _consent(question.user, "engagement_monitoring", False, NOW - timedelta(hours=1)),
                _window(
                    session.session_id, student.student_id, NOW - timedelta(minutes=90), camera=True
                ),
            ]
        )
        await db.flush()

        [one] = (await student_engagement.history(db, question.user, 20, 0)).classes

        assert one.readings.camera == "not_consented" and one.readings.camera_windows is None


async def test_no_readings_are_none_recorded_not_zero(database, question):  # noqa: F811
    async with database() as db:
        await _ended_class(db, question)
        db.add_all(
            [
                _consent(question.user, "engagement_monitoring", True, NOW - timedelta(hours=2)),
                _consent(question.user, "microphone", True, NOW - timedelta(hours=2)),
                StudentResponse(
                    session_id=question.session,
                    student_id=(
                        await db.execute(
                            select(Student.student_id).where(Student.user_id == question.user)
                        )
                    ).scalar_one(),
                    question_id=question.question,
                    selected_option=1,
                    is_correct=True,
                ),
            ]
        )
        await db.flush()

        [one] = (await student_engagement.history(db, question.user, 20, 0)).classes

        assert one.participation.answered == 1
        assert (one.readings.microphone, one.readings.microphone_windows) == ("none_recorded", None)
        assert one.readings.camera == "not_consented"


async def test_a_class_still_running_is_not_listed(database, question):  # noqa: F811
    async with database() as db:
        result = await student_engagement.history(db, question.user, 20, 0)
        assert result.classes == [] and result.total == 0


async def test_partial_sensor_signals_are_reported_separately(database, question):  # noqa: F811
    """One sensor being unavailable must not erase the other's valid reading."""
    async with database() as db:
        session, student = await _ended_class(db, question)
        granted_at = NOW - timedelta(hours=1)

        db.add_all(
            [
                _consent(question.user, "engagement_monitoring", True, granted_at),
                _consent(question.user, "camera", True, granted_at),
                _consent(question.user, "microphone", True, granted_at),
                _window(
                    session.session_id,
                    student.student_id,
                    NOW - timedelta(minutes=20),
                    camera=True,
                ),
                _window(
                    session.session_id,
                    student.student_id,
                    NOW - timedelta(minutes=19),
                    microphone=True,
                ),
            ]
        )
        await db.flush()

        [record] = (await student_engagement.history(db, question.user, 20, 0)).classes

        assert record.readings.camera == "available"
        assert record.readings.camera_windows == 1
        assert record.readings.microphone == "available"
        assert record.readings.microphone_windows == 1

        await db.rollback()


async def test_withdraw_regrant_and_erasure_never_restore_old_windows(database, question):  # noqa: F811
    """Consent changes and deleted readings must fail closed."""
    from sqlalchemy import delete

    async with database() as db:
        session, student = await _ended_class(db, question)

        monitoring = _consent(
            question.user,
            "engagement_monitoring",
            True,
            NOW - timedelta(hours=4),
        )
        camera = _consent(
            question.user,
            "camera",
            True,
            NOW - timedelta(hours=4),
        )

        db.add_all(
            [
                monitoring,
                camera,
                _window(
                    session.session_id,
                    student.student_id,
                    NOW - timedelta(hours=3),
                    camera=True,
                ),
            ]
        )
        await db.flush()

        [before] = (await student_engagement.history(db, question.user, 20, 0)).classes
        assert before.readings.camera == "available"
        assert before.readings.camera_windows == 1

        camera.granted = False
        camera.recorded_at = NOW - timedelta(hours=2)
        await db.flush()

        [withdrawn] = (await student_engagement.history(db, question.user, 20, 0)).classes
        assert withdrawn.readings.camera == "not_consented"
        assert withdrawn.readings.camera_windows is None

        camera.granted = True
        camera.recorded_at = NOW - timedelta(hours=1)
        await db.flush()

        [regranted] = (await student_engagement.history(db, question.user, 20, 0)).classes
        assert regranted.readings.camera == "none_recorded"
        assert regranted.readings.camera_windows is None

        db.add(
            _window(
                session.session_id,
                student.student_id,
                NOW - timedelta(minutes=30),
                camera=True,
            )
        )
        await db.flush()

        [new_reading] = (await student_engagement.history(db, question.user, 20, 0)).classes
        assert new_reading.readings.camera == "available"
        assert new_reading.readings.camera_windows == 1

        await db.execute(
            delete(AttentionSignalSummary).where(
                AttentionSignalSummary.session_id == session.session_id,
                AttentionSignalSummary.student_id == student.student_id,
            )
        )
        await db.flush()

        [erased] = (await student_engagement.history(db, question.user, 20, 0)).classes
        assert erased.readings.camera == "none_recorded"
        assert erased.readings.camera_windows is None

        await db.rollback()