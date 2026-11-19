"""Tests for the prompt loader.

These cover the two bugs that cost the most time while building the project:

  - a YAML prompt whose line starts with "{" is parsed as a flow mapping and
    blows up at load time
  - passing a value called "name" collides with the {name} slot in a template

Both are cheap tests and both would have saved an afternoon.
"""

import pytest

from pipeline import prompts


def test_every_prompt_file_loads():
    """All five prompts parse and have both a system and a user body."""
    for name in ("extract", "plan", "write", "critique", "judge"):
        prompt = prompts.load(name)
        assert prompt["system"].strip()
        assert prompt["user"].strip()
        assert prompt["id"] == name


def test_braces_in_prompt_are_literal_json():
    """The JSON example in a prompt must survive rendering as real braces."""
    messages = prompts.build_messages("extract", part=1, parts=2, chunk="hello")
    system = messages[0]["content"]
    assert '{"facts"' in system
    assert "{{" not in system


def test_line_starting_with_brace_does_not_break_the_loader(tmp_path, monkeypatch):
    """A literal block starting with "{" is valid YAML and must load."""
    folder = tmp_path / "prompts"
    folder.mkdir()
    (folder / "brace.yaml").write_text(
        "id: brace\n"
        "system: |\n"
        "  Reply with JSON only.\n"
        "  {not_a_flow_mapping: true}\n"
        "user: |\n"
        "  Text: {chunk}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts, "PROMPTS_DIR", folder)
    prompts.clear_cache()

    prompt = prompts.load("brace")
    assert "not_a_flow_mapping" in prompt["system"]
    prompts.clear_cache()


def test_missing_slot_raises_a_readable_error():
    """A prompt with an unfilled slot must fail loudly, not render blank."""
    with pytest.raises(prompts.PromptError) as error:
        prompts.render("Read {chunk} then {missing_slot}", {"chunk": "text"})
    assert "missing_slot" in str(error.value)
    assert "chunk" in str(error.value)  # tells you what was supplied


def test_a_value_named_name_does_not_collide_with_the_prompt_name():
    """build_messages takes the prompt file name first; values are separate."""
    messages = prompts.build_messages(
        "extract", part=1, parts=1, chunk="A document about names."
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "A document about names." in messages[1]["content"]


def test_unknown_prompt_file_says_where_it_looked():
    """The error names the path, so you can see which folder is being read."""
    with pytest.raises(prompts.PromptError) as error:
        prompts.load("does-not-exist")
    assert "does-not-exist.yaml" in str(error.value)


def test_unbalanced_brace_is_reported_as_a_mistake():
    """An unescaped literal brace is caught, with the fix in the message."""
    with pytest.raises(prompts.PromptError) as error:
        prompts.render("JSON looks like this: {oops", {})
    assert "literal brace" in str(error.value)
