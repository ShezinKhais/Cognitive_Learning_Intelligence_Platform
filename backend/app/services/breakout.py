"""The lecturer's breakout room plan for a running class.

Owner: General CS, Phase 6. See app.schemas.breakout for why C.L.I.P keeps
its own plan rather than reading Teams.

Rules: only students on the session's course can be placed; a student is in
at most one room; labels are matched as rooms.py matches them, so "Room 1"
and "room 1" are one room; and a session has at most max_rooms_per_session.
The plan lives with the running class, in memory, like the rest of it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, ValidationError
from app.models.session import Session
from app.models.student import Student
from app.models.user import User
from app.realtime.classroom import classroom
from app.realtime.hub import hub
from app.realtime.rooms import room_key, shown_label
from app.schemas.breakout import PlannedRoom, RoomMember, RoomPlanIn, RoomPlanOut
from app.services.course_membership import students_on


async def roster(db: AsyncSession, row: Session) -> dict[UUID, str]:
    """The active students on the session's course, by user id."""
    rows = await db.execute(
        select(User.user_id, User.name)
        .join(Student, Student.user_id == User.user_id)
        .where(
            Student.student_id.in_(students_on(row.course_id)),
            User.role == "student",
            User.active.is_(True),
        )
        .order_by(User.name)
    )
    return {user_id: name for user_id, name in rows.all()}


def validate_plan(
    payload: RoomPlanIn, students: dict[UUID, str], max_rooms: int
) -> dict[UUID, str]:
    """The plan as user id to room label, or why it cannot be used."""
    if not payload.rooms:
        raise ValidationError("Add at least one room.")
    if len(payload.rooms) > max_rooms:
        raise ValidationError(f"A class can have at most {max_rooms} rooms.")
    seen_labels: set[str] = set()
    plan: dict[UUID, str] = {}
    for room in payload.rooms:
        label = shown_label(room.label)
        key = room_key(label)
        if not key:
            raise ValidationError("Every room needs a name.")
        if key in seen_labels:
            raise ValidationError(f"Two rooms are called {label}.")
        seen_labels.add(key)
        for user_id in room.user_ids:
            if user_id not in students:
                raise ValidationError("A student in the plan is not on this course.")
            if user_id in plan:
                raise ValidationError(f"{students[user_id]} is in more than one room.")
            plan[user_id] = label
    return plan


def describe(row: Session, students: dict[UUID, str]) -> RoomPlanOut:
    plan = classroom.room_plan(row.session_id)
    connected = hub.student_ids(row.session_id)

    def member(user_id: UUID) -> RoomMember:
        return RoomMember(user_id=user_id, name=students[user_id], connected=user_id in connected)

    rooms: dict[str, list[RoomMember]] = {}
    for user_id, label in (plan or {}).items():
        if user_id in students:
            rooms.setdefault(label, []).append(member(user_id))
    placed = set(plan or {})
    return RoomPlanOut(
        running=plan is not None,
        rooms=[
            PlannedRoom(label=label, students=sorted(members, key=lambda m: m.name))
            for label, members in sorted(rooms.items(), key=lambda item: room_key(item[0]))
        ],
        unassigned=[member(user_id) for user_id in students if user_id not in placed],
    )


async def assign(
    db: AsyncSession, row: Session, payload: RoomPlanIn, settings: Settings
) -> RoomPlanOut:
    students = await roster(db, row)
    plan = validate_plan(payload, students, settings.max_rooms_per_session)
    if not await classroom.assign_rooms(row.session_id, plan):
        raise ConflictError("Start the class before splitting it into rooms.")
    return describe(row, students)


async def close(db: AsyncSession, row: Session) -> RoomPlanOut:
    if not await classroom.close_rooms(row.session_id):
        raise ConflictError("The class is not running.")
    return describe(row, await roster(db, row))
