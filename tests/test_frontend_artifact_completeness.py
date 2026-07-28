from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openpyxl import Workbook

from bff.routers import optimization
from bff.services.optimization_run.artifact_completeness import (
    audit_frontend_run_artifacts,
    required_frontend_artifacts,
)


def _write_artifact(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text("{}\n", encoding="utf-8")
    elif path.suffix == ".xlsx":
        workbook = Workbook()
        workbook.active.title = "summary"
        workbook.create_sheet("cost_breakdown")
        workbook.create_sheet("release_status")
        workbook.save(path)
    elif path.suffix == ".csv":
        path.write_text("key,value\n", encoding="utf-8")
    else:
        path.write_text("artifact\n", encoding="utf-8")


def _artifact_record(path: Path, *, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _complete_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    required = required_frontend_artifacts(
        research_run=True,
        require_rolling=True,
    )
    for relative_path in required:
        if relative_path == "run_manifest.json":
            continue
        _write_artifact(run_dir / relative_path)

    graph_manifest = {
        "files": ["declared_graph_artifact.csv"],
        "optional_exports": {},
    }
    (run_dir / "graph" / "manifest.json").write_text(
        json.dumps(graph_manifest),
        encoding="utf-8",
    )
    _write_artifact(run_dir / "graph" / "declared_graph_artifact.csv")
    literature_entries = []
    literature_dir = run_dir / "graph" / "literature_figures"
    for index in range(5):
        artifact_files = [
            f"{index:02d}_figure.png",
            f"{index:02d}_figure.svg",
            f"{index:02d}_figure_source.csv",
        ]
        for artifact_file in artifact_files:
            _write_artifact(literature_dir / artifact_file)
        literature_entries.append(
            {
                "kind": "figure",
                "figure_id": f"figure-{index}",
                "artifact_files": artifact_files,
                "canonical_sources": ["scenario_fleet_contract.json"],
                "artifact_records": [
                    _artifact_record(
                        literature_dir / artifact_file,
                        root=literature_dir,
                    )
                    for artifact_file in artifact_files
                ],
            }
        )
    raw_data_files = [
        f"raw_data/{index:02d}_dataset.csv" for index in range(15)
    ] + ["raw_data/raw_data_catalog.csv"]
    for artifact_file in raw_data_files:
        _write_artifact(literature_dir / artifact_file)
    literature_entries.append(
        {
            "kind": "raw_data_bundle",
            "figure_id": "analysis_ready_raw_data",
            "artifact_files": raw_data_files,
            "canonical_sources": ["scenario_fleet_contract.json"],
            "artifact_records": [
                _artifact_record(
                    literature_dir / artifact_file,
                    root=literature_dir,
                )
                for artifact_file in raw_data_files
            ],
        }
    )
    source_path = run_dir / "scenario_fleet_contract.json"
    (literature_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "literature_figure_bundle_v1",
                "status": "READY",
                "figure_count": 5,
                "raw_data_csv_count": 16,
                "raw_data_catalog": "raw_data/raw_data_catalog.csv",
                "entries": literature_entries,
                "source_artifacts": {
                    "scenario_fleet_contract.json": _artifact_record(
                        source_path,
                        root=run_dir,
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    graph_manifest["optional_exports"] = {
        "literature_figures": {
            "enabled": True,
            "manifest_file": "literature_figures/manifest.json",
        }
    }
    (run_dir / "graph" / "manifest.json").write_text(
        json.dumps(graph_manifest),
        encoding="utf-8",
    )

    rolling_dir = run_dir / "rolling_hourly_chain"
    rolling_summary = {
        "expected_step_count": 2,
        "step_count": 2,
        "chain_accepted": True,
        "all_steps_feasible": True,
    }
    (rolling_dir / "rolling_chain_summary.json").write_text(
        json.dumps(rolling_summary),
        encoding="utf-8",
    )
    (rolling_dir / "executed_day_accounting.json").write_text(
        json.dumps(
            {
                "eligible": True,
                "expected_slot_count": 4,
                "executed_slot_count": 4,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "physical_schedule_validation.json").write_text(
        json.dumps({"accepted": True}),
        encoding="utf-8",
    )
    (run_dir / "final_cost_reconciliation.json").write_text(
        json.dumps({"status": "OK"}),
        encoding="utf-8",
    )
    for index in range(2):
        step_dir = rolling_dir / f"step_{index:02d}_{index:02d}00"
        step_files = [
            "hourly_solver_result.json",
            "hourly_summary.json",
        ]
        if index == 0:
            step_files.append("state_for_next_hour.json")
        for filename in step_files:
            _write_artifact(step_dir / filename)

    declared_files = sorted(
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "research_run": True,
                "research_claim_scope": {
                    "run_profile": "day_ahead_and_hourly_rolling"
                },
                "files": declared_files,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_complete_frontend_run_artifact_contract_passes(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "OK"
    assert audit["accepted"] is True
    assert audit["missing_artifacts"] == []
    assert audit["content_errors"] == []
    assert (
        audit["required_artifact_count"]
        == audit["verified_artifact_count"]
    )


def test_literature_artifact_hash_mismatch_fails_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    artifact = (
        run_dir
        / "graph"
        / "literature_figures"
        / "00_figure_source.csv"
    )
    artifact.write_text("key,value\ntampered,1\n", encoding="utf-8")

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert any(
        "sha256 mismatch for 00_figure_source.csv" in error
        for error in audit["content_errors"]
    )


def test_literature_source_hash_mismatch_fails_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (run_dir / "scenario_fleet_contract.json").write_text(
        '{"changed": true}\n',
        encoding="utf-8",
    )

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert any(
        "sha256 mismatch for scenario_fleet_contract.json" in error
        for error in audit["content_errors"]
    )


def test_literature_manifest_cannot_omit_canonical_source_hash(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    manifest_path = (
        run_dir / "graph" / "literature_figures" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_artifacts"] = {}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert any(
        "source_artifacts must be a non-empty object" in error
        for error in audit["content_errors"]
    )


def test_missing_results_workbook_fails_frontend_artifact_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (run_dir / "results.xlsx").unlink()

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert "results.xlsx" in audit["missing_artifacts"]


def test_missing_rolling_step_state_fails_frontend_artifact_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (
        run_dir
        / "rolling_hourly_chain"
        / "step_00_0000"
        / "state_for_next_hour.json"
    ).unlink()

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert (
        "rolling_hourly_chain/step_00_0000/state_for_next_hour.json"
        in audit["missing_artifacts"]
    )


def test_invalid_canonical_json_fails_frontend_artifact_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (run_dir / "canonical_solver_result.json").write_text(
        "{broken",
        encoding="utf-8",
    )

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert "canonical_solver_result.json" in audit[
        "invalid_json_artifacts"
    ]


def test_unsafe_graph_manifest_path_fails_without_leaving_run_dir(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (run_dir / "graph" / "manifest.json").write_text(
        json.dumps(
            {
                "files": ["../../outside.csv"],
                "optional_exports": {},
            }
        ),
        encoding="utf-8",
    )

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert any(
        "unsafe file path" in error
        for error in audit["content_errors"]
    )


def test_missing_literature_bundle_artifact_fails_contract(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    (
        run_dir
        / "graph"
        / "literature_figures"
        / "00_figure_source.csv"
    ).unlink()

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert (
        "graph/literature_figures/00_figure_source.csv"
        in audit["missing_artifacts"]
    )


def test_malformed_literature_bundle_counts_fail_without_crashing(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    manifest_path = (
        run_dir / "graph" / "literature_figures" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figure_count"] = "5"
    manifest["raw_data_csv_count"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=True,
        require_rolling=True,
    )

    assert audit["status"] == "ERROR"
    assert any(
        "figure_count must be a non-negative integer" in error
        for error in audit["content_errors"]
    )
    assert any(
        "raw_data_csv_count must be a non-negative integer" in error
        for error in audit["content_errors"]
    )


def test_frontend_gate_hashes_the_final_run_manifest(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    optimization_result: dict = {}
    optimization_audit: dict = {}

    reporting = optimization._enforce_frontend_run_artifact_contract(
        run_dir=run_dir,
        optimization_result=optimization_result,
        optimization_audit=optimization_audit,
        reporting_finalizer_result={"status": "completed"},
        research_run=True,
        require_rolling=True,
    )

    completeness = json.loads(
        (run_dir / "artifact_completeness.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_bytes = (run_dir / "run_manifest.json").read_bytes()
    assert completeness["status"] == "OK"
    assert completeness["artifacts"]["run_manifest.json"][
        "sha256"
    ] == hashlib.sha256(manifest_bytes).hexdigest()
    assert reporting["artifact_completeness_status"] == "OK"
    assert optimization_result["artifact_completeness"]["accepted"] is True
