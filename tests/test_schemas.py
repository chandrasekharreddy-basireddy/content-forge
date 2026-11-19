"""Tests for the output contracts.

The validator is the safety net under the whole pipeline, so it gets tested
against the mistakes a model actually makes: three options instead of four,
an answer index that points at nothing, an empty bullet.
"""

from pipeline import schemas


def good_summary():
    return {
        "summary": "A short account of the pilot.",
        "bullets": ["It ran in four districts.", "Cost fell 14%.", "One vendor left."],
        "key_terms": ["pilot", "cost"],
    }


def good_quiz():
    return {
        "questions": [
            {
                "question": "By how much did cost fall?",
                "options": ["14%", "41%", "4%", "0%"],
                "answer_index": 0,
                "explanation": "The text says 14%.",
            }
        ]
    }


def test_a_good_summary_validates():
    ok, problems = schemas.validate("summary", good_summary())
    assert ok, problems


def test_missing_key_is_named():
    payload = good_summary()
    del payload["key_terms"]
    ok, problems = schemas.validate("summary", payload)
    assert not ok
    assert "key_terms" in " ".join(problems)


def test_too_few_bullets_is_a_problem():
    payload = good_summary()
    payload["bullets"] = ["Only one."]
    ok, problems = schemas.validate("summary", payload)
    assert not ok
    assert "at least 3" in " ".join(problems)


def test_empty_bullet_is_a_problem():
    payload = good_summary()
    payload["bullets"] = ["Fine.", "  ", "Also fine."]
    ok, problems = schemas.validate("summary", payload)
    assert not ok


def test_quiz_with_three_options_is_rejected():
    payload = good_quiz()
    payload["questions"][0]["options"] = ["14%", "41%", "4%"]
    ok, problems = schemas.validate("quiz", payload)
    assert not ok
    assert "exactly 4" in " ".join(problems)


def test_quiz_answer_index_out_of_range_is_rejected():
    payload = good_quiz()
    payload["questions"][0]["answer_index"] = 9
    ok, problems = schemas.validate("quiz", payload)
    assert not ok
    assert "out of range" in " ".join(problems)


def test_quiz_answer_index_must_be_an_integer():
    payload = good_quiz()
    payload["questions"][0]["answer_index"] = "0"
    ok, problems = schemas.validate("quiz", payload)
    assert not ok
    assert "integer" in " ".join(problems)


def test_not_an_object_is_rejected_without_raising():
    ok, problems = schemas.validate("summary", ["not", "a", "dict"])
    assert not ok
    assert "expected a JSON object" in problems[0]


def test_unknown_output_name_says_what_is_known():
    try:
        schemas.spec("podcast")
    except KeyError as error:
        assert "summary" in str(error)
    else:
        raise AssertionError("expected a KeyError")


def test_every_writable_output_has_a_json_schema():
    """A writer with no schema would be sending response_format=None."""
    for name in ("summary", "quiz", "flashcards", "report", "slides"):
        assert schemas.json_schema(name) is not None
    # Translation comes from the /translate endpoint, so it has none.
    assert schemas.json_schema("translation") is None


def test_flashcards_and_slides_validate():
    cards = {"cards": [{"front": "Q", "back": "A"}, {"front": "Q2", "back": "A2"}]}
    assert schemas.validate("flashcards", cards)[0]

    slides = {
        "slides": [
            {"title": "One", "bullets": ["a", "b"], "notes": "n"},
            {"title": "Two", "bullets": ["c", "d"], "notes": "n"},
        ]
    }
    assert schemas.validate("slides", slides)[0]


def test_a_slide_with_one_bullet_is_flagged():
    slides = {"slides": [{"title": "One", "bullets": ["only"], "notes": "n"}]}
    ok, problems = schemas.validate("slides", slides)
    assert not ok
    assert "at least 2" in " ".join(problems)
