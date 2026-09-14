"""Audit actual saved search controls independently of the engine projection."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "monthly_native_audit", Path(__file__).resolve().parents[1]
    / "output/monthly_fair_weeks_20260914/audit_budget_week.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
EXPECTED = {"stage2_gurobi_mip_focus": 1, "stage2_gurobi_method": 1}


def test_complete_original_metadata_is_valid_when_projection_omits_controls():
    document = {"metadata": dict(EXPECTED), "solver_metadata": {}}
    assert audit.read_search_controls(document, EXPECTED) == EXPECTED
    assert document["solver_metadata"] == {}


@pytest.mark.parametrize("mutation", ["missing_original", "missing_field", "wrong_value", "conflict", "boolean"])
def test_missing_changed_or_conflicting_original_controls_are_rejected(mutation):
    document = {"metadata": dict(EXPECTED), "solver_metadata": dict(EXPECTED)}
    if mutation == "missing_original":
        del document["metadata"]
    elif mutation == "missing_field":
        del document["metadata"]["stage2_gurobi_method"]
    elif mutation == "wrong_value":
        document["metadata"]["stage2_gurobi_method"] = -1
    elif mutation == "boolean":
        document["metadata"]["stage2_gurobi_method"] = True
    else:
        document["solver_metadata"]["stage2_gurobi_method"] = -1
    with pytest.raises(ValueError):
        audit.read_search_controls(document, EXPECTED)
