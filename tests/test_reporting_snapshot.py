from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO_ROOT / "scripts" / "build_reporting_snapshot.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_reporting_snapshot", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _assignment_rows(case: str) -> list[dict]:
    high = case == "sunny"
    return [
        {
            "trip_id": f"{case}-trip-1",
            "assigned_vehicle_id": f"{case}-bev-1",
            "assigned_vehicle_type": "BEV",
            "served_flag": True,
            "route_id": "route-a",
            "scheduled_departure": "2025-08-05T06:00:00",
            "scheduled_arrival": "2025-08-05T06:30:00",
            "distance_km": 10.0,
        },
        {
            "trip_id": f"{case}-trip-2",
            "assigned_vehicle_id": f"{case}-{'bev-2' if high else 'ice-1'}",
            "assigned_vehicle_type": "BEV" if high else "ICE",
            "served_flag": True,
            "route_id": "route-b",
            "scheduled_departure": "2025-08-05T07:00:00",
            "scheduled_arrival": "2025-08-05T07:30:00",
            "distance_km": 10.0,
        },
    ]


def _write_case(pair_dir: Path, case: str) -> None:
    case_dir = pair_dir / case
    high = case == "sunny"
    assignments = _assignment_rows(case)
    _write_csv(
        case_dir / "graph" / "trip_assignment.csv",
        list(assignments[0].keys()),
        assignments,
    )

    pv_per_hour = 10.0 if high else 4.0
    pv_bus_per_hour = 2.0 if high else 1.0
    pv_bess_per_hour = 3.0 if high else 1.0
    curtail_per_hour = pv_per_hour - pv_bus_per_hour - pv_bess_per_hour
    grid_per_hour = 0.5
    bess_bus_per_hour = 1.0
    hourly_rows = []
    for hour in range(24):
        hourly_rows.append(
            {
                "step_index": hour,
                "current_time": f"{hour:02d}:00",
                "execution_minutes": 60,
                "pv_generated_kwh": pv_per_hour,
                "pv_to_bus_kwh": pv_bus_per_hour,
                "pv_to_bess_kwh": pv_bess_per_hour,
                "pv_curtailed_kwh": curtail_per_hour,
                "bess_to_bus_kwh": bess_bus_per_hour,
                "grid_to_bus_kwh": grid_per_hour,
                "grid_to_bess_kwh": 0.0,
                "bess_end_soc_kwh_by_depot": json.dumps(
                    {"tsurumaki": 3000.0}
                ),
                "bev_soc_min_kwh": 80.0,
                "bev_soc_mean_kwh": 120.0,
                "charging_kw_max": 90.0,
                "on_peak_kw_max": grid_per_hour,
                "off_peak_kw_max": 0.0,
            }
        )
    _write_csv(
        case_dir / "rolling_hourly_chain" / "hourly_energy_flow_chart.csv",
        list(hourly_rows[0].keys()),
        hourly_rows,
    )

    electricity = 24 * grid_per_hour * 30.0
    fuel = 0.0 if high else 1500.0
    co2 = 6.0 if high else 80.0
    vehicle_usage = 40000.0
    total = electricity + fuel + co2 + vehicle_usage
    _write_json(
        case_dir / "rolling_hourly_chain" / "executed_day_accounting.json",
        {
            "accounting_basis": "executed_rolling_day",
            "eligible": True,
            "terminal_energy_balanced": True,
            "bev_terminal_energy_balanced": True,
            "bess_terminal_energy_balanced": True,
            "bess_terminal_soc_by_depot": {
                "tsurumaki": {
                    "policy": "fixed_target",
                    "initial_soc_kwh": 3000.0,
                    "target_soc_kwh": 3000.0,
                    "terminal_soc_kwh": 3000.0,
                    "absolute_deviation_kwh": 0.0,
                    "balanced": True,
                }
            },
            "cost_breakdown": {
                "electricity_cost": electricity,
                "demand_cost": 0.0,
                "fuel_cost": fuel,
                "vehicle_usage_cost_jpy": vehicle_usage,
                "co2_cost": co2,
                "degradation_cost": 0.0,
                "contract_overage_cost": 0.0,
                "total_cost": total,
                "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
                "used_vehicle_day_count": 2,
                "pv_generated_kwh": 24 * pv_per_hour,
                "pv_to_bus_kwh": 24 * pv_bus_per_hour,
                "pv_to_bess_kwh": 24 * pv_bess_per_hour,
                "pv_curtailed_kwh": 24 * curtail_per_hour,
                "bess_to_bus_kwh": 24 * bess_bus_per_hour,
                "grid_import_kwh": 24 * grid_per_hour,
                "grid_to_bus_kwh": 24 * grid_per_hour,
                "grid_to_bess_kwh": 0.0,
                "peak_grid_kw": grid_per_hour,
                "total_co2_kg": co2,
                "grid_electricity_co2_kg": 6.0,
                "ice_co2_kg": 0.0 if high else 74.0,
                "objective_value": total - 111500.0,
                "return_leg_bonus": 111500.0,
                "objective_is_actual_cost": False,
            },
        },
    )
    _write_json(
        case_dir / "rolling_hourly_chain" / "rolling_chain_summary.json",
        {
            "step_count": 24,
            "expected_step_count": 24,
            "chain_accepted": True,
            "time_limit_sec": 30,
            "mip_gap": 0.01,
        },
    )
    zero_metrics = {
        "unassigned_trip_count": 0,
        "duplicate_trip_count": 0,
        "vehicle_time_overlap_count": 0,
        "charger_concurrency_violation_count": 0,
        "ev_soc_lower_violation_count": 0,
        "bev_terminal_soc_violation_count": 0,
    }
    _write_json(
        case_dir / "graph" / "physical_schedule_validation.json",
        {
            "status": "VALID",
            "accepted": True,
            "failed_checks": [],
            "validation_metrics": zero_metrics,
        },
    )
    _write_json(
        case_dir / "solver_settings.json",
        {
            "time_limit_seconds_requested": 3600,
            "time_limit_seconds_effective": 3600,
            "mip_gap_requested_ratio": 0.01,
            "mip_gap_requested_percent": 1.0,
            "certified_mip_gap_percent": 0.7 if high else 0.4,
            "gurobi_raw_mip_gap_ratio": 0.007 if high else 1.0,
            "certified_mip_gap_semantics": "fixture independent bound",
            "has_feasible_incumbent": True,
            "mip_gap_target_met": True,
            "solve_time_sec": 10.0,
        },
    )
    _write_json(
        case_dir / "optimization_parameters.json",
        {
            "effective_optimization_config": {
                "phase": "phase4_integrated",
                "time_limit_sec": 3600,
                "mip_gap": 0.01,
                "gurobi_threads": 4,
                "random_seed": 42,
            },
            "effective_problem_scenario": {
                "timestep_min": 60,
                "service_coverage_mode": "strict",
            },
            "effective_model_metadata": {
                "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
            },
        },
    )
    _write_json(
        case_dir / "comparison_case_manifest.json",
        {
            "comparison_control_hash": "a" * 64,
            "pv_profile_hash": ("b" if high else "c") * 64,
            "assignment_hash": ("d" if high else "e") * 64,
            "pv_source_date": "2025-08-05" if high else "2025-08-10",
            "comparison_control_payload": {"service_date": "2025-08-05"},
        },
    )
    _write_json(
        case_dir / "case_execution_metadata.json",
        {
            "scenario_id": f"{case}-scenario",
            "prepared_input_id": f"{case}-prepared",
            "job_id": f"{case}-job",
            "run_dir": str(case_dir / f"run_{case}"),
        },
    )
    _write_json(
        case_dir / "frontend_job_terminal_response.json",
        {
            "status": "completed",
            "metadata": {
                "solver_status": "optimal" if high else "objective_limit"
            },
        },
    )
    _write_json(
        case_dir / "frontend_depot_energy_asset_request.json",
        {
            "depot_id": "tsurumaki",
            "pv_capacity_kw": 1000.0,
            "pv_capacity_input_mode": "rated_output_manual",
            "pv_capacity_kw_manual_override": True,
            "estimated_installable_area_m2": 5000.0,
            "estimated_depot_area_from_pv_capacity_m2": 14285.714286,
            "derived_pv_capacity_kw": 1000.0,
            "panel_power_density_kw_m2": 0.2,
            "usable_area_ratio": 0.35,
            "depot_area_m2": 1450.0,
            "bess_energy_kwh": 6000.0,
            "bess_power_kw": 900.0,
            "bess_initial_soc_kwh": 3000.0,
            "bess_terminal_soc_target_kwh": 3000.0,
            "pv_source_date": "2025-08-05" if high else "2025-08-10",
            "pv_case_id": f"{case}-pv",
        },
    )


