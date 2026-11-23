"""A session report as a PDF the lecturer can download or file.

Owner: General CS, Phase 7 (#65). Pure and synchronous: it is given a finished
SessionReport and returns bytes, so the report queue runs it in a thread and a
live class on the same event loop never waits on it.

Everything shown comes from the report, and every piece of text in it (titles,
topics, alert wording) is escaped before it reaches reportlab's markup, so a
topic that looks like markup is printed as written.

Built-in fonts only, so nothing has to be shipped with the app. They cover
Latin-script text; a character they lack, as in a topic written in another
script, is drawn as a box.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.report import SessionReport

_MARGIN = 18 * mm
# What a table may span: the page less its margins.
_WIDTH = A4[0] - 2 * _MARGIN
_STYLES = getSampleStyleSheet()
_CELL = ParagraphStyle("cell", parent=_STYLES["BodyText"], fontSize=9, leading=11)
_GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def render_pdf(report: SessionReport) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Session report: {report.title}",
        author="C.L.I.P",
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
    )
    document.build(
        [
            _text(f"{report.course_code}: {report.title}", "Title"),
            _text(
                f"Status: {report.status.value}. Started {_when(report.starts_at)}, "
                f"ended {_when(report.ended_at)}. Report generated {_when(report.generated_at)}."
            ),
            Spacer(1, 4 * mm),
            _text("Participation", "Heading2"),
            _table(
                ["Students", "Questions", "Answers", "Missed", "Attention prompts"],
                (0.2, 0.2, 0.2, 0.2, 0.2),
                [
                    [
                        report.participation.students,
                        report.participation.questions_delivered,
                        report.participation.answers,
                        report.participation.missed_answers,
                        report.participation.attention_prompts,
                    ]
                ],
            ),
            _text("Topics, hardest first", "Heading2"),
            *_topics(report),
            _text("Alerts raised", "Heading2"),
            *_alerts(report),
            Spacer(1, 6 * mm),
            _text(
                "Comprehension and engagement are reported separately and never combined. "
                "AI-assisted figures are estimates to prompt a look, not judgements about a "
                "student.",
                "Italic",
            ),
        ]
    )
    return buffer.getvalue()


def _topics(report: SessionReport) -> list:
    if not report.topics:
        return [_text("No answers were marked in this session.")]
    return [
        _table(
            ["Topic", "Level", "Answers", "Mastered", "Partial", "Struggling", "Uncertain"],
            (0.3, 0.15, 0.11, 0.11, 0.11, 0.11, 0.11),
            [
                [
                    t.topic,
                    t.level.value if t.level else "too few answers",
                    t.answers,
                    t.mastered,
                    t.partial,
                    t.struggling,
                    t.uncertain,
                ]
                for t in report.topics
            ],
        )
    ]


def _alerts(report: SessionReport) -> list:
    if not report.alerts:
        return [_text("No alerts were raised in this session.")]
    return [
        _table(
            ["Raised", "Alert", "Why", "Suggested", "Status"],
            (0.15, 0.25, 0.25, 0.23, 0.12),
            [
                [
                    _when(a.raised_at),
                    a.message,
                    a.reason,
                    a.recommendation,
                    a.status,
                ]
                for a in report.alerts
            ],
        )
    ]


def _text(text: str, style: str = "BodyText") -> Paragraph:
    return Paragraph(escape(text), _STYLES[style])


def _table(header: list[str], shares: tuple[float, ...], rows: list[list[object]]) -> Table:
    """A table across the page, each column given its share of the width.
    Cells wrap, so a long alert or topic grows its row, not the page."""
    cells = [[Paragraph(escape(str(value)), _CELL) for value in row] for row in [header, *rows]]
    widths = [_WIDTH * share for share in shares]
    table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(_GRID)
    return table


def _when(moment: datetime | None) -> str:
    return moment.astimezone(UTC).strftime("%d %b %Y %H:%M UTC") if moment else "not recorded"
