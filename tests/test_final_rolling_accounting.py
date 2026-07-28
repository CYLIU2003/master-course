from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from bff.routers.optimization import (
    _apply_result_claim_classification,
    _assert_final_cost_artifact_consistency,
    _should_finalize_reporting_after_rolling,
)
from bff.services.optimization_run.cost_breakdown import (
    CANONICAL_LEDGER_COMPONENT_SOURCES,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_cost_artifacts(run_dir: Path, *, total: float) -> dict:
    source_components = {
        "electricity_cost": 10.125,
        "fuel_cost": 20.25,
        "demand_cost": 3.5,
        "vehicle_usage_cost": total - 35.0,
        "co2_cost": 1.125,
    }
    assert sum(source_components.values()) == total
    source_values = {
        source_key: float(source_components.get(source_key, 0.0))
        for source_key, _flag_key in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.values()
        )
    }
    ledger_components = {
        component_key: source_values[source_key]
        for component_key, (source_key, _flag_key) in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.items()
        )
    }
    enabled_component_keys = {
        component_key
        for component_key, (source_key, _flag_key) in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.items()
        )
        if source_key in source_components
    }
    _write_json(
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json",
        {
            "eligible": True,
            "cost_breakdown": {"total_cost": total, **source_values},
        },
    )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        {
            "source": "rolling_hourly_chain/executed_day_accounting.json",
            "accounting_total_cost_jpy": total,
            "components": ledger_components,
            "component_status": {
                component_key: {
                    "enabled": component_key in enabled_component_keys,
                    "status": (
                        "ENABLED"
                        if component_key in enabled_component_keys
                        else "SKIPPED"
                    ),
                    "source_key": source_key,
                    "source_present": True,
                    "value_jpy": ledger_components[component_key],
                }
                for component_key, (source_key, _flag_key) in (
                    CANONICAL_LEDGER_COMPONENT_SOURCES.items()
                )
            },
        },
    )
    _write_json(
        run_dir / "summary.json",
        {
            "accounting_total_cost_jpy": total,
            "energy_cost_jpy": source_components["electricity_cost"],
            "fuel_cost_jpy": source_components["fuel_cost"],
            "demand_charge_cost_jpy": source_components["demand_cost"],
            "co2_cost_jpy": source_components["co2_cost"],
            "canonical_cost_components_jpy": ledger_components,
        },
    )
    _write_json(
        run_dir / "experiment_report.json",
        {
            "results": {
                "total_cost_jpy": total,
                "electricity_cost_jpy": source_components["electricity_cost"],
                "diesel_cost_jpy": source_components["fuel_cost"],
                "demand_charge_jpy": source_components["demand_cost"],
                "vehicle_usage_cost_jpy": source_components[
                    "vehicle_usage_cost"
                ],
                "vehicle_fixed_cost_jpy": source_components.get(
                    "vehicle_cost", 0.0
                ),
                "vehicle_acquisition_cost_jpy": source_components.get(
                    "vehicle_acquisition_cost", 0.0
                ),
                "co2_cost_jpy": source_components["co2_cost"],
                "canonical_cost_components_jpy": ledger_components,
            }
        },
    )
    with (run_dir / "cost_breakdown_detail.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=("key", "value", "unit"))
        writer.writeheader()
        writer.writerow({"key": "total_cost", "value": total, "unit": "JPY"})
        for key, value in source_values.items():
            writer.writerow({"key": key, "value": value, "unit": "JPY"})
        writer.writerow(
            {
                "key": "demand_charge",
                "value": source_components["demand_cost"],
                "unit": "JPY",
            }
        )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "cost_breakdown"
    sheet.append(["key", "value", "unit"])
    sheet.append(["total_cost", total, "JPY"])
    for key, value in source_values.items():
        sheet.append([key, value, "JPY"])
    sheet.append(["demand_charge", source_components["demand_cost"], "JPY"])
    workbook.save(run_dir / "results.xlsx")
    (run_dir / "experiment_report.md").write_text(
        f"canonical_executed_total_cost_jpy: `{total!r}`\n",
        encoding="utf-8",
    )
    return {
        "final_accounting_total_cost_jpy": total,
        "cost_breakdown": {"total_cost": total, **source_values},
    }


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


def test_rolling_failure_prevents_secondary_final_reporting() -> None:
    primary_failure = RuntimeError(
        "Positive Stage 2 charging power has no selected physical charger"
    )

    assert _should_finalize_reporting_after_rolling(None) is True
    assert _should_finalize_reporting_after_rolling(primary_failure) is False


def test_ineligible_executed_accounting_reports_its_reason(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "rolling_hourly_chain" / "executed_day_accounting.json",
        {
            "eligible": False,
            "reason": "executed_slot_coverage_incomplete",
            "rejection_reasons": ["missing_slots:11-23"],
        },
    )

    with pytest.raises(
        RuntimeError,
        match="executed_slot_coverage_incomplete.*missing_slots:11-23",
    ):
        _assert_final_cost_artifact_consistency(
            run_dir=tmp_path,
            optimization_result={},
        )


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


def _write_full_component_artifacts(run_dir: Path) -> dict:
    component_values = {
        component_key: float(index)
        for index, component_key in enumerate(
            CANONICAL_LEDGER_COMPONENT_SOURCES,
            start=1,
        )
    }
    source_values = {
        source_key: component_values[component_key]
        for component_key, (source_key, _flag_key) in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.items()
        )
    }
    source_values["demand_charge"] = source_values["demand_cost"]
    total = sum(component_values.values())
    _write_cost_artifacts(run_dir, total=total)
    _write_json(
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json",
        {
            "eligible": True,
            "cost_breakdown": {"total_cost": total, **source_values},
        },
    )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        {
            "source": "rolling_hourly_chain/executed_day_accounting.json",
            "accounting_total_cost_jpy": total,
            "components": component_values,
            "component_status": {
                component_key: {
                    "enabled": True,
                    "status": "ENABLED",
                    "source_key": source_key,
                    "source_present": True,
                    "value_jpy": component_values[component_key],
                }
                for component_key, (source_key, _flag_key) in (
                    CANONICAL_LEDGER_COMPONENT_SOURCES.items()
                )
            },
        },
    )
    summary = json.loads((run_dir / "summary.json").read_text())
    summary["accounting_total_cost_jpy"] = total
    summary["canonical_cost_components_jpy"] = component_values
    _write_json(run_dir / "summary.json", summary)
    report = json.loads((run_dir / "experiment_report.json").read_text())
    report["results"]["total_cost_jpy"] = total
    report["results"]["canonical_cost_components_jpy"] = component_values
    _write_json(run_dir / "experiment_report.json", report)
    with (run_dir / "cost_breakdown_detail.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=("key", "value", "unit"))
        writer.writeheader()
        writer.writerow({"key": "total_cost", "value": total, "unit": "JPY"})
        for key, value in source_values.items():
            writer.writerow({"key": key, "value": value, "unit": "JPY"})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "cost_breakdown"
    sheet.append(["key", "value", "unit"])
    sheet.append(["total_cost", total, "JPY"])
    for key, value in source_values.items():
        sheet.append([key, value, "JPY"])
    workbook.save(run_dir / "results.xlsx")
    (run_dir / "experiment_report.md").write_text(
        f"canonical_executed_total_cost_jpy: `{total!r}`\n",
        encoding="utf-8",
    )
    return {
        "final_accounting_total_cost_jpy": total,
        "cost_breakdown": {"total_cost": total, **source_values},
    }


def test_all_enabled_canonical_components_reconcile_across_final_artifacts(
    tmp_path: Path,
) -> None:
    optimization_result = _write_full_component_artifacts(tmp_path)

    reconciliation = _assert_final_cost_artifact_consistency(
        run_dir=tmp_path,
        optimization_result=optimization_result,
    )

    assert reconciliation["status"] == "OK"
    assert set(CANONICAL_LEDGER_COMPONENT_SOURCES).issubset(
        reconciliation["expected_by_metric_jpy"]
    )


def test_missing_enabled_component_in_human_report_fails(
    tmp_path: Path,
) -> None:
    optimization_result = _write_full_component_artifacts(tmp_path)
    report = json.loads((tmp_path / "experiment_report.json").read_text())
    report["results"]["canonical_cost_components_jpy"].pop(
        "driver_cost_jpy"
    )
    _write_json(tmp_path / "experiment_report.json", report)

    with pytest.raises(RuntimeError, match="driver_cost_jpy"):
        _assert_final_cost_artifact_consistency(
            run_dir=tmp_path,
            optimization_result=optimization_result,
        )


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
