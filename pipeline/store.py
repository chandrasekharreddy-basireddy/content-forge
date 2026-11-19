"""Where runs go: SQLite first, Supabase if you configured it.

The rule for this file: the local database is the truth, and Supabase is a
copy. If Supabase is down, slow, or your key expired, the run is still saved
locally and the app carries on. A demo should not die on a network hiccup.

The same table shape exists in sql/schema.sql for Supabase, so Power BI can be
pointed at either one.
"""

import json
import sqlite3
from pathlib import Path

import requests

from . import config

COLUMNS = (
    "id, doc_name, created_at, status, words, chunks, outputs_count, "
    "avg_score, cost_inr, tokens_in, tokens_out, duration_ms, depth, payload"
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    doc_name      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL,
    words         INTEGER NOT NULL DEFAULT 0,
    chunks        INTEGER NOT NULL DEFAULT 0,
    outputs_count INTEGER NOT NULL DEFAULT 0,
    avg_score     REAL,
    cost_inr      REAL NOT NULL DEFAULT 0,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    depth         TEXT,
    payload       TEXT NOT NULL
)
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating the file and table if they are missing."""
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(CREATE_TABLE)
    connection.commit()
    return connection


def save_run(record: dict, db_path: Path | None = None, supabase: bool = True) -> bool:
    """Save one run locally, then try Supabase. Returns True if local save worked."""
    row = to_row(record)

    try:
        connection = connect(db_path)
        with connection:
            connection.execute(
                f"INSERT OR REPLACE INTO runs ({COLUMNS}) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row["doc_name"],
                    row["created_at"],
                    row["status"],
                    row["words"],
                    row["chunks"],
                    row["outputs_count"],
                    row["avg_score"],
                    row["cost_inr"],
                    row["tokens_in"],
                    row["tokens_out"],
                    row["duration_ms"],
                    row["depth"],
                    row["payload"],
                ),
            )
        connection.close()
    except sqlite3.Error:
        # A broken local database is a real problem, so report it to the caller.
        return False

    if supabase and config.SUPABASE_URL and config.SUPABASE_KEY:
        push_to_supabase(record)

    return True


def push_to_supabase(record: dict) -> bool:
    """Copy a run into Supabase. Returns False on any failure, never raises."""
    row = to_row(record)
    body = {key: row[key] for key in row if key != "payload"}
    body["payload"] = json.loads(row["payload"])

    try:
        response = requests.post(
            f"{config.SUPABASE_URL}/rest/v1/runs",
            headers={
                "apikey": config.SUPABASE_KEY,
                "Authorization": f"Bearer {config.SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            json=body,
            timeout=10,
        )
        return response.status_code in (200, 201, 204)
    except requests.RequestException:
        return False


def to_row(record: dict) -> dict:
    """Flatten a run record into the columns of the runs table.

    The full record goes into "payload" as JSON, so nothing is ever lost, and
    the scalar columns exist so that Power BI and SQL can group and average
    without parsing JSON.
    """
    scores = [
        item["score"]
        for item in record.get("outputs", {}).values()
        if isinstance(item.get("score"), int)
    ]
    return {
        "id": record.get("id", ""),
        "doc_name": record.get("doc_name", ""),
        "created_at": record.get("created_at", ""),
        "status": record.get("status", "unknown"),
        "words": int(record.get("words", 0)),
        "chunks": int(record.get("chunks", 0)),
        "outputs_count": len(record.get("outputs", {})),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "cost_inr": float(record.get("usage", {}).get("cost_inr", 0.0)),
        "tokens_in": int(record.get("usage", {}).get("prompt_tokens", 0)),
        "tokens_out": int(record.get("usage", {}).get("completion_tokens", 0)),
        "duration_ms": int(record.get("duration_ms", 0)),
        "depth": record.get("plan", {}).get("depth", ""),
        "payload": json.dumps(record, ensure_ascii=False),
    }


def list_runs(limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """The most recent runs, newest first, without the payload."""
    connection = connect(db_path)
    rows = connection.execute(
        "SELECT id, doc_name, created_at, status, words, outputs_count, avg_score, "
        "cost_inr, duration_ms, depth FROM runs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_run(run_id: str, db_path: Path | None = None) -> dict | None:
    """One full run, payload included, or None."""
    connection = connect(db_path)
    row = connection.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
    connection.close()
    if row is None:
        return None
    return json.loads(row["payload"])


def runs_as_csv(db_path: Path | None = None) -> str:
    """Every run as CSV text, ready for Power BI's Get Data > Text/CSV."""
    connection = connect(db_path)
    rows = connection.execute(
        "SELECT id, doc_name, created_at, status, words, chunks, outputs_count, "
        "avg_score, cost_inr, tokens_in, tokens_out, duration_ms, depth "
        "FROM runs ORDER BY created_at"
    ).fetchall()
    connection.close()

    headers = [
        "id",
        "doc_name",
        "created_at",
        "status",
        "words",
        "chunks",
        "outputs_count",
        "avg_score",
        "cost_inr",
        "tokens_in",
        "tokens_out",
        "duration_ms",
        "depth",
    ]
    lines = [",".join(headers)]
    for row in rows:
        values = []
        for key in headers:
            value = row[key]
            text = "" if value is None else str(value)
            if "," in text or '"' in text:
                text = '"' + text.replace('"', '""') + '"'
            values.append(text)
        lines.append(",".join(values))
    return "\n".join(lines) + "\n"


def stats(db_path: Path | None = None) -> dict:
    """The four numbers the landing page and the app header show."""
    connection = connect(db_path)
    row = connection.execute(
        "SELECT COUNT(*) AS runs, COALESCE(SUM(outputs_count),0) AS outputs, "
        "COALESCE(AVG(avg_score),0) AS score, COALESCE(SUM(cost_inr),0) AS cost FROM runs"
    ).fetchone()
    connection.close()
    return {
        "runs": row["runs"],
        "outputs": row["outputs"],
        "avg_score": round(row["score"], 2),
        "cost_inr": round(row["cost"], 4),
    }
