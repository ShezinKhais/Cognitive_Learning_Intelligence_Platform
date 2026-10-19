# A one-off script: blocking HTTP calls inside the one event loop are fine here.
# ruff: noqa: ASYNC210, ASYNC212, ASYNC251
"""Fill a development database with a course that looks lived in, for a demo.

Not part of the app, and refused in production. Run from backend/ against a
backend that is already running on the same database:

    python -m scripts.demo_setup [--api http://127.0.0.1:8000]

What it makes, on course CSIT321:

- 24 students on the roster, the development student among them.
- Three lectures uploaded through the real pipeline, so the questions are the
  model's own: transfer learning and linear regression notes (PDF) and a CNN
  slide deck (PPTX). Set QUESTIONS_PER_MATERIAL above 5 on the backend for
  more of them; the grounding checks keep only some.
  Usable questions are approved; four from the deck are made ready to send.
- Two finished classes, a week apart, with each student's answers, who
  attended and who missed what, so the reports, the student summaries and
  Past sessions have something to show.
- One class prepared for now, to start live during the demo.

Running it again adds nothing twice: people, materials and classes are found
by name before anything is created.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from app.auth.store import LECTURER_ID, STUDENT_ID
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.comprehension_result import ComprehensionResult
from app.models.course import Course
from app.models.delivered_question import DeliveredQuestion
from app.models.missed_response import MissedResponse
from app.models.question import Question
from app.models.session import Session
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.services.comprehension_writer import label_response

COURSE_CODE = "CSIT321"
COURSE_NAME = "Intelligent Systems"
SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "samples"
LECTURES = {
    "lecture.pdf": "application/pdf",
    "linear_regression_notes.pdf": "application/pdf",
    "cnn_lecture.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PAST = [
    # title, days ago, which half of the regression questions it used
    ("Week 5: Transfer learning", 9, 0),
    ("Week 6: Linear regression", 2, 1),
]
UPCOMING = "Week 7: Convolutional networks"
STUDENTS = [
    "Amira Haddad",
    "Daniel Okafor",
    "Priya Raman",
    "Lucas Moreau",
    "Fatima Al Mansoori",
    "Kenji Watanabe",
    "Sofia Rossi",
    "Omar Farouk",
    "Hannah Becker",
    "Arjun Mehta",
    "Layla Nasser",
    "Mateo Silva",
    "Chloe Nguyen",
    "Yusuf Demir",
    "Isabella Costa",
    "Ethan Clarke",
    "Noor Al Hashimi",
    "Ravi Krishnan",
    "Mia Johansson",
    "Tariq Aziz",
    "Grace Lim",
    "Samuel Mensah",
    "Elena Petrova",
]
FREE_TEXT_ANSWERS = {
    "mastered": (
        "It finds the weights that make the squared error between predictions and labels "
        "as small as possible."
    ),
    "partial": "It makes the model fit the data better by changing the weights.",
    "struggling": "It is the part of the model that draws the graph.",
}
FEEDBACK = "Compare your answer with the key points on the slide."
rng = random.Random(321)


def log(message: str) -> None:
    print(f"[demo] {message}", flush=True)


# -- people ------------------------------------------------------------------------------


async def people() -> tuple[uuid.UUID, list[uuid.UUID]]:
    """The course and its roster. The development student is listed first."""
    async with get_session_factory()() as db:
        course = await db.scalar(select(Course).where(Course.code == COURSE_CODE))
        if course is None:
            course = Course(code=COURSE_CODE, name=COURSE_NAME, department="Computing and IT")
            db.add(course)
            await db.flush()
        roster: list[uuid.UUID] = []
        users = [(STUDENT_ID, None)] + [(None, name) for name in STUDENTS]
        for user_id, name in users:
            if user_id is None:
                email = name.lower().replace(" ", ".") + "@uowmail.example.edu"
                user = await db.scalar(select(User).where(User.email == email))
                if user is None:
                    user = User(name=name, role="student", email=email)
                    db.add(user)
                    await db.flush()
                user_id = user.user_id
            # A user is enrolled on one course. The development student starts
            # on the development course, so in a demo database it moves here.
            student = await db.scalar(select(Student).where(Student.user_id == user_id))
            if student is not None and student.course_id != course.id:
                student.course_id = course.id
            if student is None:
                student = Student(
                    user_id=user_id,
                    course_id=course.id,
                    consent_status="granted",
                    enrolled_at=date.today() - timedelta(days=60),
                )
                db.add(student)
                await db.flush()
            roster.append(student.student_id)
        await db.commit()
        log(f"{COURSE_CODE}: {len(roster)} students enrolled")
        return course.id, roster


# -- materials, through the running backend ----------------------------------------------


def sign_in(api: httpx.Client) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tests.dev_credentials import LECTURER_PASSWORD

    reply = api.post(
        "/auth/login", json={"email": "lecturer@clip.example.com", "password": LECTURER_PASSWORD}
    )
    reply.raise_for_status()
    api.headers["Authorization"] = f"Bearer {reply.json()['access_token']}"
    api.post("/auth/consent", json={"consent_type": "terms", "granted": True}).raise_for_status()


def material(api: httpx.Client, filename: str, content_type: str) -> str:
    """The material's id, uploading and waiting for it the first time."""
    existing = api.get("/materials", params={"limit": 200}).json()["items"]
    found = next(
        (m for m in existing if m["filename"] == filename and m["status"] != "failed"), None
    )
    if found is None:
        with open(SAMPLES / filename, "rb") as handle:
            reply = api.post("/materials", files={"file": (filename, handle, content_type)})
        reply.raise_for_status()
        found = reply.json()
        log(f"uploaded {filename}; the model is writing its questions")
    started = time.monotonic()
    while found["status"] in {"pending", "processing"}:
        if time.monotonic() - started > 900:
            sys.exit(f"{filename} is still processing after 15 minutes")
        time.sleep(5)
        reply = api.get(f"/materials/{found['id']}")
        if reply.status_code >= 400:
            sys.exit(f"{filename}: {reply.status_code} {reply.text[:300]}")
        found = reply.json()
    if found["status"] != "completed":
        sys.exit(f"{filename} failed: {found.get('error')}")
    if found.get("course_code") != COURSE_CODE:
        api.patch(f"/materials/{found['id']}", json={"course_code": COURSE_CODE}).raise_for_status()
    log(f"{filename} ready ({int(time.monotonic() - started)} s)")
    return found["id"]


