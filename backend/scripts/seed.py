"""Seed the database with one course, one lecturer, and 40 students."""

import asyncio
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.course import Course
from app.models.student import Student
from app.models.user import User

COURSE_CODE = "CLIP101"


async def seed_database() -> None:
    async with SessionLocal() as session:
        try:
            # Create or retrieve the course.
            course = await session.scalar(select(Course).where(Course.code == COURSE_CODE))

            if course is None:
                course = Course(
                    code=COURSE_CODE,
                    name="Cognitive Learning and Inclusive Participation",
                    department="Computer Science",
                )
                session.add(course)
                await session.flush()

            # Create the lecturer.
            lecturer_email = "lecturer@clip.edu"

            lecturer = await session.scalar(select(User).where(User.email == lecturer_email))

            if lecturer is None:
                session.add(
                    User(
                        name="Dr. Sarah Ahmed",
                        role="lecturer",
                        email=lecturer_email,
                    )
                )

            # Create 40 student users and student records.
            for number in range(1, 41):
                student_email = f"student{number:02d}@clip.edu"

                student_user = await session.scalar(select(User).where(User.email == student_email))

                if student_user is None:
                    student_user = User(
                        name=f"Student {number:02d}",
                        role="student",
                        email=student_email,
                    )
                    session.add(student_user)
                    await session.flush()

                student_record = await session.scalar(
                    select(Student).where(Student.user_id == student_user.user_id)
                )

                if student_record is None:
                    session.add(
                        Student(
                            user_id=student_user.user_id,
                            course_id=course.id,
                            accessibility_need=None,
                            consent_status="granted",
                            attention_threshold="medium",
                            special_consideration_status=None,
                            enrolled_at=date.today(),
                        )
                    )

            await session.commit()
            print("Seed completed: 1 course, 1 lecturer, and 40 students.")

        except Exception:
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(seed_database())
