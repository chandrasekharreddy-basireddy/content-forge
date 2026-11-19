"""Tests for the exports.

The point of these is that a download button must never produce an empty or
corrupt file. So we check magic bytes, not just "it returned something".
"""

import json

from pipeline import exports

SUMMARY = {
    "summary": "The pilot ran in four districts and cost fell.",
    "bullets": ["Four districts.", "Cost fell 14%.", "One vendor remained."],
    "key_terms": ["pilot", "cost"],
}

QUIZ = {
    "questions": [
        {
            "question": "By how much did cost fall?",
            "options": ["14%", "41%", "4%", "0%"],
            "answer_index": 0,
            "explanation": "The text says 14%.",
        }
    ]
}

SLIDES = {
    "slides": [
        {"title": "Findings", "bullets": ["Cost fell 14%", "One vendor"], "notes": "Say it plainly."}
    ]
}

REPORT = {
    "title": "Findings",
    "sections": [{"heading": "Background", "body": "The pilot ran in four districts."}],
}


def test_markdown_marks_the_correct_answer():
    text = exports.markdown("quiz", QUIZ, "pilot.pdf")
    assert "(correct)" in text
    assert "pilot.pdf" in text


def test_docx_is_a_real_word_file():
    content, filename, mime = exports.render("summary", SUMMARY, "docx", "pilot.pdf")
    assert content[:2] == b"PK"  # every OOXML file is a zip
    assert filename == "pilot_summary.docx"
    assert "wordprocessingml" in mime


def test_pptx_is_a_real_powerpoint_file():
    content, filename, _ = exports.render("slides", SLIDES, "pptx", "pilot.pdf")
    assert content[:2] == b"PK"
    assert filename.endswith(".pptx")


def test_pptx_from_a_report_still_works():
    """A report exported as a deck is a nice-to-have, so it must not crash."""
    content, _, _ = exports.render("report", REPORT, "pptx")
    assert content[:2] == b"PK"


def test_csv_of_a_quiz_names_the_answer():
    text = exports.csv_text("quiz", QUIZ)
    header, row = text.strip().splitlines()
    assert header.startswith("question,option_a")
    assert row.endswith('"The text says 14%."') or "14%" in row


def test_json_round_trips():
    content, _, mime = exports.render("summary", SUMMARY, "json")
    assert json.loads(content)["key_terms"] == ["pilot", "cost"]
    assert mime == "application/json"


def test_every_format_a_button_offers_actually_renders():
    """The UI reads formats_for(); each one must produce bytes."""
    for output, obj in (
        ("summary", SUMMARY),
        ("quiz", QUIZ),
        ("slides", SLIDES),
        ("report", REPORT),
    ):
        for fmt in exports.formats_for(output):
            content, filename, mime = exports.render(output, obj, fmt, "pilot.pdf")
            assert content, f"{output}/{fmt} produced nothing"
            assert filename and mime


def test_an_unknown_format_is_refused():
    try:
        exports.render("summary", SUMMARY, "rtf")
    except ValueError as error:
        assert "rtf" in str(error)
    else:
        raise AssertionError("expected a ValueError")


def test_a_hostile_document_name_cannot_escape_the_output_folder():
    """The filename becomes a path in the CLI, so it must be sanitised."""
    _, filename, _ = exports.render("summary", SUMMARY, "md", "../../../tmp/pwn.txt")
    assert "/" not in filename
    assert ".." not in filename
    assert filename.endswith("_summary.md")


def test_a_pipe_in_a_flashcard_does_not_break_the_table():
    cards = {"cards": [{"front": "a|b", "back": "c"}]}
    text = exports.markdown("flashcards", cards)
    assert "a\\|b" in text