def _pair_fixture(tmp_path: Path) -> Path:
    pair_dir = tmp_path / "pair-evidence"
    pair_dir.mkdir()
    _write_case(pair_dir, "sunny")
    _write_case(pair_dir, "rain")
    _write_json(
        pair_dir / "pair" / "pair_manifest.json",
        {
            "accepted_for_controlled_pv_sensitivity_comparison": True,
            "formal_research_submission_ready": True,
            "failed_checks": [],
        },
    )
    _write_json(
        pair_dir / "tariff_condition.json",
        {
            "grid_energy_price_yen_per_kwh": 30.0,
            "demand_charge_yen_per_kw": 0.0,
        },
    )
    return pair_dir


def test_snapshot_uses_final_assignment_and_excludes_internal_objective(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)

    payload, assignments = builder._build_snapshot_payload(pair_dir)

    assert len(assignments) == 4
    assert payload["cases"]["sunny"]["assignment"]["used_bev_count"] == 2
    assert payload["cases"]["rain"]["assignment"]["used_bev_count"] == 1
    assert payload["cases"]["rain"]["assignment"]["used_ice_count"] == 1
    assert payload["cases"]["rain"]["solver_quality"][
        "solution_quality_label"
    ] == "CERTIFIED_NEAR_OPTIMAL"
    assert payload["cases"]["rain"]["solver_quality"][
        "gurobi_raw_gap_percent"
    ] == 100.0
    assert payload["cases"]["sunny"]["depot_energy_asset"][
        "estimated_pv_panel_area_from_rated_output_m2"
    ] == 5000.0
    summary_rows = builder._summary_rows(payload, "f" * 64)
    assert summary_rows[1]["raw_solver_status"] == "objective_limit"
    assert summary_rows[1]["gurobi_raw_gap_percent"] == 100.0
    assert summary_rows[1]["certified_gap_percent"] == 0.4
    assert summary_rows[1]["day_ahead_time_limit_sec"] == 3600
    assert summary_rows[1]["rolling_time_limit_sec_per_step"] == 30.0
    serialized = json.dumps(payload)
    assert "return_leg_bonus" not in serialized
    assert "objective_value" not in serialized
    assert payload["comparison_pair"]["progress_presentation_ready"] is True
    assert payload["comparison_pair"]["research_submission_ready"] is False


