from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = (
    REPO_ROOT / "scripts" / "build_frontend_pv_pair_progress_report.py"
)


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_frontend_pv_pair_progress_report",
        BUILDER_PATH,
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_literature_bundle(case_dir: Path) -> None:
    output_dir = case_dir / "graph" / "literature_figures"
    output_dir.mkdir(parents=True)
    entries = []
    for index in range(1, 6):
        names = [
            f"{index:02d}_figure.png",
            f"{index:02d}_figure.svg",
            f"{index:02d}_figure_source.csv",
        ]
        records = []
        for name in names:
            path = output_dir / name
            path.write_bytes(f"fixture:{name}\n".encode())
            records.append(
                {
                    "path": name,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        entries.append(
            {
                "kind": "figure",
                "figure_id": f"fixture_{index}",
                "title": f"Fixture figure {index}",
                "analytical_question": f"Fixture question {index}",
                "artifact_files": names,
                "artifact_records": records,
                "canonical_sources": ["vehicle_timelines.csv"],
            }
        )
    _write_json(
        output_dir / "manifest.json",
        {
            "schema_version": "literature_figure_bundle_v1",
            "status": "READY",
            "entries": entries,
        },
    )


def _write_hourly(case_dir: Path, *, high_pv: bool) -> None:
    fields = [
        "step_index",
        "current_time",
        "execution_minutes",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "bess_to_bus_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "bess_end_soc_kwh_by_depot",
        "bev_soc_min_kwh",
        "bev_soc_mean_kwh",
        "charging_kw_max",
        "on_peak_kw_max",
        "off_peak_kw_max",
        "vehicle_source_provenance_exact",
        "vehicle_source_allocation_policy",
    ]
    rows = []
    for hour in range(24):
        daylight = 6 <= hour <= 17
        pv = (100.0 if high_pv else 20.0) if daylight else 0.0
        rows.append(
            {
                "step_index": hour,
                "current_time": f"{hour:02d}:00",
                "execution_minutes": 60,
                "pv_generated_kwh": pv,
                "pv_to_bus_kwh": pv * 0.2,
                "pv_to_bess_kwh": pv * 0.5,
                "pv_curtailed_kwh": pv * 0.3,
                "bess_to_bus_kwh": 10.0 if not daylight else 0.0,
                "grid_to_bus_kwh": 2.0,
                "grid_to_bess_kwh": 0.0,
                "bess_end_soc_kwh_by_depot": json.dumps(
                    {"tsurumaki": 3000.0}
                ),
                "bev_soc_min_kwh": 50.0,
                "bev_soc_mean_kwh": 100.0,
                "charging_kw_max": 90.0,
                "on_peak_kw_max": 2.0,
                "off_peak_kw_max": 0.0,
                "vehicle_source_provenance_exact": False,
                "vehicle_source_allocation_policy": (
                    "proportional_by_depot_timestep"
                ),
            }
        )
    _write_csv(
        case_dir
        / "rolling_hourly_chain"
        / "hourly_energy_flow_chart.csv",
        fields,
        rows,
    )


def _write_case(pair_dir: Path, case: str) -> None:
    case_dir = pair_dir / case
    high_pv = case == "sunny"
    case_dir.mkdir(parents=True)
    _write_json(
        case_dir / "artifact_completeness.json",
        {"status": "OK", "accepted": True},
    )
    _write_json(
        case_dir / "case_execution_metadata.json",
        {
            "scenario_id": f"{case}-scenario",
            "prepared_input_id": f"{case}-prepared",
            "job_id": f"{case}-job",
            "run_dir": str(case_dir / f"{case}-source-run"),
            "frozen_git_sha": "a" * 40,
        },
    )
    _write_json(
        case_dir / "comparison_case_manifest.json",
        {
            "assignment_hash": f"{case}-assignment",
            "pv_profile_hash": f"{case}-pv",
        },
    )
    _write_json(
        case_dir / "kpi_summary.json",
        {
            "served_trip_count": 2,
            "unserved_trip_count": 0,
            "service_km": 20.0,
            "deadhead_total_km": 2.0,
        },
    )
    _write_json(
        case_dir / "input_audit.json",
        {
            "scenario_id": f"{case}-scenario",
            "prepared_input_id": f"{case}-prepared",
        },
    )
    _write_json(
        case_dir / "physical_schedule_validation.json",
        {"accepted": True},
    )
    _write_json(
        case_dir / "research_claim_scope.json",
        {
            "teacher_release_status": "BLOCKED",
            "teacher_release_failed_checks": [
                "controlled_counterfactual_pair_not_verified"
            ],
        },
    )
    (case_dir / "results.xlsx").write_bytes(b"PK fixture workbook")
    _write_json(
        case_dir / "simulation_conditions.json",
        {
            "charger_count": 10,
            "depot_energy_assets": [
                {
                    "depot_id": "tsurumaki",
                    "pv_capacity_kw": 1000.0,
                    "estimated_installable_area_m2": 5000.0,
                    "estimated_depot_area_from_pv_capacity_m2": (
                        14285.714286
                    ),
                    "bess_energy_kwh": 6000.0,
                    "bess_power_kw": 900.0,
                    "bess_initial_soc_kwh": 3000.0,
                    "bess_terminal_soc_target_kwh": 3000.0,
                }
            ],
        },
    )
    _write_json(
        case_dir / "solver_settings.json",
        {"mip_gap_requested_ratio": 0.01},
    )
    vehicle_rows = [
        {
            "vehicle_id": f"{case}-bev",
            "vehicle_type": "BEV",
            "trip_id": f"{case}-trip-1",
            "is_service": True,
        },
        {
            "vehicle_id": f"{case}-{'bev-2' if high_pv else 'ice'}",
            "vehicle_type": "BEV" if high_pv else "ICE",
            "trip_id": f"{case}-trip-2",
            "is_service": True,
        },
    ]
    _write_csv(
        case_dir / "vehicle_timelines.csv",
        ["vehicle_id", "vehicle_type", "trip_id", "is_service"],
        vehicle_rows,
    )
    cost = {
        "pv_generated_kwh": 1200.0 if high_pv else 240.0,
        "grid_import_kwh": 48.0,
        "pv_to_bus_kwh": 240.0 if high_pv else 48.0,
        "pv_to_bess_kwh": 600.0 if high_pv else 120.0,
        "bess_to_bus_kwh": 120.0,
        "pv_curtailed_kwh": 360.0 if high_pv else 72.0,
        "electricity_cost": 1440.0,
        "fuel_cost": 0.0 if high_pv else 1500.0,
        "demand_cost": 0.0,
        "vehicle_usage_cost_jpy": 40000.0,
        "co2_cost": 24.0 if high_pv else 80.0,
        "total_cost": 41464.0 if high_pv else 43020.0,
        "total_co2_kg": 24.0 if high_pv else 80.0,
    }
    _write_json(
        case_dir
        / "rolling_hourly_chain"
        / "executed_day_accounting.json",
        {"eligible": True, "cost_breakdown": cost},
    )
    _write_json(
        case_dir
        / "rolling_hourly_chain"
        / "rolling_chain_summary.json",
        {"accepted": True, "accepted_steps": 24},
    )
    _write_hourly(case_dir, high_pv=high_pv)
    _write_literature_bundle(case_dir)


def _write_pair_fixture(pair_dir: Path) -> None:
    pair_dir.mkdir()
    _write_case(pair_dir, "sunny")
    _write_case(pair_dir, "rain")
    _write_json(
        pair_dir / "assignment_difference.json",
        {"assignment_hashes_equal": False, "changed_trip_count": 1},
    )
    _write_csv(
        pair_dir / "solver_comparison.csv",
        ["case", "certified_gap"],
        [
            {"case": "sunny", "certified_gap": 0.007},
            {"case": "rain", "certified_gap": 0.004},
        ],
    )
    metric_rows = []
    values = {
        "PV generation": ("kWh", 1200.0, 240.0),
        "Grid import": ("kWh", 48.0, 48.0),
        "PV to bus": ("kWh", 240.0, 48.0),
        "PV to BESS": ("kWh", 600.0, 120.0),
        "BESS to bus": ("kWh", 120.0, 120.0),
        "PV curtailed": ("kWh", 360.0, 72.0),
        "Used BEV": ("vehicles", 2, 1),
        "Used ICE": ("vehicles", 0, 1),
        "BEV trips": ("trips", 2, 1),
        "ICE trips": ("trips", 0, 1),
        "Fuel consumption": ("L", 0.0, 10.0),
        "Electricity cost": ("JPY", 1440.0, 1440.0),
        "Fuel cost": ("JPY", 0.0, 1500.0),
        "Demand charge": ("JPY", 0.0, 0.0),
        "Total cost": ("JPY", 41464.0, 43020.0),
        "CO2": ("kgCO2", 24.0, 80.0),
        "Certified MILP gap": ("ratio", 0.007, 0.004),
    }
    for metric, (unit, sunny, rain) in values.items():
        metric_rows.append(
            {
                "metric": metric,
                "unit": unit,
                "sunny": sunny,
                "rain": rain,
                "rain_minus_sunny": rain - sunny,
                "sunny_source_artifact": "sunny/source.json",
                "rain_source_artifact": "rain/source.json",
            }
        )
    _write_csv(
        pair_dir / "research_comparison.csv",
        list(metric_rows[0]),
        metric_rows,
    )
    case_checks = {
        check: True
        for check in _load_builder().REQUIRED_CASE_GATE_KEYS
    }
    _write_json(
        pair_dir / "case_gate_audits.json",
        {
            case: {
                "accepted": True,
                "checks": case_checks,
                "failed_checks": [],
            }
            for case in ("sunny", "rain")
        },
    )
    _write_json(
        pair_dir / "pair" / "pair_control_audit.json",
        {
            "accepted": True,
            "checks": {
                check: True
                for check in _load_builder().REQUIRED_PAIR_GATE_KEYS
            },
            "controls": {
                "service_date": {
                    "sunny": "2025-08-05",
                    "rain": "2025-08-05",
                    "match": True,
                },
                "git_sha": {
                    "sunny": "a" * 40,
                    "rain": "a" * 40,
                    "match": True,
                },
            },
            "comparison_control_hash": "b" * 64,
        },
    )
    _write_json(
        pair_dir / "pair" / "pair_manifest.json",
        {
            "accepted_for_controlled_pv_sensitivity_comparison": True,
            "formal_research_submission_ready": True,
            "git_sha": "a" * 40,
        },
    )


def test_progress_report_builder_exports_complete_lineage_bundle(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    pair_dir = tmp_path / "pair-evidence"
    _write_pair_fixture(pair_dir)
    source_hashes = {
        path.relative_to(pair_dir): _sha256(path)
        for path in pair_dir.rglob("*")
        if path.is_file()
    }

    manifest = builder.build_progress_report(pair_dir)

    assert manifest["status"] == "READY"
    assert manifest["bundle_complete"] is True
    assert manifest["figure_count"] == 7
    assert manifest["figure_format_count"] == 14
    assert manifest["table_count"] == 6
    assert manifest["per_run_detailed_figure_count"] == 10
    assert manifest["pair_formal_research_submission_ready"] is True
    assert manifest["standalone_case_statuses"]["sunny"] == {
        "teacher_release_status": "BLOCKED",
        "failed_checks": ["controlled_counterfactual_pair_not_verified"],
    }
    report_dir = pair_dir / "progress_report"
    for stem in (
        "00_progress_summary",
        "01_fleet_and_trip_composition",
        "02_energy_flow_comparison",
        "03_hourly_energy_profiles",
        "04_cost_breakdown_comparison",
        "05_fuel_and_emissions",
        "06_solver_and_acceptance",
    ):
        assert (report_dir / f"{stem}.png").stat().st_size > 0
        assert (report_dir / f"{stem}.svg").stat().st_size > 0
    outcome_rows = _read_csv_for_test(report_dir / "02_outcome_kpis.csv")
    assert [row["used_bev"] for row in outcome_rows] == ["2", "1"]
    hourly_rows = _read_csv_for_test(
        report_dir / "04_hourly_energy_comparison.csv"
    )
    assert len(hourly_rows) == 48
    gate_rows = _read_csv_for_test(
        report_dir / "03_validation_gate_matrix.csv"
    )
    assert all(row["passed"] == "True" for row in gate_rows)
    evidence_index = json.loads(
        (report_dir / "evidence_index.json").read_text(encoding="utf-8")
    )
    source_paths = {
        row["path"] for row in evidence_index["source_artifacts"]
    }
    assert "sunny/results.xlsx" in source_paths
    assert "rain/graph/literature_figures/01_figure.png" in source_paths
    assert {
        path: _sha256(pair_dir / path) for path in source_hashes
    } == source_hashes
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        builder.build_progress_report(pair_dir)


def test_progress_report_rejects_manifest_path_escape(tmp_path: Path) -> None:
    builder = _load_builder()
    parent = tmp_path / "figures"
    parent.mkdir()

    with pytest.raises(ValueError, match="escapes its declared directory"):
        builder._safe_child(parent, "../outside.csv")


def _read_csv_for_test(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
