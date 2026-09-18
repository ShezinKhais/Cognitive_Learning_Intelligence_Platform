    async def apply_review(
        self,
        question: Question,
        *,
        status: str,
        reviewer_id: uuid.UUID,
        prompt: str | None = None,
        options: list[str] | None = None,
        correct_option: int | None = None,
        difficulty: str | None = None,
    ) -> Question:
        """Mutate a question in place per a review decision and flush.

        Only overwrites fields the caller actually supplied (edit is
        optional on approve/reject -- a lecturer can approve without
        changing anything). status, reviewed_by and reviewed_at always
        update, since every call through here is itself a review action.

        Raises ConflictError if the requested status is not a valid move
        from the question's current status (see _ALLOWED_TRANSITIONS), or
        if any edit fields are supplied for a question that is already
        staged or delivered -- once a question has been staged for
        delivery, silently changing its prompt or correct_option would
        change what past or in-flight student responses meant without
        anyone knowing.

        Raises ValidationError if the question's final shape -- prompt and,
        for an MCQ, its options and correct_option -- isn't usable, but
        only when status is "approved" (see _validate_option_shape and
        _validate_prompt): an out-of-range or duplicate/blank answer key,
        fewer than two options, or a blank prompt, would otherwise let a
        lecturer approve a question that is structurally broken even
        though correct_option happened to be a technically valid index.
        A reject is never blocked by this -- a broken draft has to be
        rejectable without being fixed first.
        """
        current = question.status
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ConflictError(
                f"Cannot move a question from '{current}' to '{status}'.",
                {"current_status": current, "requested_status": status},
            )

        editing = prompt is not None or options is not None or correct_option is not None
        if editing and current in {"staged", "delivered"}:
            raise ConflictError(
                f"Cannot edit a question that is already '{current}'.",
                {"current_status": current},
            )

        # Structural validation (prompt, option shape) only applies when the
        # result would be approved -- a broken draft must still be
        # rejectable without editing it first, since reject is exactly the
        # action a lecturer takes on a bad question. Applying these checks
        # on every transition made rejecting a one-option or blank-prompt
        # draft impossible without fixing it, which is backwards.
        if status == "approved":
            _validate_option_shape(
                question.options, options, question.correct_option, correct_option
            )
            effective_prompt = prompt if prompt is not None else question.question_text
            _validate_prompt(effective_prompt)

        question.status = status
        question.reviewed_by = reviewer_id
        question.reviewed_at = datetime.now(UTC)
        if prompt is not None:
            question.question_text = prompt
        if options is not None:
            question.options = options
        if correct_option is not None:
            question.correct_option = correct_option
        if difficulty is not None:
            question.difficulty = difficulty

        self.session.add(question)
        await self.session.flush()
        await self.session.refresh(question)
        return question
