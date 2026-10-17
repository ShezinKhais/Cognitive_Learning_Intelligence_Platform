"""Deletion test (Phase 8, BBIS).

    PYTHONPATH=. python scripts/db_deletion_test.py

Erases one student end to end on a throwaway database, with a real second
database for history, and checks what went and what stayed. Also checks the
approval rules and the failure-and-retry case. Never touches the live database.
Prints a Markdown section and exits 1 if a check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.history.database import create_history_tables
from app.history.models import StudentSemesterSummary
from app.models.attention_signal_summary import AttentionSignalSummary
from app.models.audit_log import AuditLog
from app.models.comprehension_result import ComprehensionResult
from app.models.engagement_record import EngagementRecord
from app.models.session_participant import SessionParticipant
from app.models.student import Student
from app.models.student_response import StudentResponse
from app.models.user import User
from app.services.deletion_requests import (
    SelfApproval,
    WrongState,
    approve,
    create_request,
    execute,
)
from app.services.retention_tasks import SessionDataPurge
from app.services.student_data import StudentNotFound, export_student_data
from scripts.db_evidence import prepare, scratch_url
from scripts.db_purge_simulation import recreate_database, seed

KEYS = ("answers", "labels", "engagement", "attention", "attendance")
PER_STUDENT = (
    ("answers", StudentResponse),
    ("engagement", EngagementRecord),
    ("attention", AttentionSignalSummary),
    ("attendance", SessionParticipant),
)


async def student_counts(db: AsyncSession, student_id: UUID | None = None) -> dict[str, int]:
    """Rows per kind, for one student or for everyone."""
    counts = {}
    for label, model in PER_STUDENT:
        query = select(func.count()).select_from(model)
        if student_id is not None:
            query = query.where(model.student_id == student_id)
        counts[label] = await db.scalar(query) or 0
    labels = select(func.count()).select_from(ComprehensionResult)
    if student_id is not None:
        labels = labels.join(
            StudentResponse, StudentResponse.response_id == ComprehensionResult.response_id
        ).where(StudentResponse.student_id == student_id)
    counts["labels"] = await db.scalar(labels) or 0
    return counts


async def history_rows(factory: async_sessionmaker[AsyncSession], student_id: UUID) -> int:
    async with factory() as db:
        return (
            await db.scalar(
                select(func.count())
                .select_from(StudentSemesterSummary)
                .where(StudentSemesterSummary.student_id == student_id)
            )
            or 0
        )


async def run(name: str) -> int:
    main_engine = create_async_engine(scratch_url(name))
    history_engine = create_async_engine(scratch_url(f"{name}_history"))
    await create_history_tables(history_engine)
    main = async_sessionmaker(main_engine, class_=AsyncSession, expire_on_commit=False)
    history = async_sessionmaker(history_engine, class_=AsyncSession, expire_on_commit=False)

    await seed(main, 1)
    purge = SessionDataPurge(lambda: main, history=lambda: history)
    cutoff = datetime.now(UTC) - timedelta(days=120)
    while await purge.purge(cutoff, 25) == 25:
        pass  # fills history with what a real purge would have kept

    async with main() as db:
        first = User(name="Admin One", role="admin", email="a1@sim.test")
        second_admin = User(name="Admin Two", role="admin", email="a2@sim.test")
        db.add_all([first, second_admin])
        await db.flush()
        admin_one, admin_two = first.user_id, second_admin.user_id
        await db.commit()
        rows = (
            await db.execute(
                select(Student.student_id, Student.user_id).order_by(Student.student_id).limit(2)
            )
        ).all()
    (target, target_user), (retry, _retry_user) = rows
    use_history: Any = lambda: history  # noqa: E731

    # -- before ------------------------------------------------------------------------
    async with main() as db:
        before = await student_counts(db, target)
        everyone_before = await student_counts(db)
        export = await export_student_data(db, target_user, history=use_history)
        await db.commit()
    history_before = await history_rows(history, target)
    export_matches = (
        len(export["answers"]) == before["answers"] and len(export["history"]) == history_before
    )

    # -- the approval rules ---------------------------------------------------------------
    async with main() as db:
        request = await create_request(
            db, target_type="student", target_id=target, requested_by=admin_one, reason="Test"
        )
        request_id = request.request_id
        await db.commit()
    async with main() as db:
        try:
            await approve(db, request_id, admin_id=admin_one)
            self_refused = False
        except SelfApproval:
            self_refused = True
        await db.rollback()
    async with main() as db:
        try:
            await execute(db, request_id, admin_id=admin_two, history=use_history)
            early_refused = False
        except WrongState:
            early_refused = True
        await db.rollback()
    still_there = await history_rows(history, target) == history_before

    # -- the erasure ------------------------------------------------------------------------
    async with main() as db:
        await approve(db, request_id, admin_id=admin_two)
        await db.commit()
    async with main() as db:
        done = await execute(db, request_id, admin_id=admin_two, history=use_history)
        outcome = dict(done.outcome or {})
        await db.commit()

    async with main() as db:
        gone = await db.scalar(
            select(func.count()).select_from(Student).where(Student.student_id == target)
        )
        after = await student_counts(db, target)
        everyone_after = await student_counts(db)
        loaded = await db.get(User, target_user)
        account = (
            None
            if loaded is None
            else SimpleNamespace(
                name=loaded.name,
                email=loaded.email,
                active=loaded.active,
                password_hash=loaded.password_hash,
            )
        )
        actions = (
            await db.scalars(
                select(AuditLog.action_type)
                .where(AuditLog.target_id == target)
                .order_by(AuditLog.timestamp)
            )
        ).all()
        try:
            await export_student_data(db, target_user, history=use_history)
            export_refused = False
        except StudentNotFound:
            export_refused = True
        await db.rollback()
    async with main() as db:
        try:
            await execute(db, request_id, admin_id=admin_two, history=use_history)
            twice_refused = False
        except WrongState:
            twice_refused = True
        await db.rollback()
    history_after = await history_rows(history, target)

    # -- failure, then retry --------------------------------------------------------------------
    def broken() -> None:
        raise RuntimeError("the history database is down")

    async with main() as db:
        again = await create_request(
            db, target_type="student", target_id=retry, requested_by=admin_one
        )
        again_id = again.request_id
        await db.commit()
    async with main() as db:
        await approve(db, again_id, admin_id=admin_two)
        await db.commit()
    retry_history_before = await history_rows(history, retry)
    async with main() as db:
        try:
            await execute(db, again_id, admin_id=admin_two, history=lambda: broken)
            failed_closed = False
        except RuntimeError:
            failed_closed = True
        await db.rollback()
    async with main() as db:
        survived = await db.scalar(
            select(func.count()).select_from(Student).where(Student.student_id == retry)
        )
    history_untouched = await history_rows(history, retry) == retry_history_before
    async with main() as db:
        finished = await execute(db, again_id, admin_id=admin_two, history=use_history)
        status = finished.status
        await db.commit()
    async with main() as db:
        retry_gone = not await db.scalar(
            select(func.count()).select_from(Student).where(Student.student_id == retry)
        )
    retry_history_after = await history_rows(history, retry)

    checks = [
        (
            "The student's export matched their stored data",
            export_matches,
            f"{before['answers']} answers, {history_before} history rows",
        ),
        ("The requester cannot approve their own request", self_refused, ""),
        (
            "Nothing runs before approval, and nothing was deleted by trying",
            early_refused and still_there,
            "",
        ),
        (
            "The student is gone from the main database",
            gone == 0 and all(after[key] == 0 for key in KEYS),
            f"removed {before}",
        ),
        (
            "The outcome counts what was removed",
            outcome.get("answers") == before["answers"]
            and outcome.get("engagement") == before["engagement"],
            str(outcome),
        ),
        (
            "Their history rows are gone",
            history_before > 0
            and history_after == 0
            and outcome.get("history_rows") == history_before,
            f"{history_before} -> {history_after}",
        ),
        (
            "Nobody else's data changed",
            all(everyone_after[key] == everyone_before[key] - before[key] for key in KEYS),
            "every other student's rows are intact",
        ),
        (
            "The account is anonymised, not deleted",
            account is not None
            and account.name == "Deleted student"
            and account.email.startswith("deleted-")
            and account.active is False
            and account.password_hash is None,
            f"{account.name if account else None}",
        ),
        (
            "The request and its audit trail remain",
            [a for a in actions if a.startswith("DELETION")]
            == ["DELETION_REQUESTED", "DELETION_APPROVED", "DELETION_EXECUTED"]
            and "STUDENT_DATA_EXPORTED" in actions,
            ", ".join(actions),
        ),
        ("The student's export now says not found", export_refused, ""),
        ("Executing the same request again is refused", twice_refused, ""),
        (
            "With history down, execution stops before touching anything",
            failed_closed and bool(survived) and history_untouched,
            "student and history rows intact",
        ),
        (
            "The retry finishes the job",
            status == "executed" and retry_gone and retry_history_after == 0,
            f"history {retry_history_before} -> {retry_history_after}",
        ),
    ]

    print("## Deletion test\n")
    print(
        "One student was erased end to end on a throwaway database with a separate "
        "history database, using the same services the admin routes call.\n"
    )
    print("| Check | Result | Detail |")
    print("|---|---|---|")
    for check, passed, detail in checks:
        print(f"| {check} | {'PASS' if passed else 'FAIL'} | {detail} |")
    await main_engine.dispose()
    await history_engine.dispose()
    return 0 if all(passed for _, passed, _ in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default="clip_evidence", help="scratch database name")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        prepare(args.database)
        recreate_database(f"{args.database}_history")
    return asyncio.run(run(args.database))


if __name__ == "__main__":
    raise SystemExit(main())
