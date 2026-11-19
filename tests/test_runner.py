"""Tests for the agentic workflow.

These are the important ones. They prove, without an API key and without a
network, that:

  - the critic loop actually fires and actually stops
  - a draft below the bar is repaired, not shipped silently
  - one broken output does not take the other outputs down with it
  - the trace records what happened, so the claim is checkable
"""

import pytest
from fakes import FakeModel, FakeTranslator

from pipeline import runner


def run_once(text, scores=(3, 5), outputs=None, translate_to=None, **kwargs):
    model = FakeModel(scores=list(scores), **kwargs)
    translator = FakeTranslator()
    record = runner.run(
        doc_name="pilot.txt",
        text=text,
        outputs=outputs,
        translate_to=translate_to,
        call=model,
        translate_fn=translator,
    )
    return record, model, translator


def test_a_full_run_produces_every_output(sample_text):
    record, model, _ = run_once(sample_text, outputs=["summary", "quiz"])
    assert record["status"] == "ok"
    assert set(record["outputs"]) == {"summary", "quiz"}
    assert record["outputs"]["summary"]["object"]["summary"]
    assert model.calls  # the model was actually asked


def test_the_critic_loop_fires_and_then_stops(sample_text):
    """Score 3 forces one repair; the next 5 ends it. Two writes, one repair."""
    record, _, _ = run_once(sample_text, scores=[3, 5], outputs=["summary"])
    summary = record["outputs"]["summary"]
    assert summary["rounds"] == 1
    assert summary["score"] == 5
    assert summary["status"] == "ok"

    critiques = [
        row for row in record["trace"]
        if row["step"] == "summary" and row["note"].startswith("score")
    ]
    assert len(critiques) == 2  # one critique per draft: the rejected one, then the accepted one
    repairs = [
        row for row in record["trace"]
        if row["step"] == "summary" and row["note"].startswith("round")
    ]
    assert len(repairs) == 1  # exactly one trip back to the writer


def test_repairs_stop_at_the_limit_and_the_result_is_flagged(sample_text):
    """Always-failing drafts stop after MAX_REPAIRS and are labelled, not hidden."""
    record, _, _ = run_once(sample_text, scores=[2, 2, 2, 2, 2], outputs=["summary"])
    summary = record["outputs"]["summary"]
    assert summary["status"] == "flagged"
    assert summary["error"]
    assert summary["object"] is not None  # we still ship the best draft
    # Exact, not <=: an off-by-one in the budget must fail here.
    from pipeline import config

    assert summary["rounds"] == config.MAX_REPAIRS
    writes = [
        row for row in record["trace"]
        if row["step"] == "summary" and row["note"] in ("first draft", "round 1", "round 2")
    ]
    assert len(writes) == config.MAX_REPAIRS + 1


def test_a_failing_output_does_not_kill_the_run(sample_text):
    """The quiz writer explodes; the summary still arrives. Status is partial."""
    record, _, _ = run_once(
        sample_text, outputs=["summary", "quiz"], fail_outputs=("quiz",)
    )
    assert record["outputs"]["summary"]["status"] == "ok"
    assert record["outputs"]["quiz"]["status"] == "failed"
    assert record["status"] == "partial"


def test_translation_runs_and_is_stored(sample_text):
    record, _, translator = run_once(
        sample_text, outputs=["summary"], translate_to="hi-IN"
    )
    assert record["translation"]["status"] == "ok"
    assert record["translation"]["language"] == "hi-IN"
    assert record["translation"]["text"].startswith("[hi-IN]")
    assert translator.calls[0]["target"] == "hi-IN"


def test_a_failed_translation_is_reported_not_raised(sample_text):
    """A dead translate endpoint must not lose the outputs we already have."""

    def broken_translate(text, target_language="hi-IN", **kwargs):
        raise RuntimeError("translate endpoint down")

    model = FakeModel(scores=[5])
    record = runner.run(
        doc_name="pilot.txt",
        text=sample_text,
        outputs=["summary"],
        translate_to="ta-IN",
        call=model,
        translate_fn=broken_translate,
    )
    assert record["outputs"]["summary"]["status"] == "ok"
    assert record["translation"]["status"] == "failed"
    assert "down" in record["translation"]["error"]


def test_the_trace_explains_the_run(sample_text):
    """Every step leaves a row with a model, a duration and a note."""
    record, _, _ = run_once(sample_text, outputs=["summary"])
    steps = [row["step"] for row in record["trace"]]
    assert any(step.startswith("extract") for step in steps)
    assert "plan" in steps
    for row in record["trace"]:
        assert {"step", "model", "ms", "tokens_in", "tokens_out", "note"} <= set(row)
        assert row["note"]


