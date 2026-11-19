"""Tests for the deterministic grounding check.

This is the part of the critic that is not a model: every number in a draft is
looked up in the source, and one that is missing overrides the score. It exists
because a measured run found an invented figure and still scored the draft 4/5.
"""

from pipeline import agents, checks, config


def long_summary(text: str) -> dict:
    """A summary of realistic length, so the length check does not fire.

    The other tests here are about numbers; a four-word summary would trip the
    separate shape rule and hide what they are testing.
    """
    padding = " The report sets this out in its opening section. " * 12
    return {"summary": text + padding, "bullets": ["one", "two", "three"]}


SOURCE = (
    "By October 2026, India's solar capacity reached 174.55 GW AC. "
    "The Bhadla park holds 2,245 MW. Cost fell by 14% in 2025."
)


def test_numbers_are_found_and_normalised():
    assert "2245" in checks.numbers_in("a capacity of 2,245 MW")
    assert "174.55" in checks.numbers_in("174.55 GW")
    assert "14" in checks.numbers_in("fell 14%")


def test_a_number_in_the_source_is_not_a_defect():
    draft = long_summary("Capacity reached 174.55 GW in October 2026.")
    source = "Project 1 is the Academia-Industry Skill Mapping and Placement Portal."
    assert checks.unsourced_numbers(draft, source) == []


def test_an_invented_number_is_named():
    draft = long_summary("Capacity reached 974.55 GW in October 2026.")
    missing = checks.unsourced_numbers(draft, SOURCE)
    assert "974.55" in missing


def test_a_number_only_in_the_keys_is_not_searched():
    """Keys are structure, not content: a key like 'option_2' is not a claim."""
    draft = {"question_3": "What is the capacity?", "answer": "174.55 GW"}
    assert checks.unsourced_numbers(draft, SOURCE) == []


def test_defect_line_quotes_the_value():
    draft = long_summary("It fell 42% in 2024.")
    lines = checks.grounding_defects(draft, SOURCE)
    assert lines and "42" in lines[0]
    assert "does not appear" in lines[0]


def test_the_check_overrides_a_generous_score(monkeypatch):
    """The critic says 5; the code says no."""
    monkeypatch.setattr(config, "GROUNDING_CHECK", True)

    def generous(messages, **kwargs):
        return (
            '{"score": 5, "verdict": "pass", "defects": [], "reason": "fine"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    verdict, _ = agents.critique(
        "summary", long_summary("Capacity reached 974.55 GW."), SOURCE, call=generous
    )
    assert verdict["score"] == 2
    assert verdict["verdict"] == "revise"
    assert verdict["defects"]


def test_a_grounded_draft_keeps_its_score(monkeypatch):
    monkeypatch.setattr(config, "GROUNDING_CHECK", True)

    def generous(messages, **kwargs):
        return (
            '{"score": 5, "verdict": "pass", "defects": [], "reason": "fine"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    verdict, _ = agents.critique(
        "summary", long_summary("Capacity reached 174.55 GW."), SOURCE, call=generous
    )
    assert verdict["score"] == 5
    assert verdict["defects"] == []


def test_the_switch_can_turn_it_off(monkeypatch):
    monkeypatch.setattr(config, "GROUNDING_CHECK", False)

    def generous(messages, **kwargs):
        return (
            '{"score": 5, "verdict": "pass", "defects": [], "reason": "fine"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    verdict, _ = agents.critique(
        "summary", long_summary("Capacity reached 974.55 GW."), SOURCE, call=generous
    )
    assert verdict["score"] == 5


def test_a_figure_the_critic_already_named_is_not_repeated(monkeypatch):
    """One problem should read as one defect, not two."""
    monkeypatch.setattr(config, "GROUNDING_CHECK", True)

    def critic(messages, **kwargs):
        return (
            '{"score": 3, "verdict": "revise", "defects": [{"quote": "974.55 GWAC",'
            ' "problem": "the source says 174.55 GWAC"}], "reason": "wrong figure"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    verdict, _ = agents.critique(
        "summary", long_summary("Capacity reached 974.55 GW."), SOURCE, call=critic
    )
    assert len(verdict["defects"]) == 1
    assert "does not appear" not in verdict["defects"][0]
    assert verdict["score"] == 2  # the cap still applies


