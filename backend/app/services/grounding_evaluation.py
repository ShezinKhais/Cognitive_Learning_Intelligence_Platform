"""How often generated questions survive the grounding checks, and why not.

Owner: AI 1, Phase 8 (#73). The generator's drafts are counted by outcome:
replies that could not be read, drafts accepted, and drafts rejected, with
each rejection's reasons grouped into a few kinds. The accepted questions are
written out for a person to judge whether the cited slide really supports
each one, which is the grounding precision the checks are meant to protect.
Plain functions, so they need no model; scripts/evaluate_grounding.py runs
the generator against them.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.services.material_seams import DraftQuestion

# A rejection reason's kind, matched on the words rejection_reasons writes.
# Checked in order, most specific first; the first that matches names it.
REASON_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("verifier: not exactly one right option", ("verifier:",)),
    ("safety: instructions or links", ("instructions", "links to")),
    ("citation: missing or wrong page", ("citation", "cites page")),
    # The MCQ answer, or a free-text reference answer or key point.
    ("answer not supported by the excerpt", ("has little overlap with the cited excerpt",)),
    ("question off the cited page", ("question has little overlap",)),
    ("excerpt not found on the page", ("excerpt not grounded", "no source excerpt")),
    (
        "format: options or answer",
        (
            "options",
            "correct_option",
            "prompt is empty",
            "key point",
            "reference answer",
            "multiple choice fields",
        ),
    ),
)
OTHER = "other"


def reason_kind(reason: str) -> str:
    text = reason.lower()
    for kind, words in REASON_KINDS:
        if any(word in text for word in words):
            return kind
    return OTHER


@dataclass
class GroundingTally:
    replies: int = 0
    unreadable: int = 0
    accepted: list[DraftQuestion] = field(default_factory=list)
    rejected: int = 0
    # How many rejected drafts had at least one reason of each kind.
    kinds: Counter = field(default_factory=Counter)

    @property
    def drafts(self) -> int:
        return len(self.accepted) + self.rejected

    @property
    def acceptance_rate(self) -> float | None:
        return len(self.accepted) / self.drafts if self.drafts else None

    def add_reply(self, outcomes: Sequence[tuple[DraftQuestion, list[str]]] | None) -> None:
        """One model reply: None when it could not be read, else each draft
        with its rejection reasons (empty when it passed)."""
        self.replies += 1
        if outcomes is None:
            self.unreadable += 1
            return
        for draft, reasons in outcomes:
            if not reasons:
                self.accepted.append(draft)
                continue
            self.rejected += 1
            for kind in {reason_kind(r) for r in reasons}:
                self.kinds[kind] += 1


def summary_markdown(tally: GroundingTally, model: str, material: str) -> str:
    rate = tally.acceptance_rate
    lines = [
        "# Question grounding",
        "",
        f"Model `{model}` on `{material}`, {tally.replies} replies asked for.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Replies that could not be read | {tally.unreadable} of {tally.replies} |",
        f"| Drafts | {tally.drafts} |",
        f"| Accepted | {len(tally.accepted)} |",
        f"| Rejected | {tally.rejected} |",
        f"| Acceptance rate | {'-' if rate is None else f'{rate:.0%}'} |",
        "",
        "Rejected drafts by kind of reason (a draft can have more than one):",
        "",
        "| Reason | Drafts |",
        "|---|---|",
    ]
    for kind, count in tally.kinds.most_common():
        lines.append(f"| {kind} | {count} |")
    return "\n".join(lines) + "\n"


ACCEPTED_FIELDS = (
    "id",
    "type",
    "question",
    "options",
    "correct_answer",
    "source_slide",
    "source_excerpt",
    "grounded_luna",
    "notes",
)


def write_accepted(path: Path, accepted: Sequence[DraftQuestion]) -> None:
    """The accepted questions with an empty column for a person to judge:
    yes when the cited slide supports the question and its answer, no when
    it does not."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACCEPTED_FIELDS, lineterminator="\n")
        writer.writeheader()
        for n, draft in enumerate(accepted, start=1):
            options = draft.options or ()
            correct = draft.correct_option
            writer.writerow(
                {
                    "id": f"g{n:02d}",
                    "type": draft.type.value,
                    "question": draft.prompt,
                    "options": " | ".join(options),
                    "correct_answer": options[correct]
                    if correct is not None and 0 <= correct < len(options)
                    else (draft.reference_answer or ""),
                    "source_slide": draft.source_slide,
                    "source_excerpt": draft.source_excerpt or "",
                    "grounded_luna": "",
                    "notes": "",
                }
            )


def grounding_precision(path: Path, column: str = "grounded_luna") -> tuple[int, int]:
    """(judged supported, judged) from a filled-in accepted-questions file."""
    with path.open(newline="", encoding="utf-8") as f:
        marks = [row[column].strip().lower() for row in csv.DictReader(f)]
    judged = [m for m in marks if m in {"yes", "no"}]
    return sum(m == "yes" for m in judged), len(judged)