def test_snapshot_fails_when_vehicle_day_cost_does_not_reconcile(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    accounting_path = (
        pair_dir
        / "rain"
        / "rolling_hourly_chain"
        / "executed_day_accounting.json"
    )
    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    accounting["cost_breakdown"]["vehicle_usage_cost_jpy"] = 20000.0
    accounting["cost_breakdown"]["total_cost"] -= 20000.0
    _write_json(accounting_path, accounting)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="vehicle_usage_cost_reconciles",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_snapshot_fails_when_required_accounting_field_is_missing(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    accounting_path = (
        pair_dir
        / "rain"
        / "rolling_hourly_chain"
        / "executed_day_accounting.json"
    )
    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    del accounting["cost_breakdown"]["electricity_cost"]
    _write_json(accounting_path, accounting)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="Missing required executed-day accounting field: electricity_cost",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_snapshot_rejects_vehicle_id_with_two_powertrains(tmp_path: Path) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    assignment_path = pair_dir / "rain" / "graph" / "trip_assignment.csv"
    with assignment_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[1]["assigned_vehicle_id"] = rows[0]["assigned_vehicle_id"]
    _write_csv(assignment_path, list(rows[0]), rows)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="vehicle IDs assigned to multiple powertrains",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_snapshot_rejects_inconsistent_pv_rated_output_reverse_calculation(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    asset_path = pair_dir / "rain" / "frontend_depot_energy_asset_request.json"
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    asset["estimated_installable_area_m2"] = 4999.0
    _write_json(asset_path, asset)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="pv_rated_output_reverse_calculation_reconciles",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_snapshot_rejects_mismatched_pair_asset_controls(tmp_path: Path) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    asset_path = pair_dir / "rain" / "frontend_depot_energy_asset_request.json"
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    asset["bess_power_kw"] = 800.0
    _write_json(asset_path, asset)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="depot_energy_asset_controls_match",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_snapshot_rejects_solver_settings_that_differ_from_effective_inputs(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    solver_path = pair_dir / "rain" / "solver_settings.json"
    solver = json.loads(solver_path.read_text(encoding="utf-8"))
    solver["time_limit_seconds_effective"] = 1800
    _write_json(solver_path, solver)

    with pytest.raises(
        builder.ReportingSnapshotError,
        match="solver_settings_match_effective_inputs",
    ):
        builder._build_snapshot_payload(pair_dir)


def test_reporting_release_has_single_digest_and_preserves_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _load_builder()
    pair_dir = _pair_fixture(tmp_path)
    source_hashes_before = builder._hash_sources(builder._source_paths(pair_dir))

    def fake_workbook(
        workbook_payload: dict,
        output_path: Path,
        _node_executable: Path,
        _node_modules_dir: Path,
        _preview_dir: Path,
    ) -> dict:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        digest = workbook_payload["reporting_snapshot_sha256"]
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.writestr(
                "xl/sharedStrings.xml",
                f"<sst><si><t>{digest}</t></si></sst>",
            )
        return {
            "status": "OK",
            "reporting_snapshot_sha256": digest,
            "sheet_count": 8,
            "preview_count": 8,
            "formula_error_scan": "",
        }

    monkeypatch.setattr(builder, "_run_workbook_builder", fake_workbook)
    output_dir = pair_dir / "release"
    result = builder.build_reporting_release(
        pair_dir=pair_dir,
        output_dir=output_dir,
        zip_path=pair_dir / "release.zip",
        node_executable=tmp_path / "node.exe",
        node_modules_dir=tmp_path / "node_modules",
        workbook_preview_dir=tmp_path / "previews",
    )

    assert result["status"] == "READY_FOR_PROGRESS_PRESENTATION"
    assert result["research_submission_ready"] is False
    assert result["release_file_count"] == 15
    assert builder._hash_sources(builder._source_paths(pair_dir)) == source_hashes_before
    snapshot = json.loads(
        (output_dir / "reporting_snapshot.json").read_text(encoding="utf-8")
    )
    digest = snapshot["reporting_snapshot_sha256"]
    assert digest == builder._canonical_digest(snapshot["snapshot_payload"])
    for path in output_dir.rglob("*"):
        if path.is_file():
            assert builder._verify_public_digest(path, digest), path
    assert not builder._scan_stale_markers(output_dir)
    with zipfile.ZipFile(pair_dir / "release.zip") as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 15


def test_stale_warning_scan_blocks_superseded_text(tmp_path: Path) -> None:
    builder = _load_builder()
    release = tmp_path / "release"
    release.mkdir()
    (release / "warning.txt").write_text(
        "vehicle-soc-violation | OUT_OF_SCOPE_REMAINS",
        encoding="utf-8",
    )

    findings = builder._scan_stale_markers(release)

    assert findings
    assert any("OUT_OF_SCOPE_REMAINS" in finding for finding in findings)


@pytest.mark.parametrize(
    "output_relative,zip_relative",
    [
        ("release", "../outside.zip"),
        ("release", "release/nested.zip"),
        ("release", ".hidden.zip"),
        ("release", "release.txt"),
        ("same.zip", "same.zip"),
    ],
)
def test_release_paths_reject_destructive_zip_targets(
    tmp_path: Path,
    output_relative: str,
    zip_relative: str,
) -> None:
    builder = _load_builder()
    pair_dir = tmp_path / "pair-evidence"
    pair_dir.mkdir()
    output_dir = pair_dir / output_relative
    zip_path = pair_dir / zip_relative

    if output_dir.suffix.lower() == ".zip":
        with pytest.raises(builder.ReportingSnapshotError):
            builder._safe_output_dir(pair_dir, output_dir)
        return

    builder._safe_output_dir(pair_dir, output_dir)
    with pytest.raises(builder.ReportingSnapshotError):
        builder._safe_zip_path(pair_dir, output_dir, zip_path)
