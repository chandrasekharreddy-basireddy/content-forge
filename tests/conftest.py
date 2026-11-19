"""Shared test setup.

Two things happen here:

1. The project root and the tests folder go on sys.path, so `import pipeline`
   and `from fakes import FakeModel` both work however pytest is invoked.
2. Every test that touches storage gets a temporary database, so a test run
   never writes into your real data/runs.db.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "evals"))  # rouge.py lives with the harness

from pipeline import config  # noqa: E402


@pytest.fixture(autouse=True)
def pin_config(monkeypatch):
    """Pin the behaviour constants for every test.

    config.py loads .env at import, so without this a developer's own settings
    (PASS_SCORE=5, MAX_REPAIRS=5) change what the tests assert. The suite must
    give the same answer on a fresh clone and on a configured machine.
    """
    for name, value in {
        "PASS_SCORE": 4.0,
        "MAX_REPAIRS": 2,
        "EXTRACT_WINDOW": 6000,
        "MAX_EXTRACT_CALLS": 6,
        "CHUNK_SIZE": 1200,
        "CHUNK_OVERLAP": 150,
        "TRANSLATE_CHUNK": 900,
        "MAX_UPLOAD_BYTES": 10 * 1024 * 1024,
        # The fake model writes numbers the fixture text does not contain, so
        # the grounding check is pinned off here and tested on its own.
        "GROUNDING_CHECK": False,
    }.items():
        monkeypatch.setattr(config, name, value)


@pytest.fixture
def temp_db(tmp_path):
    """A throwaway SQLite file, one per test."""
    return tmp_path / "runs.db"


@pytest.fixture
def sample_text():
    """About 1,200 words of dull but factual prose, used across the tests."""
    paragraph = (
        "The pilot programme ran across four districts between January and "
        "December 2025. Cost per learner fell by 14% in the second half of the "
        "year, mainly because two vendors were consolidated into one. "
    )
    return ("\n\n".join([paragraph * 3] * 4)).strip()
