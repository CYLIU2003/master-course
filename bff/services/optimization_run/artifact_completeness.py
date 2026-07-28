"""Fail-closed completeness audit for interactive optimization run artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_CONTRACT_VERSION = "frontend_run_artifacts_v1"

# These artifacts are generated for every successfully finalized interactive
# optimization run.  Optional visualizations are validated through
# graph/manifest.json instead of being hard-coded here.
BASE_REQUIRED_ARTIFACTS = (
    "assignment_validation_diagnostics.json",
    "canonical_solver_result.json",
    "charging_schedule.csv",
    "charging_source_provenance.json",
    "charging_summary.csv",
    "charging_summary.json",
    "co2_breakdown.csv",
    "co2_breakdown.json",
    "cost_breakdown_detail.csv",
    "cost_breakdown_detail.json",
    "depot_energy_flows.csv",
    "depot_energy_flows.json",
    "experiment_report.json",
    "experiment_report.md",
    "kpi_summary.json",
    "objective_breakdown.csv",
    "objective_breakdown.json",
    "optimization_audit.json",
    "optimization_result.json",
    "raw/assignment.csv",
    "raw/canonical_solver_result.json",
    "raw/optimization_audit.json",
    "raw/optimization_result.json",
    "raw/solver_result.json",
    "raw/unserved_trips.csv",
    "rebuild_reporting_log.json",
    "refuel_events.csv",
    "research_claim_scope.json",
    "results.xlsx",
    "run_manifest.json",
    "simulation_conditions.json",
    "simulation_conditions_contract_limits.csv",
    "simulation_conditions_provenance.json",
    "simulation_conditions_tou_prices.csv",
    "simulation_conditions_vehicle_costs.csv",
    "site_power_balance.csv",
    "solver_result.json",
    "solver_settings.json",
    "strict_reconciliation.csv",
    "strict_reconciliation.md",
    "strict_reconciliation_after_rebuild.csv",
    "strict_reconciliation_after_rebuild.md",
    "summary.json",
    "targeted_trips.csv",
    "targeted_trips.json",
    "trip_type_counts.csv",
    "trip_type_counts.json",
    "vehicle_schedule.csv",
    "vehicle_timeline_gantt.csv",
    "vehicle_timelines.csv",
    "vehicle_timelines.json",
    "graph/canonical_cost_ledger.json",
    "graph/data_flow_validation.csv",
    "graph/manifest.json",
)

RESEARCH_PROVENANCE_ARTIFACTS = (
    "code_provenance.json",
    "optimization_parameters.json",
    "prepare_input_audit.json",
    "run_input_manifest.json",
    "run_input_summary.md",
    "run_input_validation.json",
    "scenario_input_snapshot.json",
)

ROLLING_REQUIRED_ARTIFACTS = (
    "comparison_case_manifest.json",
    "effective_pv_profiles.json",
    "effective_scenario.json",
    "final_cost_reconciliation.json",
    "input_audit.json",
    "manifest.json",
    "physical_schedule_validation.json",
    "scenario_fleet_contract.json",
    "rolling_hourly_chain/charging_schedule.csv",
    "rolling_hourly_chain/day_ahead_vs_rolling_summary.json",
    "rolling_hourly_chain/executed_day_accounting.json",
    "rolling_hourly_chain/hourly_energy_flow_chart.csv",
    "rolling_hourly_chain/rolling_chain_summary.json",
    "graph/charger_occupancy_timeline.csv",
    "graph/physical_schedule_validation.json",
    "graph/physical_schedule_violations.csv",
    "graph/vehicle_event_timeline.csv",
    "graph/vehicle_location_timeline.csv",
)

REQUIRED_WORKBOOK_SHEETS = (
    "summary",
    "cost_breakdown",
    "release_status",
)


def _load_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("expected a JSON object")
    return dict(loaded)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_paths(paths: Iterable[str]) -> list[str]:
    return sorted(
        {
            Path(str(path)).as_posix()
            for path in paths
            if str(path or "").strip()
        }
    )


def _safe_relative_path(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    path = Path(text)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    return path.as_posix()


def required_frontend_artifacts(
    *,
    research_run: bool,
    require_rolling: bool,
) -> list[str]:
    """Return the semantic artifact contract for one finalized frontend run."""

    paths = list(BASE_REQUIRED_ARTIFACTS)
    if research_run:
        paths.extend(RESEARCH_PROVENANCE_ARTIFACTS)
    if require_rolling:
        paths.extend(ROLLING_REQUIRED_ARTIFACTS)
    return _normalized_paths(paths)


def _graph_manifest_artifacts(
    *,
    run_dir: Path,
    content_errors: list[str],
) -> list[str]:
    manifest_path = run_dir / "graph" / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = _load_json_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        content_errors.append(f"graph/manifest.json: {exc}")
        return []

    declared: list[str] = []
    for raw_path in list(manifest.get("files") or ()):
        relative_path = _safe_relative_path(raw_path)
        if relative_path is None:
            content_errors.append(
                f"graph/manifest.json: unsafe file path {raw_path!r}"
            )
            continue
        declared.append(f"graph/{relative_path}")
    optional = dict(manifest.get("optional_exports") or {})
    for name, raw_config in optional.items():
        config = dict(raw_config or {})
        if config.get("enabled") is not True:
            continue
        raw_manifest_file = config.get("manifest_file")
        manifest_file = _safe_relative_path(raw_manifest_file)
        if manifest_file is None:
            content_errors.append(
                f"graph/manifest.json: enabled optional export {name!r} "
                f"has an empty or unsafe manifest_file {raw_manifest_file!r}"
            )
            continue
        optional_manifest_relative = (
            Path("graph") / Path(manifest_file)
        ).as_posix()
        declared.append(optional_manifest_relative)
        optional_manifest_path = run_dir / optional_manifest_relative
        if not optional_manifest_path.is_file():
            continue
        try:
            optional_manifest = _load_json_object(
                optional_manifest_path
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(
                f"{optional_manifest_relative}: {exc}"
            )
            continue
        optional_parent = Path(optional_manifest_relative).parent
        for entry in list(optional_manifest.get("entries") or ()):
            if not isinstance(entry, dict):
                content_errors.append(
                    f"{optional_manifest_relative}: non-object entry"
                )
                continue
            raw_diagram_file = entry.get("diagram_file")
            diagram_file = _safe_relative_path(raw_diagram_file)
            if diagram_file is None:
                content_errors.append(
                    f"{optional_manifest_relative}: entry has an empty or "
                    f"unsafe diagram_file {raw_diagram_file!r}"
                )
                continue
            declared.append(
                (optional_parent / Path(diagram_file)).as_posix()
            )
    return _normalized_paths(declared)


def _rolling_step_artifacts(
    *,
    run_dir: Path,
    content_errors: list[str],
) -> list[str]:
    summary_path = (
        run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    )
    if not summary_path.is_file():
        return []
    try:
        summary = _load_json_object(summary_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        content_errors.append(
            f"rolling_hourly_chain/rolling_chain_summary.json: {exc}"
        )
        return []

    expected_step_count = int(summary.get("expected_step_count") or 0)
    step_count = int(summary.get("step_count") or 0)
    step_dirs = sorted(
        path
        for path in (run_dir / "rolling_hourly_chain").glob("step_*")
        if path.is_dir()
    )
    if expected_step_count <= 0:
        content_errors.append(
            "rolling_chain_summary.expected_step_count must be positive"
        )
    if step_count != expected_step_count:
        content_errors.append(
            "rolling_chain_summary step_count does not equal "
            f"expected_step_count: {step_count} != {expected_step_count}"
        )
    if len(step_dirs) != expected_step_count:
        content_errors.append(
            "rolling step directory count does not equal expected_step_count: "
            f"{len(step_dirs)} != {expected_step_count}"
        )
    if summary.get("chain_accepted") is not True:
        content_errors.append("rolling_chain_summary.chain_accepted is not true")
    if summary.get("all_steps_feasible") is not True:
        content_errors.append(
            "rolling_chain_summary.all_steps_feasible is not true"
        )

    artifacts: list[str] = []
    for step_index, step_dir in enumerate(step_dirs):
        required_step_files = [
            "hourly_solver_result.json",
            "hourly_summary.json",
        ]
        # The final slot has no successor handoff. Every earlier step must
        # persist its state transition for the next solve.
        if step_index < len(step_dirs) - 1:
            required_step_files.append("state_for_next_hour.json")
        for filename in required_step_files:
            artifacts.append(
                (step_dir.relative_to(run_dir) / filename).as_posix()
            )
    return _normalized_paths(artifacts)


def _validate_rolling_content(
    *,
    run_dir: Path,
    content_errors: list[str],
) -> None:
    executed_path = (
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    if executed_path.is_file():
        try:
            executed = _load_json_object(executed_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(
                f"rolling_hourly_chain/executed_day_accounting.json: {exc}"
            )
        else:
            if executed.get("eligible") is not True:
                content_errors.append(
                    "executed_day_accounting.eligible is not true"
                )
            expected_slots = int(executed.get("expected_slot_count") or 0)
            executed_slots = int(executed.get("executed_slot_count") or 0)
            if expected_slots <= 0 or executed_slots != expected_slots:
                content_errors.append(
                    "executed-day slot coverage is incomplete: "
                    f"{executed_slots} != {expected_slots}"
                )

    physical_path = run_dir / "physical_schedule_validation.json"
    if physical_path.is_file():
        try:
            physical = _load_json_object(physical_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(
                f"physical_schedule_validation.json: {exc}"
            )
        else:
            if physical.get("accepted") is not True:
                content_errors.append(
                    "physical_schedule_validation.accepted is not true"
                )

    reconciliation_path = run_dir / "final_cost_reconciliation.json"
    if reconciliation_path.is_file():
        try:
            reconciliation = _load_json_object(reconciliation_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(f"final_cost_reconciliation.json: {exc}")
        else:
            if reconciliation.get("status") != "OK":
                content_errors.append(
                    "final_cost_reconciliation.status is not OK"
                )


def audit_frontend_run_artifacts(
    run_dir: Path,
    *,
    research_run: bool,
    require_rolling: bool,
) -> dict[str, Any]:
    """Audit files and essential content without changing solver results."""

    run_dir = Path(run_dir).resolve()
    content_errors: list[str] = []
    required = required_frontend_artifacts(
        research_run=research_run,
        require_rolling=require_rolling,
    )
    required.extend(
        _graph_manifest_artifacts(
            run_dir=run_dir,
            content_errors=content_errors,
        )
    )
    if require_rolling:
        required.extend(
            _rolling_step_artifacts(
                run_dir=run_dir,
                content_errors=content_errors,
            )
        )
        _validate_rolling_content(
            run_dir=run_dir,
            content_errors=content_errors,
        )
    required = _normalized_paths(required)

    missing: list[str] = []
    empty: list[str] = []
    invalid_json: dict[str, str] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for relative_path in required:
        path = run_dir / relative_path
        if not path.is_file():
            missing.append(relative_path)
            continue
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            empty.append(relative_path)
            continue
        if path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                invalid_json[relative_path] = str(exc)
                continue
        artifacts[relative_path] = {
            "size_bytes": size_bytes,
            "sha256": _sha256(path),
        }

    workbook_errors: list[str] = []
    workbook_path = run_dir / "results.xlsx"
    if workbook_path.is_file() and workbook_path.stat().st_size > 0:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(
                workbook_path,
                read_only=True,
                data_only=False,
            )
            try:
                missing_sheets = sorted(
                    set(REQUIRED_WORKBOOK_SHEETS)
                    - set(workbook.sheetnames)
                )
            finally:
                workbook.close()
            if missing_sheets:
                workbook_errors.append(
                    "results.xlsx missing sheets: "
                    + ", ".join(missing_sheets)
                )
        except Exception as exc:
            workbook_errors.append(f"results.xlsx unreadable: {exc}")

    run_manifest_errors: list[str] = []
    run_manifest_path = run_dir / "run_manifest.json"
    if run_manifest_path.is_file():
        try:
            run_manifest = _load_json_object(run_manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            run_manifest_errors.append(f"run_manifest.json: {exc}")
        else:
            declared_files = {
                Path(str(path)).as_posix()
                for path in list(run_manifest.get("files") or ())
            }
            undeclared = sorted(
                path
                for path in required
                if path != "run_manifest.json" and path not in declared_files
            )
            if undeclared:
                run_manifest_errors.append(
                    "run_manifest.files omits required artifacts: "
                    + ", ".join(undeclared)
                )

    accepted = not any(
        (
            missing,
            empty,
            invalid_json,
            content_errors,
            workbook_errors,
            run_manifest_errors,
        )
    )
    return {
        "schema_version": ARTIFACT_CONTRACT_VERSION,
        "status": "OK" if accepted else "ERROR",
        "accepted": accepted,
        "run_dir": str(run_dir),
        "research_run": bool(research_run),
        "rolling_required": bool(require_rolling),
        "required_artifact_count": len(required),
        "verified_artifact_count": len(artifacts),
        "total_file_count": sum(
            1 for path in run_dir.rglob("*") if path.is_file()
        ),
        "required_artifacts": required,
        "artifacts": artifacts,
        "missing_artifacts": missing,
        "empty_artifacts": empty,
        "invalid_json_artifacts": invalid_json,
        "content_errors": content_errors,
        "workbook_errors": workbook_errors,
        "run_manifest_errors": run_manifest_errors,
        "semantics": (
            "This gate proves required frontend output files are present, "
            "readable, and internally eligible where specified. It does not "
            "upgrade research acceptance or global optimality."
        ),
    }


def persist_frontend_run_artifact_audit(
    run_dir: Path,
    *,
    research_run: bool,
    require_rolling: bool,
) -> dict[str, Any]:
    """Audit and persist ``artifact_completeness.json`` in the run root."""

    audit = audit_frontend_run_artifacts(
        run_dir,
        research_run=research_run,
        require_rolling=require_rolling,
    )
    (Path(run_dir) / "artifact_completeness.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit
