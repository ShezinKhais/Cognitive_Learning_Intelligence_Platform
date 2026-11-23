"""How many generated questions a lecturer can actually use, and at what cost.

Owner: AI 1 (#235). The grounding checks decide which drafts reach a lecturer;
this measures what the lecturer then finds. Every question that passed the
checks is judged by people, separately, as usable as it is, usable after a
correction, or not usable, with the kind of fault and the seconds it took.
From that come the usable-question yield, the questions that passed the checks
but are wrong, the kinds of failure, and the lecturer's correction time, each
compared with thresholds the team agreed before the run.

Plain functions over rows, so they need no model.
scripts/evaluate_question_yield.py runs the generator, collects the judgements
and writes the report with them.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from app.services.classifier_evaluation import cohen_kappa
from app.services.grounding_evaluation import reason_kind
from app.services.material_seams import DraftQuestion

USABLE, EDIT, REJECT = "usable", "edit", "reject"
VERDICTS = (USABLE, EDIT, REJECT)

# What a judge may name as wrong with a question, and how the report words it.
PROBLEMS: dict[str, str] = {
    "wrong_answer": "the marked answer is wrong",
    "several_right": "more than one option is right, or none is",
    "not_in_material": "the cited page does not support it",
    "unclear": "ambiguous or badly worded",
    "trivial": "tests nothing worth asking",
    "other": "something else (see the judge's note)",
}
# The faults that make a question wrong rather than weak. A question the
# checks passed with one of these is the failure the checks exist to prevent.
INCORRECT = frozenset({"wrong_answer", "several_right", "not_in_material"})

TEXT_ONLY = "text only"

# The thresholds file. The first two say who agreed the numbers and when; a
# run is a rehearsal until both are filled in.
AGREED_BY, AGREED_ON = "agreed_by", "agreed_on"
MIN_USABLE_SHARE = "min_usable_share_of_passed"
MAX_INCORRECT_SHARE = "max_incorrect_share_of_passed"
MIN_USABLE_PER_MATERIAL = "min_usable_per_material"
MAX_MEDIAN_SECONDS = "max_median_review_seconds"
THRESHOLD_KEYS = (
    MIN_USABLE_SHARE,
    MAX_INCORRECT_SHARE,
    MIN_USABLE_PER_MATERIAL,
    MAX_MEDIAN_SECONDS,
)


def thresholds_agreed(thresholds: Mapping) -> bool:
    return bool(thresholds.get(AGREED_BY)) and bool(thresholds.get(AGREED_ON))


def missing_thresholds(thresholds: Mapping) -> list[str]:
    return [
        key
        for key in THRESHOLD_KEYS
        if isinstance(thresholds.get(key), bool) or not isinstance(thresholds.get(key), int | float)
    ]


def text_hash(text: str) -> str:
    """Enough of a hash to tell whether a prompt changed between two runs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- the sheets a run writes ---------------------------------------------------

QUESTION_FIELDS = (
    "id",
    "material",
    "type",
    "question",
    "options",
    "correct_answer",
    "key_points",
    "source_page",
    "source_excerpt",
    "page_kinds",
)
JUDGEMENT_FIELDS = ("verdict", "problem", "seconds", "notes")
SHEET_FIELDS = QUESTION_FIELDS + JUDGEMENT_FIELDS
REJECTED_FIELDS = QUESTION_FIELDS + ("reason_kinds", "reasons")


def page_kinds(tags: Mapping[str, Sequence[int]], page: int | None) -> list[str]:
    """What the lecturer said is on a page: diagram, formula, table and so on."""
    return sorted(kind for kind, pages in tags.items() if page in pages)


def question_row(
    question_id: str, material: str, draft: DraftQuestion, tags: Mapping[str, Sequence[int]]
) -> dict[str, str]:
    options = draft.options or ()
    correct = draft.correct_option
    answer = (
        options[correct]
        if isinstance(correct, int) and 0 <= correct < len(options)
        else (draft.reference_answer or "")
    )
    return {
        "id": question_id,
        "material": material,
        "type": draft.type.value,
        "question": draft.prompt,
        "options": " | ".join(options),
        "correct_answer": answer,
        "key_points": " | ".join(draft.key_points or ()),
        "source_page": "" if draft.source_slide is None else str(draft.source_slide),
        "source_excerpt": draft.source_excerpt or "",
        "page_kinds": "; ".join(page_kinds(tags, draft.source_slide)),
    }


def rejected_row(question: dict[str, str], reasons: Sequence[str]) -> dict[str, str]:
    kinds = sorted({reason_kind(reason) for reason in reasons})
    return {**question, "reason_kinds": "; ".join(kinds), "reasons": "; ".join(reasons)}


