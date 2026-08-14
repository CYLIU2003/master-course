"""Fail-closed completion audit for the thesis model-improvement phases.

The optimizer already emits focused provenance, physical-validation,
accounting, ablation, and sensitivity artifacts.  This module does not infer
missing evidence or invoke a solver.  It composes those artifacts into one
phase ledger and prevents a later phase from being declared complete while an
earlier phase is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from bff.services.optimization_run.input_provenance import (
    validate_run_input_provenance,
)
from bff.services.optimization_run.sensitivity_execution_contract import (
    is_supported_sensitivity_execution_schema,
)


SCHEMA_VERSION = "thesis_model_phase_gate_audit_v1"
ABLATION_SCHEMA_VERSION = "thesis_day_ahead_ablation_comparison_v1"
EQUATION_MAP_SCHEMA_VERSION = "thesis_equation_code_test_map_audit_v1"

_PHASE_TITLES = {
    "phase0": "Frozen baseline and reproducible run evidence",
    "phase1": "Trip connections, deadhead, turnaround, and compatibility",
    "phase2": "Trip-level energy model and coefficient sensitivity",
    "phase3": "Objective, vehicle-day, deadhead, and CO2 semantics",
    "phase4": "Time discretization and charging-power model",
    "phase5": "Same-input M0-M3 ablation comparison",
    "phase6": "PV, price, infrastructure, SOC, and CO2 sensitivity",
    "phase7": "Equation-code-test-report integration",
}

_FAMILY_CASES: dict[str, tuple[str, ...]] = {
    "route_band_ablation": ("ROUTE_BAND_ON", "ROUTE_BAND_OFF"),
    "turnaround_buffer_sensitivity": (
        "TURNAROUND_BUFFER_5",
        "TURNAROUND_BUFFER_10",
        "TURNAROUND_BUFFER_15",
    ),
    "trip_energy_sensitivity": (
        "ENERGY_0.8",
        "ENERGY_0.9",
        "ENERGY_1.0",
        "ENERGY_1.1",
        "ENERGY_1.2",
    ),
    "bev_trip_energy_sensitivity": (
        "BEV_ENERGY_0.8",
        "BEV_ENERGY_0.9",
        "BEV_ENERGY_1.0",
        "BEV_ENERGY_1.1",
        "BEV_ENERGY_1.2",
    ),
    "ice_trip_fuel_sensitivity": (
        "ICE_FUEL_0.8",
        "ICE_FUEL_0.9",
        "ICE_FUEL_1.0",
        "ICE_FUEL_1.1",
        "ICE_FUEL_1.2",
    ),
    "vehicle_day_cost_sensitivity": (
        "VEHICLE_DAY_0",
        "VEHICLE_DAY_20000",
    ),
    "time_discretization": ("TIME_15", "TIME_30", "TIME_60"),
    "pv_supply_transition": (
        "PV_0.00",
        "PV_0.25",
        "PV_0.50",
        "PV_0.75",
        "PV_1.00",
    ),
    "cost_co2_epsilon_frontier": (
        "CO2_UNCAPPED",
        "CO2_CAP_750",
        "CO2_CAP_500",
        "CO2_CAP_250",
        "CO2_CAP_100",
    ),
}

# These Phase 6 families are part of the active research goal but are not yet
# declared by build_thesis_experiment_matrix.py.  Keeping them explicit here
# makes the gate forward-compatible and, importantly, fail-closed today.
_PHASE6_MINIMUM_FAMILY_CASES = {
    "electricity_price_sensitivity": 3,
    "diesel_price_sensitivity": 3,
    "charger_capacity_sensitivity": 3,
    "initial_terminal_soc_sensitivity": 3,
    "pv_tariff_transition_map": 4,
}


@dataclass(frozen=True)
class _PhaseContext:
    artifacts: Mapping[str, Mapping[str, Any]]
    artifact_errors: Sequence[str]
    input_validation: Mapping[str, Any]
    snapshot_evidence: Mapping[str, Any]
    sensitivity_evidence: Mapping[str, Any]
    ablation_evidence: Mapping[str, Any]
    equation_map_evidence: Mapping[str, Any]
    prepared_scope_audit: Mapping[str, Any]
    solver_metadata: Mapping[str, Any]
    git_sha: str
    prepared_trip_count: int | None
    served_trip_count: int | None
    unserved_trip_count: int | None
    expected_count_matches: bool


def build_thesis_phase_gate_audit(
    *,
    run_dir: Path,
    sensitivity_manifest_paths: Iterable[Path] = (),
    ablation_comparison_path: Path | None = None,
    equation_map_audit_path: Path | None = None,
    expected_trip_count: int | None = None,
    verify_prepared_source: bool = True,
) -> dict[str, Any]:
    """Build a machine-readable Phase 0--7 completion ledger.

    Args:
        run_dir: Frozen frontend/BFF run used as the reference case.
        sensitivity_manifest_paths: Audited sensitivity execution manifests.
        ablation_comparison_path: Same-input M0--M3 comparison artifact.
        equation_map_audit_path: Final equation/code/test traceability audit.
        expected_trip_count: Optional independently declared trip count.
        verify_prepared_source: Re-hash the materialized prepared input.

    Returns:
        A JSON-serializable fail-closed phase ledger.  This function is
        read-only and never upgrades the source run's own release status.
    """

    resolved_run_dir = Path(run_dir).resolve()
    artifacts, artifact_errors = _load_run_artifacts(resolved_run_dir)
    input_validation = _validate_input_provenance(
        resolved_run_dir,
        verify_prepared_source=verify_prepared_source,
    )
    solver_settings = artifacts["solver_settings.json"]
    summary = artifacts["summary.json"]
    completeness = artifacts["artifact_completeness.json"]
    optimization_result = artifacts["optimization_result.json"]
    solver_metadata = _solver_metadata(optimization_result)
    prepare_audit = artifacts["prepare_input_audit.json"]
    prepared_scope_audit = _prepared_scope_audit(optimization_result)
    code_provenance = artifacts["code_provenance.json"]

    git_sha = str(
        code_provenance.get("git_sha")
        or solver_settings.get("git_sha")
        or ""
    ).strip()
    sensitivity_evidence = _load_sensitivity_evidence(
        sensitivity_manifest_paths,
        expected_git_sha=git_sha,
    )
    ablation_evidence = _load_ablation_evidence(
        ablation_comparison_path,
        expected_git_sha=git_sha,
    )
    equation_map_evidence = _load_equation_map_evidence(
        equation_map_audit_path,
        expected_git_sha=git_sha,
    )
    snapshot_evidence = _verify_artifact_snapshot(
        run_dir=resolved_run_dir,
        completeness=completeness,
    )

    prepared_trip_count = _first_int(
        prepare_audit.get("prepared_trip_count"),
        _nested_value(prepare_audit, "prepare_snapshot", "trip_count"),
        _nested_value(
            prepared_scope_audit,
            "strict_coverage_precheck",
            "trip_count",
        ),
        _nested_value(prepared_scope_audit, "trip_distance_audit", "total_count"),
    )
    served_trip_count = _as_int(summary.get("trip_count_served"))
    unserved_trip_count = _as_int(summary.get("trip_count_unserved"))
    expected_count_matches = bool(
        expected_trip_count is None
        or (
            prepared_trip_count == expected_trip_count
            and served_trip_count == expected_trip_count
        )
    )

    phase_checks = _build_phase_checks(
        _PhaseContext(
            artifacts=artifacts,
            artifact_errors=artifact_errors,
            input_validation=input_validation,
            snapshot_evidence=snapshot_evidence,
            sensitivity_evidence=sensitivity_evidence,
            ablation_evidence=ablation_evidence,
            equation_map_evidence=equation_map_evidence,
            prepared_scope_audit=prepared_scope_audit,
            solver_metadata=solver_metadata,
            git_sha=git_sha,
            prepared_trip_count=prepared_trip_count,
            served_trip_count=served_trip_count,
            unserved_trip_count=unserved_trip_count,
            expected_count_matches=expected_count_matches,
        )
    )

    phases = _build_dependent_phase_results(phase_checks)
    highest_complete_phase = None
    for phase_id in _PHASE_TITLES:
        if phases[phase_id]["status"] != "COMPLETE":
            break
        highest_complete_phase = phase_id

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(resolved_run_dir),
        "reference_git_sha": git_sha or None,
        "reference_prepared_input_id": prepare_audit.get("prepared_input_id"),
        "reference_prepared_trip_count": prepared_trip_count,
        "expected_trip_count": expected_trip_count,
        "status": (
            "COMPLETE"
            if phases["phase7"]["status"] == "COMPLETE"
            else "BLOCKED"
        ),
        "highest_complete_phase": highest_complete_phase,
        "next_blocked_phase": _next_blocked_phase(phases),
        "phases": phases,
        "artifact_load_errors": artifact_errors,
        "input_provenance_validation": input_validation,
        "artifact_snapshot_validation": snapshot_evidence,
        "sensitivity_evidence": sensitivity_evidence,
        "ablation_evidence": ablation_evidence,
        "equation_map_evidence": equation_map_evidence,
        "claim_scope": (
            "Phase-completion evidence composition only. This audit does not "
            "upgrade any source run, sensitivity case, ablation, optimality, "
            "or teacher-release decision beyond its own recorded gates."
        ),
    }
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


_RUN_ARTIFACT_NAMES = (
    "artifact_completeness.json",
    "assignment_economic_audit.json",
    "code_provenance.json",
    "final_cost_reconciliation.json",
    "optimization_parameters.json",
    "optimization_result.json",
    "physical_schedule_validation.json",
    "prepare_input_audit.json",
    "run_manifest.json",
    "solver_settings.json",
    "summary.json",
    "rolling_hourly_chain/executed_day_accounting.json",
    "rolling_hourly_chain/rolling_chain_summary.json",
)


def _build_phase_checks(
    context: _PhaseContext,
) -> dict[str, dict[str, bool]]:
    return {
        "phase0": _phase0_checks(context),
        "phase1": _phase1_checks(context),
        "phase2": _phase2_checks(context),
        "phase3": _phase3_checks(context),
        "phase4": _phase4_checks(context),
        "phase5": _phase5_checks(context),
        "phase6": _phase6_checks(context),
        "phase7": _phase7_checks(context),
    }


def _phase0_checks(context: _PhaseContext) -> dict[str, bool]:
    artifacts = context.artifacts
    code = artifacts["code_provenance.json"]
    settings = artifacts["solver_settings.json"]
    manifest = artifacts["run_manifest.json"]
    summary = artifacts["summary.json"]
    physical = artifacts["physical_schedule_validation.json"]
    rolling = artifacts["rolling_hourly_chain/rolling_chain_summary.json"]
    accounting = artifacts[
        "rolling_hourly_chain/executed_day_accounting.json"
    ]
    reconciliation = artifacts["final_cost_reconciliation.json"]
    completeness = artifacts["artifact_completeness.json"]
    expected_steps = _as_int(rolling.get("expected_step_count"))
    return {
        "required_run_artifacts_readable": not context.artifact_errors,
        "input_provenance_valid": (
            context.input_validation.get("valid") is True
        ),
        "input_provenance_research_ready": (
            context.input_validation.get("research_ready") is True
        ),
        "clean_nonempty_frozen_git_sha": bool(
            context.git_sha
            and code.get("git_state_available") is True
            and code.get("git_dirty") is False
        ),
        "same_git_sha_across_run_artifacts": bool(
            context.git_sha
            and settings.get("git_sha") == context.git_sha
            and manifest.get("git_sha") == context.git_sha
        ),
        "git_state_unchanged_during_solve": (
            settings.get("git_state_unchanged_during_solve") is True
        ),
        "formal_research_run_accepted": bool(
            settings.get("research_run") is True
            and settings.get("research_run_accepted") is True
            and manifest.get("research_run") is True
            and manifest.get("research_run_accepted") is True
        ),
        "explicit_phase4_integrated_execution": _phase4_execution_recorded(
            settings,
            manifest,
        ),
        "complete_successor_network": (
            settings.get("successor_pruning_enabled") is False
        ),
        "no_fallback_or_postsolve_repair": bool(
            settings.get("fallback_applied") is False
            and context.solver_metadata.get("fallback_applied") is False
            and context.solver_metadata.get("postsolve_soc_repair_applied")
            is False
            and context.solver_metadata.get("postsolve_modified_solution")
            is False
        ),
        "all_prepared_trips_served_once": bool(
            context.prepared_trip_count is not None
            and context.prepared_trip_count > 0
            and context.served_trip_count == context.prepared_trip_count
            and context.unserved_trip_count == 0
        ),
        "independent_expected_trip_count_matches": (
            context.expected_count_matches
        ),
        "physical_schedule_valid": bool(
            physical.get("schema_version") == "physical_schedule_validation_v2"
            and physical.get("status") == "VALID"
            and physical.get("accepted") is True
            and not list(physical.get("failed_checks") or [])
        ),
        "rolling_chain_accepted": bool(
            rolling.get("chain_accepted") is True
            and rolling.get("all_steps_feasible") is True
            and expected_steps is not None
            and _as_int(rolling.get("step_count")) == expected_steps
        ),
        "executed_day_accounting_eligible": accounting.get("eligible") is True,
        "final_cost_reconciliation_passed": bool(
            reconciliation.get("status") == "OK"
            and not list(reconciliation.get("failed_artifacts") or [])
        ),
        "artifact_bundle_complete": bool(
            completeness.get("status") == "OK"
            and completeness.get("accepted") is True
            and completeness.get("research_run") is True
        ),
        "finalized_artifact_hashes_match": (
            context.snapshot_evidence.get("valid") is True
        ),
        "declared_mip_gap_target_met": bool(
            settings.get("mip_gap_target_met") is True
            and summary.get("mip_gap_target_met") is True
        ),
    }


def _phase4_execution_recorded(
    settings: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bool:
    phase_fields = ("requested_phase", "resolved_phase", "executed_phase")
    return all(
        artifact.get(field) == "phase4_integrated"
        for artifact in (settings, manifest)
        for field in phase_fields
    )


def _phase1_checks(context: _PhaseContext) -> dict[str, bool]:
    scope = context.prepared_scope_audit
    route_band = dict(scope.get("route_band_off_transition_audit") or {})
    turnaround = dict(scope.get("turnaround_buffer_sensitivity_audit") or {})
    compatibility = dict(scope.get("vehicle_trip_compatibility_audit") or {})
    physical = context.artifacts["physical_schedule_validation.json"]
    return {
        "formal_transition_network_ready": (
            scope.get("formal_transition_network_ready") is True
        ),
        "route_band_off_network_checked": bool(
            scope.get("route_band_off_transition_audit_checked") is True
            and route_band.get("checked") is True
        ),
        "route_band_off_deadhead_missing_zero": bool(
            _blocked_reason_count(route_band, "deadhead_missing") == 0
            and _as_int(scope.get("route_band_off_deadhead_missing_count")) == 0
        ),
        "turnaround_5_10_15_structurally_valid": bool(
            scope.get("formal_turnaround_sensitivity_ready") is True
            and turnaround.get("status") == "VALID"
            and turnaround.get("levels_minutes") == [5, 10, 15]
            and turnaround.get("transition_graph_evaluated_all_levels") is True
        ),
        "vehicle_trip_compatibility_explicit": bool(
            scope.get("formal_vehicle_trip_compatibility_ready") is True
            and compatibility.get("implicit_fallback_trip_count") == 0
            and compatibility.get("solver_powertrain_projection_exact") is True
            and str(compatibility.get("compatibility_matrix_sha256") or "")
        ),
        "route_band_on_off_optimized_comparison_accepted": _family_passed(
            context.sensitivity_evidence,
            "route_band_ablation",
        ),
        "turnaround_5_10_15_optimized_comparison_accepted": _family_passed(
            context.sensitivity_evidence,
            "turnaround_buffer_sensitivity",
        ),
        "deadhead_included_in_independent_physical_validation": bool(
            dict(physical.get("checks") or {}).get(
                "independent_event_schedule_accepted"
            )
            is True
            and _as_int(
                dict(physical.get("validation_metrics") or {}).get(
                    "infeasible_transition_count"
                )
            )
            == 0
        ),
    }


def _phase2_checks(context: _PhaseContext) -> dict[str, bool]:
    assignment = context.artifacts["assignment_economic_audit.json"]
    return {
        "trip_level_energy_model_enabled": (
            assignment.get("trip_energy_model") == "literature_proxy_v1"
        ),
        "trip_energy_model_has_declared_provenance": bool(
            assignment.get("trip_energy_model")
            and assignment.get("trip_energy_model") != "distance_average_v0"
        ),
        "energy_80_to_120_percent_sensitivity_accepted": _family_passed(
            context.sensitivity_evidence,
            "trip_energy_sensitivity",
        ),
        "bev_energy_80_to_120_percent_one_factor_sensitivity_accepted": (
            _family_passed(
                context.sensitivity_evidence,
                "bev_trip_energy_sensitivity",
            )
        ),
        "ice_fuel_80_to_120_percent_one_factor_sensitivity_accepted": (
            _family_passed(
                context.sensitivity_evidence,
                "ice_trip_fuel_sensitivity",
            )
        ),
    }


def _phase3_checks(context: _PhaseContext) -> dict[str, bool]:
    assignment = context.artifacts["assignment_economic_audit.json"]
    settings = context.artifacts["solver_settings.json"]
    return {
        "research_lexicographic_objective_enabled": bool(
            assignment.get("objective_preset") == "research_lexicographic_v1"
            and settings.get("integrated_primary_objective_kind")
            == "minimum_used_vehicle_days_lexicographic"
        ),
        "vehicle_usage_cost_semantics_classified": bool(
            assignment.get("vehicle_usage_cost_semantics_classified") is True
            and assignment.get("vehicle_usage_cost_semantics_research_eligible")
            is True
        ),
        "canonical_actual_cost_structure_valid": (
            settings.get("actual_cost_objective_structural_contract_passed")
            is True
        ),
        "deadhead_and_charge_session_tiebreakers_declared": (
            context.solver_metadata.get("objective_semantics")
            == (
                "lexicographic_vehicle_days_then_canonical_cost_then_"
                "deadhead_and_charge_sessions"
            )
        ),
        "vehicle_day_cost_sensitivity_accepted": _family_passed(
            context.sensitivity_evidence,
            "vehicle_day_cost_sensitivity",
        ),
        "co2_role_explicit": "co2_emissions_cap_kg" in assignment,
    }


def _phase4_checks(context: _PhaseContext) -> dict[str, bool]:
    assignment = context.artifacts["assignment_economic_audit.json"]
    model = dict(
        context.artifacts["optimization_parameters.json"].get(
            "effective_model_metadata"
        )
        or {}
    )
    return {
        "piecewise_soc_taper_enabled": (
            assignment.get("charging_power_model")
            == "piecewise_soc_taper_v1"
        ),
        "setup_teardown_and_minimum_session_declared": all(
            _positive_number(model.get(field))
            for field in (
                "charge_setup_minutes",
                "charge_teardown_minutes",
                "minimum_charge_session_minutes",
            )
        ),
        "time_15_30_60_sensitivity_accepted": _family_passed(
            context.sensitivity_evidence,
            "time_discretization",
        ),
    }


def _phase5_checks(context: _PhaseContext) -> dict[str, bool]:
    return {
        "same_input_m0_m3_ablation_ready": (
            context.ablation_evidence.get("passed") is True
        )
    }


def _phase6_checks(context: _PhaseContext) -> dict[str, bool]:
    checks = {
        "pv_supply_transition_sensitivity_accepted": _family_passed(
            context.sensitivity_evidence,
            "pv_supply_transition",
        ),
        "cost_co2_epsilon_frontier_accepted": _family_passed(
            context.sensitivity_evidence,
            "cost_co2_epsilon_frontier",
        ),
    }
    checks.update(
        {
            f"{family}_accepted": _family_passed(
                context.sensitivity_evidence,
                family,
                minimum_case_count=minimum_case_count,
            )
            for family, minimum_case_count in _PHASE6_MINIMUM_FAMILY_CASES.items()
        }
    )
    return checks


def _phase7_checks(context: _PhaseContext) -> dict[str, bool]:
    physical = context.artifacts["physical_schedule_validation.json"]
    accounting = context.artifacts[
        "rolling_hourly_chain/executed_day_accounting.json"
    ]
    reconciliation = context.artifacts["final_cost_reconciliation.json"]
    return {
        "equation_code_test_map_complete": (
            context.equation_map_evidence.get("passed") is True
        ),
        "all_public_outputs_use_canonical_sources": bool(
            physical.get("accepted") is True
            and accounting.get("eligible") is True
            and reconciliation.get("status") == "OK"
            and context.snapshot_evidence.get("valid") is True
        ),
    }


def _load_run_artifacts(
    run_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    artifacts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for relative_name in _RUN_ARTIFACT_NAMES:
        path = run_dir / relative_name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON root is not an object")
            artifacts[relative_name] = payload
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            artifacts[relative_name] = {}
            errors.append(f"{relative_name}:{type(exc).__name__}")
    return artifacts, errors


def _validate_input_provenance(
    run_dir: Path,
    *,
    verify_prepared_source: bool,
) -> dict[str, Any]:
    try:
        return validate_run_input_provenance(
            run_dir,
            verify_prepared_source=verify_prepared_source,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "valid": False,
            "research_ready": False,
            "failed_checks": ["input_provenance_validation_error"],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _verify_artifact_snapshot(
    *,
    run_dir: Path,
    completeness: Mapping[str, Any],
) -> dict[str, Any]:
    declared = completeness.get("artifacts")
    if not isinstance(declared, Mapping) or not declared:
        return {
            "valid": False,
            "verified_count": 0,
            "failed_artifacts": ["artifact_snapshot_missing"],
        }
    failures: list[str] = []
    verified_count = 0
    for relative_name, raw_evidence in declared.items():
        evidence = raw_evidence if isinstance(raw_evidence, Mapping) else {}
        candidate = (run_dir / str(relative_name)).resolve()
        try:
            candidate.relative_to(run_dir)
        except ValueError:
            failures.append(f"{relative_name}:outside_run_dir")
            continue
        if not candidate.is_file():
            failures.append(f"{relative_name}:missing")
            continue
        expected_size = _as_int(evidence.get("size_bytes"))
        expected_sha = str(evidence.get("sha256") or "")
        if expected_size != candidate.stat().st_size:
            failures.append(f"{relative_name}:size")
            continue
        if not expected_sha or _sha256_file(candidate) != expected_sha:
            failures.append(f"{relative_name}:sha256")
            continue
        verified_count += 1
    return {
        "valid": not failures and verified_count == len(declared),
        "verified_count": verified_count,
        "declared_count": len(declared),
        "failed_artifacts": failures,
    }


def _load_sensitivity_evidence(
    paths: Iterable[Path],
    *,
    expected_git_sha: str,
) -> dict[str, Any]:
    family_candidates: dict[str, list[dict[str, Any]]] = {}
    manifest_rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        row: dict[str, Any] = {
            "path": str(path),
            "valid": False,
            "families": [],
        }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON root is not an object")
            declared_sha = str(payload.get("payload_sha256") or "")
            unsigned = dict(payload)
            unsigned.pop("payload_sha256", None)
            payload_hash_valid = bool(
                declared_sha and declared_sha == _payload_sha(unsigned)
            )
            outcomes = [
                item
                for item in list(payload.get("outcomes") or [])
                if isinstance(item, Mapping)
            ]
            families = sorted(
                {
                    str(item.get("family") or "")
                    for item in outcomes
                    if str(item.get("family") or "")
                }
            )
            selected_case_ids = {
                str(case_id)
                for case_id in list(payload.get("selected_case_ids") or [])
            }
            completed_case_ids = {
                str(case_id)
                for case_id in list(payload.get("completed_case_ids") or [])
            }
            outcome_case_ids = {
                str(item.get("case_id") or "") for item in outcomes
            }
            outcome_checks_valid = bool(
                outcomes
                and all(
                    item.get("case_accepted") is True
                    and not list(item.get("failed_checks") or [])
                    and isinstance(item.get("checks"), Mapping)
                    and bool(item.get("checks"))
                    and all(
                        value is True
                        for value in dict(item.get("checks") or {}).values()
                    )
                    for item in outcomes
                )
            )
            common_valid = bool(
                is_supported_sensitivity_execution_schema(
                    payload.get("schema_version")
                )
                and payload_hash_valid
                and expected_git_sha
                and payload.get("frozen_git_sha") == expected_git_sha
                and bool(str(payload.get("audit_builder_git_sha") or ""))
                and selected_case_ids
                and selected_case_ids == completed_case_ids
                and selected_case_ids == outcome_case_ids
                and outcome_checks_valid
                and payload.get("all_selected_cases_completed") is True
                and payload.get("all_selected_cases_accepted") is True
                and payload.get("stable_nonvaried_controls_match") is True
                and payload.get("status")
                in {
                    "COMPLETED_SUBSET",
                    "READY_FOR_SENSITIVITY_ANALYSIS",
                }
            )
            row.update(
                {
                    "valid": common_valid,
                    "schema_version": payload.get("schema_version"),
                    "payload_hash_valid": payload_hash_valid,
                    "frozen_git_sha": payload.get("frozen_git_sha"),
                    "case_identity_consistent": bool(
                        selected_case_ids
                        and selected_case_ids == completed_case_ids
                        and selected_case_ids == outcome_case_ids
                    ),
                    "outcome_checks_valid": outcome_checks_valid,
                    "families": families,
                    "selected_case_ids": list(
                        payload.get("selected_case_ids") or []
                    ),
                    "status": payload.get("status"),
                }
            )
            for family in families:
                family_candidates.setdefault(family, []).append(
                    {
                        "manifest_path": str(path),
                        "manifest_valid": common_valid,
                        "case_ids": sorted(
                            str(item.get("case_id") or "")
                            for item in outcomes
                            if str(item.get("family") or "") == family
                            and item.get("case_accepted") is True
                        ),
                    }
                )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        manifest_rows.append(row)

    family_results: dict[str, dict[str, Any]] = {}
    all_families = {
        *_FAMILY_CASES,
        *_PHASE6_MINIMUM_FAMILY_CASES,
        *family_candidates,
    }
    for family in sorted(all_families):
        required = set(_FAMILY_CASES.get(family, ()))
        minimum_count = _PHASE6_MINIMUM_FAMILY_CASES.get(family)
        candidates = family_candidates.get(family, [])
        accepted_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate["manifest_valid"]
                and (
                    required.issubset(set(candidate["case_ids"]))
                    if required
                    else len(set(candidate["case_ids"]))
                    >= int(minimum_count or 1)
                )
            ),
            None,
        )
        family_results[family] = {
            "passed": accepted_candidate is not None,
            "required_case_ids": sorted(required),
            "minimum_case_count": minimum_count,
            "accepted_manifest_path": (
                accepted_candidate.get("manifest_path")
                if accepted_candidate
                else None
            ),
            "candidate_manifests": candidates,
        }
    return {"manifests": manifest_rows, "families": family_results}


def _load_ablation_evidence(
    path: Path | None,
    *,
    expected_git_sha: str,
) -> dict[str, Any]:
    if path is None:
        return {"passed": False, "path": None, "reason": "not_provided"}
    resolved = Path(path).resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root is not an object")
        declared_sha = str(payload.get("payload_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("payload_sha256", None)
        hash_valid = bool(declared_sha and declared_sha == _payload_sha(unsigned))
        passed = bool(
            payload.get("schema_version") == ABLATION_SCHEMA_VERSION
            and hash_valid
            and expected_git_sha
            and payload.get("git_sha") == expected_git_sha
            and payload.get("status")
            == "READY_FOR_DAY_AHEAD_METHOD_COMPARISON"
            and payload.get("complete_four_method_comparison_available") is True
            and payload.get("research_conclusion_eligible") is True
            and payload.get("available_method_ids")
            == ["M0", "M1", "M2", "M3"]
            and not list(payload.get("failed_checks") or [])
        )
        return {
            "passed": passed,
            "path": str(resolved),
            "payload_hash_valid": hash_valid,
            "git_sha": payload.get("git_sha"),
            "status": payload.get("status"),
            "failed_checks": list(payload.get("failed_checks") or []),
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "passed": False,
            "path": str(resolved),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _load_equation_map_evidence(
    path: Path | None,
    *,
    expected_git_sha: str,
) -> dict[str, Any]:
    if path is None:
        return {"passed": False, "path": None, "reason": "not_provided"}
    resolved = Path(path).resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root is not an object")
        declared_sha = str(payload.get("payload_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("payload_sha256", None)
        hash_valid = bool(declared_sha and declared_sha == _payload_sha(unsigned))
        passed = bool(
            payload.get("schema_version") == EQUATION_MAP_SCHEMA_VERSION
            and hash_valid
            and expected_git_sha
            and payload.get("git_sha") == expected_git_sha
            and payload.get("status") == "COMPLETE"
            and payload.get("all_equations_mapped") is True
            and payload.get("all_required_tests_passed") is True
            and payload.get("all_required_figures_generated") is True
            and not list(payload.get("blocking_reasons") or [])
        )
        return {
            "passed": passed,
            "path": str(resolved),
            "payload_hash_valid": hash_valid,
            "git_sha": payload.get("git_sha"),
            "status": payload.get("status"),
            "blocking_reasons": list(
                payload.get("blocking_reasons") or []
            ),
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "passed": False,
            "path": str(resolved),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_dependent_phase_results(
    phase_checks: Mapping[str, Mapping[str, bool]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    previous_complete = True
    for phase_id, title in _PHASE_TITLES.items():
        checks = dict(phase_checks.get(phase_id) or {})
        failed_checks = [name for name, passed in checks.items() if not passed]
        local_complete = bool(checks and not failed_checks)
        if local_complete and previous_complete:
            status = "COMPLETE"
        elif local_complete:
            status = "BLOCKED_BY_PREVIOUS_PHASE"
        else:
            status = "BLOCKED"
        results[phase_id] = {
            "title": title,
            "status": status,
            "local_checks_complete": local_complete,
            "checks": checks,
            "failed_checks": failed_checks,
            "blocking_reasons": (
                failed_checks
                if failed_checks
                else (
                    ["previous_phase_incomplete"]
                    if status == "BLOCKED_BY_PREVIOUS_PHASE"
                    else []
                )
            ),
        }
        previous_complete = previous_complete and status == "COMPLETE"
    return results


def _family_passed(
    evidence: Mapping[str, Any],
    family: str,
    *,
    minimum_case_count: int | None = None,
) -> bool:
    row = dict(dict(evidence.get("families") or {}).get(family) or {})
    if row.get("passed") is not True:
        return False
    if minimum_case_count is None:
        return True
    for candidate in list(row.get("candidate_manifests") or []):
        if candidate.get("manifest_valid") is True and len(
            set(candidate.get("case_ids") or [])
        ) >= minimum_case_count:
            return True
    return False


def _prepared_scope_audit(
    optimization_result: Mapping[str, Any],
) -> dict[str, Any]:
    direct = optimization_result.get("prepared_scope_audit")
    if isinstance(direct, Mapping):
        return dict(direct)
    summary = optimization_result.get("summary")
    if isinstance(summary, Mapping) and isinstance(
        summary.get("prepared_scope_audit"), Mapping
    ):
        return dict(summary["prepared_scope_audit"])
    return {}


def _solver_metadata(
    optimization_result: Mapping[str, Any],
) -> dict[str, Any]:
    direct = optimization_result.get("solver_metadata")
    if isinstance(direct, Mapping):
        return dict(direct)
    solver_result = optimization_result.get("solver_result")
    if isinstance(solver_result, Mapping) and isinstance(
        solver_result.get("solver_metadata"), Mapping
    ):
        return dict(solver_result["solver_metadata"])
    return {}


def _blocked_reason_count(
    audit: Mapping[str, Any],
    reason: str,
) -> int | None:
    counts = audit.get("blocked_transition_reason_counts")
    if not isinstance(counts, Mapping):
        return None
    return _as_int(counts.get(reason, 0))


def _nested_value(
    payload: Mapping[str, Any],
    *keys: str,
) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0.0
    except (TypeError, ValueError):
        return False


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _as_int(value)
        if parsed is not None:
            return parsed
    return None


def _next_blocked_phase(
    phases: Mapping[str, Mapping[str, Any]],
) -> str | None:
    for phase_id in _PHASE_TITLES:
        if dict(phases.get(phase_id) or {}).get("status") != "COMPLETE":
            return phase_id
    return None


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_sha(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
