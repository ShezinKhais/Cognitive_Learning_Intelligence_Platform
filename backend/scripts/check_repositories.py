"""Verify the initial repository/query layer."""

import asyncio

from app.core.database import get_session_factory
from app.repositories.course_repository import CourseRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository


async def check_repositories() -> None:
    async with get_session_factory()() as session:
        course_repository = CourseRepository(session)
        student_repository = StudentRepository(session)
        user_repository = UserRepository(session)

        course = await course_repository.get_by_code("CLIP101")
        assert course is not None, "CLIP101 course was not found."

        lecturers = await user_repository.list_by_role("lecturer")
        students = await user_repository.list_by_role("student")
        student_records = await student_repository.list_by_course(course.id)

        assert len(lecturers) == 1, f"Expected 1 lecturer, found {len(lecturers)}."
        assert len(students) == 40, f"Expected 40 student users, found {len(students)}."
        assert len(student_records) == 40, (
            f"Expected 40 student records, found {len(student_records)}."
        )

        print("Repository check passed:")
        print(f"- Course: {course.code} - {course.name}")
        print(f"- Lecturers: {len(lecturers)}")
        print(f"- Student users: {len(students)}")
        print(f"- Student records: {len(student_records)}")


if __name__ == "__main__":
    asyncio.run(check_repositories())