def write_rows(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fields})


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "") for k, v in row.items() if k} for row in csv.DictReader(f)]


# ---- one judge's marks ---------------------------------------------------------


@dataclass(frozen=True)
class Judgement:
    verdict: str
    problem: str = ""
    seconds: float | None = None


def judgement(row: Mapping[str, str]) -> Judgement | None:
    """A row's mark, or None while the judge has not filled it in. A mark
    that is filled in wrongly raises, so a typo is fixed rather than dropped."""
    verdict = row.get("verdict", "").strip().lower()
    if not verdict:
        return None
    where = f"question {row.get('id', '?')}"
    if verdict not in VERDICTS:
        raise ValueError(f"{where}: verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
    problem = row.get("problem", "").strip().lower()
    if verdict == USABLE:
        problem = ""
    elif problem not in PROBLEMS:
        raise ValueError(
            f"{where}: a question marked {verdict} needs a problem, one of {', '.join(PROBLEMS)}"
        )
    raw = row.get("seconds", "").strip()
    try:
        seconds = float(raw) if raw else None
    except ValueError:
        raise ValueError(f"{where}: seconds {raw!r} is not a number") from None
    if seconds is not None and seconds < 0:
        raise ValueError(f"{where}: seconds cannot be negative")
    return Judgement(verdict, problem, seconds)


def judgements(rows: Sequence[Mapping[str, str]]) -> dict[str, Judgement]:
    marks = {}
    for row in rows:
        mark = judgement(row)
        if mark is not None:
            marks[row["id"]] = mark
    return marks


def consensus(verdicts: Sequence[str]) -> str:
    """The strictest judge decides: one rejection rejects the question, and
    one correction means it was not usable as it was."""
    if REJECT in verdicts:
        return REJECT
    return EDIT if EDIT in verdicts else USABLE


# ---- the report ----------------------------------------------------------------


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson interval for a share. Used here rather than the
    bootstrap the other evaluations use, because resampling "0 of 12 wrong"
    only ever gives 0, an interval of 0% to 0%, which claims a certainty a
    dozen questions cannot give. This one still leaves room above zero."""
    share = successes / total
    centre = share + z * z / (2 * total)
    spread = z * ((share * (1 - share) + z * z / (4 * total)) / total) ** 0.5
    scale = 1 + z * z / total
    return max(0.0, (centre - spread) / scale), min(1.0, (centre + spread) / scale)


def _share(successes: int, total: int) -> str:
    if not total:
        return "-"
    low, high = wilson(successes, total)
    return f"{successes} of {total} ({successes / total:.0%}, 95% interval {low:.0%} to {high:.0%})"


def _met(passed: bool | None) -> str:
    return "not measured" if passed is None else ("met" if passed else "**not met**")


def study_report(
    run: Mapping,
    sheet: Sequence[Mapping[str, str]],
    rejected: Sequence[Mapping[str, str]],
    judged: Mapping[str, Sequence[Mapping[str, str]]],
) -> str:
    """The yield report, from what the run wrote and what each judge marked.

    `run` is run.json, `sheet` the questions that passed the checks, `rejected`
    the drafts that did not, and `judged` each judge's filled-in copy of the
    sheet by judge name.
    """
    thresholds = run["thresholds"]
    materials = run["materials"]
    marks = {name: judgements(rows) for name, rows in judged.items()}
    names = sorted(marks)
    known = {row["id"] for row in sheet}
    for name in names:
        strangers = sorted(set(marks[name]) - known)
        if strangers:
            raise ValueError(f"{name} judged questions that are not in this run: {strangers}")

    # Only a question every judge has marked has a consensus.
    complete = [row for row in sheet if names and all(row["id"] in marks[n] for n in names)]
    verdict = {
        row["id"]: consensus([marks[n][row["id"]].verdict for n in names]) for row in complete
    }
    problems = {row["id"]: {marks[n][row["id"]].problem for n in names} - {""} for row in complete}
    incorrect = {qid for qid, named in problems.items() if named & INCORRECT}

    drafts = sum(m["drafts"] for m in materials)
    passed = len(sheet)
    judged_count = len(complete)
    as_is = sum(v == USABLE for v in verdict.values())
    edited = sum(v == EDIT for v in verdict.values())
    usable = as_is + edited
    everything_judged = bool(passed) and judged_count == passed

    lines = [
        "# Question yield with lecturer evaluation (#235)",
        "",
        f"Model `{run['model']}`, commit `{run['commit']}`, run on {run['started']}.",
        f"{len(materials)} material(s), {drafts} drafts, {passed} passed the automated checks, "
        f"{judged_count} judged by all of {len(names)} judge(s)"
        f"{': ' + ', '.join(names) if names else ''}.",
        "",
    ]
    if not thresholds_agreed(thresholds):
        lines += [
            "> **Rehearsal.** The thresholds were not agreed before this run, so it cannot",
            "> be used as evidence. Agree them, then run again on material nobody has seen.",
            "",
        ]
    if passed and not everything_judged:
        lines += [
            f"> **Incomplete.** {passed - judged_count} of {passed} questions have not been "
            "judged by every judge, so the shares below cover only the judged ones.",
            "",
        ]

    lines += [
        "## Yield",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Drafts that passed the automated checks | {_share(passed, drafts)} |",
        f"| Passed and usable as they are | {_share(as_is, judged_count)} |",
        f"| Passed and usable after a correction | {_share(edited, judged_count)} |",
        f"| Passed and usable either way | {_share(usable, judged_count)} |",
        f"| Passed but not usable | {_share(judged_count - usable, judged_count)} |",
        f"| **Passed but wrong** (wrong answer, several right, or not in the material) | "
        f"{_share(len(incorrect), judged_count)} |",
        "| **Usable-question yield** (usable either way, of all drafts) | "
        f"{_share(usable, drafts) if everything_judged else '-'} |",
        "",
    ]

    lines += [
        "## By material",
        "",
        "| Material | Asked for | Drafts | Passed | Usable as is | After a correction | Wrong |",
        "|---|---|---|---|---|---|---|",
    ]
    usable_per_material = []
    for material in materials:
        ids = [row["id"] for row in complete if row["material"] == material["name"]]
        usable_here = sum(verdict[i] != REJECT for i in ids)
        usable_per_material.append(usable_here)
        lines.append(
            f"| {material['name']} | {material['asked']} | {material['drafts']} "
            f"| {material['passed']} | {sum(verdict[i] == USABLE for i in ids)} "
            f"| {sum(verdict[i] == EDIT for i in ids)} | {sum(i in incorrect for i in ids)} |"
        )
    lines.append("")

    lines += [
        "## By what is on the cited page",
        "",
        "Pages are tagged by hand before the run. A draft citing a page with two kinds",
        "counts under both.",
        "",
        "| On the page | Drafts citing it | Passed | Usable either way | Wrong |",
        "|---|---|---|---|---|",
    ]

    def kinds_of(row: Mapping[str, str]) -> list[str]:
        return [k.strip() for k in row["page_kinds"].split(";") if k.strip()] or [TEXT_ONLY]

    cited: Counter = Counter()
    passed_by_kind: Counter = Counter()
    usable_by_kind: Counter = Counter()
    wrong_by_kind: Counter = Counter()
    for row in rejected:
        cited.update(kinds_of(row))
    for row in sheet:
        for kind in kinds_of(row):
            cited[kind] += 1
            passed_by_kind[kind] += 1
            usable_by_kind[kind] += verdict.get(row["id"], REJECT) != REJECT
            wrong_by_kind[kind] += row["id"] in incorrect
    for kind in sorted(cited, key=lambda k: (k == TEXT_ONLY, k)):
        lines.append(
            f"| {kind} | {cited[kind]} | {passed_by_kind[kind]} | {usable_by_kind[kind]} "
            f"| {wrong_by_kind[kind]} |"
        )
    lines.append("")

    lines += [
        "## Why drafts failed",
        "",
        "Rejected by the automated checks (a draft can have more than one reason):",
        "",
        "| Reason | Drafts |",
        "|---|---|",
    ]
    reasons: Counter = Counter()
    for row in rejected:
        reasons.update(k.strip() for k in row["reason_kinds"].split(";") if k.strip())
    lines += [f"| {kind} | {count} |" for kind, count in reasons.most_common()] or ["| none | 0 |"]
    duplicates = sum(m.get("duplicates", 0) for m in materials)
    empty = sum(m.get("empty_calls", 0) for m in materials)
    calls = sum(m.get("calls", 0) for m in materials)
    lines += [
        "",
        f"{duplicates} more draft(s) passed but repeated a question already kept, and "
        f"{empty} of {calls} model replies gave no drafts at all (unreadable or empty).",
        "",
        "Passed the checks, then faulted by a judge (a question can have more than one fault):",
        "",
        "| Fault | Questions |",
        "|---|---|",
    ]
    faults = Counter(problem for named in problems.values() for problem in named)
    lines += [
        f"| {PROBLEMS[problem]} | {faults[problem]} |" for problem in PROBLEMS if faults[problem]
    ] or ["| none | 0 |"]
    lines.append("")

    lines += [
        "## Judges and review time",
        "",
        "| Judge | Usable | Correct it | Reject | Median seconds a question | Total minutes |",
        "|---|---|---|---|---|---|",
    ]
    all_seconds: list[float] = []
    totals: list[float] = []
    for name in names:
        mine = [marks[name][row["id"]] for row in complete]
        seconds = [m.seconds for m in mine if m.seconds is not None]
        all_seconds += seconds
        if seconds:
            totals.append(sum(seconds))
        lines.append(
            f"| {name} | {sum(m.verdict == USABLE for m in mine)} "
            f"| {sum(m.verdict == EDIT for m in mine)} "
            f"| {sum(m.verdict == REJECT for m in mine)} "
            f"| {f'{median(seconds):.0f}' if seconds else '-'} "
            f"| {f'{sum(seconds) / 60:.1f}' if seconds else '-'} |"
        )
    lines.append("")
    median_seconds = median(all_seconds) if all_seconds else None
    if totals and usable:
        per_usable = sum(totals) / len(totals) / usable
        lines.append(
            f"One judge spent about {per_usable:.0f} seconds of review for each usable "
            "question, counting the time spent on the ones thrown away."
        )
    if len(names) >= 2 and complete:
        first, second = names[0], names[1]
        a = [marks[first][row["id"]].verdict for row in complete]
        b = [marks[second][row["id"]].verdict for row in complete]
        same = sum(x == y for x, y in zip(a, b, strict=True))
        lines.append(
            f"{first} and {second} gave the same verdict on {same} of {len(complete)} "
            f"questions (Cohen's kappa {cohen_kappa(a, b, VERDICTS):.2f})."
        )
    elif names:
        lines.append("Only one judge so far: a second, independent judge is still needed.")
    lines.append("")

    usable_share = usable / judged_count if judged_count else None
    incorrect_share = len(incorrect) / judged_count if judged_count else None
    fewest = min(usable_per_material) if usable_per_material and everything_judged else None

    def at_least(value: float | None, key: str) -> bool | None:
        return None if value is None else value >= thresholds[key]

    def at_most(value: float | None, key: str) -> bool | None:
        return None if value is None else value <= thresholds[key]

    def shown(value: float | None, style: str) -> str:
        return "-" if value is None else format(value, style)

    agreed = (
        f"agreed by {', '.join(thresholds[AGREED_BY])} on {thresholds[AGREED_ON]}"
        if thresholds_agreed(thresholds)
        else "**not agreed before the run**"
    )
    lines += [
        "## Against the thresholds",
        "",
        f"Thresholds {agreed}.",
        "",
        "| Threshold | Agreed | Measured | Result |",
        "|---|---|---|---|",
        f"| Passed questions usable, as they are or after a correction | at least "
        f"{thresholds[MIN_USABLE_SHARE]:.0%} | {shown(usable_share, '.0%')} "
        f"| {_met(at_least(usable_share, MIN_USABLE_SHARE))} |",
        f"| Passed questions that are wrong | at most {thresholds[MAX_INCORRECT_SHARE]:.0%} "
        f"| {shown(incorrect_share, '.0%')} "
        f"| {_met(at_most(incorrect_share, MAX_INCORRECT_SHARE))} |",
        f"| Usable questions from the material with the fewest | at least "
        f"{thresholds[MIN_USABLE_PER_MATERIAL]} | {shown(fewest, 'd')} "
        f"| {_met(at_least(fewest, MIN_USABLE_PER_MATERIAL))} |",
        f"| Median review time for a question | at most {thresholds[MAX_MEDIAN_SECONDS]} s "
        f"| {shown(median_seconds, '.0f')}{' s' if median_seconds is not None else ''} "
        f"| {_met(at_most(median_seconds, MAX_MEDIAN_SECONDS))} |",
        "",
        "Whatever these say, a lecturer still approves every question before a class",
        "sees it. Nothing here changes that.",
        "",
        "## What was run",
        "",
        "| Setting | Value |",
        "|---|---|",
    ]
    lines += [f"| {key} | `{value}` |" for key, value in run["settings"].items()]
    lines += [f"| prompt: {key} | `{value}` |" for key, value in run["prompts"].items()]
    lines += [
        "",
        "| Material | SHA-256 (first 12) | Pages | Chunks | Tagged pages |",
        "|---|---|---|---|---|",
    ]
    for material in materials:
        tags = "; ".join(
            f"{kind}: {', '.join(str(p) for p in pages)}"
            for kind, pages in sorted(material.get("tags", {}).items())
        )
        lines.append(
            f"| {material['name']} | `{material['sha256'][:12]}` | {material['pages']} "
            f"| {material['chunks']} | {tags or 'none'} |"
        )
    lines += [
        "",
        "Every draft is kept beside this report: `sheet.csv` (passed the checks),",
        "`rejected.csv` (did not, with the reasons) and one `judged_<name>.csv` for each judge.",
    ]
    return "\n".join(lines) + "\n"