def test_a_figure_the_critic_missed_is_added(monkeypatch):
    monkeypatch.setattr(config, "GROUNDING_CHECK", True)

    def critic(messages, **kwargs):
        return (
            '{"score": 5, "verdict": "pass", "defects": [], "reason": "fine"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    verdict, _ = agents.critique(
        "summary", long_summary("Capacity reached 974.55 GW."), SOURCE, call=critic
    )
    assert len(verdict["defects"]) == 1
    assert "does not appear" in verdict["defects"][0]


def test_a_summary_that_is_a_numeric_dump_is_a_defect():
    """Measured case: 320 words of figures passed the critic at 4/5."""
    draft = {"summary": "word " * 320, "bullets": ["a", "b", "c"]}
    defects = checks.length_defects("summary", draft)
    assert defects and "320 words" in defects[0]


def test_a_summary_in_range_is_fine():
    draft = {"summary": "word " * 150, "bullets": ["a"] * 5}
    assert checks.length_defects("summary", draft) == []


def test_too_many_bullets_is_a_defect():
    draft = {"summary": "word " * 150, "bullets": ["a"] * 12}
    defects = checks.length_defects("summary", draft)
    assert any("bullets" in defect for defect in defects)


def test_the_shape_check_caps_the_score(monkeypatch):
    monkeypatch.setattr(config, "GROUNDING_CHECK", True)

    def generous(messages, **kwargs):
        return (
            '{"score": 5, "verdict": "pass", "defects": [], "reason": "fine"}',
            {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1, "cost_inr": 0},
        )

    draft = {"summary": "174.55 " * 320, "bullets": ["a", "b", "c"]}
    verdict, _ = agents.critique("summary", draft, SOURCE, call=generous)
    assert verdict["score"] <= 3
    assert any("words" in defect for defect in verdict["defects"])


def test_a_magnitude_suffix_matches_the_expanded_figure():
    """A measured run flagged 78000 and 96000 as invented because the source
    wrote them 78K and 96K. Rounding to a magnitude is summarising, not lying."""
    source = "Revenue 2.90M across 96K trips, 78K of them by card."
    draft = {"summary": "Revenue 2,899,158.52 across 96000 trips, 78000 by card."}
    assert checks.unsourced_numbers(draft, source) == []


def test_a_changed_year_is_still_caught():
    """Tolerance must not swallow 2006 for 2026 - that is the error a reader sees."""
    source = "Trip records for January 02, 2026 are in the appendix."
    draft = {"summary": "Trip records for January 02, 2006 are in the appendix."}
    assert "2006" in checks.unsourced_numbers(draft, source)


def test_a_plain_small_number_must_appear_exactly():
    assert checks.unsourced_numbers({"s": "it fell 4 points"}, "it fell 4.04 points") == ["4"]


def test_a_list_summary_may_run_longer():
    """Ten items need ten bullets and more words; that is not a dump."""
    draft = {"summary": "word " * 280, "bullets": ["item"] * 10}
    assert checks.length_defects("summary", draft) == []


def test_eleven_bullets_is_still_too_many():
    draft = {"summary": "word " * 150, "bullets": ["item"] * 11}
    assert any("bullets" in defect for defect in checks.length_defects("summary", draft))


def test_a_quiz_answer_index_is_not_treated_as_a_claim():
    """`"answer_index": 0` is a position, not a number in the source."""
    draft = {
        "questions": [
            {
                "question": "What is Project 1 called?",
                "options": ["Portal", "Assistant", "Platform", "Engine"],
                "answer_index": 0,
                "explanation": "The source names the portal first.",
            }
        ]
    }
    assert checks.unsourced_numbers(draft, SOURCE) == []


def test_a_one_question_quiz_is_a_defect():
    draft = {"questions": [{"question": "q", "options": ["a", "b", "c", "d"],
                            "answer_index": 0, "explanation": "e"}]}
    assert any("at least three" in defect for defect in checks.length_defects("quiz", draft))


def test_twenty_flashcards_is_a_defect():
    draft = {"cards": [{"front": f"f{i}", "back": f"b{i}"} for i in range(20)]}
    assert any("cut it to eight" in defect for defect in checks.length_defects("flashcards", draft))
