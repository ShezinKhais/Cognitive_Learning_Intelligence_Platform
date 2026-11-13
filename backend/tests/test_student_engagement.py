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
