"""Question grounding for the AI evaluation report (Phase 8, AI 1, #73).

Not a test. Needs Ollama running with the chat model from .env. Asks the
generator for questions about a sample lecture several times, runs every draft
through the same grounding checks the upload pipeline uses, and reports how
many were accepted and why the rest were rejected. Run from backend/:

    python -m scripts.evaluate_grounding
    python -m scripts.evaluate_grounding --rounds 10 --type free_text
    OLLAMA_MODEL=qwen2.5:3b python -m scripts.evaluate_grounding

It writes the summary to tests/eval/GROUNDING_RESULTS.md and the accepted
questions to tests/eval/grounding_accepted.csv. Open that file and fill the
grounded_luna column with yes or no: does the cited slide really support the
question and its answer? Then run with --precision to get the share judged
grounded.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.schemas.content import QuestionType
from app.services.extraction import process_material
from app.services.generation import build_prompt, parse_drafts, rejection_reasons, screened
from app.services.grounding_evaluation import (
    GroundingTally,
    grounding_precision,
    summary_markdown,
    write_accepted,
)

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
        tally.add_reply(outcomes)
        kept = sum(not reasons for _, reasons in outcomes)
        print(f"round {round_number}: {kept} of {len(outcomes)} drafts accepted")

    summary = summary_markdown(tally, settings.ollama_model, args.material)
    print("\n" + summary)
    args.out.write_text(summary)
    write_accepted(args.accepted, tally.accepted)
    print(f"written to {args.out} and {args.accepted}")


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
    asyncio.run(main(parser.parse_args()))
