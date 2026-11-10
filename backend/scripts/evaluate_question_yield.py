"""Question yield with lecturer evaluation (AI 1, #235).

Not a test. Three steps, run from backend/. The first needs Ollama running
with the models in .env; the other two need nothing.

1. Write questions for real course material, exactly as an upload does (same
   model, prompt, settings and checks), and keep every draft:

    python -m scripts.evaluate_question_yield run ~/course/week3.pptx ~/course/week4.pdf \
        --tags ~/course/tags.json --dir tests/eval/yield/run1

   It refuses to start until tests/eval/yield/thresholds.json says who agreed
   the thresholds and when. --rehearsal runs anyway, and the report says so.

2. Each judge marks every question that passed the checks, on their own:

    python -m scripts.evaluate_question_yield judge --name farhad --dir tests/eval/yield/run1

   One question at a time, timed. It can be stopped and picked up again.
   A judge who prefers a spreadsheet copies sheet.csv to judged_<name>.csv
   and fills in verdict, problem, seconds and notes.

3. Write the report from the judges' files:

    python -m scripts.evaluate_question_yield report --dir tests/eval/yield/run1

tests/eval/yield/README.md explains the judging rules and the tags file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.core.config import get_settings
from app.services import generation
from app.services.ai_gateway import AiUnavailableError, Priority, get_ai_gateway
from app.services.extraction import extract_material, finish_material
from app.services.generation import GenerationOutcome, QuestionGenerator
from app.services.grounding_evaluation import reason_kind
from app.services.image_captioning import ImageCaptioner, add_captions
from app.services.processing_security import validate_extraction
from app.services.question_yield import (
    EDIT,
    JUDGEMENT_FIELDS,
    PROBLEMS,
    REJECT,
    REJECTED_FIELDS,
    SHEET_FIELDS,
    USABLE,
    file_hash,
    judgement,
    missing_thresholds,
    question_row,
    read_rows,
    rejected_row,
    study_report,
    text_hash,
    thresholds_agreed,
    write_rows,
)
from app.services.uploads import (
    MATERIAL_MODEL_ATTEMPTS,
    MATERIAL_MODEL_TIMEOUT_SECONDS,
    MATERIAL_QUEUE_TIMEOUT_SECONDS,
    _ocr_reader,
    _vector_converter,
)

BACKEND = Path(__file__).resolve().parent.parent
YIELD_DIR = BACKEND / "tests" / "eval" / "yield"
RUN, SHEET, REJECTED, REPORT = "run.json", "sheet.csv", "rejected.csv", "QUESTION_YIELD.md"


# How much of a reply that could not be read is kept in run.json, and how
# many such replies, enough to see what the model wrote instead.
KEPT_REPLY_CHARACTERS = 1500
KEPT_REPLIES = 3


class _ReplyRecorder:
    """A chat client that remembers the text of every reply it passes on."""

    def __init__(self, client) -> None:
        self.replies: list[str] = []
        recorder = self

        async def create(**kwargs):
            response = await client.chat.completions.create(**kwargs)
            recorder.replies.append(response.choices[0].message.content or "")
            return response

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


class RecordingGenerator(QuestionGenerator):
    """The upload's generator, remembering what each model call produced, so
    the drafts it throws away can be counted and kept, and a reply that could
    not be read at all is kept to show why."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._client = _ReplyRecorder(self._client)
        self.outcomes: list[GenerationOutcome] = []
        self.unreadable: list[str] = []

    async def _draft(self, *args, **kwargs) -> GenerationOutcome:
        # The first reply in a call is the questions; any after it are the
        # option verifier's, one per draft that passed the other checks.
        first = len(self._client.replies)
        outcome = await super()._draft(*args, **kwargs)
        self.outcomes.append(outcome)
        if not outcome.accepted and not outcome.rejected:
            replies = self._client.replies[first:]
            self.unreadable.append(replies[0] if replies else "")
        return outcome


