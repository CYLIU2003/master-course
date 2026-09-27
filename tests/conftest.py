from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def admitted_gurobi_session():
    """Native regressions must reuse an explicitly admitted shared session."""
    from src.gurobi_session import current_session
    session = current_session()
    if session is None:
        pytest.skip("Native regression requires shared license admission")
    from src.gurobi_runtime import is_gurobi_available
    if not is_gurobi_available():
        pytest.skip("Gurobi unavailable in admitted session")
    return session
