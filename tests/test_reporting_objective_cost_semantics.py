from __future__ import annotations

import csv
import json
import shutil

import pytest

from src.reporting import rebuild_reporting_artifacts_in_place
from tests._reporting_finalizer_utils import source_run_dir


def _validation_row(run_dir, check_name: str) -> dict[str, str]:
    with (run_dir / "graph" / "data_flow_validation.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    return next(row for row in rows if row["check_name"] == check_name)


def _write_objective_contract(
    run_dir,
    *,
    objective_mode: str,
    equality_required: bool,
) -> None:
    first_pass = rebuild_reporting_artifacts_in_place(run_dir)
    total = first_pass.cost_totals["total_cost"]
    ledger = {
        "schema_version": "canonical_cost_ledger_v1",
        "currency": "JPY",
        "components": {
            "electricity_cost_jpy": total,
            "fuel_cost_jpy": 0.0,
            "demand_charge_cost_jpy": 0.0,
            "contract_overage_cost_jpy": 0.0,
            "vehicle_fixed_cost_jpy": 0.0,
            "vehicle_usage_cost_jpy": 0.0,
            "driver_cost_jpy": 0.0,
            "unserved_penalty_jpy": 0.0,
            "switch_cost_jpy": 0.0,
            "battery_degradation_cost_jpy": 0.0,
            "deviation_cost_jpy": 0.0,
            "co2_cost_jpy": 0.0,
        },
        "details": {
            "grid_purchase_cost_jpy": total,
            "bess_total_flow_cost_jpy": 0.0,
        },
        "co2": {},
        "usage": {},
        "accounting_total_cost_jpy": total,
        "reported_total_cost_jpy": total,
        "accounting_residual_jpy": 0.0,
        "objective_mode": objective_mode,
        "solver_objective_unit": (
            "JPY" if equality_required else "solver_objective_score"
        ),
        "objective_is_actual_cost": equality_required,
        "objective_accounting_equality_required": equality_required,
    }
    (run_dir / "graph" / "canonical_cost_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_co2_objective_difference_is_skipped_not_error(tmp_path) -> None:
    run_dir = tmp_path / "co2-objective"
    shutil.copytree(source_run_dir("run_20260606_1559"), run_dir)
    _write_objective_contract(
        run_dir,
        objective_mode="co2",
        equality_required=False,
    )

    rebuild_reporting_artifacts_in_place(run_dir)

    row = _validation_row(
        run_dir, "objective_value_matches_canonical_accounting_total"
    )
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert row["status"] == "SKIPPED"
    assert row["severity"] == "INFO"
    assert summary["objective_mode"] == "co2"
    assert summary["objective_value_unit"] == "solver_objective_score"
    assert summary["objective_accounting_equality_required"] is False
    assert summary["objective_is_actual_cost"] is False


def test_actual_cost_objective_difference_remains_error(tmp_path) -> None:
    run_dir = tmp_path / "cost-objective"
    shutil.copytree(source_run_dir("run_20260606_1559"), run_dir)
    _write_objective_contract(
        run_dir,
        objective_mode="total_cost",
        equality_required=True,
    )

    rebuild_reporting_artifacts_in_place(run_dir)

    row = _validation_row(
        run_dir, "objective_value_matches_canonical_accounting_total"
    )
    assert row["status"] == "NG"
    assert row["severity"] == "ERROR"
