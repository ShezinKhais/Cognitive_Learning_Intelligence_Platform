"""Per-resource ownership checks for the question-review routes.

require_roles (app.api.deps) answers "is this caller a lecturer at all".
That's necessary but not sufficient: the Phase 2 plan calls for protecting
review operations "by lecturer and session ownership", meaning a lecturer
must only be able to act on questions whose session they are the
instructor of. An admin bypasses this, matching how /admin routes already
work: admins operate across all lecturers' data by design.

This lives in app.services rather than app.api.deps because it needs a DB
lookup (whose session owns this question), unlike every existing guard in
deps.py, which only inspects the token/principal already in hand.
"""

from __future__ import annotations

import uuid

from app.api.deps import Principal
from app.core.errors import NotFoundError, PermissionError_
from app.models.question import Question
from app.repositories.question_repository import QuestionRepository
from app.schemas.identity import Role


async def get_owned_question(
    question_id: uuid.UUID,
    principal: Principal,
    repo: QuestionRepository,
    *,
    material_id: uuid.UUID | None = None,
) -> Question:
    """Fetch a question, or raise, after checking the caller may act on it.

    material_id, when given, is enforced as part of the lookup itself (see
    QuestionRepository.get_with_owner): a question that exists but belongs
    to a different material is treated the same as one that doesn't exist
    at all, so a lecturer cannot reach a question that isn't theirs by
    guessing at a different material_id in the URL for a question_id they
    already know.

    Raises NotFoundError if the question does not exist (or does not
    belong to material_id, when given) -- deliberately not PermissionError_
    in that case, so a caller probing random ids cannot distinguish "not
    yours" from "does not exist" for a resource that isn't theirs, which
    would otherwise leak which question ids are valid.

    Raises PermissionError_ if the question exists but its session belongs
    to a different lecturer. Admins skip this check entirely.
    """
    found = await repo.get_with_owner(question_id, material_id=material_id)
    if found is None:
        raise NotFoundError(
            "Question not found.",
            {"question_id": str(question_id)},
        )

    question, owner_id = found

    if principal.role != Role.ADMIN and owner_id != principal.user_id:
        raise PermissionError_(
            "You can only review questions from sessions you teach.",
            {"question_id": str(question_id)},
        )

    return question


async def filter_owned_questions(
    question_ids: list[uuid.UUID],
    principal: Principal,
    repo: QuestionRepository,
    *,
    material_id: uuid.UUID | None = None,
) -> tuple[list[Question], list[uuid.UUID]]:
    """Bulk version of get_owned_question.

    material_id, when given, is enforced the same way as in
    get_owned_question: an id in the request that belongs to a different
    material comes back in rejected, indistinguishable from an id that
    doesn't exist at all or belongs to a different lecturer.

    Returns (owned, rejected_ids). A bulk request naming a mix of the
    caller's own questions and someone else's does not fail the whole
    request: it processes what the caller legitimately owns and reports
    the rest back as skipped, since "approve all" is meant to be a single
    convenient action, not an all-or-nothing transaction that one stray id
    can block.
    """
    found = await repo.list_by_ids_with_owner(question_ids, material_id=material_id)
    found_by_id = {q.question_id: (q, owner_id) for q, owner_id in found}

    owned: list[Question] = []
    rejected: list[uuid.UUID] = []

    for qid in question_ids:
        entry = found_by_id.get(qid)
        if entry is None:
            rejected.append(qid)
            continue
        question, owner_id = entry
        if principal.role != Role.ADMIN and owner_id != principal.user_id:
            rejected.append(qid)
            continue
        owned.append(question)

    return owned, rejected
