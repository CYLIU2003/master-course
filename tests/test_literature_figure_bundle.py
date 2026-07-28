from __future__ import annotations

import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from bff.services.optimization_run import literature_figures
from bff.services.optimization_run.artifact_completeness import (
    _validate_literature_artifact_integrity,
)
from bff.services.optimization_run.literature_figures import (
    LiteratureFigureError,
    generate_literature_figure_bundle,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    graph_dir = run_dir / "graph"
    rolling_dir = run_dir / "rolling_hourly_chain"
    _write_json(
        graph_dir / "manifest.json",
        {"files": [], "optional_exports": {}},
    )
    _write_json(
        rolling_dir / "executed_day_accounting.json",
        {
            "eligible": True,
            "expected_slot_count": 4,
            "executed_slot_count": 4,
            "cost_breakdown": {
                "pv_generated_kwh": 75.0,
                "grid_import_kwh": 15.0,
                "bus_charge_kwh": 58.0,
                "fuel_consumption_l": 4.5,
                "total_cost_jpy": 12345.0,
            },
        },
    )
    _write_json(
        run_dir / "physical_schedule_validation.json",
        {
            "accepted": True,
            "status": "VALID",
            "validation_metrics": {
                "unassigned_trip_count": 0,
                "duplicate_trip_count": 0,
                "vehicle_time_overlap_count": 0,
                "charger_conflict_count": 0,
                "ev_soc_lower_violation_count": 0,
            },
        },
    )
    _write_json(
        run_dir / "scenario_fleet_contract.json",
        {
            "active_inventory_by_powertrain": {"BEV": 1, "ICE": 1},
            "active_vehicle_parameters": [
                {
                    "vehicle_id": "bev-1",
                    "vehicle_type": "BEV",
                    "powertrain": "BEV",
                    "depot_id": "depot-a",
                    "initial_soc_kwh": 120.0,
                    "battery_capacity_kwh": 200.0,
                    "energy_consumption_kwh_per_km": 1.0,
                    "max_charge_power_kw": 90.0,
                    "available": True,
                },
                {
                    "vehicle_id": "ice-1",
                    "vehicle_type": "ICE",
                    "powertrain": "ICE",
                    "depot_id": "depot-a",
                    "initial_fuel_l": 100.0,
                    "fuel_consumption_l_per_km": 0.3,
                    "available": True,
                },
            ],
            "excluded_vehicle_records": [
                {
                    "vehicle_id": "bev-maintenance",
                    "reason": "available_false",
                }
            ],
        },
    )
    _write_json(
        graph_dir / "canonical_cost_ledger.json",
        {
            "source": (
                "rolling_hourly_chain/executed_day_accounting.json"
            ),
            "accounting_residual_satisfied": True,
            "accounting_total_cost_jpy": 12345.0,
            "components": {
                "electricity_cost_jpy": 500.0,
                "fuel_cost_jpy": 900.0,
                "demand_charge_cost_jpy": 45.0,
                "vehicle_usage_cost_jpy": 10900.0,
            },
            "co2": {
                "grid_co2_kg": 6.0,
                "ice_co2_kg": 11.61,
                "total_co2_kg": 17.61,
            },
        },
    )
    _write_json(
        run_dir / "research_claim_scope.json",
        {
            "research_submission_ready": False,
            "teacher_release_status": "BLOCKED",
            "teacher_release_failed_checks": ["gap_target_not_met"],
        },
    )

    _write_csv(
        graph_dir / "vehicle_event_timeline.csv",
        [
            {
                "event_id": "bev-service",
                "vehicle_id": "bev-1",
                "event_type": "service_trip",
                "start_min": 360,
                "end_min": 420,
                "start_location": "depot-a",
                "end_location": "stop-a",
                "distance_km": 20.0,
                "energy_kwh": 20.0,
                "fuel_l": 0.0,
                "trip_id": "trip-1",
                "charger_id": "",
                "power_kw": 0.0,
                "power_limit_kw": 0.0,
                "source_artifact": "executed",
            },
            {
                "event_id": "bev-charge",
                "vehicle_id": "bev-1",
                "event_type": "charging",
                "start_min": 720,
                "end_min": 780,
                "start_location": "depot-a",
                "end_location": "depot-a",
                "distance_km": 0.0,
                "energy_kwh": 45.0,
                "fuel_l": 0.0,
                "trip_id": "",
                "charger_id": "charger-1",
                "power_kw": 45.0,
                "power_limit_kw": 90.0,
                "source_artifact": "executed",
            },
            {
                "event_id": "ice-service",
                "vehicle_id": "ice-1",
                "event_type": "service_trip",
                "start_min": 480,
                "end_min": 555,
                "start_location": "depot-a",
                "end_location": "depot-a",
                "distance_km": 15.0,
                "energy_kwh": 0.0,
                "fuel_l": 4.5,
                "trip_id": "trip-2",
                "charger_id": "",
                "power_kw": 0.0,
                "power_limit_kw": 0.0,
                "source_artifact": "executed",
            },
        ],
    )
    _write_csv(
        graph_dir / "vehicle_soc_event_timeline.csv",
        [
            {
                "vehicle_id": "bev-1",
                "event_id": "bev-initial",
                "event_type": "initial_state",
                "time_min": 0,
                "soc_before_kwh": 120.0,
                "soc_after_kwh": 120.0,
                "soc_before_percent": 60.0,
                "soc_after_percent": 60.0,
                "reserve_soc_kwh": 30.0,
                "reserve_soc_percent": 15.0,
                "battery_capacity_kwh": 200.0,
                "charging_efficiency": 0.95,
                "source_artifact": "independent_validation",
            },
            {
                "vehicle_id": "bev-1",
                "event_id": "bev-service",
                "event_type": "service_trip",
                "time_min": 420,
                "soc_before_kwh": 120.0,
                "soc_after_kwh": 100.0,
                "soc_before_percent": 60.0,
                "soc_after_percent": 50.0,
                "reserve_soc_kwh": 30.0,
                "reserve_soc_percent": 15.0,
                "battery_capacity_kwh": 200.0,
                "charging_efficiency": 0.95,
                "source_artifact": "independent_validation",
            },
            {
                "vehicle_id": "bev-1",
                "event_id": "bev-charge",
                "event_type": "charging",
                "time_min": 780,
                "soc_before_kwh": 100.0,
                "soc_after_kwh": 142.75,
                "soc_before_percent": 50.0,
                "soc_after_percent": 71.375,
                "reserve_soc_kwh": 30.0,
                "reserve_soc_percent": 15.0,
                "battery_capacity_kwh": 200.0,
                "charging_efficiency": 0.95,
                "source_artifact": "independent_validation",
            },
        ],
    )
    _write_csv(
        graph_dir / "charger_occupancy_timeline.csv",
        [
            {
                "event_id": "bev-charge",
                "vehicle_id": "bev-1",
                "charger_id": "charger-1",
                "depot_id": "depot-a",
                "start_min": 720,
                "end_min": 780,
                "energy_kwh": 45.0,
                "power_kw": 45.0,
                "power_limit_kw": 90.0,
                "source_artifact": "executed",
            }
        ],
    )
    hourly_rows: list[dict] = []
    co2_rows: list[dict] = []
    cost_rows: list[dict] = []
    for step, hour in enumerate((0, 6, 12, 18)):
        timestamp = f"2025-08-05T{hour:02d}:00:00"
        hourly_rows.append(
            {
                "step_index": step,
                "current_time": timestamp,
                "execution_minutes": 60,
                "pv_generated_kwh": 30.0 if hour == 12 else 15.0,
                "pv_to_bus_kwh": 12.0 if hour == 12 else 3.0,
                "pv_to_bess_kwh": 10.0 if hour == 12 else 2.0,
                "pv_curtailed_kwh": 0.0,
                "bess_to_bus_kwh": 5.0,
                "grid_to_bus_kwh": 1.0,
                "grid_to_bess_kwh": 0.0,
                "bess_end_soc_kwh_by_depot": json.dumps(
                    {"depot-a": 100.0 + step * 5.0}
                ),
            }
        )
        co2_rows.append(
            {
                "timestamp": timestamp,
                "grid_emission_factor_kg_per_kwh": 0.4 + step * 0.02,
                "grid_co2_kg": 0.4 + step * 0.02,
                "ice_co2_kg": 2.9025,
                "total_co2_kg": 3.3025 + step * 0.02,
            }
        )
        cost_rows.append(
            {
                "time": timestamp,
                "grid_energy_price_yen_per_kwh": 18 + step,
                "grid_purchase_cost_jpy": 18 + step,
                "fuel_cost_jpy": 225.0,
                "total_cost_jpy": 243.0 + step,
            }
        )
    _write_csv(rolling_dir / "hourly_energy_flow_chart.csv", hourly_rows)
    _write_csv(
        run_dir / "vehicle_schedule.csv",
        [
            {
                "vehicle_id": "bev-1",
                "trip_id": "trip-1",
                "departure_time": "06:00",
                "arrival_time": "07:00",
            },
            {
                "vehicle_id": "ice-1",
                "trip_id": "trip-2",
                "departure_time": "08:00",
                "arrival_time": "09:15",
            },
        ],
    )
    _write_csv(
        rolling_dir / "charging_schedule.csv",
        [
            {
                "vehicle_id": "bev-1",
                "charger_id": "charger-1",
                "time": "2025-08-05T12:00:00",
                "charge_kw": 45.0,
                "energy_source": "pv",
            }
        ],
    )
    _write_csv(graph_dir / "co2_timeseries.csv", co2_rows)
    _write_csv(graph_dir / "cost_timeseries.csv", cost_rows)
    return run_dir


def test_generates_literature_figures_and_analysis_ready_csv_bundle(
    tmp_path: Path,
) -> None:
    run_dir = _fixture_run(tmp_path)

    manifest = generate_literature_figure_bundle(run_dir)

    output_dir = run_dir / "graph" / "literature_figures"
    assert manifest["status"] == "READY"
    assert manifest["figure_count"] == 5
    assert manifest["diagnostic_only"] is True
    assert manifest["raw_data_csv_count"] == 16
    for entry in manifest["entries"]:
        for relative_path in entry["artifact_files"]:
            artifact = output_dir / relative_path
            assert artifact.is_file()
            assert artifact.stat().st_size > 0
            if artifact.suffix == ".png":
                with Image.open(artifact) as image:
                    assert image.width >= 900
                    assert image.height >= 500
            if artifact.suffix == ".svg":
                ET.parse(artifact)
    catalog = list(
        csv.DictReader(
            (
                output_dir / "raw_data" / "raw_data_catalog.csv"
            ).open(encoding="utf-8-sig")
        )
    )
    assert len(catalog) == 15
    assert {
        row["data_level"] for row in catalog
    } >= {"canonical_copy", "canonical_json_to_csv"}
    eligibility = list(
        csv.DictReader(
            (output_dir / "figure_eligibility.csv").open(
                encoding="utf-8-sig"
            )
        )
    )
    uncertainty = next(
        row
        for row in eligibility
        if row["literature_output_family"]
        == "Monte Carlo uncertainty distribution"
    )
    assert uncertainty["single_run_status"] == (
        "REQUIRES_MULTI_RUN_EXPERIMENT"
    )
    graph_manifest = json.loads(
        (run_dir / "graph" / "manifest.json").read_text(encoding="utf-8")
    )
    literature_export = graph_manifest["optional_exports"][
        "literature_figures"
    ]
    assert literature_export["enabled"] is True
    assert (
        literature_export["manifest_file"]
        == "literature_figures/manifest.json"
    )
    integrity_errors: list[str] = []
    _validate_literature_artifact_integrity(
        run_dir=run_dir,
        manifest_path=output_dir / "manifest.json",
        manifest=manifest,
        content_errors=integrity_errors,
    )
    assert integrity_errors == []


def test_charger_figure_preserves_simultaneous_ports_and_total_power(
    tmp_path: Path,
) -> None:
    run_dir = _fixture_run(tmp_path)
    charger_path = run_dir / "graph" / "charger_occupancy_timeline.csv"
    _write_csv(
        charger_path,
        [
            {
                "event_id": "bev-1-charge",
                "vehicle_id": "bev-1",
                "charger_id": "charger-1",
                "depot_id": "depot-a",
                "start_min": 720,
                "end_min": 780,
                "energy_kwh": 45.0,
                "power_kw": 45.0,
                "power_limit_kw": 90.0,
                "source_artifact": "executed",
            },
            {
                "event_id": "bev-2-charge",
                "vehicle_id": "bev-2",
                "charger_id": "charger-1",
                "depot_id": "depot-a",
                "start_min": 720,
                "end_min": 780,
                "energy_kwh": 30.0,
                "power_kw": 30.0,
                "power_limit_kw": 90.0,
                "source_artifact": "executed",
            },
        ],
    )

    manifest = generate_literature_figure_bundle(run_dir)

    source_rows = list(
        csv.DictReader(
            (
                run_dir
                / "graph"
                / "literature_figures"
                / "04_charger_occupancy_heatmap_source.csv"
            ).open(encoding="utf-8-sig")
        )
    )
    occupied = next(
        row
        for row in source_rows
        if row["charger_id"] == "charger-1"
        and int(row["start_min"]) == 720
    )
    assert int(occupied["occupied_port_count"]) == 2
    assert float(occupied["total_power_kw"]) == pytest.approx(75.0)
    charger_entry = next(
        entry
        for entry in manifest["entries"]
        if entry.get("figure_id") == "charger_occupancy_heatmap"
    )
    assert (
        charger_entry["metrics"]["maximum_simultaneous_occupied_ports"]
        == 2
    )
    assert charger_entry["metrics"][
        "peak_aggregate_charging_power_kw"
    ] == pytest.approx(75.0)


def test_energy_figure_preserves_depot_specific_price_signals(
    tmp_path: Path,
) -> None:
    run_dir = _fixture_run(tmp_path)
    cost_path = run_dir / "graph" / "cost_timeseries.csv"
    existing_rows = list(
        csv.DictReader(cost_path.open(encoding="utf-8-sig"))
    )
    multi_depot_rows: list[dict] = []
    for row in existing_rows:
        multi_depot_rows.append({**row, "depot_id": "depot-a"})
        multi_depot_rows.append(
            {
                **row,
                "depot_id": "depot-b",
                "grid_energy_price_yen_per_kwh": (
                    float(row["grid_energy_price_yen_per_kwh"]) + 5.0
                ),
            }
        )
    _write_csv(cost_path, multi_depot_rows)

    manifest = generate_literature_figure_bundle(run_dir)

    source_rows = list(
        csv.DictReader(
            (
                run_dir
                / "graph"
                / "literature_figures"
                / "03_energy_management_profile_source.csv"
            ).open(encoding="utf-8-sig")
        )
    )
    prices = json.loads(source_rows[0]["grid_energy_price_by_depot_json"])
    assert set(prices) == {"depot-a", "depot-b"}
    assert source_rows[0]["grid_energy_price_yen_per_kwh"] == ""
    energy_entry = next(
        entry
        for entry in manifest["entries"]
        if entry.get("figure_id") == "energy_management_profile"
    )
    assert energy_entry["metrics"]["price_depot_count"] == 2


def test_unreadable_local_literature_file_is_recorded_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = literature_figures._LITERATURE_REFERENCES[0]
    reference_path = tmp_path / str(reference["relative_path"])
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_bytes(b"reference")
    original_sha256 = literature_figures._sha256

    def _raise_for_reference(path: Path) -> str:
        if path == reference_path:
            raise PermissionError("locked for review")
        return original_sha256(path)

    monkeypatch.setattr(literature_figures, "_sha256", _raise_for_reference)

    rows = literature_figures._literature_reference_rows(tmp_path)

    affected = next(
        row
        for row in rows
        if row["reference_id"] == reference["reference_id"]
    )
    assert affected["local_file_available"] is False
    assert affected["local_file_hash_status"] == "ERROR"
    assert "PermissionError" in affected["local_file_hash_error"]


def test_rejects_unaccepted_physical_schedule(tmp_path: Path) -> None:
    run_dir = _fixture_run(tmp_path)
    _write_json(
        run_dir / "physical_schedule_validation.json",
        {"accepted": False, "validation_metrics": {}},
    )

    with pytest.raises(
        LiteratureFigureError,
        match="accepted physical schedule",
    ):
        generate_literature_figure_bundle(run_dir)
