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
