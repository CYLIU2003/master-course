from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_day_ahead_diagnostic_pair_report.py"
SPEC = importlib.util.spec_from_file_location(
    "build_day_ahead_diagnostic_pair_report", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _case_fixture(
    root: Path,
    *,
    case: str,
    pv_source_date: str,
    pv_generation_kwh: float,
    bev_trips: int,
    ice_trips: int,
    used_bev: int,
    used_ice: int,
    vehicle_usage_cost: float = 20_000.0,
    driver_cost: float = 0.0,
) -> Path:
    run_dir = root / case
    total_trips = bev_trips + ice_trips
    electricity_cost = 300.0 if case == "sunny" else 400.0
    fuel_cost = float(ice_trips * 10)
    co2_cost = float(ice_trips)
    vehicle_cost = float((used_bev + used_ice) * vehicle_usage_cost)
    total_cost = electricity_cost + fuel_cost + co2_cost + vehicle_cost + driver_cost
    pv_to_bus = pv_generation_kwh * 0.2
    pv_to_bess = pv_generation_kwh * 0.5
    pv_curtailed = pv_generation_kwh - pv_to_bus - pv_to_bess

    kpi = {
        "bev_trip_count": bev_trips,
        "ice_trip_count": ice_trips,
        "electricity_cost_jpy": electricity_cost,
        "fuel_cost_jpy": fuel_cost,
        "vehicle_usage_cost_jpy": vehicle_cost,
        "co2_cost_jpy": co2_cost,
        "accounting_total_cost_jpy": total_cost,
        "pv_generation_kwh": pv_generation_kwh,
        "pv_to_bus_kwh": pv_to_bus,
        "pv_to_bess_kwh": pv_to_bess,
        "bess_to_bus_kwh": pv_to_bess * 0.9,
        "grid_import_kwh": 10.0,
        "pv_curtailed_kwh": pv_curtailed,
        "peak_grid_import_kw": 10.0,
        "total_co2_kg": co2_cost,
        "mip_gap_requested_percent": 1.0,
    }
    _write_json(run_dir / "kpi_summary.json", kpi)
    _write_json(
        run_dir / "summary.json",
        {
            "solver_status": "time_limit",
            "solve_time_seconds": 120.0,
            "trip_count_served": total_trips,
            "trip_count_unserved": 0,
            "accounting_total_cost_jpy": total_cost,
            "canonical_cost_components_jpy": {
                "electricity_cost_jpy": electricity_cost,
                "fuel_cost_jpy": fuel_cost,
                "demand_charge_cost_jpy": 0.0,
                "contract_overage_cost_jpy": 0.0,
                "vehicle_fixed_cost_jpy": 0.0,
                "vehicle_usage_cost_jpy": vehicle_cost,
                "driver_cost_jpy": driver_cost,
                "unserved_penalty_jpy": 0.0,
                "switch_cost_jpy": 0.0,
                "battery_degradation_cost_jpy": 0.0,
                "deviation_cost_jpy": 0.0,
                "co2_cost_jpy": co2_cost,
            },
            "rolling_execution": {"status": "not_executed"},
            "solution_validity": {
                "physical_validation_status": "VALID",
                "validation_metrics": {
                    "all_required_validation_checks_passed": True
                },
            },
        },
    )
    _write_json(
        run_dir / "solver_settings.json",
        {
            "certified_mip_gap_percent": 1.2,
            "gurobi_threads": 4,
            "git_state_unchanged_during_solve": True,
        },
    )
    asset = {
        "depot_id": "tsurumaki",
        "pv_capacity_kw": 1000.0,
        "bess_energy_kwh": 6000.0,
        "bess_power_kw": 900.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_terminal_soc_target_kwh": 3000.0,
        "allow_grid_to_bess": False,
        "pv_source_date": pv_source_date,
    }
    _write_json(
        run_dir / "simulation_conditions.json",
        {
            "service_date": "2025-08-05",
            "day_type": "WEEKDAY",
            "depot_energy_assets": [asset],
            "vehicle_usage_cost_jpy_per_used_bus": vehicle_usage_cost,
            "vehicle_usage_cost_semantics": "fixed_vehicle_day_cost",
            "charger_count": 10,
            "charger_power_kw": 90.0,
            "time_step_min": 60,
            "time_limit_seconds": 600,
            "mip_gap": 0.01,
            "random_seed": 42,
            "milp_max_successors_per_trip": 0,
        },
    )
    _write_json(run_dir / "optimization_parameters.json", {"vehicle_count": 60})
    _write_json(
        run_dir / "research_claim_scope.json",
        {"research_submission_ready": False, "teacher_release_status": "BLOCKED"},
    )
    _write_json(
        run_dir / "artifact_completeness.json",
        {"status": "OK", "accepted": True},
    )
    _write_json(
        run_dir / "case_execution_metadata.json",
        {
            "scenario_id": f"scenario-{case}",
            "prepared_input_id": f"prepared-{case}",
            "job_id": f"job-{case}",
            "total_wall_time_sec": 630.0,
        },
    )
    _write_json(
        run_dir / "code_provenance.json",
        {"git_sha": "abc123", "git_dirty": False},
    )
    _write_csv(
        run_dir / "simulation_conditions_tou_prices.csv",
        ["grid_energy_price_yen_per_kwh", "demand_charge_weight"],
        [
            {
                "grid_energy_price_yen_per_kwh": 30.0,
                "demand_charge_weight": 0.0,
            }
            for _ in range(24)
        ],
    )
    assignment_rows: list[dict[str, Any]] = []
    for index in range(total_trips):
        is_bev = index < bev_trips
        count = used_bev if is_bev else used_ice
        vehicle_index = index % max(count, 1)
        assignment_rows.append(
            {
                "trip_id": f"trip-{index}",
                "assigned_vehicle_id": f"{'bev' if is_bev else 'ice'}-{vehicle_index}",
                "assigned_vehicle_type": "BEV" if is_bev else "ICE",
                "served_flag": True,
            }
        )
    _write_csv(
        run_dir / "graph" / "trip_assignment.csv",
        ["trip_id", "assigned_vehicle_id", "assigned_vehicle_type", "served_flag"],
        assignment_rows,
    )
    hourly_rows = []
    for hour in range(24):
        hourly_rows.append(
            {
                "time": f"{hour:02d}:00",
                "pv_generation_slot_kwh": pv_generation_kwh / 24,
                "pv_to_bus_slot_kwh": pv_to_bus / 24,
                "pv_to_bess_slot_kwh": pv_to_bess / 24,
                "bess_to_bus_slot_kwh": pv_to_bess * 0.9 / 24,
                "grid_to_bus_slot_kwh": 10.0 / 24,
                "pv_curtailed_slot_kwh": pv_curtailed / 24,
                "bess_soc_kwh": 3000.0,
            }
        )
    _write_csv(
        run_dir / "graph" / "energy_flow_timeseries.csv",
        list(hourly_rows[0]),
        hourly_rows,
    )
    _write_csv(
        run_dir / "graph" / "data_flow_validation.csv",
        ["check_name", "status", "severity", "message"],
        [
            {
                "check_name": "fixture_balance",
                "status": "OK",
                "severity": "INFO",
                "message": "OK",
            },
            {
                "check_name": "fixture_documented_skip",
                "status": "SKIPPED",
                "severity": "INFO",
                "message": "Not applicable to this accounting definition.",
            },
        ],
    )
    return run_dir


def test_builds_diagnostic_pair_bundle_from_matching_controls(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
    )
    output = tmp_path / "report"

    snapshot = MODULE.build_report(sunny, rain, output)

    assert snapshot["status"] == "DIAGNOSTIC"
    assert snapshot["research_submission_ready"] is False
    assert snapshot["control_mismatches"] == []
    assert snapshot["differences"]["sunny_minus_rain_bev_trips"] == 5
    assert snapshot["cases"]["sunny"]["data_flow_validation_status"] == (
        "OK_WITH_DOCUMENTED_SKIPS"
    )
    assert snapshot["cases"]["sunny"]["data_flow_skipped_check_count"] == 1
    assert (output / "comparison_summary.csv").is_file()
    assert (output / "report.md").is_file()
    assert (output / "figures" / "dispatch_comparison.png").is_file()
    assert (output / "figures" / "hourly_energy_flows.svg").is_file()
    manifest = json.loads((output / "artifact_manifest.json").read_text())
    assert manifest["status"] == "DIAGNOSTIC"
    assert manifest["reporting_snapshot_sha256"]


def test_uses_all_canonical_cost_components(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
        driver_cost=125.0,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
        driver_cost=125.0,
    )

    snapshot = MODULE.build_report(sunny, rain, tmp_path / "report")

    assert snapshot["cases"]["sunny"]["other_cost_jpy"] == pytest.approx(125.0)
    with (tmp_path / "report" / "cost_breakdown.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert float(rows[0]["driver_cost_jpy"]) == pytest.approx(125.0)
    assert float(rows[0]["reconciliation_error_jpy"]) == pytest.approx(0.0)


def test_rejects_vehicle_usage_cost_control_mismatch(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
        vehicle_usage_cost=20_000.0,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
        vehicle_usage_cost=0.0,
    )

    with pytest.raises(ValueError, match="vehicle_usage_cost_jpy_per_used_bus"):
        MODULE.build_report(sunny, rain, tmp_path / "report")


def test_rejects_non_valid_physical_schedule(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
    )
    summary = json.loads((rain / "summary.json").read_text())
    summary["solution_validity"]["physical_validation_status"] = "INVALID"
    _write_json(rain / "summary.json", summary)

    with pytest.raises(ValueError, match="physical validation is not VALID"):
        MODULE.build_report(sunny, rain, tmp_path / "report")


def test_rejects_failed_data_flow_validation(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
    )
    _write_csv(
        rain / "graph" / "data_flow_validation.csv",
        ["check_name", "status"],
        [{"check_name": "fixture_balance", "status": "ERROR"}],
    )

    with pytest.raises(ValueError, match="data-flow validation is not fully OK"):
        MODULE.build_report(sunny, rain, tmp_path / "report")


def test_rejects_incomplete_source_artifacts(tmp_path: Path) -> None:
    sunny = _case_fixture(
        tmp_path,
        case="sunny",
        pv_source_date="2025-08-05",
        pv_generation_kwh=6000.0,
        bev_trips=8,
        ice_trips=2,
        used_bev=4,
        used_ice=1,
    )
    rain = _case_fixture(
        tmp_path,
        case="rain",
        pv_source_date="2025-08-10",
        pv_generation_kwh=1000.0,
        bev_trips=3,
        ice_trips=7,
        used_bev=2,
        used_ice=3,
    )
    _write_json(
        rain / "artifact_completeness.json",
        {"status": "ERROR", "accepted": False},
    )

    with pytest.raises(ValueError, match="artifact completeness gate is not accepted"):
        MODULE.build_report(sunny, rain, tmp_path / "report")
