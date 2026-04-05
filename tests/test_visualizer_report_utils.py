from __future__ import annotations

import json
from pathlib import Path

from tools._visualizer_report_utils import (
    build_professor_report_markdown,
    build_solver_comparison_markdown,
    collect_run_meta,
    collect_run_metas_from_report_bundle,
    export_route_band_diagram_assets,
    parse_run_path,
    resolve_run_dir_input,
    write_solver_comparison_exports,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_parse_run_path_supports_new_scenario_layout() -> None:
    run_dir = Path(
        "C:/master-course/output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/mode_alns_only/tsurumaki/WEEKDAY/run_20260405_1713"
    )

    parsed = parse_run_path(run_dir)

    assert parsed["date"] == "2025-08-04"
    assert parsed["scenario_id"] == "237d5623-aa94-4f72-9da1-17b9070264be"
    assert parsed["mode"] == "mode_alns_only"
    assert parsed["depot"] == "tsurumaki"
    assert parsed["service"] == "WEEKDAY"
    assert parsed["run_id"] == "run_20260405_1713"


def test_collect_run_metas_from_report_bundle_reads_comparison_rows_and_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "2025-08-04" / "scenario" / "scenario-1" / "mode_milp_only" / "dep-1" / "WEEKDAY" / "run_20260405_1708"
    _write_json(
        run_dir / "optimization_result.json",
        {
            "scenario_id": "scenario-1",
            "prepared_input_id": "prepared-1",
            "objective_mode": "total_cost",
            "scope": {"depotId": "dep-1", "serviceId": "WEEKDAY"},
            "summary": {
                "trip_count_served": 10,
                "trip_count_unserved": 0,
                "vehicle_count_used": 2,
            },
            "cost_breakdown": {
                "total_cost": 123.4,
                "total_co2_kg": 56.7,
            },
        },
    )
    _write_json(
        run_dir / "canonical_solver_result.json",
        {
            "solver_status": "time_limit_baseline",
            "termination_reason": "time_limit",
            "metadata": {"source": "dispatch_baseline_after_time_limit_no_incumbent"},
            "solver_metadata": {"supports_exact_milp": False},
            "objective_value": 123.4,
        },
    )
    _write_json(run_dir / "summary.json", {"solver_status": "time_limit_baseline", "objective_value": 123.4, "solve_time_seconds": 300.0})
    _write_json(run_dir / "cost_breakdown_detail.json", {"total_operating_cost": 123.4})
    _write_json(run_dir / "co2_breakdown.json", {"total_co2_kg": 56.7})

    report_dir = tmp_path / "output" / "reports" / "bundle-1"
    _write_json(
        report_dir / "comparison.json",
        [
            {
                "mode": "milp",
                "run_dir": str(run_dir),
                "solver_status": "time_limit_baseline",
                "objective_value": 123.4,
                "solve_time_seconds": 300.0,
                "trip_count_served": 10,
                "trip_count_unserved": 0,
                "vehicle_count_used": 2,
                "supports_exact_milp": False,
                "termination_reason": "time_limit",
                "plan_source": "dispatch_baseline_after_time_limit_no_incumbent",
            }
        ],
    )
    _write_json(
        report_dir / "run_manifest.json",
        {
            "scenario_id": "scenario-1",
            "prepared_input_id": "prepared-1",
            "depot_id": "dep-1",
            "service_id": "WEEKDAY",
            "objective_mode": "total_cost",
        },
    )

    metas = collect_run_metas_from_report_bundle(report_dir)

    assert len(metas) == 1
    meta = metas[0]
    assert meta.source_kind == "report_bundle"
    assert meta.report_bundle_name == "bundle-1"
    assert meta.mode == "milp"
    assert meta.prepared_input_id == "prepared-1"
    assert meta.trip_count_served == 10
    assert meta.trip_count_unserved == 0
    assert meta.vehicle_count_used == 2
    assert meta.exactness_label == "fallback"


def test_resolve_run_dir_input_picks_best_objective_from_report_bundle_and_professor_report_mentions_exactness(tmp_path: Path) -> None:
    run_dir_a = tmp_path / "output" / "2025-08-04" / "scenario" / "scenario-1" / "mode_ga_only" / "dep-1" / "WEEKDAY" / "run_a"
    run_dir_b = tmp_path / "output" / "2025-08-04" / "scenario" / "scenario-1" / "mode_alns_only" / "dep-1" / "WEEKDAY" / "run_b"
    for run_dir, total_cost in ((run_dir_a, 200.0), (run_dir_b, 150.0)):
        _write_json(
            run_dir / "optimization_result.json",
            {
                "scenario_id": "scenario-1",
                "prepared_input_id": "prepared-1",
                "objective_mode": "total_cost",
                "scope": {"depotId": "dep-1", "serviceId": "WEEKDAY"},
                "summary": {"trip_count_served": 10, "trip_count_unserved": 0, "vehicle_count_used": 2},
                "cost_breakdown": {"total_cost": total_cost, "total_co2_kg": 10.0},
            },
        )
        _write_json(run_dir / "summary.json", {"solver_status": "feasible", "objective_value": total_cost, "solve_time_seconds": 100.0})
        _write_json(run_dir / "cost_breakdown_detail.json", {"total_operating_cost": total_cost})
        _write_json(run_dir / "co2_breakdown.json", {"total_co2_kg": 10.0})

    report_dir = tmp_path / "output" / "reports" / "bundle-2"
    _write_json(
        report_dir / "comparison.json",
        [
            {
                "mode": "ga",
                "run_dir": str(run_dir_a),
                "solver_status": "feasible",
                "objective_value": 200.0,
                "solve_time_seconds": 100.0,
                "trip_count_served": 10,
                "trip_count_unserved": 0,
                "vehicle_count_used": 2,
                "termination_reason": "time_limit_or_early_stop",
                "plan_source": "dispatch_pooled_shared_path_cover_baseline",
            },
            {
                "mode": "alns",
                "run_dir": str(run_dir_b),
                "solver_status": "feasible",
                "objective_value": 150.0,
                "solve_time_seconds": 100.0,
                "trip_count_served": 10,
                "trip_count_unserved": 0,
                "vehicle_count_used": 2,
                "termination_reason": "time_limit_or_early_stop",
                "plan_source": "dispatch_pooled_shared_path_cover_baseline",
            },
        ],
    )
    _write_json(
        report_dir / "run_manifest.json",
        {
            "scenario_id": "scenario-1",
            "prepared_input_id": "prepared-1",
            "depot_id": "dep-1",
            "service_id": "WEEKDAY",
            "objective_mode": "total_cost",
        },
    )

    resolved_run_dir, metadata = resolve_run_dir_input(report_dir)
    metas = collect_run_metas_from_report_bundle(report_dir)
    markdown = build_professor_report_markdown(metas, title="教授向けシナリオ報告")

    assert resolved_run_dir == run_dir_b
    assert metadata["input_kind"] == "report_bundle"
    assert metadata["selected_run_id"] == "run_b"
    assert "best_objective_run" in markdown
    assert "metaheuristic" in markdown
    assert "prepared-1" in markdown


def test_collect_run_meta_loads_external_simulation_result_and_professor_report_mentions_it(tmp_path: Path, monkeypatch) -> None:
    run_dir = (
        tmp_path
        / "output"
        / "2025-08-04"
        / "scenario"
        / "scenario-1"
        / "mode_alns_only"
        / "dep-1"
        / "WEEKDAY"
        / "run_20260405_1713"
    )
    _write_json(
        run_dir / "optimization_result.json",
        {
            "scenario_id": "scenario-1",
            "feed_context": {"feedId": "tokyu", "snapshotId": "2026-03-23"},
            "prepared_input_id": "prepared-1",
            "objective_mode": "total_cost",
            "scope": {"depotId": "dep-1", "serviceId": "WEEKDAY"},
            "prepared_scope_summary": {
                "service_date": "2025-08-04",
                "planning_days": 1,
                "route_ids": ["r1", "r2"],
            },
            "build_report": {"vehicle_count": 12, "charger_count": 3},
            "summary": {
                "trip_count_served": 10,
                "trip_count_unserved": 0,
                "vehicle_count_used": 2,
            },
            "cost_breakdown": {
                "total_cost": 123.4,
                "total_co2_kg": 56.7,
            },
        },
    )
    _write_json(
        run_dir / "summary.json",
        {"solver_status": "feasible", "objective_value": 123.4, "solve_time_seconds": 100.0},
    )
    _write_json(run_dir / "cost_breakdown_detail.json", {"total_operating_cost": 123.4})
    _write_json(run_dir / "co2_breakdown.json", {"total_co2_kg": 56.7})
    simulation_dir = (
        tmp_path
        / "output"
        / "tokyu"
        / "2026-03-23"
        / "simulation"
        / "scenario-1"
        / "dep-1"
        / "WEEKDAY"
    )
    _write_json(
        simulation_dir / "simulation_result.json",
        {
            "scenario_id": "scenario-1",
            "source": "optimization_result",
            "total_distance_km": 88.0,
            "total_energy_kwh": 55.0,
            "feasibility_violations": [],
            "simulation_summary": {
                "feasible": True,
                "total_operating_cost": 123.4,
                "total_co2_kg": 56.7,
            },
        },
    )
    monkeypatch.setenv("MC_OUTPUTS_DIR", str(tmp_path / "output"))

    meta = collect_run_meta(run_dir)
    markdown = build_professor_report_markdown([meta], title="教授向けシナリオ報告")

    assert meta.mode == "alns"
    assert meta.service_date == "2025-08-04"
    assert meta.route_count == 2
    assert meta.vehicle_count_available == 12
    assert meta.charger_count_available == 3
    assert meta.simulation_result_path == simulation_dir / "simulation_result.json"
    assert meta.simulation_source == "optimization_result"
    assert meta.simulation_feasible is True
    assert meta.simulation_total_distance_km == 88.0
    assert "simulation_result_path" in markdown
    assert "candidate_vehicle_count" in markdown
    assert "linked_run" in markdown
    assert "best_run_route_band_diagrams" in markdown


def test_solver_comparison_and_route_band_exports_write_explicit_files(tmp_path: Path) -> None:
    report_dir = tmp_path / "output" / "reports" / "bundle-3"
    metas = []
    for mode, objective_value in (("mode_milp_only", 120.0), ("mode_alns_only", 100.0)):
        run_dir = (
            tmp_path
            / "output"
            / "2025-08-04"
            / "scenario"
            / "scenario-1"
            / mode
            / "dep-1"
            / "WEEKDAY"
            / f"run_{mode}"
        )
        _write_json(
            run_dir / "optimization_result.json",
            {
                "scenario_id": "scenario-1",
                "prepared_input_id": "prepared-1",
                "objective_mode": "total_cost",
                "scope": {"depotId": "dep-1", "serviceId": "WEEKDAY"},
                "summary": {
                    "trip_count_served": 10,
                    "trip_count_unserved": 0,
                    "vehicle_count_used": 2,
                },
                "cost_breakdown": {
                    "total_cost": objective_value,
                    "total_co2_kg": 10.0,
                },
            },
        )
        _write_json(
            run_dir / "summary.json",
            {
                "solver_status": "feasible",
                "objective_value": objective_value,
                "solve_time_seconds": 100.0,
            },
        )
        _write_json(run_dir / "cost_breakdown_detail.json", {"total_operating_cost": objective_value})
        _write_json(run_dir / "co2_breakdown.json", {"total_co2_kg": 10.0})
        route_band_dir = run_dir / "graph" / "route_band_diagrams"
        _write_json(
            route_band_dir / "manifest.json",
            {
                "entries": [
                    {"band_id": "渋24", "diagram_file": "渋24.svg"},
                ]
            },
        )
        (route_band_dir / "渋24.svg").write_text("<svg/>", encoding="utf-8")
        metas.append(collect_run_meta(run_dir))

    table_paths = write_solver_comparison_exports(metas, report_dir)
    route_band_export = export_route_band_diagram_assets(metas, report_dir)
    markdown = build_solver_comparison_markdown(metas, title="4 Solver Comparison")

    assert table_paths["csv_path"].exists()
    assert table_paths["markdown_path"].exists()
    assert "served / total" in markdown
    assert "route-band dir" in markdown
    assert route_band_export["manifest_path"].exists()
    assert (report_dir / "graph" / "route_band_diagrams" / "渋24.svg").exists()
    assert (report_dir / "solver_route_band_diagrams" / "alns_run_mode_alns_only" / "渋24.svg").exists()
