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
