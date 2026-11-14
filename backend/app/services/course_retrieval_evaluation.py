"""Whether the tutor's search finds the right page, and stays quiet when no
page answers (#252).

Owner: AI 1. The first retrieval evaluation (retrieval_evaluation.py, #127)
asked 32 questions of three sample lectures, one lecture at a time. The tutor
searches every material of a course at once and drops excerpts further than
tutor_guardrails.RETRIEVAL_MAX_DISTANCE from the question, so it can say the
material does not cover it. That cutoff was set by hand and never measured.

This measures both, course by course:

- where the first excerpt from a page that answers a question ranks, by kind
  of question (text, diagram, table, formula, picture-only, student wording,
  another language, scanned pages);
- whether the top excerpt cites the right lecture and page;
- for a question no page answers, whether the tutor would abstain, and for
  one a page does answer, whether it would wrongly abstain, at the current
  cutoff and at the cutoff that does best on the dev questions, scored on
  held-out questions nobody tuned on.

Plain functions, so they need no model; scripts/evaluate_course_retrieval.py
runs them against one.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.services.tutor_guardrails import MAX_CONTEXT_CHUNKS, RETRIEVAL_MAX_DISTANCE

TOP_K = MAX_CONTEXT_CHUNKS
SPLITS = ("dev", "heldout")
# What makes a question hard to find. A question can be several.
KINDS = {
    "text": "answered by the page's text",
    "diagram": "answered by a diagram",
    "table": "answered by a table",
    "image-only": "answered only by a picture, photo or plot",
    "formula": "about a formula or its symbols",
    "code": "about code or program output",
    "student-wording": "worded as a student would, not as the slide is",
    "arabic": "asked in Arabic",
    "scanned": "answered by a scanned page, read with OCR",
    "off-topic": "about nothing in any course",
    "other-course": "answered only by another course's material",
}
UNANSWERABLE_KINDS = frozenset({"off-topic", "other-course"})


@dataclass(frozen=True)
class CourseQuery:
    id: str
    course: str
    split: str
    kinds: tuple[str, ...]
    query: str
    # (material, page) pairs that answer it; empty when nothing in the
    # course does, and the tutor should abstain.
    answers: frozenset[tuple[str, int]]

    @property
    def answerable(self) -> bool:
        return bool(self.answers)


def load_query_set(path: Path) -> tuple[dict[str, list[str]], list[CourseQuery]]:
    """The courses (name -> material files) and the questions, checked so a
    typo is found before an hour of embedding, not after."""
    data = json.loads(path.read_text())
    courses = {name: list(files) for name, files in data["courses"].items()}
    queries = []
    seen = set()
    for item in data["queries"]:
        qid = item["id"]
        where = f"{path.name}, question {qid}"
        if qid in seen:
            raise ValueError(f"{where}: the id is used twice")
        seen.add(qid)
        if item["course"] not in courses:
            raise ValueError(f"{where}: no course named {item['course']!r}")
        if item["split"] not in SPLITS:
            raise ValueError(f"{where}: split must be one of {', '.join(SPLITS)}")
        kinds = tuple(item["kinds"])
        unknown = [k for k in kinds if k not in KINDS]
        if not kinds or unknown:
            raise ValueError(f"{where}: kinds must be some of {', '.join(KINDS)}")
        answers = set()
        for answer in item.get("answers", []):
            if answer["material"] not in courses[item["course"]]:
                raise ValueError(
                    f"{where}: {answer['material']!r} is not one of {item['course']}'s materials"
                )
            if not answer["pages"]:
                raise ValueError(f"{where}: an answer needs at least one page")
            answers.update((answer["material"], int(p)) for p in answer["pages"])
        unanswerable = bool(set(kinds) & UNANSWERABLE_KINDS)
        if unanswerable == bool(answers):
            raise ValueError(
                f"{where}: a question has answers exactly when it is not off-topic or other-course"
            )
        queries.append(
            CourseQuery(
                qid, item["course"], item["split"], kinds, item["query"], frozenset(answers)
            )
        )
    return courses, queries


@dataclass(frozen=True)
class Excerpt:
    """One chunk of a course, as the tutor's search sees it."""

    material: str
    page: int | None
    vector: tuple[float, ...]


@dataclass(frozen=True)
class Found:
    material: str
    page: int | None
    distance: float  # cosine distance, as pgvector's <=> gives it


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - (sum(x * y for x, y in zip(a, b, strict=True)) / norms if norms else 0.0)


def search(query_vector: Sequence[float], excerpts: Sequence[Excerpt]) -> list[Found]:
    """Every excerpt of the course, nearest first, as the tutor orders them.
    Ties keep their order."""
    found = [Found(e.material, e.page, cosine_distance(query_vector, e.vector)) for e in excerpts]
    return sorted(found, key=lambda f: f.distance)


