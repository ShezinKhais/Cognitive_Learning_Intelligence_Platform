"""Adding a list of students to a course at once (#293).

A lecturer or admin pastes or uploads a list of emails, or `name,email` lines,
and sees what each line will do before anything changes. Confirming applies
exactly that, in one transaction. The rules are those for adding one student
(course_membership.add_student): the caller must be an admin or teach the
course, and only student accounts are added. An admin may also create the
accounts that do not exist yet; a lecturer may not, since creating people is
admin work everywhere else.

Lines are read here, not in the browser, so the preview and the confirm are
worked out by the same code from the same text.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import PermissionError_, ValidationError
from app.models.course_enrollment import CourseEnrollment
from app.models.student import Student
from app.models.user import User
from app.schemas.accounts import (
    EMAIL_PATTERN,
    BulkRosterIn,
    BulkRosterLine,
    BulkRosterOut,
    BulkRosterOutcome,
)
from app.schemas.identity import Role
from app.services import course_membership

MAX_LINES = 500
_EMAIL = re.compile(EMAIL_PATTERN)
_HEADER_WORDS = {"email", "e-mail", "mail", "name", "full name", "student", "student email"}


def parse(text: str) -> list[tuple[int, str, str | None]]:
    """(line number, email, name) for each non-blank line. A line is an email
    alone, or name and email in either order, split by comma, tab or
    semicolon. A first line made only of header words is skipped."""
    rows: list[tuple[int, str, str | None]] = []
    dialect = csv.excel
    sample = text[:4096]
    if "\t" in sample and "," not in sample:
        dialect = csv.excel_tab
    elif ";" in sample and "," not in sample:
        dialect = type("semi", (csv.excel,), {"delimiter": ";"})
    for number, cells in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
        cells = [cell.strip() for cell in cells if cell.strip()]
        if not cells:
            continue
        if number == 1 and all(cell.lower() in _HEADER_WORDS for cell in cells):
            continue
        emails = [cell for cell in cells if "@" in cell]
        email = (emails[0] if emails else cells[0]).lower()
        others = [cell for cell in cells if cell.lower() != email]
        name = others[0][:100] if others else None
        rows.append((number, email, name))
    return rows


def _name_from(email: str) -> str:
    """jane.doe@uni.edu as Jane Doe, for an account the file names no one for."""
    local = email.split("@", 1)[0]
    words = [word for word in re.split(r"[._\-+]+", local) if word]
    return (" ".join(word.capitalize() for word in words) or local)[:100]


async def run(
    db: AsyncSession, principal: Principal, code: str, payload: BulkRosterIn
) -> BulkRosterOut:
    course = await course_membership._course(db, code)
    await course_membership._may_manage(db, principal, course)
    if payload.create_missing and not principal.is_(Role.ADMIN):
        raise PermissionError_("Only an admin can create accounts from a list.")

    rows = parse(payload.text)
    if not rows:
        raise ValidationError("The list has no lines with an email.", {"field": "text"})
    if len(rows) > MAX_LINES:
        raise ValidationError(
            f"A list can have at most {MAX_LINES} students. Split it into smaller lists.",
            {"field": "text", "lines": len(rows)},
        )

    wanted = {email for _, email, _ in rows if _EMAIL.match(email)}
    users = {
        user.email: user for user in await db.scalars(select(User).where(User.email.in_(wanted)))
    }
    students = {
        student.user_id: student
        for student in await db.scalars(
            select(Student).where(Student.user_id.in_([u.user_id for u in users.values()]))
        )
    }
    on_course = set(await db.scalars(course_membership.students_on(course.id)))

    lines: list[BulkRosterLine] = []
    seen: set[str] = set()
    for number, email, name in rows:
        if not _EMAIL.match(email) or len(email) > 255:
            outcome = BulkRosterOutcome.INVALID
        elif email in seen:
            outcome = BulkRosterOutcome.DUPLICATE
        elif (user := users.get(email)) is None:
            outcome = (
                BulkRosterOutcome.CREATE if payload.create_missing else BulkRosterOutcome.NO_ACCOUNT
            )
        elif user.role != Role.STUDENT.value:
            outcome = BulkRosterOutcome.NOT_STUDENT
        elif not user.active:
            outcome = BulkRosterOutcome.INACTIVE
        elif (student := students.get(user.user_id)) is not None and (
            student.student_id in on_course
        ):
            outcome = BulkRosterOutcome.ALREADY
        else:
            outcome = BulkRosterOutcome.ADD
        seen.add(email)
        lines.append(
            BulkRosterLine(
                line=number,
                email=email[:255],
                name=name or (users[email].name if email in users else None),
                outcome=outcome,
            )
        )

    if payload.confirm:
        for line in lines:
            if line.outcome == BulkRosterOutcome.ADD:
                user = users[line.email]
                student = students.get(user.user_id)
                if student is None:
                    # A student account with no student record yet: this
                    # course becomes its home course.
                    db.add(
                        Student(
                            user_id=user.user_id,
                            course_id=course.id,
                            consent_status="pending",
                            enrolled_at=date.today(),
                        )
                    )
                else:
                    await db.execute(
                        insert(CourseEnrollment)
                        .values(student_id=student.student_id, course_id=course.id)
                        .on_conflict_do_nothing()
                    )
            elif line.outcome == BulkRosterOutcome.CREATE:
                # No website password: students sign in through Teams. An admin
                # can issue one later from the Accounts page.
                user = User(
                    name=line.name or _name_from(line.email),
                    role=Role.STUDENT.value,
                    email=line.email,
                )
                db.add(user)
                await db.flush()
                db.add(
                    Student(
                        user_id=user.user_id,
                        course_id=course.id,
                        consent_status="pending",
                        enrolled_at=date.today(),
                    )
                )
        await db.commit()

    counts: dict[str, int] = {}
    for line in lines:
        counts[line.outcome.value] = counts.get(line.outcome.value, 0) + 1
    return BulkRosterOut(
        applied=payload.confirm,
        lines=lines,
        counts=counts,
        roster=await course_membership.roster(db, principal, code) if payload.confirm else None,
    )
