"""Per-page previews of a material's extracted content.

Owner: BBIS with AI 2, Phase 2.

The lecturer's workspace shows each page or slide as it was read, and flags
the ones questions are unlikely to be drawn from: pages with almost no text,
and pages that are mostly pictures. Built from the stored extraction elements,
so the preview is exactly what processing worked from.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from app.schemas.content import MaterialPageOut

# Below this many words a page gives the generator almost nothing to ground a
# question in: a title slide, a section divider, a caption.
THIN_PAGE_WORDS = 20

# A page with at least this many images and fewer words than VISUAL_PAGE_WORDS
# carries most of its meaning in pictures, which extraction does not read.
VISUAL_PAGE_IMAGES = 2
VISUAL_PAGE_WORDS = 60

VISUAL_ELEMENT_TYPES = {"image"}


class ExtractedContent(Protocol):
    element_type: str
    content: str | None
    source_page: int | None


def page_previews(elements: Iterable[ExtractedContent]) -> list[MaterialPageOut]:
    """One preview per page that has content, in page order.

    Elements without a page (a format with no pagination) are shown as page 1,
    which is how extraction numbers them.
    """
    texts: dict[int, list[str]] = defaultdict(list)
    visuals: dict[int, int] = defaultdict(int)

    for element in elements:
        page = element.source_page or 1
        if element.element_type in VISUAL_ELEMENT_TYPES:
            visuals[page] += 1
        elif element.content:
            texts[page].append(element.content)

    previews = []
    for page in sorted(set(texts) | set(visuals)):
        text = "\n".join(texts[page])
        words = len(re.findall(r"\w+", text))
        images = visuals[page]
        previews.append(
            MaterialPageOut(
                page_number=page,
                text=text,
                word_count=words,
                visual_element_count=images,
                is_thin=words < THIN_PAGE_WORDS,
                is_visual_heavy=images >= VISUAL_PAGE_IMAGES and words < VISUAL_PAGE_WORDS,
            )
        )
    return previews
