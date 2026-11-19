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
    assert checks.unsourced_numbers(draft, SOURCE) == []


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
