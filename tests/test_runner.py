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
    assert summary["rounds"] <= 2


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
