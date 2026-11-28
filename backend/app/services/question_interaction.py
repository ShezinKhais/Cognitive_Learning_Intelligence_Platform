"""Keep solution keys server-side and render structured responses for reports."""

from random import SystemRandom

from app.core.errors import ValidationError
from app.schemas.question_interaction import (
    InteractionInput,
    PublicInteraction,
    QuestionInteraction,
)

KINDS = frozenset({"matching", "ordering"})


def build_interaction(kind: str, payload: InteractionInput | None) -> QuestionInteraction:
    if (
        payload is None
        or (kind == "matching" and len(payload.labels) != len(payload.choices))
        or (kind == "ordering" and payload.labels)
    ):
        raise ValidationError("Provide a complete set of matching pairs or ordered items.")
    if kind == "matching" and any("|" in item for item in payload.labels + payload.choices):
        raise ValidationError("Matching terms and meanings cannot contain the pair separator |.")
    permutation = list(range(len(payload.choices)))
    # Keep all permutations possible. For two items, ruling out the authored
    # order would make swapping the choices a guaranteed correct answer.
    SystemRandom().shuffle(permutation)
    return QuestionInteraction(
        kind=kind,
        labels=payload.labels,
        choices=[payload.choices[index] for index in permutation],
        correct_order=[permutation.index(index) for index in range(len(permutation))],
    )


def describe_answer(interaction: PublicInteraction, order: list[int]) -> str:
    if sorted(order) != list(range(len(interaction.choices))):
        raise ValidationError("Use every choice exactly once.")
    choices = [interaction.choices[index] for index in order]
    if interaction.kind == "matching":
        return "\n".join(
            f"{label} → {choice}" for label, choice in zip(interaction.labels, choices, strict=True)
        )
    return "\n".join(f"{index}. {choice}" for index, choice in enumerate(choices, 1))