def approve(api: httpx.Client, material_id: str) -> list[dict]:
    """Approve every draft that can be approved, and return the questions."""
    questions = api.get(f"/materials/{material_id}/questions", params={"limit": 200}).json()[
        "items"
    ]
    for question in questions:
        if question["status"] == "draft":
            # One at a time, so a draft the review rules refuse is skipped
            # rather than failing the batch.
            api.patch(
                f"/materials/{material_id}/questions/{question['id']}", json={"status": "approved"}
            )
    return api.get(f"/materials/{material_id}/questions", params={"limit": 200}).json()["items"]


# -- history, written as a class would have left it ---------------------------------------


async def past_class(
    course_id: uuid.UUID,
    roster: list[uuid.UUID],
    title: str,
    days_ago: int,
    question_ids: list[uuid.UUID],
) -> None:
    async with get_session_factory()() as db:
        if await db.scalar(select(Session).where(Session.title == title)) is not None:
            log(f"{title}: already there")
            return
        day = datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0)
        start = day - timedelta(days=days_ago)
        end = start + timedelta(minutes=50)
        session = Session(
            instructor_id=LECTURER_ID,
            course_id=course_id,
            title=title,
            start_time=start,
            end_time=end,
            ended_at=end,
            mode="in_person",
            status="ended",
        )
        db.add(session)
        await db.flush()

        # Most of the class came; the development student always did.
        present = [roster[0]] + [s for s in roster[1:] if rng.random() < 0.88]
        for student_id in present:
            joined = start + timedelta(minutes=rng.randint(0, 6))
            db.add(
                SessionParticipant(
                    session_id=session.session_id,
                    student_id=student_id,
                    joined_at=joined,
                    last_seen_at=end,
                    left_at=end,
                    connection_count=1,
                )
            )

        # Each question is easier or harder than the last, so the topics differ.
        rates = [0.86, 0.62, 0.38, 0.78, 0.52, 0.3]
        for index, question_id in enumerate(question_ids):
            question = await db.get(Question, question_id)
            assert question is not None
            question.status = "delivered"
            question.session_id = session.session_id
            delivered_at = start + timedelta(minutes=8 + index * 9)
            answered = [s for s in present if s == roster[0] or rng.random() < 0.9]
            if index == len(question_ids) - 1 and roster[0] in answered:
                answered.remove(roster[0])  # one the development student let pass
            delivery = DeliveredQuestion(
                session_id=session.session_id,
                question_id=question_id,
                delivered_at=delivered_at,
                closes_at=delivered_at + timedelta(seconds=60),
                closed_at=delivered_at + timedelta(seconds=60),
                close_reason="window_elapsed",
                window_seconds=60,
                eligible_count=len(present),
                respondent_count=len(answered),
            )
            db.add(delivery)
            await db.flush()
            rate = rates[index % len(rates)]
            for student_id in answered:
                right = rng.random() < rate if student_id != roster[0] else index % 3 != 1
                submitted = delivered_at + timedelta(seconds=rng.randint(6, 55))
                if question.question_type == "mcq" and question.options:
                    correct = question.correct_option or 0
                    wrong = [i for i in range(len(question.options)) if i != correct]
                    response = StudentResponse(
                        session_id=session.session_id,
                        student_id=student_id,
                        question_id=question_id,
                        selected_option=correct if right else rng.choice(wrong),
                        is_correct=right,
                        elapsed_ms=int((submitted - delivered_at).total_seconds() * 1000),
                        submitted_at=submitted,
                    )
                    db.add(response)
                else:
                    label = "mastered" if right else rng.choice(["partial", "struggling"])
                    response = StudentResponse(
                        session_id=session.session_id,
                        student_id=student_id,
                        question_id=question_id,
                        free_text=FREE_TEXT_ANSWERS[label],
                        elapsed_ms=int((submitted - delivered_at).total_seconds() * 1000),
                        submitted_at=submitted,
                    )
                    db.add(response)
                    await db.flush()
                    db.add(
                        ComprehensionResult(
                            response_id=response.response_id,
                            label=label,
                            confidence_score=round(rng.uniform(0.7, 0.95), 2),
                            score={"mastered": 0.9, "partial": 0.55, "struggling": 0.2}[label],
                            ai_feedback_text=FEEDBACK,
                            reasons=[],
                            key_point_coverage=[],
                        )
                    )
            for student_id in present:
                if student_id not in answered:
                    db.add(MissedResponse(delivery_id=delivery.delivery_id, student_id=student_id))
        await db.commit()
        log(f"{title}: {len(present)} attended, {len(question_ids)} questions")