def test_cost_and_tokens_are_added_up(sample_text):
    record, _, _ = run_once(sample_text, outputs=["summary", "quiz"])
    usage = record["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["cost_inr"] > 0
    assert usage["calls"] == len([r for r in record["trace"] if r["model"] not in ("-", "")])


def test_a_planner_failure_falls_back_to_all_outputs(sample_text, monkeypatch):
    """If the planner returns nonsense, the run still produces everything."""
    model = FakeModel(scores=[5])

    def bad_planner(messages, **kwargs):
        if "You are the planner" in messages[0]["content"]:
            return "I cannot help with that.", {"model": "fake", "prompt_tokens": 1,
                                                "completion_tokens": 1, "cost_inr": 0}
        return model(messages, **kwargs)

    record = runner.run("pilot.txt", sample_text, call=bad_planner,
                        translate_fn=FakeTranslator())
    assert record["plan"]["outputs"] == ["summary", "quiz", "flashcards", "report", "slides"]
    assert "fallback" in " ".join(row["note"] for row in record["trace"])


def test_a_critic_failure_ships_the_draft_as_unverified(sample_text):
    """No critic is not the same as a bad draft: say 'unverified', not 'failed'."""
    model = FakeModel(scores=[5])

    def no_critic(messages, **kwargs):
        if "You are the critic" in messages[0]["content"]:
            raise RuntimeError("critic is down")
        return model(messages, **kwargs)

    record = runner.run("pilot.txt", sample_text, outputs=["summary"], call=no_critic)
    assert record["outputs"]["summary"]["status"] == "unverified"
    assert record["outputs"]["summary"]["object"] is not None


def test_empty_text_is_refused():
    with pytest.raises(ValueError):
        runner.run("empty.txt", "   ", outputs=["summary"], call=FakeModel())


def test_the_writer_sees_the_facts_first():
    """Context puts evidence before raw text, so truncation keeps the facts."""
    context = runner.build_context(["RAW " * 500], ["A fact."], ["14%"])
    assert context.index("FACTS FROM THE DOCUMENT") < context.index("SOURCE TEXT")
    assert len(context) <= runner.MAX_CONTEXT_CHARS


def test_a_short_document_costs_one_extract_call(sample_text):
    """3,000 words must not become twenty model calls: groups, not chunks."""
    groups = runner.group_chunks(["x" * 1000] * 3)
    assert len(groups) == 1
    assert len(groups[0]) == 1000 * 3 + 4  # joined with a blank line


def test_a_long_document_is_capped_but_still_covered():
    """Twenty chunks become at most six calls, sampled across the document."""
    chunks = [f"part{index} " + "y" * 1000 for index in range(20)]
    groups = runner.group_chunks(chunks)
    assert len(groups) <= 6
    assert "part0" in groups[0]
    assert "part19" in groups[-1]  # the end is represented, not truncated away


def test_a_long_document_does_not_lose_its_first_and_last_chunk():
    chunks = [f"chunk-{index}" for index in range(50)]
    groups = runner.group_chunks(chunks, window=20, max_groups=3)
    joined = " ".join(groups)
    assert "chunk-0" in joined
    assert "chunk-49" in joined


def test_a_wrongly_shaped_draft_is_rejected_by_our_validator(sample_text):
    """The schema check runs before the critic, and says so in the trace."""
    from fakes import FakeModel, FakeTranslator

    model = FakeModel(scores=[5, 5, 5], mode="schema_invalid")
    record = runner.run(
        "pilot.txt", sample_text, outputs=["summary"], call=model,
        translate_fn=FakeTranslator(),
    )
    summary = record["outputs"]["summary"]
    assert summary["status"] == "flagged"
    assert any("invalid shape" in row["note"] for row in record["trace"])
    # The repair must be told what was wrong, not just "try again".
    assert "bullets" in model.last_user


def test_prose_instead_of_json_is_a_failed_output_not_a_crash(sample_text):
    from fakes import FakeModel, FakeTranslator

    model = FakeModel(mode="invalid_json")
    record = runner.run(
        "pilot.txt", sample_text, outputs=["summary"], call=model,
        translate_fn=FakeTranslator(),
    )
    assert record["outputs"]["summary"]["status"] == "failed"
    assert record["status"] == "failed"


def test_a_run_that_shipped_only_flagged_outputs_is_partial_not_failed(sample_text):
    """A flagged draft is still usable content; calling the run failed is wrong."""
    record, _, _ = run_once(sample_text, scores=[1] * 10, outputs=["summary"])
    assert record["outputs"]["summary"]["status"] == "flagged"
    assert record["status"] == "partial"


def test_structured_defects_become_readable_lines():
    """The critic returns {quote, problem}; the record keeps readable strings."""
    from pipeline.agents import _read_defects

    raw = [
        {"quote": "974.55 GWAC", "problem": "the source says 174.55 GWAC"},
        {"quote": "", "problem": "the summary misses the document's main claim"},
        "legacy string defect",
    ]
    lines = _read_defects(raw)
    assert lines[0] == '"974.55 GWAC" - the source says 174.55 GWAC'
    assert lines[1] == "the summary misses the document's main claim"
    assert lines[2] == "legacy string defect"
    assert _read_defects([]) == []
    assert _read_defects(None) == []
