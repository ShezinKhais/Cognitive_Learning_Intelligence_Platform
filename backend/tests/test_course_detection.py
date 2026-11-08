"""Filing a material under the course it names."""

import uuid

from app.services.course_detection import TEXT_WINDOW, codes_in, detect_course

CSIT = uuid.uuid4()
CSCI = uuid.uuid4()
KNOWN = {"CSIT321": CSIT, "CSCI235": CSCI}


def test_codes_are_found_however_they_are_written() -> None:
    assert codes_in("CSIT321_week3.pptx") == {"CSIT321"}
    assert codes_in("Lecture for csci 235 and ISIT-312") == {"CSCI235", "ISIT312"}
    assert codes_in("MATH221A notes") == {"MATH221A"}


def test_numbers_and_words_that_only_look_like_codes_are_ignored() -> None:
    assert codes_in("Version 2024 of chapter 12, room A101x9") == set()


def test_the_file_name_files_it() -> None:
    assert detect_course("CSIT321 Week 3.pdf", ["nothing here"], KNOWN) == CSIT


def test_the_text_files_it_when_the_name_does_not() -> None:
    assert detect_course("week3.pdf", ["Title slide: CSIT 321 Teams Project"], KNOWN) == CSIT


def test_the_file_name_wins_over_courses_mentioned_in_the_text() -> None:
    text = ["CSIT321 builds on CSCI235, so revise CSCI235 first."]
    assert detect_course("CSIT321_w2.pdf", text, KNOWN) == CSIT


def test_two_courses_and_no_name_leave_it_unfiled() -> None:
    assert detect_course("notes.pdf", ["CSIT321 and CSCI235 joint session"], KNOWN) is None


def test_an_unknown_code_leaves_it_unfiled() -> None:
    assert detect_course("ABCD999.pdf", ["ABCD999"], KNOWN) is None
    assert detect_course("CSIT321.pdf", [], {}) is None


def test_only_the_start_of_the_text_is_read() -> None:
    late = ["x" * TEXT_WINDOW, "CSIT321"]
    assert detect_course("notes.pdf", late, KNOWN) is None
