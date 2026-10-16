"""Question grounding for the AI evaluation report (Phase 8, AI 1, #73).

Not a test. Needs Ollama running with the chat model from .env. Asks the
generator for questions about a sample lecture several times, runs every draft
through the same grounding checks the upload pipeline uses, and reports how
many were accepted and why the rest were rejected. Run from backend/:

    python -m scripts.evaluate_grounding
    python -m scripts.evaluate_grounding --rounds 10 --type free_text
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding --verify
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding --check-accepted

It writes the summary to tests/eval/GROUNDING_RESULTS.md and the accepted
questions to tests/eval/grounding_accepted.csv. Open that file and fill the
grounded_luna column with yes or no: does the cited slide really support the
question and its answer? Then run with --precision to get the share judged
grounded.

--verify also runs the option verifier (generation.verify_draft) on every
draft that passes the other checks, as uploads do. --check-accepted runs only
the verifier, on the questions already in the accepted file, and compares its
verdict with the grounded_luna marks: how many of the questions judged wrong
it catches, and how many judged right it wrongly drops.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.schemas.content import Difficulty, QuestionType
from app.services.extraction import process_material
from app.services.generation import (
    ask_verifier,
    build_prompt,
    parse_drafts,
    rejection_reasons,
    screened,
    verification_reason,
    verify_draft,
)
from app.services.grounding_evaluation import (
    GroundingTally,
    grounding_precision,
    summary_markdown,
    write_accepted,
)
from app.services.material_seams import DraftQuestion

BACKEND = Path(__file__).resolve().parent.parent
SAMPLES = BACKEND / "tests" / "samples"
EVAL_DIR = BACKEND / "tests" / "eval"


async def main(args: argparse.Namespace) -> None:
    if args.precision:
        supported, judged = grounding_precision(args.accepted)
        if not judged:
            raise SystemExit(f"No yes/no marks in {args.accepted} yet.")
        print(f"grounding precision {supported / judged:.0%} ({supported} of {judged} judged)")
        return

    settings = get_settings()
    client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    question_type = QuestionType(args.type)
    result = process_material(str(SAMPLES / args.material), uuid.uuid4())
    chunks = result.chunks
    if args.check_accepted:
        await check_accepted(client, settings.ollama_model, chunks, args.accepted)
        return
    shown = screened(chunks)
    print(f"model {settings.ollama_model}, {len(chunks)} chunks, {args.rounds} rounds\n")

    tally = GroundingTally()
    for round_number in range(1, args.rounds + 1):
        response = await client.chat.completions.create(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": build_prompt(shown, args.count, question_type)}],
        )
        try:
            drafts = parse_drafts(response.choices[0].message.content or "", question_type)
        except ValueError:
            tally.add_reply(None)
            print(f"round {round_number}: reply could not be read")
            continue
        outcomes = [(draft, rejection_reasons(draft, chunks)) for draft in drafts]
        if args.verify:
            for n, (draft, reasons) in enumerate(outcomes):
                if not reasons and draft.type == QuestionType.MCQ:
                    reason = await verify_draft(client, settings.ollama_model, draft, chunks)
                    outcomes[n] = (draft, [reason] if reason else [])
        tally.add_reply(outcomes)
        kept = sum(not reasons for _, reasons in outcomes)
        print(f"round {round_number}: {kept} of {len(outcomes)} drafts accepted")

    summary = summary_markdown(tally, settings.ollama_model, args.material)
    print("\n" + summary)
    args.out.write_text(summary)
    write_accepted(args.accepted, tally.accepted)
    print(f"written to {args.out} and {args.accepted}")


def accepted_drafts(path: Path) -> list[tuple[str, str, DraftQuestion]]:
    """(id, grounded_luna mark, draft) for each multiple choice row."""
    import csv

    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            options = tuple(o.strip() for o in row["options"].split(" | "))
            if row["type"] != QuestionType.MCQ.value or row["correct_answer"] not in options:
                continue
            draft = DraftQuestion(
                QuestionType.MCQ,
                Difficulty.MEDIUM,
                row["question"],
                options,
                options.index(row["correct_answer"]),
                source_slide=int(row["source_slide"]),
                source_excerpt=row["source_excerpt"],
            )
            rows.append((row["id"], row["grounded_luna"].strip().lower(), draft))
    return rows


async def check_accepted(client, model: str, chunks, path: Path) -> None:
    """The verifier's verdict on questions a person has already judged."""
    caught = missed = kept = dropped = unreadable = 0
    for question_id, mark, draft in accepted_drafts(path):
        raw, supported = await ask_verifier(client, model, draft, chunks)
        if supported is None:
            unreadable += 1
            reason = None
            verdict = f"reply could not be read, so it keeps it: {raw.strip()[:200]!r}"
        else:
            reason = verification_reason(draft, supported)
            letters = ", ".join("ABCD"[i] for i in sorted(supported)) or "none"
            marked = "ABCD"[draft.correct_option]
            verdict = f"slide supports {letters}, marked {marked}: {reason or 'keeps it'}"
        print(f"{question_id} (judged {mark or '-'}): {verdict}")
        if mark == "no":
            caught += reason is not None
            missed += reason is None
        elif mark == "yes":
            dropped += reason is not None
            kept += reason is None
    print(
        f"\nquestions judged wrong: verifier rejected {caught} of {caught + missed}"
        f"\nquestions judged right: verifier kept {kept} of {kept + dropped}"
        f"\nreplies that could not be read: {unreadable}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--material", default="lecture.pptx", help="a file in tests/samples")
    parser.add_argument("--rounds", type=int, default=5, help="replies to ask for")
    parser.add_argument("--count", type=int, default=5, help="questions asked for per reply")
    parser.add_argument("--type", default="mcq", choices=[t.value for t in QuestionType])
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "GROUNDING_RESULTS.md")
    parser.add_argument("--accepted", type=Path, default=EVAL_DIR / "grounding_accepted.csv")
    parser.add_argument(
        "--precision", action="store_true", help="score a filled-in accepted-questions file"
    )
    parser.add_argument(
        "--verify", action="store_true", help="also run the option verifier, as uploads do"
    )
    parser.add_argument(
        "--check-accepted",
        action="store_true",
        help="run only the verifier on the judged questions in the accepted file",
    )
    asyncio.run(main(parser.parse_args()))
