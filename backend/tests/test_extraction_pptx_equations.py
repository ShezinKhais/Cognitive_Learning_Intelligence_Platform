"""PowerPoint text boxes that hold an equation (#264). Owner: AI 1.

PowerPoint wraps a shape made with Insert > Equation in mc:AlternateContent,
which python-pptx does not list, so the reader lost every word in it. These
decks are built here with the same XML PowerPoint writes.
"""

from __future__ import annotations

import uuid

from lxml import etree
from pptx import Presentation
from pptx.util import Inches

from app.services.extraction import process_material, read_pptx

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A14 = "http://schemas.microsoft.com/office/drawing/2010/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = f'xmlns:p="{P}" xmlns:a="{A}" xmlns:mc="{MC}" xmlns:a14="{A14}" xmlns:m="{M}"'


def math_run(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def shape_xml(paragraphs: str, shape_id: int = 10) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/><p:cNvSpPr/>'
        "<p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/>"
        f"{paragraphs}</p:txBody></p:sp>"
    )


def equation_box(choice: str, fallback: str) -> etree._Element:
    """A box as PowerPoint saves it: the equation, then a fallback for old
    readers with the same words and the equation as a picture."""
    return etree.fromstring(
        f'<mc:AlternateContent {NS}><mc:Choice Requires="a14">{shape_xml(choice)}</mc:Choice>'
        f"<mc:Fallback>{shape_xml(fallback, 11)}</mc:Fallback></mc:AlternateContent>"
    )


# "Does set A exist where |ℕ| < |A| ?" with the symbols as an equation, in
# the styled italic letter (U+1D434) PowerPoint uses for a variable.
HILBERT = (
    "<a:p><a:r><a:t>Does set </a:t></a:r>"
    f"<a14:m><m:oMath>{math_run('𝐴')}</m:oMath></a14:m>"
    "<a:r><a:t> exist where </a:t></a:r>"
    '<a14:m><m:oMath><m:d><m:dPr><m:begChr m:val="|"/><m:endChr m:val="|"/></m:dPr>'
    f"<m:e>{math_run('ℕ')}</m:e></m:d>{math_run('&lt;')}"
    '<m:d><m:dPr><m:begChr m:val="|"/><m:endChr m:val="|"/></m:dPr>'
    f"<m:e>{math_run('𝐴')}</m:e></m:d></m:oMath></a14:m>"
    "<a:r><a:t> ?</a:t></a:r></a:p>"
    "<a:p><a:r><a:t>Matiyasevich proved it undecidable in 1970.</a:t></a:r></a:p>"
)
FALLBACK = "<a:p><a:r><a:t>Does set exist where ?</a:t></a:r></a:p>"


def deck(tmp_path, *boxes, title="Hilbert's 10th Problem", group=False):
    """One slide with a title, an ordinary text box, and the given XML
    after it, inside a group when asked."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title
    slide.shapes.add_textbox(Inches(1), Inches(5), Inches(4), Inches(1)).text = "Plain text box"
    tree = slide.shapes._spTree
    if group:
        grouped = slide.shapes.add_group_shape()
        grouped.shapes.add_textbox(Inches(1), Inches(1), Inches(1), Inches(1)).text = "In a group"
        tree = grouped._element
    for box in boxes:
        tree.append(box)
    path = tmp_path / "deck.pptx"
    prs.save(path)
    return str(path)


def body(path: str) -> str:
    return "\n".join(e.content for e in read_pptx(path) if e.el_type == "text")


def test_the_words_in_a_box_with_an_equation_are_read(tmp_path):
    text = body(deck(tmp_path, equation_box(HILBERT, FALLBACK)))
    assert "Does set A exist where |ℕ|<|A| ?" in text
    assert "Matiyasevich proved it undecidable in 1970." in text
    # Ordinary boxes are still read, once each.
    assert text.count("Plain text box") == 1


def test_the_fallback_is_read_only_when_the_equation_holds_no_text(tmp_path):
    text = body(deck(tmp_path, equation_box("<a:p/>", FALLBACK)))
    assert "Does set exist where ?" in text
    text = body(deck(tmp_path, equation_box(HILBERT, FALLBACK)))
    assert "Does set exist where ?" not in text


def test_a_box_with_an_equation_inside_a_group_is_read(tmp_path):
    text = body(deck(tmp_path, equation_box(HILBERT, FALLBACK), group=True))
    assert "In a group" in text
    assert "Matiyasevich proved" in text


def test_powers_subscripts_and_fractions_keep_their_layout(tmp_path):
    equation = (
        "<a:p><a14:m><m:oMath>"
        f"<m:sSup><m:e>{math_run('𝑥')}</m:e><m:sup>{math_run('2')}</m:sup></m:sSup>"
        f"{math_run('+')}"
        f"<m:sSub><m:e>{math_run('𝑦')}</m:e><m:sub>{math_run('1')}</m:sub></m:sSub>"
        f"{math_run('=')}"
        f"<m:f><m:num>{math_run('1')}</m:num><m:den>{math_run('2')}</m:den></m:f>"
        "</m:oMath></a14:m></a:p>"
        # A bracket left at its default is a round one.
        f"<a:p><a14:m><m:oMath><m:d><m:e>{math_run('a')}</m:e></m:d></m:oMath></a14:m></a:p>"
    )
    text = body(deck(tmp_path, equation_box(equation, FALLBACK)))
    assert "x^2+y_1=1/2" in text
    assert "(a)" in text


def test_a_slide_whose_only_text_is_in_an_equation_box_is_not_lost(tmp_path):
    path = deck(tmp_path, equation_box(HILBERT, FALLBACK), title="")
    result = process_material(path, uuid.uuid4())
    assert any("Matiyasevich" in chunk.chunk_text for chunk in result.chunks)