async def collect(
    generator: RecordingGenerator,
    chunks: Sequence,
    material: str,
    prefix: str,
    tags: Mapping[str, Sequence[int]],
) -> tuple[list[dict], list[dict], dict]:
    """One material's questions: the rows that passed, the rows that did not,
    and the counts for run.json."""
    generator.outcomes = []
    generator.unreadable = []
    kept = await generator.generate(uuid.uuid4(), chunks)
    outcomes = generator.outcomes
    passed = [
        question_row(f"{prefix}-q{n:02d}", material, draft, tags)
        for n, draft in enumerate(kept, start=1)
    ]
    thrown = [pair for outcome in outcomes for pair in outcome.rejected]
    rejected = [
        rejected_row(question_row(f"{prefix}-x{n:02d}", material, draft, tags), reasons)
        for n, (draft, reasons) in enumerate(thrown, start=1)
    ]
    passed_before_duplicates = sum(len(outcome.accepted) for outcome in outcomes)
    kinds = Counter(kind for _, reasons in thrown for kind in {reason_kind(r) for r in reasons})
    counts = {
        "calls": len(outcomes),
        "empty_calls": sum(not o.accepted and not o.rejected for o in outcomes),
        "drafts": passed_before_duplicates + len(thrown),
        "passed": len(kept),
        "duplicates": passed_before_duplicates - len(kept),
        "rejected_kinds": dict(kinds.most_common()),
        "unreadable_replies": [
            reply[:KEPT_REPLY_CHARACTERS] for reply in generator.unreadable[:KEPT_REPLIES]
        ],
    }
    return passed, rejected, counts


def commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=BACKEND, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return git("rev-parse", "--short", "HEAD") + (
            " with uncommitted changes" if git("status", "--porcelain", "-uno") else ""
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_thresholds(path: Path, rehearsal: bool) -> dict:
    thresholds = json.loads(path.read_text())
    missing = missing_thresholds(thresholds)
    if missing:
        raise SystemExit(f"{path} needs a number for: {', '.join(missing)}")
    if not thresholds_agreed(thresholds) and not rehearsal:
        raise SystemExit(
            f"The thresholds in {path} have not been agreed: fill in agreed_by and "
            "agreed_on once the team has, so the pass marks are fixed before the "
            "results are seen. To try the tool first, add --rehearsal."
        )
    return thresholds


def load_tags(path: Path | None, names: Sequence[str]) -> dict[str, dict[str, list[int]]]:
    if path is None:
        return {}
    tags = json.loads(path.read_text())
    # One tags file can cover more lectures than a run uses. A lecture run
    # without tags is the likelier mistake (a renamed download), so say so.
    untagged = sorted(set(names) - set(tags))
    if untagged:
        print(f"No tags in {path} for: {', '.join(untagged)}. Their pages count as text only.")
    return {name: tags[name] for name in names if name in tags}


async def run(args: argparse.Namespace) -> None:
    names = [path.name for path in args.materials]
    if len(set(names)) < len(names):
        raise SystemExit("Two materials share a file name: rename one.")
    for path in args.materials:
        if not path.is_file():
            raise SystemExit(f"No such file: {path}")
    if (args.dir / SHEET).exists():
        raise SystemExit(f"{args.dir} already holds a run. Use a new --dir for a new one.")
    thresholds = load_thresholds(args.thresholds, args.rehearsal)
    tags = load_tags(args.tags, names)

    settings = get_settings()
    gateway = get_ai_gateway()
    # The same wiring as an upload (uploads.build_pipeline), so the numbers
    # describe what a lecturer would get.
    generator = RecordingGenerator(
        gateway.chat_client(
            "question_generation",
            priority=Priority.BACKGROUND,
            timeout=MATERIAL_MODEL_TIMEOUT_SECONDS,
            max_attempts=MATERIAL_MODEL_ATTEMPTS,
            queue_timeout=MATERIAL_QUEUE_TIMEOUT_SECONDS,
        ),
        settings.ollama_model,
        count=settings.questions_per_material,
        free_text=settings.free_text_questions_enabled,
        verify=settings.question_verification_enabled,
    )
    captioner = (
        ImageCaptioner(
            gateway,
            settings.image_caption_model,
            timeout=settings.image_caption_timeout_seconds,
            queue_timeout=MATERIAL_QUEUE_TIMEOUT_SECONDS,
            max_images=settings.image_caption_max_images,
            converter=_vector_converter(settings.libreoffice_path),
        )
        if settings.image_captioning_enabled
        else None
    )
    reader = _ocr_reader(settings)

    sheet: list[dict] = []
    rejected: list[dict] = []
    materials: list[dict] = []
    try:
        for number, path in enumerate(args.materials, start=1):
            material_id = uuid.uuid4()
            extraction = extract_material(
                str(path),
                settings.max_upload_bytes,
                with_images=captioner is not None,
                ocr=reader.read if reader is not None else None,
            )
            validate_extraction(extraction.elements, settings)
            if captioner is not None and any(e.image for e in extraction.elements):
                elements, _ = await add_captions(extraction.elements, captioner, material_id)
                extraction = replace(extraction, elements=elements)
            result = finish_material(extraction, material_id)
            page_tags = tags.get(path.name, {})
            passed, thrown, counts = await collect(
                generator, result.chunks, path.name, f"m{number}", page_tags
            )
            sheet += passed
            rejected += thrown
            materials.append(
                {
                    "name": path.name,
                    "sha256": file_hash(path),
                    "pages": result.page_count,
                    "chunks": len(result.chunks),
                    "parser": result.parser_used,
                    "asked": settings.questions_per_material,
                    "tags": page_tags,
                    **counts,
                }
            )
            print(f"{path.name}: {counts['drafts']} drafts, {counts['passed']} passed the checks")
            if counts["calls"] and counts["empty_calls"] == counts["calls"]:
                print(
                    f"  None of the model's {counts['calls']} replies could be read as questions. "
                    f"The first is saved in run.json under unreadable_replies."
                )
    except AiUnavailableError:
        raise SystemExit(
            f"The model server at {settings.ollama_base_url} did not answer. Is Ollama "
            f"running, with {settings.ollama_model} pulled? Nothing was written."
        ) from None
    finally:
        await gateway.shutdown()

    record = {
        "started": date.today().isoformat(),
        "commit": commit(),
        "model": settings.ollama_model,
        "settings": {
            "questions_per_material": settings.questions_per_material,
            "question_verification_enabled": settings.question_verification_enabled,
            "free_text_questions_enabled": settings.free_text_questions_enabled,
            "image_captioning_enabled": settings.image_captioning_enabled,
            "image_caption_model": settings.image_caption_model,
            "ocr_enabled": settings.ocr_enabled,
            "DRAFTS_PER_CALL": generation.DRAFTS_PER_CALL,
            "MAX_PROMPT_CHUNKS": generation.MAX_PROMPT_CHUNKS,
            "GROUNDING_THRESHOLD": generation.GROUNDING_THRESHOLD,
            "ANSWER_SUPPORT_THRESHOLD": generation.ANSWER_SUPPORT_THRESHOLD,
            "QUESTION_SUPPORT_THRESHOLD": generation.QUESTION_SUPPORT_THRESHOLD,
            "FREE_TEXT_SUPPORT_THRESHOLD": generation.FREE_TEXT_SUPPORT_THRESHOLD,
        },
        "prompts": {
            "multiple choice (hash)": text_hash(generation.PROMPT_TEMPLATE),
            "short answer (hash)": text_hash(generation.FREE_TEXT_PROMPT_TEMPLATE),
            "verifier": f"{generation.VERIFY_PROMPT_VERSION} "
            f"({text_hash(generation.VERIFY_PROMPT)})",
        },
        "thresholds": thresholds,
        "materials": materials,
    }
    args.dir.mkdir(parents=True, exist_ok=True)
    (args.dir / RUN).write_text(json.dumps(record, indent=2) + "\n")
    write_rows(args.dir / SHEET, SHEET_FIELDS, sheet)
    write_rows(args.dir / REJECTED, REJECTED_FIELDS, rejected)
    print(
        f"\n{len(sheet)} question(s) to judge in {args.dir / SHEET}; "
        f"{len(rejected)} rejected draft(s) kept in {args.dir / REJECTED}."
    )


# ---- judging -------------------------------------------------------------------


def judged_path(folder: Path, name: str) -> Path:
    if not name.isalnum():
        raise SystemExit("--name must be letters and digits only, such as farhad or judge2.")
    return folder / f"judged_{name.lower()}.csv"


def ask(prompt: str, choices: Mapping[str, str]) -> str:
    while True:
        reply = input(prompt).strip().lower()
        if reply in choices:
            return choices[reply]
        print(f"  Please type one of: {', '.join(choices)}")


def show(row: Mapping[str, str], position: int, total: int) -> None:
    print(f"\n{'=' * 70}\nQuestion {position} of {total}  ({row['id']})")
    kinds = f", tagged: {row['page_kinds']}" if row["page_kinds"] else ""
    print(f"From {row['material']}, page {row['source_page']}{kinds}")
    print(f'Quoted from the page: "{row["source_excerpt"]}"\n')
    print(row["question"])
    if row["options"]:
        for letter, option in zip("ABCD", row["options"].split(" | "), strict=False):
            mark = "   <- marked right" if option == row["correct_answer"] else ""
            print(f"  {letter}. {option}{mark}")
    else:
        print(f"  Model answer: {row['correct_answer']}")
        for point in filter(None, row["key_points"].split(" | ")):
            print(f"  Key point: {point}")


def judge(args: argparse.Namespace) -> None:
    sheet = read_rows(args.dir / SHEET)
    path = judged_path(args.dir, args.name)
    done = {row["id"]: row for row in read_rows(path)} if path.exists() else {}
    rows = [
        {**row, **{f: done.get(row["id"], {}).get(f, "") for f in JUDGEMENT_FIELDS}}
        for row in sheet
    ]
    waiting = [row for row in rows if judgement(row) is None]
    print(
        f"{len(rows) - len(waiting)} of {len(rows)} already judged. Have each material open "
        "at the cited page.\nPlease do not look at another judge's marks. Ctrl+C stops; "
        "your marks so far are saved."
    )
    verdicts = {"u": USABLE, "e": EDIT, "r": REJECT}
    numbered = {str(n): key for n, key in enumerate(PROBLEMS, start=1)}
    try:
        for position, row in enumerate(waiting, start=1):
            show(row, position, len(waiting))
            started = time.monotonic()
            row["verdict"] = ask(
                "\n[u] usable as it is   [e] usable after a correction   [r] not usable: ",
                verdicts,
            )
            if row["verdict"] != USABLE:
                for number, key in numbered.items():
                    print(f"  {number}. {PROBLEMS[key]}")
                row["problem"] = ask("What is the main problem? ", numbered)
                wanted = "the corrected wording" if row["verdict"] == EDIT else "why"
                row["notes"] = input(f"Type {wanted}: ").strip()
            # Reading, deciding and writing the fix: what approving it costs.
            row["seconds"] = f"{time.monotonic() - started:.0f}"
            write_rows(path, SHEET_FIELDS, rows)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
    left = sum(judgement(row) is None for row in rows)
    print(f"Saved to {path}. {left} question(s) left to judge.")


def report(args: argparse.Namespace) -> None:
    judged = {
        path.stem.removeprefix("judged_"): read_rows(path)
        for path in sorted(args.dir.glob("judged_*.csv"))
    }
    text = study_report(
        json.loads((args.dir / RUN).read_text()),
        read_rows(args.dir / SHEET),
        read_rows(args.dir / REJECTED),
        judged,
    )
    (args.dir / REPORT).write_text(text)
    print(text + f"\nwritten to {args.dir / REPORT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    steps = parser.add_subparsers(dest="step", required=True)

    run_step = steps.add_parser("run", help="write questions for the materials and keep them")
    run_step.add_argument("materials", nargs="+", type=Path, help="lecture files, any folder")
    run_step.add_argument("--tags", type=Path, help="JSON: file name -> kind -> page numbers")
    run_step.add_argument("--thresholds", type=Path, default=YIELD_DIR / "thresholds.json")
    run_step.add_argument(
        "--rehearsal", action="store_true", help="run before the thresholds are agreed"
    )

    judge_step = steps.add_parser("judge", help="mark the questions, one judge at a time")
    judge_step.add_argument("--name", required=True, help="the judge's name, one word")

    report_step = steps.add_parser("report", help="write the report from the judges' files")

    for step in (run_step, judge_step, report_step):
        step.add_argument("--dir", type=Path, required=True, help="this run's folder")

    arguments = parser.parse_args()
    if arguments.step == "run":
        asyncio.run(run(arguments))
    elif arguments.step == "judge":
        judge(arguments)
    else:
        report(arguments)
