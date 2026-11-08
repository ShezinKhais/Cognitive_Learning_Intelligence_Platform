"""Filing an uploaded material under its course without being asked.

Owner: General CS, Phase 8. Lecture files usually carry their course code,
in the file name ("CSIT321_week3.pptx") or on the first slide. When a
material finishes processing with no course, the codes in its name and the
start of its text are matched against the courses C.L.I.P knows. Exactly one
match files it there; none, or several, leave it under any course, and the
lecturer can still choose one on the materials page.

The file name decides when it names a known course, since a deck often
mentions other courses (prerequisites, related units) further in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from uuid import UUID

# Letters then three or four digits, optionally one letter: CSIT321,
# CSCI 235, ISIT-312, MATH221A. Underscores count as separators, so a file
# name like CSIT321_week3 still matches.
_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,5})[\s_-]?(\d{3,4}[A-Za-z]?)(?![A-Za-z0-9])")

# Only the start of the text is read: the title slide and the first pages.
TEXT_WINDOW = 20_000


def normalise(code: str) -> str:
    return re.sub(r"[\s_-]", "", code).upper()


def codes_in(text: str) -> set[str]:
    return {normalise(letters + digits) for letters, digits in _CODE.findall(text)}


def _single(found: Iterable[str], known: Mapping[str, UUID]) -> UUID | None:
    matches = {known[code] for code in found if code in known}
    return matches.pop() if len(matches) == 1 else None


def detect_course(filename: str, texts: Iterable[str], known: Mapping[str, UUID]) -> UUID | None:
    """The one known course this material names, or None.

    `known` maps each course's normalised code to its id.
    """
    if not known:
        return None
    by_name = {known[code] for code in codes_in(filename) if code in known}
    if by_name:
        return by_name.pop() if len(by_name) == 1 else None
    window: list[str] = []
    size = 0
    for text in texts:
        if size >= TEXT_WINDOW:
            break
        window.append(text[: TEXT_WINDOW - size])
        size += len(window[-1])
    return _single(codes_in("\n".join(window)), known)
