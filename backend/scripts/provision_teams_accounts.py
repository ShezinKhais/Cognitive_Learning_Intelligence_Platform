"""Create the C.L.I.P accounts for the team's Teams tenant (CLIP736).

Teams single sign-on finds an account by the Microsoft sign-in name and never
creates one, so each person who uses the Teams app needs a row here first.
Students sign in only through Teams and get no password. The lecturer and the
administrator also use the website, so they get one, generated here and
printed once. Nobody else sees it: it is not stored anywhere but as a hash.

The backend image does not include scripts/, so pipe this into the container
from the repository root (one command):

    docker compose -p clip-demo -f docker-compose.demo.yml exec -T backend
        python - < backend/scripts/provision_teams_accounts.py

Add --reset-passwords after the dash to issue new staff passwords. Running it
again changes nothing else: accounts are found by email first.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from datetime import date

from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.security import hash_password
from app.models.course import Course
from app.models.student import Student
from app.models.user import User

DOMAIN = "clip736.onmicrosoft.com"
COURSE_CODE = "CSIT321"
COURSE_NAME = "Intelligent Systems"

# (sign-in name, role, display name). Sign-in names are stored lower case,
# as the sign-in routes compare them.
ACCOUNTS = [
    ("admin2", "admin", "C.L.I.P Admin"),
    ("lecturer", "lecturer", "Lecturer"),
    ("student1", "student", "Student 1"),
    ("student2", "student", "Student 2"),
    ("student3", "student", "Student 3"),
    ("student4", "student", "Student 4"),
]
STAFF = {"admin", "lecturer"}


async def provision(reset_passwords: bool) -> list[tuple[str, str]]:
    issued = []
    async with get_session_factory()() as db:
        course = await db.scalar(select(Course).where(Course.code == COURSE_CODE))
        if course is None:
            course = Course(code=COURSE_CODE, name=COURSE_NAME, department="Computing and IT")
            db.add(course)
            await db.flush()

        for name, role, display in ACCOUNTS:
            email = f"{name}@{DOMAIN}"
            user = await db.scalar(select(User).where(User.email == email))
            created = user is None
            if created:
                user = User(name=display, role=role, email=email)
                db.add(user)
                await db.flush()
            elif user.role != role:
                raise SystemExit(
                    f"{email} already exists as {user.role}, not {role}. Fix it by hand."
                )

            if role in STAFF and (created or reset_passwords or not user.password_hash):
                password = secrets.token_urlsafe(12)
                user.password_hash = hash_password(password)
                issued.append((email, password))

            if role == "student":
                enrolled = await db.scalar(select(Student).where(Student.user_id == user.user_id))
                if enrolled is None:
                    db.add(
                        Student(
                            user_id=user.user_id,
                            course_id=course.id,
                            accessibility_need=None,
                            consent_status="pending",
                            attention_threshold="medium",
                            special_consideration_status=None,
                            enrolled_at=date.today(),
                        )
                    )
            print(f"{'created' if created else 'exists '}  {role:<8} {email}")

        await db.commit()
    return issued


def main() -> None:
    issued = asyncio.run(provision("--reset-passwords" in sys.argv[1:]))
    if issued:
        print("\nWebsite passwords (shown once, hand each one over in person):")
        for email, password in issued:
            print(f"  {email}  {password}")
    print(f"\nStudents are on {COURSE_CODE} and sign in through Teams only.")


if __name__ == "__main__":
    main()