@dataclass(frozen=True)
class Result:
    query: CourseQuery
    found: tuple[Found, ...]  # the course's excerpts, nearest first

    @property
    def rank(self) -> int | None:
        """1-based rank of the first excerpt from an answering page, or None
        when there is none (always None for an unanswerable question)."""
        for rank, f in enumerate(self.found, start=1):
            if (f.material, f.page) in self.query.answers:
                return rank
        return None

    @property
    def top_distance(self) -> float:
        return self.found[0].distance if self.found else math.inf

    def answered(self, cutoff: float) -> bool:
        """Whether the tutor would show any excerpt: one is within the cutoff."""
        return self.top_distance <= cutoff

    def precision(self, k: int = TOP_K) -> float:
        """Share of the top k excerpts that come from an answering page."""
        return sum((f.material, f.page) in self.query.answers for f in self.found[:k]) / k

    @property
    def right_material_on_top(self) -> bool:
        """Whether the top excerpt is from a lecture that answers, whatever
        its page: the citation names the right lecture at least."""
        materials = {m for m, _ in self.query.answers}
        return bool(self.found) and self.found[0].material in materials


@dataclass(frozen=True)
class RankScore:
    questions: int
    hit_at_1: int
    hit_at_k: int
    reciprocal: float  # sum of 1/rank
    precision: float  # sum of precision@k
    right_material: int

    @property
    def mrr(self) -> float:
        return self.reciprocal / self.questions

    @property
    def mean_precision(self) -> float:
        return self.precision / self.questions


def rank_score(results: Sequence[Result], k: int = TOP_K) -> RankScore:
    """How the answerable questions in `results` ranked."""
    answerable = [r for r in results if r.query.answerable]
    if not answerable:
        raise ValueError("no answerable questions to score")
    ranks = [r.rank for r in answerable]
    return RankScore(
        questions=len(answerable),
        hit_at_1=sum(rank == 1 for rank in ranks),
        hit_at_k=sum(rank is not None and rank <= k for rank in ranks),
        reciprocal=sum(1 / rank for rank in ranks if rank is not None),
        precision=sum(r.precision(k) for r in answerable),
        right_material=sum(r.right_material_on_top for r in answerable),
    )


@dataclass(frozen=True)
class AbstainScore:
    cutoff: float
    unanswerable: int
    abstained: int  # unanswerable questions the tutor would stay quiet on
    answerable: int
    wrongly_abstained: int  # answerable questions it would refuse

    @property
    def balanced_accuracy(self) -> float:
        """The mean of the two things it should do: abstain when nothing
        answers, and answer when something does. Each counts the same however
        many questions of each kind there are."""
        rates = []
        if self.unanswerable:
            rates.append(self.abstained / self.unanswerable)
        if self.answerable:
            rates.append(1 - self.wrongly_abstained / self.answerable)
        return sum(rates) / len(rates) if rates else 0.0


def abstain_score(results: Sequence[Result], cutoff: float) -> AbstainScore:
    unanswerable = [r for r in results if not r.query.answerable]
    answerable = [r for r in results if r.query.answerable]
    return AbstainScore(
        cutoff=cutoff,
        unanswerable=len(unanswerable),
        abstained=sum(not r.answered(cutoff) for r in unanswerable),
        answerable=len(answerable),
        wrongly_abstained=sum(not r.answered(cutoff) for r in answerable),
    )


