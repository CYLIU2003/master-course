from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from bff.routers.optimization import (
    _apply_result_claim_classification,
    _assert_final_cost_artifact_consistency,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_cost_artifacts(run_dir: Path, *, total: float) -> dict:
    components = {
        "electricity_cost": 10.125,
        "fuel_cost": 20.25,
        "demand_cost": 3.5,
        "vehicle_usage_cost": total - 35.0,
        "co2_cost": 1.125,
    }
    assert sum(components.values()) == total
    _write_json(
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json",
        {
            "eligible": True,
            "cost_breakdown": {"total_cost": total, **components},
        },
    )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        {
            "source": "rolling_hourly_chain/executed_day_accounting.json",
            "accounting_total_cost_jpy": total,
            "components": {
                "electricity_cost_jpy": components["electricity_cost"],
                "fuel_cost_jpy": components["fuel_cost"],
                "demand_charge_cost_jpy": components["demand_cost"],
                "vehicle_usage_cost_jpy": components[
                    "vehicle_usage_cost"
                ],
                "co2_cost_jpy": components["co2_cost"],
            },
        },
    )
    _write_json(
        run_dir / "summary.json",
        {
            "accounting_total_cost_jpy": total,
            "energy_cost_jpy": components["electricity_cost"],
            "fuel_cost_jpy": components["fuel_cost"],
            "demand_charge_cost_jpy": components["demand_cost"],
            "co2_cost_jpy": components["co2_cost"],
        },
    )
    _write_json(
        run_dir / "experiment_report.json",
        {
            "results": {
                "total_cost_jpy": total,
                "electricity_cost_jpy": components["electricity_cost"],
                "diesel_cost_jpy": components["fuel_cost"],
                "demand_charge_jpy": components["demand_cost"],
                "vehicle_fixed_cost_jpy": components[
                    "vehicle_usage_cost"
                ],
                "co2_cost_jpy": components["co2_cost"],
            }
        },
    )
    with (run_dir / "cost_breakdown_detail.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=("key", "value", "unit"))
        writer.writeheader()
        for key, value in (
            ("total_cost", total),
            ("electricity_cost", components["electricity_cost"]),
            ("fuel_cost", components["fuel_cost"]),
            ("demand_charge", components["demand_cost"]),
            ("vehicle_usage_cost", components["vehicle_usage_cost"]),
            ("co2_cost", components["co2_cost"]),
        ):
            writer.writerow({"key": key, "value": value, "unit": "JPY"})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "cost_breakdown"
    sheet.append(["key", "value", "unit"])
    for key, value in (
        ("total_cost", total),
        ("electricity_cost", components["electricity_cost"]),
        ("fuel_cost", components["fuel_cost"]),
        ("demand_charge", components["demand_cost"]),
        ("vehicle_usage_cost", components["vehicle_usage_cost"]),
        ("co2_cost", components["co2_cost"]),
    ):
        sheet.append([key, value, "JPY"])
    workbook.save(run_dir / "results.xlsx")
    (run_dir / "experiment_report.md").write_text(
        f"canonical_executed_total_cost_jpy: `{total!r}`\n",
        encoding="utf-8",
    )
    return {"final_accounting_total_cost_jpy": total}


def test_final_cost_artifacts_must_equal_executed_rolling_accounting(
    tmp_path: Path,
) -> None:
    total = 724_618.0043661146
    optimization_result = _write_cost_artifacts(tmp_path, total=total)

    reconciliation = _assert_final_cost_artifact_consistency(
        run_dir=tmp_path,
        optimization_result=optimization_result,
    )

    assert reconciliation["status"] == "OK"
    assert reconciliation["failed_artifacts"] == {}


def test_final_cost_mismatch_fails_job_above_one_micro_yen(
    tmp_path: Path,
) -> None:
    total = 724_618.0043661146
    optimization_result = _write_cost_artifacts(tmp_path, total=total)
    experiment = json.loads(
        (tmp_path / "experiment_report.json").read_text(encoding="utf-8")
    )
    experiment["results"]["total_cost_jpy"] = total - 34.5918146095
    _write_json(tmp_path / "experiment_report.json", experiment)

    with pytest.raises(RuntimeError, match="experiment_report_json"):
        _assert_final_cost_artifact_consistency(
            run_dir=tmp_path,
            optimization_result=optimization_result,
        )

    reconciliation = json.loads(
        (tmp_path / "final_cost_reconciliation.json").read_text(
            encoding="utf-8"
        )
    )
    assert reconciliation["status"] == "ERROR"


def test_gap_miss_is_labeled_feasible_candidate() -> None:
    result = {
        "solution_validity": {"validated_feasible": True},
        "solver_settings": {
            "mip_gap_requested_ratio": 0.1,
            "mip_gap_target_met": False,
            "stage1_certified_mip_gap_ratio": 0.10488,
            "stage1_gurobi_raw_mip_gap_ratio": 1.0,
        },
        "solver_metadata": {"supports_integrated_exact_milp": False},
        "summary": {},
    }

    classification = _apply_result_claim_classification(result)

    assert classification["label"] == "feasible_candidate"
    assert classification["optimality_claim_eligible"] is False
    assert result["result_status"] == "FEASIBLE_CANDIDATE"
    assert set(classification["optimality_blocking_reasons"]) == {
        "requested_mip_gap_not_met",
        "not_an_integrated_global_assignment_and_charging_milp",
    }
