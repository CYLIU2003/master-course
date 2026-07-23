"""Persist and verify the exact input provenance of a frontend optimization run."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "frontend_run_input_provenance_v1"
SCENARIO_SNAPSHOT_FILE = "scenario_input_snapshot.json"
PREPARE_AUDIT_FILE = "prepare_input_audit.json"
PARAMETERS_FILE = "optimization_parameters.json"
SUMMARY_FILE = "run_input_summary.md"
MANIFEST_FILE = "run_input_manifest.json"
VALIDATION_FILE = "run_input_validation.json"
CORE_ARTIFACTS = (
    SCENARIO_SNAPSHOT_FILE,
    PREPARE_AUDIT_FILE,
    PARAMETERS_FILE,
    SUMMARY_FILE,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HEAVY_SCENARIO_FIELDS = frozenset(
    {
        "blocks",
        "duties",
        "graph",
        "optimization_audit",
        "optimization_result",
        "simulation_result",
        "stop_sequences",
        "stop_time_sequences",
        "stops",
        "timetable_rows",
        "trips",
    }
)
_PREPARE_SNAPSHOT_FIELDS = (
    "prepared_input_id",
    "prepared_input_schema_version",
    "scenario_id",
    "dataset_id",
    "dataset_version",
    "random_seed",
    "scenario_hash",
    "scope_hash",
    "prepared_at",
    "solver_mode_requested",
    "solver_mode_effective",
    "prepare_profile",
    "depot_ids",
    "route_ids",
    "service_ids",
    "service_date",
    "service_dates",
    "planning_days",
    "primary_depot_id",
    "trip_count",
    "timetable_row_count",
    "scope",
    "counts",
    "dispatch_scope",
    "prepared_scope_audit",
    "trip_distance_enrichment",
)


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _repo_relative_path(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _bounded_mapping(
    source: Mapping[str, Any],
    *,
    excluded_fields: frozenset[str] = frozenset(),
    max_field_bytes: int = 512_000,
    max_total_bytes: int = 2_000_000,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    included: dict[str, Any] = {}
    omitted: list[dict[str, Any]] = []
    total_bytes = 0
    for original_key in sorted(source, key=lambda item: str(item)):
        key = str(original_key)
        if key in excluded_fields:
            omitted.append({"field": key, "reason": "large_or_derived_runtime_field"})
            continue
        value = _json_safe(source[original_key])
        value_bytes = len(_canonical_json_bytes(value))
        if value_bytes > max_field_bytes:
            omitted.append(
                {
                    "field": key,
                    "reason": "field_exceeds_snapshot_limit",
                    "serialized_bytes": value_bytes,
                }
            )
            continue
        if total_bytes + value_bytes > max_total_bytes:
            omitted.append(
                {
                    "field": key,
                    "reason": "snapshot_total_limit_reached",
                    "serialized_bytes": value_bytes,
                }
            )
            continue
        included[key] = value
        total_bytes += value_bytes
    return included, omitted


def _route_identity(route: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "route_id",
        "routeId",
        "route_code",
        "routeCode",
        "family_id",
        "route_family_code",
        "name",
        "short_name",
        "long_name",
        "origin",
        "destination",
        "direction",
        "route_variant_type",
        "service_id",
        "operator_id",
        "distance_km",
    )
    return {
        field: _json_safe(route.get(field))
        for field in fields
        if route.get(field) is not None
    }


def _inventory_hash(items: Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(items)).hexdigest()


def _scenario_snapshot(
    *,
    base_scenario: Mapping[str, Any],
    effective_scenario: Mapping[str, Any],
    prepared_input: Mapping[str, Any],
) -> dict[str, Any]:
    persisted_snapshot, omitted_fields = _bounded_mapping(
        base_scenario,
        excluded_fields=_HEAVY_SCENARIO_FIELDS,
    )
    vehicles = list(prepared_input.get("vehicles") or ())
    chargers = list(prepared_input.get("chargers") or ())
    depots = list(prepared_input.get("depots") or ())
    routes = [
        _route_identity(item)
        for item in list(prepared_input.get("routes") or ())
        if isinstance(item, Mapping)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": str(
            effective_scenario.get("scenario_id")
            or base_scenario.get("scenario_id")
            or prepared_input.get("scenario_id")
            or ""
        ),
        "snapshot_semantics": (
            "Persisted scenario fields plus the effective configuration and "
            "prepared inventories actually used by the run. Heavy timetable "
            "rows remain in the immutable prepared artifact identified by SHA-256."
        ),
        "persisted_scenario": persisted_snapshot,
        "persisted_scenario_omissions": omitted_fields,
        "effective_configuration": {
            "simulation_config": dict(
                effective_scenario.get("simulation_config") or {}
            ),
            "scenario_overlay": dict(
                effective_scenario.get("scenario_overlay") or {}
            ),
            "dispatch_scope": dict(effective_scenario.get("dispatch_scope") or {}),
            "prepare_profile": dict(effective_scenario.get("prepare_profile") or {}),
            "scope_hash": effective_scenario.get("scope_hash"),
        },
        "prepared_inventory": {
            "vehicle_count": len(vehicles),
            "vehicles_sha256": _inventory_hash(vehicles),
            "vehicles": vehicles,
            "charger_count": len(chargers),
            "chargers_sha256": _inventory_hash(chargers),
            "chargers": chargers,
            "depot_count": len(depots),
            "depots_sha256": _inventory_hash(depots),
            "depots": depots,
            "route_count": len(routes),
            "routes_sha256": _inventory_hash(routes),
            "routes": routes,
        },
    }


def _prepare_audit(
    *,
    prepared_input: Mapping[str, Any],
    prepared_input_path: Path,
    prepared_sha256: str,
    requested_prepared_input_id: str | None,
) -> dict[str, Any]:
    source_stat = prepared_input_path.stat()
    snapshot = {
        field: _json_safe(prepared_input.get(field))
        for field in _PREPARE_SNAPSHOT_FIELDS
        if field in prepared_input
    }
    omitted_fields = sorted(
        set(str(key) for key in prepared_input).difference(snapshot)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": str(prepared_input.get("scenario_id") or ""),
        "prepared_input_id": str(prepared_input.get("prepared_input_id") or ""),
        "requested_prepared_input_id": requested_prepared_input_id,
        "source_artifact": {
            "absolute_path": str(prepared_input_path.resolve()),
            "repository_relative_path": _repo_relative_path(prepared_input_path),
            "size_bytes": source_stat.st_size,
            "modified_at_utc": datetime.fromtimestamp(
                source_stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(),
            "sha256": prepared_sha256,
        },
        "prepare_snapshot": snapshot,
        "omitted_large_payload_fields": omitted_fields,
        "omission_semantics": (
            "Large row-level prepared fields are not duplicated into each run. "
            "The source artifact path, byte size, full SHA-256, scope hashes, "
            "counts, profile, and audit make later identity checks fail-closed."
        ),
    }


def _optimization_parameters(
    *,
    scenario_id: str,
    prepared_input_id: str,
    frontend_request: Mapping[str, Any],
    optimization_config: Any,
    canonical_problem: Any,
) -> dict[str, Any]:
    metadata, omitted_metadata = _bounded_mapping(
        dict(getattr(canonical_problem, "metadata", {}) or {}),
    )
    problem_scenario = getattr(canonical_problem, "scenario", None)
    trips = tuple(getattr(canonical_problem, "trips", ()) or ())
    vehicles = tuple(getattr(canonical_problem, "vehicles", ()) or ())
    chargers = tuple(getattr(canonical_problem, "chargers", ()) or ())
    price_slots = tuple(getattr(canonical_problem, "price_slots", ()) or ())
    pv_slots = tuple(getattr(canonical_problem, "pv_slots", ()) or ())
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "prepared_input_id": prepared_input_id,
        "parameter_precedence": [
            "persisted_scenario",
            "prepared_input_snapshot",
            "frontend_run_request_overrides",
            "weather_policy_application",
            "ProblemBuilder_defaults_and_normalization",
        ],
        "frontend_request": _json_safe(frontend_request),
        "effective_optimization_config": _json_safe(optimization_config),
        "effective_problem_scenario": _json_safe(problem_scenario),
        "effective_derived_values": {
            "planning_horizon_hours": getattr(
                problem_scenario,
                "planning_horizon_hours",
                None,
            ),
            "demand_charge_horizon_factor": getattr(
                problem_scenario,
                "demand_charge_horizon_factor",
                None,
            ),
        },
        "effective_model_metadata": metadata,
        "effective_model_metadata_omissions": omitted_metadata,
        "canonical_input_dimensions": {
            "trip_count": len(trips),
            "vehicle_count": len(vehicles),
            "charger_count": len(chargers),
            "price_slot_count": len(price_slots),
            "pv_slot_count": len(pv_slots),
            "trip_ids_sha256": _inventory_hash(
                [str(getattr(item, "trip_id", "")) for item in trips]
            ),
            "vehicle_ids_sha256": _inventory_hash(
                [str(getattr(item, "vehicle_id", "")) for item in vehicles]
            ),
            "charger_ids_sha256": _inventory_hash(
                [str(getattr(item, "charger_id", "")) for item in chargers]
            ),
        },
        "interpretation": {
            "frontend_request": "Values requested by the manual frontend run.",
            "effective_optimization_config": (
                "Values passed to OptimizationEngine after request normalization."
            ),
            "effective_problem_scenario": (
                "Canonical horizon, timestep, and coverage semantics built for the solver."
            ),
            "effective_model_metadata": (
                "Bounded snapshot of effective costs, SOC, PV/BESS, dispatch, "
                "weather, and solver-model controls."
            ),
        },
    }


def _summary_markdown(
    scenario_snapshot: Mapping[str, Any],
    prepare_audit: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> str:
    prepare = dict(prepare_audit.get("prepare_snapshot") or {})
    source = dict(prepare_audit.get("source_artifact") or {})
    request = dict(parameters.get("frontend_request") or {})
    config = dict(parameters.get("effective_optimization_config") or {})
    dimensions = dict(parameters.get("canonical_input_dimensions") or {})
    lines = [
        "# Run Input Summary",
        "",
        "このrunを後から再確認するための入力監査サマリーです。",
        "",
        "## Scenario",
        "",
        f"- scenario_id: `{scenario_snapshot.get('scenario_id')}`",
        f"- service_date: `{prepare.get('service_date')}`",
        f"- service_ids: `{prepare.get('service_ids')}`",
        f"- depot_ids: `{prepare.get('depot_ids')}`",
        f"- route_count: `{len(prepare.get('route_ids') or [])}`",
        "",
        "## Prepare",
        "",
        f"- prepared_input_id: `{prepare_audit.get('prepared_input_id')}`",
        f"- prepared_at: `{prepare.get('prepared_at')}`",
        f"- scenario_hash: `{prepare.get('scenario_hash')}`",
        f"- scope_hash: `{prepare.get('scope_hash')}`",
        f"- prepared artifact SHA-256: `{source.get('sha256')}`",
        f"- prepared artifact size: `{source.get('size_bytes')}` bytes",
        f"- prepare profile: `{prepare.get('prepare_profile')}`",
        "",
        "## Requested / Effective Optimization",
        "",
        f"- requested mode: `{request.get('mode')}`",
        f"- effective phase: `{config.get('executed_phase') or config.get('phase')}`",
        f"- requested time limit: `{request.get('time_limit_seconds')}` s",
        f"- requested MIP gap: `{request.get('mip_gap')}`",
        f"- random seed: `{request.get('random_seed')}`",
        f"- timestep: `{request.get('timestep_min')}` min",
        f"- trips / vehicles / chargers: "
        f"`{dimensions.get('trip_count')} / {dimensions.get('vehicle_count')} / "
        f"{dimensions.get('charger_count')}`",
        "",
        "## Verification",
        "",
        f"- `{MANIFEST_FILE}`: compact input artifactsのSHA-256",
        f"- `{VALIDATION_FILE}`: run生成時の相互整合検査",
        "- 後日、prepared sourceも含めて再検証する場合:",
        "  `python scripts/verify_run_input_provenance.py --run-dir <RUN_DIR>`",
        "",
        "詳細値はJSON成果物を正本とし、このMarkdownは閲覧用です。",
        "",
    ]
    return "\n".join(lines)


def persist_run_input_provenance(
    *,
    run_dir: Path,
    base_scenario: Mapping[str, Any],
    effective_scenario: Mapping[str, Any],
    prepared_input: Mapping[str, Any],
    prepared_input_path: Path,
    requested_prepared_input_id: str | None,
    frontend_request: Mapping[str, Any],
    optimization_config: Any,
    canonical_problem: Any,
) -> dict[str, Any]:
    """Write a compact, hash-verified input bundle before the solver starts."""

    resolved_run_dir = run_dir.resolve()
    resolved_run_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = prepared_input_path.resolve()
    prepared_input_id = str(prepared_input.get("prepared_input_id") or "")
    if not prepared_input_id:
        raise ValueError("Prepared input has no prepared_input_id")
    if prepared_path.stem != prepared_input_id:
        raise ValueError(
            "Prepared input path/id mismatch: "
            f"path={prepared_path.name!r}, id={prepared_input_id!r}"
        )
    prepared_sha256 = _sha256_file(prepared_path)
    scenario_snapshot = _scenario_snapshot(
        base_scenario=base_scenario,
        effective_scenario=effective_scenario,
        prepared_input=prepared_input,
    )
    prepare_audit = _prepare_audit(
        prepared_input=prepared_input,
        prepared_input_path=prepared_path,
        prepared_sha256=prepared_sha256,
        requested_prepared_input_id=requested_prepared_input_id,
    )
    parameters = _optimization_parameters(
        scenario_id=str(scenario_snapshot.get("scenario_id") or ""),
        prepared_input_id=str(prepare_audit.get("prepared_input_id") or ""),
        frontend_request=frontend_request,
        optimization_config=optimization_config,
        canonical_problem=canonical_problem,
    )
    _write_json(resolved_run_dir / SCENARIO_SNAPSHOT_FILE, scenario_snapshot)
    _write_json(resolved_run_dir / PREPARE_AUDIT_FILE, prepare_audit)
    _write_json(resolved_run_dir / PARAMETERS_FILE, parameters)
    (resolved_run_dir / SUMMARY_FILE).write_text(
        _summary_markdown(scenario_snapshot, prepare_audit, parameters),
        encoding="utf-8",
    )

    artifacts = {
        name: {
            "size_bytes": (resolved_run_dir / name).stat().st_size,
            "sha256": _sha256_file(resolved_run_dir / name),
        }
        for name in CORE_ARTIFACTS
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario_id": scenario_snapshot.get("scenario_id"),
        "prepared_input_id": prepare_audit.get("prepared_input_id"),
        "prepared_source_sha256": prepared_sha256,
        "artifacts": artifacts,
        "validation_command": (
            "python scripts/verify_run_input_provenance.py --run-dir "
            f'"{resolved_run_dir}"'
        ),
    }
    _write_json(resolved_run_dir / MANIFEST_FILE, manifest)
    validation = validate_run_input_provenance(
        resolved_run_dir,
        verify_prepared_source=False,
    )
    _write_json(resolved_run_dir / VALIDATION_FILE, validation)
    if not validation["valid"]:
        raise ValueError(
            "Run input provenance validation failed: "
            f"{validation.get('failed_checks')}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "OK",
        "manifest_path": MANIFEST_FILE,
        "validation_path": VALIDATION_FILE,
        "summary_path": SUMMARY_FILE,
        "prepared_source_sha256": prepared_sha256,
        "artifacts": artifacts,
    }


def validate_run_input_provenance(
    run_dir: Path,
    *,
    verify_prepared_source: bool = True,
) -> dict[str, Any]:
    """Validate compact artifacts and, optionally, the original prepared file."""

    resolved_run_dir = run_dir.resolve()
    manifest_path = resolved_run_dir / MANIFEST_FILE
    checks: dict[str, bool] = {"manifest_exists": manifest_path.is_file()}
    details: dict[str, Any] = {}
    if not checks["manifest_exists"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "checks": checks,
            "failed_checks": ["manifest_exists"],
            "details": details,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks["schema_version_supported"] = (
        manifest.get("schema_version") == SCHEMA_VERSION
    )
    artifact_payloads: dict[str, Any] = {}
    for name in CORE_ARTIFACTS:
        artifact_path = (resolved_run_dir / name).resolve()
        within_run = artifact_path.parent == resolved_run_dir
        exists = within_run and artifact_path.is_file()
        expected = dict((manifest.get("artifacts") or {}).get(name) or {})
        checks[f"{name}:exists"] = exists
        checks[f"{name}:size"] = (
            exists and artifact_path.stat().st_size == expected.get("size_bytes")
        )
        checks[f"{name}:sha256"] = (
            exists and _sha256_file(artifact_path) == expected.get("sha256")
        )
        if exists and name.endswith(".json"):
            artifact_payloads[name] = json.loads(
                artifact_path.read_text(encoding="utf-8")
            )

    scenario = dict(artifact_payloads.get(SCENARIO_SNAPSHOT_FILE) or {})
    prepare = dict(artifact_payloads.get(PREPARE_AUDIT_FILE) or {})
    parameters = dict(artifact_payloads.get(PARAMETERS_FILE) or {})
    scenario_ids = {
        str(value)
        for value in (
            manifest.get("scenario_id"),
            scenario.get("scenario_id"),
            prepare.get("scenario_id"),
            parameters.get("scenario_id"),
        )
        if value is not None
    }
    prepared_ids = {
        str(value)
        for value in (
            manifest.get("prepared_input_id"),
            prepare.get("prepared_input_id"),
            parameters.get("prepared_input_id"),
        )
        if value is not None
    }
    checks["scenario_id_consistent"] = len(scenario_ids) == 1
    checks["prepared_input_id_consistent"] = len(prepared_ids) == 1
    frontend_request = dict(parameters.get("frontend_request") or {})
    checks["frontend_request_scenario_id_consistent"] = (
        not frontend_request.get("scenario_id")
        or str(frontend_request.get("scenario_id")) in scenario_ids
    )
    checks["frontend_request_prepared_input_id_consistent"] = (
        not frontend_request.get("prepared_input_id")
        or str(frontend_request.get("prepared_input_id")) in prepared_ids
    )

    source = dict(prepare.get("source_artifact") or {})
    if verify_prepared_source:
        source_path = Path(str(source.get("absolute_path") or ""))
        if not source_path.is_file() and source.get("repository_relative_path"):
            source_path = _REPO_ROOT / str(source["repository_relative_path"])
        checks["prepared_source_exists"] = source_path.is_file()
        checks["prepared_source_size"] = (
            source_path.is_file()
            and source_path.stat().st_size == source.get("size_bytes")
        )
        checks["prepared_source_sha256"] = (
            source_path.is_file()
            and _sha256_file(source_path) == source.get("sha256")
            and source.get("sha256") == manifest.get("prepared_source_sha256")
        )
        details["prepared_source_path_checked"] = str(source_path)
    else:
        checks["prepared_source_identity_recorded"] = bool(
            source.get("size_bytes")
            and source.get("sha256")
            and source.get("sha256") == manifest.get("prepared_source_sha256")
        )
        details["prepared_source_rehash_deferred"] = True

    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": SCHEMA_VERSION,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "valid": not failed_checks,
        "verify_prepared_source": verify_prepared_source,
        "checks": checks,
        "failed_checks": failed_checks,
        "details": details,
    }