def best_cutoff(results: Sequence[Result]) -> float:
    """The cutoff with the best balanced accuracy on `results`.

    Only the gaps between the questions' top distances change anything, so
    each midpoint is tried. Of equally good cutoffs the largest is taken: it
    refuses fewer real questions, which a student notices more than a reply
    that says too little. Rounded to two places, so it reads as a setting.
    """
    distances = sorted({r.top_distance for r in results if math.isfinite(r.top_distance)})
    if not distances:
        raise ValueError("no distances to choose a cutoff from")
    candidates = [distances[0] - 0.01, distances[-1] + 0.01]
    candidates += [(a + b) / 2 for a, b in zip(distances, distances[1:], strict=False)]
    best = max(candidates, key=lambda c: (abstain_score(results, c).balanced_accuracy, c))
    return round(best, 2)


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a share; honest at 0 of n and n of n."""
    share = successes / total
    centre = share + z * z / (2 * total)
    spread = z * math.sqrt((share * (1 - share) + z * z / (4 * total)) / total)
    scale = 1 + z * z / total
    return max(0.0, (centre - spread) / scale), min(1.0, (centre + spread) / scale)


def share(successes: int, total: int) -> str:
    if not total:
        return "-"
    low, high = wilson(successes, total)
    return f"{successes} of {total} ({successes / total:.0%}, {low:.0%} to {high:.0%})"


# ---- the report ----------------------------------------------------------------


def _rank_rows(groups: Sequence[tuple[str, Sequence[Result]]], k: int) -> list[str]:
    lines = [
        f"| Questions | n | Right page on top | Right page in top {k} | MRR "
        f"| precision@{k} | Right lecture on top |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, members in groups:
        if not any(r.query.answerable for r in members):
            continue
        s = rank_score(members, k)
        lines.append(
            f"| {name} | {s.questions} | {share(s.hit_at_1, s.questions)} "
            f"| {share(s.hit_at_k, s.questions)} | {s.mrr:.2f} | {s.mean_precision:.2f} "
            f"| {share(s.right_material, s.questions)} |"
        )
    return lines


def _abstain_row(name: str, s: AbstainScore) -> str:
    return (
        f"| {name} | {s.cutoff:.2f} | {share(s.abstained, s.unanswerable)} "
        f"| {share(s.wrongly_abstained, s.answerable)} | {s.balanced_accuracy:.2f} |"
    )


def report(
    results: Sequence[Result],
    *,
    header: Sequence[str],
    current_cutoff: float = RETRIEVAL_MAX_DISTANCE,
    k: int = TOP_K,
) -> str:
    """The Markdown report: ranks by kind, course and split, then abstention
    at the current cutoff and at the one chosen on the dev questions, scored
    on the held-out ones, then every question."""
    dev = [r for r in results if r.query.split == "dev"]
    heldout = [r for r in results if r.query.split == "heldout"]
    lines = [*header, ""]

    lines += ["## Finding the right page", ""]
    lines.append(
        "Answerable questions only. A share is followed by its 95% interval; with "
        "few questions per row, the intervals are wide."
    )
    lines.append("")
    by_kind = [
        (f"{kind}: {KINDS[kind]}", [r for r in results if kind in r.query.kinds])
        for kind in KINDS
        if kind not in UNANSWERABLE_KINDS
    ]
    by_course = [
        (f"course: {c}", [r for r in results if r.query.course == c])
        for c in dict.fromkeys(r.query.course for r in results)
    ]
    by_split = [(f"split: {s}", [r for r in results if r.query.split == s]) for s in SPLITS]
    lines += _rank_rows([*by_kind, *by_course, *by_split, ("all", list(results))], k)
    lines.append("")

    lines += ['## Saying "not in the material"', ""]
    lines.append(
        "The tutor drops every excerpt further than the cutoff from the question. "
        "When all of them are dropped it says the material does not cover it "
        "(abstains). It should abstain on off-topic and other-course questions, "
        "and answer the rest."
    )
    lines.append("")
    lines += [
        "| Questions | Cutoff | Abstained when nothing answers | Wrongly abstained "
        "when a page answers | Balanced accuracy |",
        "|---|---|---|---|---|",
        _abstain_row("all, current setting", abstain_score(results, current_cutoff)),
    ]
    if dev and heldout and any(not r.query.answerable for r in dev):
        chosen = best_cutoff(dev)
        lines += [
            _abstain_row("dev, current setting", abstain_score(dev, current_cutoff)),
            _abstain_row("dev, best cutoff on dev", abstain_score(dev, chosen)),
            _abstain_row("**held-out, current setting**", abstain_score(heldout, current_cutoff)),
            _abstain_row("**held-out, cutoff chosen on dev**", abstain_score(heldout, chosen)),
            "",
            f"The cutoff chosen on the dev questions is **{chosen:.2f}** (now "
            f"{current_cutoff:.2f}). Only the held-out rows say how it would do on "
            "questions nobody tuned on.",
        ]
    else:
        lines += [
            "",
            "No cutoff is chosen: that needs dev questions, including unanswerable "
            "ones, and held-out questions to score it on.",
        ]
    lines.append("")

    lines += [
        "## Every question",
        "",
        "Rank of the first excerpt from an answering page (`-`: none in the course); "
        "the top excerpt as lecture, page and distance.",
        "",
        "| Id | Split | Kinds | Question | Answer on | Rank | Top excerpt |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        q = r.query
        pages: dict[str, list[int]] = {}
        for material, page in sorted(q.answers):
            pages.setdefault(material, []).append(page)
        answer = "; ".join(f"{m} p.{', '.join(map(str, ps))}" for m, ps in pages.items())
        answer = answer or "nothing"
        top = r.found[0] if r.found else None
        shown = f"{top.material} p.{top.page}, {top.distance:.3f}" if top else "-"
        rank = "-" if r.rank is None else str(r.rank)
        question = q.query.replace("|", "\\|")
        kinds = ", ".join(q.kinds)
        lines.append(f"| {q.id} | {q.split} | {kinds} | {question} | {answer} | {rank} | {shown} |")
    return "\n".join(lines) + "\n"