async def label_answers() -> None:
    """Label every marked answer the way the live class does, so the report's
    topics and the student summaries have comprehension to read."""
    async with get_session_factory()() as db:
        answers = (
            await db.scalars(select(StudentResponse).where(StudentResponse.is_correct.isnot(None)))
        ).all()
        for response in answers:
            await label_response(db, response)
        await db.commit()
        log(f"{len(answers)} marked answers labelled")


# -- the class to run live ----------------------------------------------------------------


def upcoming(api: httpx.Client, staged: int) -> None:
    sessions = api.get("/sessions", params={"limit": 200}).json()["items"]
    if any(s["title"] == UPCOMING and s["status"] in {"prepared", "active"} for s in sessions):
        log(f"{UPCOMING}: already prepared")
        return
    starts = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    api.post(
        "/sessions", json={"course_code": COURSE_CODE, "title": UPCOMING, "starts_at": starts}
    ).raise_for_status()
    log(f"{UPCOMING}: prepared, {staged} questions ready to send")


async def run(api_base: str) -> None:
    # One event loop for the whole run: the engine is cached against the first.
    course_id, roster = await people()
    with httpx.Client(base_url=f"{api_base}/api/v1", timeout=60) as api:
        sign_in(api)
        ids = {name: material(api, name, kind) for name, kind in LECTURES.items()}
        notes = [approve(api, ids[name]) for name in ("lecture.pdf", "linear_regression_notes.pdf")]
        deck = approve(api, ids["cnn_lecture.pptx"])

        # Week 5 asks from the first notes and week 6 from the second; when
        # one gave too few, the two share what there is.
        usable = [[q["id"] for q in qs if q["status"] in {"approved", "delivered"}] for qs in notes]
        halves = usable
        if min(len(h) for h in usable) < 2:
            pooled = usable[0] + usable[1]
            halves = [pooled[: len(pooled) // 2], pooled[len(pooled) // 2 :]]
        for title, days_ago, half in PAST:
            chosen = [uuid.UUID(q) for q in halves[half][:6]]
            if chosen:
                await past_class(course_id, roster, title, days_ago, chosen)

        ready = [q for q in deck if q["status"] == "approved"][:4]
        for question in ready:
            api.patch(
                f"/materials/{ids['cnn_lecture.pptx']}/questions/{question['id']}",
                json={"status": "staged"},
            )
        upcoming(api, len(ready))
    await label_answers()
    log("done. Sign in as the lecturer or the student and look around.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if get_settings().is_production:
        sys.exit("Refusing to run in production.")
    asyncio.run(run(args.api))


if __name__ == "__main__":
    main()
