"""Tests for the run store: local SQLite, and the CSV that feeds Power BI."""

from pipeline import store


def sample_record(run_id="abc123"):
    return {
        "id": run_id,
        "doc_name": "pilot.pdf",
        "created_at": "2026-11-19T09:00:00+00:00",
        "status": "ok",
        "words": 1200,
        "chunks": 3,
        "plan": {"outputs": ["summary", "quiz"], "depth": "standard", "reason": "r"},
        "outputs": {
            "summary": {"object": {"summary": "s"}, "score": 5, "status": "ok"},
            "quiz": {"object": {"questions": []}, "score": 3, "status": "flagged"},
        },
        "translation": None,
        "trace": [],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "cost_inr": 0.0125, "calls": 4},
        "duration_ms": 4200,
    }


def test_a_run_is_saved_and_read_back(temp_db):
    record = sample_record()
    assert store.save_run(record, db_path=temp_db) is True

    fetched = store.get_run("abc123", db_path=temp_db)
    assert fetched["doc_name"] == "pilot.pdf"
    assert fetched["outputs"]["summary"]["score"] == 5


def test_scalar_columns_are_derived_from_the_record(temp_db):
    """The columns Power BI reads are computed here, not in the dashboard."""
    store.save_run(sample_record(), db_path=temp_db)
    row = store.list_runs(db_path=temp_db)[0]
    assert row["outputs_count"] == 2
    assert row["avg_score"] == 4.0  # (5 + 3) / 2
    assert row["cost_inr"] == 0.0125
    assert row["depth"] == "standard"


def test_saving_twice_updates_rather_than_duplicates(temp_db):
    store.save_run(sample_record(), db_path=temp_db)
    changed = sample_record()
    changed["status"] = "partial"
    store.save_run(changed, db_path=temp_db)
    runs = store.list_runs(db_path=temp_db)
    assert len(runs) == 1
    assert runs[0]["status"] == "partial"


def test_the_csv_has_a_header_and_a_row_per_run(temp_db):
    store.save_run(sample_record("one"), db_path=temp_db)
    store.save_run(sample_record("two"), db_path=temp_db)
    csv_text = store.runs_as_csv(db_path=temp_db)
    lines = [line for line in csv_text.strip().splitlines() if line]
    assert lines[0].startswith("id,doc_name,created_at,status")
    assert len(lines) == 3


def test_a_document_name_with_a_comma_is_quoted(temp_db):
    """Power BI splits on commas, so the CSV must quote them."""
    record = sample_record()
    record["doc_name"] = "annual report, 2025.pdf"
    store.save_run(record, db_path=temp_db)
    csv_text = store.runs_as_csv(db_path=temp_db)
    assert '"annual report, 2025.pdf"' in csv_text


def test_stats_add_up(temp_db):
    store.save_run(sample_record("one"), db_path=temp_db)
    store.save_run(sample_record("two"), db_path=temp_db)
    summary = store.stats(db_path=temp_db)
    assert summary["runs"] == 2
    assert summary["outputs"] == 4
    assert summary["avg_score"] == 4.0


def test_supabase_is_skipped_when_not_configured(temp_db, monkeypatch):
    """With no Supabase settings, saving must not attempt a network call.

    Asserting the absence of the call, not the return value: save_run returns
    True either way, so a return-value assertion cannot see a missing guard.
    """
    monkeypatch.setattr(store.config, "SUPABASE_URL", "")
    monkeypatch.setattr(store.config, "SUPABASE_KEY", "")
    calls = []
    monkeypatch.setattr(store.requests, "post", lambda *a, **k: calls.append(a))

    assert store.save_run(sample_record(), db_path=temp_db) is True
    assert calls == []


def test_a_configured_supabase_is_attempted(temp_db, monkeypatch):
    monkeypatch.setattr(store.config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(store.config, "SUPABASE_KEY", "key")
    calls = []

    class Response:
        status_code = 201

    monkeypatch.setattr(store.requests, "post", lambda *a, **k: calls.append(a) or Response())
    assert store.save_run(sample_record(), db_path=temp_db) is True
    assert len(calls) == 1


def test_a_public_demo_run_keeps_scalars_only(temp_db):
    """A stranger's pasted text must not be stored as a payload."""
    record = sample_record()
    record["doc_name"] = "web-demo.txt"
    store.save_run(record, db_path=temp_db, supabase=False, keep_payload=False)
    fetched = store.get_run("abc123", db_path=temp_db)
    assert "outputs" not in fetched
    assert fetched["status"] == record["status"]


def test_a_csv_cell_starting_with_an_equals_sign_is_neutralised(temp_db):
    """Otherwise a filename becomes a formula in Excel and Power BI."""
    record = sample_record()
    record["doc_name"] = "=cmd|' /C calc'!A0.pdf"
    store.save_run(record, db_path=temp_db)
    csv_text = store.runs_as_csv(db_path=temp_db)
    assert "'=cmd" in csv_text
    assert ",=cmd" not in csv_text


def test_a_dead_supabase_does_not_lose_the_run(temp_db, monkeypatch):
    """The local save is the truth; a network failure must not change that."""
    monkeypatch.setattr(store.config, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(store.config, "SUPABASE_KEY", "key")

    import requests

    def explode(*args, **kwargs):
        raise requests.RequestException("no route to host")

    monkeypatch.setattr(store.requests, "post", explode)
    assert store.save_run(sample_record(), db_path=temp_db) is True
    assert store.get_run("abc123", db_path=temp_db) is not None


def test_configured_paths_are_always_absolute(monkeypatch):
    """A relative OUTPUT_DIR in .env must not break a run from another folder."""
    from pipeline import config

    monkeypatch.setenv("OUTPUT_DIR", "outputs")
    monkeypatch.setenv("DB_PATH", "data/runs.db")
    assert config._path("OUTPUT_DIR", "unused").is_absolute()
    assert config._path("DB_PATH", "unused").is_absolute()
    assert config._path("OUTPUT_DIR", "unused") == config.ROOT / "outputs"


def test_the_cli_paths_can_be_printed_relative_to_the_project():
    """The crash a Windows run hit: relative_to() on a relative path."""
    from pipeline import config

    assert config.OUTPUT_DIR.is_relative_to(config.ROOT)
    assert config.DB_PATH.is_relative_to(config.ROOT)


def test_env_file_wins_over_a_stale_shell_variable(tmp_path, monkeypatch):
    """A SARVAM_API_KEY left in a shell session must not shadow .env.

    python-dotenv defaults to the opposite, which made a replaced key look
    unchanged: you edit the file, the app keeps sending the old value.
    """
    import os

    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("SARVAM_API_KEY=sk_from_the_file\n", encoding="utf-8")

    monkeypatch.setenv("SARVAM_API_KEY", "sk_from_the_shell")
    load_dotenv(env_file, override=True)
    assert os.environ["SARVAM_API_KEY"] == "sk_from_the_file"
