from app.services.lecture_question_match import supported_by_recent_lecture


def test_enzyme_question_is_eligible_after_enzyme_teaching():
    assert supported_by_recent_lecture(
        "What are enzymes?",
        "enzymes",
        ["Today we are studying enzymes and how they work."],
    )


def test_future_animals_topic_is_not_eligible():
    assert not supported_by_recent_lecture(
        "What are mammals?",
        "mammals",
        ["Today we are studying enzymes and catalysts."],
    )


def test_topic_mention_does_not_prove_specific_concept():
    assert not supported_by_recent_lecture(
        "What is enzyme inhibition?",
        "enzyme",
        ["An enzyme is a biological catalyst."],
    )


def test_specific_concept_becomes_eligible_when_discussed():
    assert supported_by_recent_lecture(
        "What is enzyme inhibition?",
        "enzyme",
        ["We are discussing enzyme inhibition."],
    )


def test_no_transcript_means_no_automatic_question():
    assert not supported_by_recent_lecture(
        "What are enzymes?",
        "enzymes",
        [],
    )


def test_arabic_exact_terms_can_match():
    assert supported_by_recent_lecture(
        "ما هي الإنزيمات؟",
        "الإنزيمات",
        ["اليوم ندرس الإنزيمات"],
    )


def test_english_question_does_not_guess_arabic_equivalence():
    assert not supported_by_recent_lecture(
        "What are enzymes?",
        "enzymes",
        ["اليوم ندرس الإنزيمات"],
    )


def test_only_recent_whisper_segments_are_selected():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.services.lecture_question_match import recent_transcript_segments

    now = datetime(2026, 11, 23, 10, 40, tzinfo=UTC)

    notes = [
        SimpleNamespace(
            occurred_at=now - timedelta(minutes=30),
            text="Animals and mammals",
            origin="live_transcript",
        ),
        SimpleNamespace(
            occurred_at=now - timedelta(minutes=5),
            text="Enzyme inhibition",
            origin="live_transcript",
        ),
        SimpleNamespace(
            occurred_at=now - timedelta(minutes=12),
            text="Enzymes are catalysts",
            origin="live_transcript",
        ),
        SimpleNamespace(
            occurred_at=now - timedelta(minutes=2),
            text="Lecturer private note",
            origin="lecturer",
        ),
        SimpleNamespace(
            occurred_at=now + timedelta(minutes=1),
            text="Future topic",
            origin="live_transcript",
        ),
    ]

    recent = recent_transcript_segments(notes, now)

    assert recent == [
        "Enzymes are catalysts",
        "Enzyme inhibition",
    ]

    assert supported_by_recent_lecture(
        "What is enzyme inhibition?",
        "enzyme",
        recent,
    )

    assert not supported_by_recent_lecture(
        "What are mammals?",
        "mammals",
        recent,
    )


def test_transcript_window_accepts_10_to_20_minutes_only():
    from datetime import UTC, datetime

    import pytest

    from app.services.lecture_question_match import recent_transcript_segments

    now = datetime.now(UTC)

    assert recent_transcript_segments([], now, 10) == []
    assert recent_transcript_segments([], now, 20) == []

    with pytest.raises(ValueError):
        recent_transcript_segments([], now, 30)
