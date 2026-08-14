"""Persist and verify the exact input provenance of a frontend optimization run."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "frontend_run_input_provenance_v2"
LEGACY_SCHEMA_VERSIONS = frozenset({"frontend_run_input_provenance_v1"})
SCENARIO_SNAPSHOT_FILE = "scenario_input_snapshot.json"
PREPARE_AUDIT_FILE = "prepare_input_audit.json"
PARAMETERS_FILE = "optimization_parameters.json"
SUMMARY_FILE = "run_input_summary.md"
CODE_PROVENANCE_FILE = "code_provenance.json"
MANIFEST_FILE = "run_input_manifest.json"
VALIDATION_FILE = "run_input_validation.json"
TRIP_STRUCTURE_SCHEMA = "canonical_trip_structure_v2_energy_demand_excluded"
PREPARED_TRIP_INPUT_SCHEMA = "prepared_trip_rows_v1"
CORE_ARTIFACTS = (
    SCENARIO_SNAPSHOT_FILE,
    PREPARE_AUDIT_FILE,
    PARAMETERS_FILE,
    SUMMARY_FILE,
    CODE_PROVENANCE_FILE,
)
LEGACY_CORE_ARTIFACTS = CORE_ARTIFACTS[:-1]

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


def collect_git_state(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Collect an explicit, portable Git provenance record.

    A manual frontend run must never silently emit an empty commit field merely
    because the BFF process was launched without Git on ``PATH``.  The record
    is intentionally non-fatal for diagnostic runs: a missing executable is
    represented explicitly and formal acceptance can reject it later.
    """

    root = (repo_root or _REPO_ROOT).resolve()
    git_executable = shutil.which("git")
    if git_executable is None:
        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Git" / "cmd" / "git.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "Git"
            / "cmd"
            / "git.exe",
        ]
        codex_runtime_root = (
            Path(os.environ.get("USERPROFILE", ""))
            / ".cache"
            / "codex-runtimes"
        )
        if codex_runtime_root.is_dir():
            candidates.extend(
                sorted(
                    codex_runtime_root.glob(
                        "*/dependencies/native/git/cmd/git.exe"
                    )
                )
            )
        git_executable = next(
            (str(candidate) for candidate in candidates if candidate.is_file()),
            None,
        )
    if git_executable is None:
        return {
            "schema_version": "git_provenance_v1",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(root),
            "git_sha": None,
            "git_dirty": None,
            "git_state_available": False,
            "git_state_error": "Git executable was not found",
        }

    try:
        git_sha = subprocess.check_output(
            [git_executable, "rev-parse", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
        status_porcelain = subprocess.check_output(
            [git_executable, "status", "--porcelain"],
            cwd=root,
            text=True,
        ).rstrip("\r\n")
        git_dirty = bool(status_porcelain)
        tracked_patch = subprocess.check_output(
            [git_executable, "diff", "--binary", "HEAD", "--"],
            cwd=root,
        )
        untracked_paths = subprocess.check_output(
            [
                git_executable,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            cwd=root,
        ).split(b"\0")
        untracked_entries: list[dict[str, Any]] = []
        for raw_path in sorted(item for item in untracked_paths if item):
            relative_path = raw_path.decode("utf-8", errors="surrogateescape")
            candidate = (root / relative_path).resolve()
            if not candidate.is_file():
                continue
            untracked_entries.append(
                {
                    "path": relative_path.replace("\\", "/"),
                    "size_bytes": candidate.stat().st_size,
                    "sha256": _sha256_file(candidate),
                }
            )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
        return {
            "schema_version": "git_provenance_v1",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(root),
            "git_sha": None,
            "git_dirty": None,
            "git_state_available": False,
            "git_state_error": f"{type(exc).__name__}: {exc}",
        }
    if not git_sha:
        return {
            "schema_version": "git_provenance_v1",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(root),
            "git_sha": None,
            "git_dirty": None,
            "git_state_available": False,
            "git_state_error": "git rev-parse HEAD returned an empty SHA",
        }
    patch_identity = {
        "tracked_patch_sha256": (
            hashlib.sha256(tracked_patch).hexdigest() if tracked_patch else None
        ),
        "untracked_files": untracked_entries,
    }
    patch_bytes = _canonical_json_bytes(patch_identity)
    return {
        "schema_version": "git_provenance_v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(root),
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "worktree_patch_sha256": (
            hashlib.sha256(patch_bytes).hexdigest() if git_dirty else None
        ),
        "status_porcelain": status_porcelain.splitlines(),
        **patch_identity,
        "git_state_available": True,
        "git_state_error": None,
    }


def _runtime_environment() -> dict[str, Any]:
    gurobi_available = False
    gurobi_version: str | None = None
    try:
        import gurobipy as gp

        gurobi_available = True
        version = gp.gurobi.version()
        gurobi_version = ".".join(str(item) for item in version)
    except (ImportError, AttributeError, RuntimeError):
        pass
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "gurobi_available": gurobi_available,
        "gurobi_version": gurobi_version,
    }


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
    prepared_trips = list(prepared_input.get("trips") or ())
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
        "prepared_trip_input_schema": PREPARED_TRIP_INPUT_SCHEMA,
        "prepared_trip_count": len(prepared_trips),
        "prepared_trip_input_sha256": _inventory_hash(prepared_trips),
        "prepare_snapshot": snapshot,
        "omitted_large_payload_fields": omitted_fields,
        "omission_semantics": (
            "Large row-level prepared fields are not duplicated into each run. "
            "The source artifact path, byte size, full SHA-256, scope hashes, "
            "counts, profile, and audit make later identity checks fail-closed."
        ),
    }


def _trip_structure_input(trip_input: Sequence[Any]) -> list[Any]:
    """Remove every demand-derived field from canonical trip structure.

    ``required_soc_departure_percent`` is derived from the selected trip
    energy model and its sensitivity scale.  Keeping it in a structure hash
    made a controlled energy-demand sensitivity look like timetable drift.
    """

    demand_derived_fields = {
        "energy_kwh",
        "fuel_l",
        "energy_kwh_by_vehicle_type",
        "fuel_l_by_vehicle_type",
        "energy_model_id",
        "energy_model_provenance",
        "required_soc_departure_percent",
    }
    return [
        {
            key: value
            for key, value in dict(item).items()
            if key not in demand_derived_fields
        }
        if isinstance(item, Mapping)
        else item
        for item in trip_input
    ]


def _optimization_parameters(
    *,
    scenario_id: str,
    prepared_input_id: str,
    frontend_request: Mapping[str, Any],
    optimization_config: Any,
    canonical_problem: Any,
    code_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    metadata, omitted_metadata = _bounded_mapping(
        dict(getattr(canonical_problem, "metadata", {}) or {}),
    )
    problem_scenario = getattr(canonical_problem, "scenario", None)
    trips = tuple(getattr(canonical_problem, "trips", ()) or ())
    vehicles = tuple(getattr(canonical_problem, "vehicles", ()) or ())
    chargers = tuple(getattr(canonical_problem, "chargers", ()) or ())
    depots = tuple(getattr(canonical_problem, "depots", ()) or ())
    vehicle_types = tuple(
        getattr(canonical_problem, "vehicle_types", ()) or ()
    )
    price_slots = tuple(getattr(canonical_problem, "price_slots", ()) or ())
    pv_slots = tuple(getattr(canonical_problem, "pv_slots", ()) or ())
    trip_input = [_json_safe(item) for item in trips]
    trip_structure_input = _trip_structure_input(trip_input)
    vehicle_input = [_json_safe(item) for item in vehicles]
    charger_input = [_json_safe(item) for item in chargers]
    depot_input = [_json_safe(item) for item in depots]
    vehicle_type_input = [_json_safe(item) for item in vehicle_types]
    price_input = [_json_safe(item) for item in price_slots]
    price_value_set_input = sorted(
        {
            (
                float(getattr(item, "grid_buy_yen_per_kwh", 0.0) or 0.0),
                float(getattr(item, "grid_sell_yen_per_kwh", 0.0) or 0.0),
                float(getattr(item, "demand_charge_weight", 0.0) or 0.0),
                float(getattr(item, "co2_factor", 0.0) or 0.0),
            )
            for item in price_slots
        }
    )
    objective_weights_input = _json_safe(
        getattr(canonical_problem, "objective_weights", None)
    )
    pv_input = {
        "pv_slots": [_json_safe(item) for item in pv_slots],
        "depot_energy_assets": _json_safe(
            getattr(canonical_problem, "depot_energy_assets", {}) or {}
        ),
    }
    energy_asset_control_input = _json_safe(
        getattr(canonical_problem, "depot_energy_assets", {}) or {}
    )
    if isinstance(energy_asset_control_input, Mapping):
        energy_asset_control_input = {
            str(depot_id): {
                key: value
                for key, value in dict(asset).items()
                if key
                not in {
                    "pv_generation_kwh_by_slot",
                    "available_pv_surplus_kwh_by_slot",
                    "capacity_factor_by_slot",
                    "pv_supply_scale",
                }
            }
            if isinstance(asset, Mapping)
            else asset
            for depot_id, asset in energy_asset_control_input.items()
        }
    canonical_ablation_input = {
        "scenario": _json_safe(problem_scenario),
        "objective_weights": objective_weights_input,
        "trips": trip_input,
        "vehicles": vehicle_input,
        "vehicle_types": vehicle_type_input,
        "depots": depot_input,
        "chargers": charger_input,
        "price_slots": price_input,
        "pv_input": pv_input,
        "feasible_connections": _json_safe(
            getattr(canonical_problem, "feasible_connections", {}) or {}
        ),
        "baseline_plan": _json_safe(
            getattr(canonical_problem, "baseline_plan", None)
        ),
    }
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
        "code_provenance": _json_safe(code_provenance),
        "runtime_environment": _runtime_environment(),
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
            "trip_input_sha256": hashlib.sha256(
                _canonical_json_bytes(trip_input)
            ).hexdigest(),
            "trip_structure_input_schema": TRIP_STRUCTURE_SCHEMA,
            "trip_structure_input_sha256": hashlib.sha256(
                _canonical_json_bytes(trip_structure_input)
            ).hexdigest(),
            "vehicle_input_sha256": hashlib.sha256(
                _canonical_json_bytes(vehicle_input)
            ).hexdigest(),
            "charger_input_sha256": hashlib.sha256(
                _canonical_json_bytes(charger_input)
            ).hexdigest(),
            "depot_input_sha256": hashlib.sha256(
                _canonical_json_bytes(depot_input)
            ).hexdigest(),
            "vehicle_type_input_sha256": hashlib.sha256(
                _canonical_json_bytes(vehicle_type_input)
            ).hexdigest(),
            "price_input_sha256": hashlib.sha256(
                _canonical_json_bytes(price_input)
            ).hexdigest(),
            "price_value_set_sha256": hashlib.sha256(
                _canonical_json_bytes(price_value_set_input)
            ).hexdigest(),
            "energy_asset_control_input_sha256": hashlib.sha256(
                _canonical_json_bytes(energy_asset_control_input)
            ).hexdigest(),
            "objective_weights_sha256": hashlib.sha256(
                _canonical_json_bytes(objective_weights_input)
            ).hexdigest(),
            "pv_profile_sha256": hashlib.sha256(
                _canonical_json_bytes(pv_input)
            ).hexdigest(),
            "canonical_ablation_input_sha256": hashlib.sha256(
                _canonical_json_bytes(canonical_ablation_input)
            ).hexdigest(),
        },
        "comparison_contract": {
            "service_date": metadata.get("service_date"),
            "weather_observation_date": metadata.get(
                "weather_observation_date",
                metadata.get("weather_reference_date"),
            ),
            "weather_profile_source": metadata.get(
                "weather_profile_source",
                metadata.get("weather_source"),
            ),
            "comparison_type": metadata.get(
                "comparison_type",
                (
                    "counterfactual_weather_profile"
                    if metadata.get("weather_pv_counterfactual")
                    else "actual_service_day"
                ),
            ),
            "service_calendar_validation": metadata.get(
                "service_calendar_validation"
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
    code_provenance = dict(parameters.get("code_provenance") or {})
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
        f"- git SHA: `{code_provenance.get('git_sha')}`",
        f"- git dirty: `{code_provenance.get('git_dirty')}`",
        f"- Git provenance available: `{code_provenance.get('git_state_available')}`",
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
    code_provenance: Mapping[str, Any] | None = None,
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
    resolved_code_provenance = dict(code_provenance or collect_git_state())
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
        code_provenance=resolved_code_provenance,
    )
    _write_json(resolved_run_dir / SCENARIO_SNAPSHOT_FILE, scenario_snapshot)
    _write_json(resolved_run_dir / PREPARE_AUDIT_FILE, prepare_audit)
    _write_json(resolved_run_dir / PARAMETERS_FILE, parameters)
    _write_json(resolved_run_dir / CODE_PROVENANCE_FILE, resolved_code_provenance)
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
        "git_sha": resolved_code_provenance.get("git_sha"),
        "git_dirty": resolved_code_provenance.get("git_dirty"),
        "git_state_available": bool(
            resolved_code_provenance.get("git_state_available", False)
        ),
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
        "research_ready": bool(validation.get("research_ready", False)),
        "manifest_path": MANIFEST_FILE,
        "validation_path": VALIDATION_FILE,
        "summary_path": SUMMARY_FILE,
        "prepared_source_sha256": prepared_sha256,
        "code_provenance": resolved_code_provenance,
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
    schema_version = str(manifest.get("schema_version") or "")
    checks["schema_version_supported"] = schema_version in {
        SCHEMA_VERSION,
        *LEGACY_SCHEMA_VERSIONS,
    }
    artifact_names = (
        CORE_ARTIFACTS
        if schema_version == SCHEMA_VERSION
        else LEGACY_CORE_ARTIFACTS
    )
    artifact_payloads: dict[str, Any] = {}
    for name in artifact_names:
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
    if schema_version == SCHEMA_VERSION:
        code_provenance = dict(artifact_payloads.get(CODE_PROVENANCE_FILE) or {})
        checks["code_provenance_git_state_declared"] = {
            "git_sha",
            "git_dirty",
            "git_state_available",
            "git_state_error",
        }.issubset(code_provenance)
        checks["code_provenance_git_state_available_is_boolean"] = isinstance(
            code_provenance.get("git_state_available"),
            bool,
        )
        checks["code_provenance_matches_manifest"] = (
            manifest.get("git_sha") == code_provenance.get("git_sha")
            and manifest.get("git_dirty") == code_provenance.get("git_dirty")
            and bool(manifest.get("git_state_available", False))
            == bool(code_provenance.get("git_state_available", False))
        )
    else:
        details["legacy_code_provenance"] = (
            "This v1 input bundle predates the explicit Git provenance artifact."
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
    code_provenance = dict(artifact_payloads.get(CODE_PROVENANCE_FILE) or {})
    research_ready = bool(
        not failed_checks
        and schema_version == SCHEMA_VERSION
        and code_provenance.get("git_state_available") is True
        and code_provenance.get("git_dirty") is False
        and str(code_provenance.get("git_sha") or "").strip()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "valid": not failed_checks,
        "research_ready": research_ready,
        "research_readiness_reasons": (
            []
            if research_ready
            else [
                *failed_checks,
                *(
                    ["git_state_unavailable"]
                    if code_provenance.get("git_state_available") is not True
                    else []
                ),
                *(
                    ["git_worktree_dirty"]
                    if code_provenance.get("git_dirty") is not False
                    else []
                ),
                *(
                    ["git_sha_missing"]
                    if not str(code_provenance.get("git_sha") or "").strip()
                    else []
                ),
            ]
        ),
        "verify_prepared_source": verify_prepared_source,
        "checks": checks,
        "failed_checks": failed_checks,
        "details": details,
    }
