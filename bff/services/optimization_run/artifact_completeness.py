"""Fail-closed completeness audit for interactive optimization run artifacts."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_CONTRACT_VERSION = "frontend_run_artifacts_v1"
PHYSICAL_VALIDATION_INPUT_MANIFEST_SCHEMA_VERSION = (
    "physical_validation_input_manifest_v1"
)

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
    "physical_validation_input_manifest.json",
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
    "graph/vehicle_soc_event_timeline.csv",
    "graph/literature_figures/manifest.json",
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


def _required_manifest_count(
    payload: dict[str, Any],
    *,
    key: str,
    artifact: str,
    content_errors: list[str],
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        content_errors.append(
            f"{artifact}: {key} must be a non-negative integer"
        )
        return 0
    return value


def _validate_artifact_record(
    *,
    root: Path,
    record: Any,
    artifact: str,
    content_errors: list[str],
) -> str | None:
    if not isinstance(record, dict):
        content_errors.append(f"{artifact}: artifact record must be an object")
        return None
    relative_path = _safe_relative_path(record.get("path"))
    if relative_path is None:
        content_errors.append(
            f"{artifact}: artifact record has an empty or unsafe path"
        )
        return None
    size_bytes = record.get("size_bytes")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        content_errors.append(
            f"{artifact}: {relative_path} has invalid size_bytes"
        )
        return relative_path
    expected_sha256 = str(record.get("sha256") or "").strip().lower()
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        content_errors.append(
            f"{artifact}: {relative_path} has invalid sha256"
        )
        return relative_path
    path = root / relative_path
    if not path.is_file():
        content_errors.append(
            f"{artifact}: recorded artifact is missing: {relative_path}"
        )
        return relative_path
    try:
        actual_size = path.stat().st_size
        actual_sha256 = _sha256(path)
    except OSError as exc:
        content_errors.append(
            f"{artifact}: cannot verify {relative_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return relative_path
    if actual_size != size_bytes:
        content_errors.append(
            f"{artifact}: size mismatch for {relative_path}: "
            f"{actual_size} != {size_bytes}"
        )
    if actual_sha256 != expected_sha256:
        content_errors.append(
            f"{artifact}: sha256 mismatch for {relative_path}: "
            f"{actual_sha256} != {expected_sha256}"
        )
    return relative_path


def _validate_literature_artifact_integrity(
    *,
    run_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    content_errors: list[str],
) -> None:
    artifact_name = manifest_path.relative_to(run_dir).as_posix()
    manifest_parent = manifest_path.parent
    canonical_source_paths: list[str] = []
    for entry in list(manifest.get("entries") or ()):
        if not isinstance(entry, dict):
            continue
        figure_id = str(entry.get("figure_id") or "<missing>")
        entry_artifact = f"{artifact_name}:{figure_id}"
        raw_files = entry.get("artifact_files")
        artifact_files = (
            [
                relative_path
                for value in raw_files
                if (relative_path := _safe_relative_path(value)) is not None
            ]
            if isinstance(raw_files, (list, tuple))
            else []
        )
        records = entry.get("artifact_records")
        if not isinstance(records, (list, tuple)):
            content_errors.append(
                f"{entry_artifact}: artifact_records must be a list"
            )
            continue
        recorded_paths = [
            relative_path
            for record in records
            if (
                relative_path := _validate_artifact_record(
                    root=manifest_parent,
                    record=record,
                    artifact=entry_artifact,
                    content_errors=content_errors,
                )
            )
            is not None
        ]
        if len(recorded_paths) != len(set(recorded_paths)):
            content_errors.append(
                f"{entry_artifact}: duplicate artifact record paths"
            )
        if sorted(artifact_files) != sorted(recorded_paths):
            content_errors.append(
                f"{entry_artifact}: artifact_files and artifact_records "
                "do not declare the same paths"
            )
        for raw_source in list(entry.get("canonical_sources") or ()):
            source_path = _safe_relative_path(raw_source)
            if source_path is None:
                content_errors.append(
                    f"{entry_artifact}: canonical source has an empty or "
                    f"unsafe path {raw_source!r}"
                )
                continue
            canonical_source_paths.append(source_path)

    source_artifacts = manifest.get("source_artifacts")
    if not isinstance(source_artifacts, dict) or not source_artifacts:
        content_errors.append(
            f"{artifact_name}: source_artifacts must be a non-empty object"
        )
        return
    recorded_source_paths: list[str] = []
    for raw_path, record in source_artifacts.items():
        declared_path = _safe_relative_path(raw_path)
        record_path = _validate_artifact_record(
            root=run_dir,
            record=record,
            artifact=f"{artifact_name}:source_artifacts",
            content_errors=content_errors,
        )
        if declared_path is None:
            content_errors.append(
                f"{artifact_name}: source_artifacts has an unsafe key "
                f"{raw_path!r}"
            )
            continue
        recorded_source_paths.append(declared_path)
        if record_path != declared_path:
            content_errors.append(
                f"{artifact_name}: source_artifacts key/path mismatch for "
                f"{declared_path}"
            )
    if len(recorded_source_paths) != len(set(recorded_source_paths)):
        content_errors.append(
            f"{artifact_name}: duplicate source artifact paths"
        )
    if sorted(set(canonical_source_paths)) != sorted(recorded_source_paths):
        content_errors.append(
            f"{artifact_name}: canonical_sources and source_artifacts "
            "do not declare the same paths"
        )


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
            raw_artifact_files = entry.get("artifact_files")
            if raw_artifact_files is not None:
                if not isinstance(raw_artifact_files, (list, tuple)):
                    content_errors.append(
                        f"{optional_manifest_relative}: artifact_files must "
                        "be a list"
                    )
                    continue
                if not raw_artifact_files:
                    content_errors.append(
                        f"{optional_manifest_relative}: artifact_files is "
                        "empty"
                    )
                    continue
                for raw_artifact_file in raw_artifact_files:
                    artifact_file = _safe_relative_path(raw_artifact_file)
                    if artifact_file is None:
                        content_errors.append(
                            f"{optional_manifest_relative}: entry has an "
                            "empty or unsafe artifact file "
                            f"{raw_artifact_file!r}"
                        )
                        continue
                    declared.append(
                        (optional_parent / Path(artifact_file)).as_posix()
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

    input_manifest_path = run_dir / "physical_validation_input_manifest.json"
    if input_manifest_path.is_file():
        try:
            input_manifest = _load_json_object(input_manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(
                f"physical_validation_input_manifest.json: {exc}"
            )
        else:
            if (
                input_manifest.get("schema_version")
                != PHYSICAL_VALIDATION_INPUT_MANIFEST_SCHEMA_VERSION
            ):
                content_errors.append(
                    "physical_validation_input_manifest schema_version is invalid"
                )
            expected_sources = {
                "assignment_source": "canonical_solver_result.json",
                "charging_source": (
                    "rolling_hourly_chain/charging_schedule.csv"
                ),
                "refueling_source": "canonical_solver_result.json",
            }
            for key, expected_source in expected_sources.items():
                if input_manifest.get(key) != expected_source:
                    content_errors.append(
                        "physical_validation_input_manifest "
                        f"{key} is not {expected_source!r}"
                    )
            for key, source in (
                ("canonical_solver_result_sha256", "canonical_solver_result.json"),
                (
                    "executed_charging_schedule_sha256",
                    "rolling_hourly_chain/charging_schedule.csv",
                ),
            ):
                declared_sha = str(input_manifest.get(key) or "").strip().lower()
                source_path = run_dir / source
                if (
                    len(declared_sha) != 64
                    or not all(
                        character in "0123456789abcdef"
                        for character in declared_sha
                    )
                ):
                    content_errors.append(
                        "physical_validation_input_manifest "
                        f"{key} is not a SHA-256 digest"
                    )
                elif (
                    source_path.is_file()
                    and declared_sha != _sha256(source_path)
                ):
                    content_errors.append(
                        "physical_validation_input_manifest "
                        f"{key} does not match {source}"
                    )
            assignment_hash = str(
                input_manifest.get("day_ahead_assignment_hash") or ""
            ).strip().lower()
            if (
                len(assignment_hash) != 64
                or not all(
                    character in "0123456789abcdef"
                    for character in assignment_hash
                )
            ):
                content_errors.append(
                    "physical_validation_input_manifest "
                    "day_ahead_assignment_hash is not a SHA-256 digest"
                )
            chain_summary_path = (
                run_dir
                / "rolling_hourly_chain"
                / "rolling_chain_summary.json"
            )
            canonical_path = run_dir / "canonical_solver_result.json"
            try:
                chain_summary = _load_json_object(chain_summary_path)
                canonical = _load_json_object(canonical_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                content_errors.append(
                    "physical_validation_input_manifest provenance source "
                    f"is unreadable: {exc}"
                )
            else:
                chain_canonical_sha = str(
                    chain_summary.get("day_ahead_result_sha256") or ""
                ).strip().lower()
                chain_assignment_hash = str(
                    chain_summary.get("day_ahead_assignment_hash") or ""
                ).strip().lower()
                if (
                    len(chain_canonical_sha) != 64
                    or not all(
                        character in "0123456789abcdef"
                        for character in chain_canonical_sha
                    )
                ):
                    content_errors.append(
                        "rolling_chain_summary day_ahead_result_sha256 "
                        "is not a SHA-256 digest"
                    )
                elif chain_canonical_sha != _sha256(canonical_path):
                    content_errors.append(
                        "rolling_chain_summary day_ahead_result_sha256 does "
                        "not match canonical_solver_result.json"
                    )
                elif (
                    input_manifest.get("canonical_solver_result_sha256")
                    != chain_canonical_sha
                ):
                    content_errors.append(
                        "physical_validation_input_manifest "
                        "canonical_solver_result_sha256 does not match "
                        "rolling_chain_summary"
                    )
                if (
                    len(chain_assignment_hash) != 64
                    or not all(
                        character in "0123456789abcdef"
                        for character in chain_assignment_hash
                    )
                ):
                    content_errors.append(
                        "rolling_chain_summary day_ahead_assignment_hash "
                        "is not a SHA-256 digest"
                    )
                elif assignment_hash != chain_assignment_hash:
                    content_errors.append(
                        "physical_validation_input_manifest "
                        "day_ahead_assignment_hash does not match "
                        "rolling_chain_summary"
                    )

                raw_paths = canonical.get("vehicle_paths")
                served_trip_ids = canonical.get("served_trip_ids")
                unserved_trip_ids = canonical.get("unserved_trip_ids")
                if not isinstance(raw_paths, dict):
                    content_errors.append(
                        "canonical_solver_result.vehicle_paths must be an object"
                    )
                elif not isinstance(served_trip_ids, list):
                    content_errors.append(
                        "canonical_solver_result.served_trip_ids must be a list"
                    )
                elif not isinstance(unserved_trip_ids, list):
                    content_errors.append(
                        "canonical_solver_result.unserved_trip_ids must be a list"
                    )
                elif not all(
                    isinstance(trip_ids, list)
                    for trip_ids in raw_paths.values()
                ):
                    content_errors.append(
                        "canonical_solver_result.vehicle_paths values must be lists"
                    )
                else:
                    assigned_trip_ids = [
                        str(trip_id)
                        for trip_ids in raw_paths.values()
                        for trip_id in trip_ids
                    ]
                    normalized_served_trip_ids = [
                        str(trip_id) for trip_id in served_trip_ids
                    ]
                    actual_counts = {
                        "vehicle_path_count": len(raw_paths),
                        "assigned_trip_occurrence_count": len(
                            assigned_trip_ids
                        ),
                        "served_trip_occurrence_count": len(
                            normalized_served_trip_ids
                        ),
                        "problem_trip_count": len(normalized_served_trip_ids)
                        + len(unserved_trip_ids),
                        "unserved_trip_count": len(unserved_trip_ids),
                    }
                    for key, actual_count in actual_counts.items():
                        if input_manifest.get(key) != actual_count:
                            content_errors.append(
                                "physical_validation_input_manifest "
                                f"{key} does not match canonical_solver_result"
                            )
                    if Counter(assigned_trip_ids) != Counter(
                        normalized_served_trip_ids
                    ):
                        content_errors.append(
                            "canonical_solver_result vehicle_paths and "
                            "served_trip_ids disagree"
                        )
                    if unserved_trip_ids:
                        content_errors.append(
                            "canonical_solver_result unserved_trip_ids is not empty"
                        )
            counts: dict[str, int] = {}
            for key in (
                "vehicle_path_count",
                "assigned_trip_occurrence_count",
                "served_trip_occurrence_count",
                "problem_trip_count",
                "unserved_trip_count",
            ):
                value = input_manifest.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                ):
                    content_errors.append(
                        "physical_validation_input_manifest "
                        f"{key} must be a non-negative integer"
                    )
                    continue
                counts[key] = value
            if counts and (
                counts.get("assigned_trip_occurrence_count")
                != counts.get("served_trip_occurrence_count")
                or counts.get("assigned_trip_occurrence_count")
                != counts.get("problem_trip_count")
                or counts.get("unserved_trip_count") != 0
            ):
                content_errors.append(
                    "physical_validation_input_manifest trip coverage counts "
                    "are inconsistent"
                )
            validation_contract = input_manifest.get("validation_contract")
            required_contract_checks = (
                "canonical_sha_matches_rolling_chain",
                "vehicle_paths_match_served_trip_ids",
                "vehicle_paths_cover_problem_trips_exactly",
                "unserved_trip_ids_empty",
                "executed_charging_overlay_only",
            )
            if not isinstance(validation_contract, dict) or any(
                validation_contract.get(key) is not True
                for key in required_contract_checks
            ):
                content_errors.append(
                    "physical_validation_input_manifest validation_contract "
                    "is incomplete or not verified"
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

    literature_manifest_path = (
        run_dir / "graph" / "literature_figures" / "manifest.json"
    )
    if literature_manifest_path.is_file():
        try:
            literature_manifest = _load_json_object(
                literature_manifest_path
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            content_errors.append(
                f"graph/literature_figures/manifest.json: {exc}"
            )
        else:
            if (
                literature_manifest.get("schema_version")
                != "literature_figure_bundle_v1"
            ):
                content_errors.append(
                    "literature figure manifest schema_version is invalid"
                )
            if literature_manifest.get("status") != "READY":
                content_errors.append(
                    "literature figure manifest status is not READY"
                )
            figure_count = _required_manifest_count(
                literature_manifest,
                key="figure_count",
                artifact="graph/literature_figures/manifest.json",
                content_errors=content_errors,
            )
            entries = [
                entry
                for entry in list(
                    literature_manifest.get("entries") or ()
                )
                if isinstance(entry, dict)
                and entry.get("kind") == "figure"
            ]
            if figure_count < 5 or len(entries) != figure_count:
                content_errors.append(
                    "literature figure manifest does not declare all five "
                    "required figures"
                )
            for entry in entries:
                artifact_files = list(entry.get("artifact_files") or ())
                if not {
                    Path(str(path)).suffix.lower()
                    for path in artifact_files
                }.issuperset({".png", ".svg", ".csv"}):
                    content_errors.append(
                        "literature figure entry is missing PNG, SVG, or "
                        f"source CSV: {entry.get('figure_id')!r}"
                    )
            raw_entries = [
                entry
                for entry in list(
                    literature_manifest.get("entries") or ()
                )
                if isinstance(entry, dict)
                and entry.get("kind") == "raw_data_bundle"
            ]
            raw_data_csv_count = _required_manifest_count(
                literature_manifest,
                key="raw_data_csv_count",
                artifact="graph/literature_figures/manifest.json",
                content_errors=content_errors,
            )
            if raw_data_csv_count < 16 or len(raw_entries) != 1:
                content_errors.append(
                    "literature figure manifest does not declare the "
                    "analysis-ready raw CSV bundle"
                )
            elif len(
                [
                    path
                    for path in list(
                        raw_entries[0].get("artifact_files") or ()
                    )
                    if Path(str(path)).suffix.lower() == ".csv"
                ]
            ) != raw_data_csv_count:
                content_errors.append(
                    "literature raw-data CSV count does not match its "
                    "declared artifact files"
                )
            if (
                literature_manifest.get("raw_data_catalog")
                != "raw_data/raw_data_catalog.csv"
            ):
                content_errors.append(
                    "literature raw-data catalog path is missing or invalid"
                )
            _validate_literature_artifact_integrity(
                run_dir=run_dir,
                manifest_path=literature_manifest_path,
                manifest=literature_manifest,
                content_errors=content_errors,
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
