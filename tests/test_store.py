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
    """With no Supabase settings, saving must not attempt a network call."""
    monkeypatch.setattr(store.config, "SUPABASE_URL", "")
    monkeypatch.setattr(store.config, "SUPABASE_KEY", "")
    assert store.save_run(sample_record(), db_path=temp_db) is True


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
