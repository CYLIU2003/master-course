from __future__ import annotations

import json
from pathlib import Path

import pytest

from bff.services.optimization_run.pv_pair_manifest import (
    build_frontend_pv_pair_artifacts,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_composition_certificate() -> dict:
    return {
        "schema_version": "stage1_used_powertrain_composition_search_v1",
        "enabled": True,
        "radius_requested": 2,
        "primary_used_powertrain_composition": {"used_bev": 13, "used_ice": 19},
        "selected_inventory": {
            "available_electric_vehicle_count": 35,
            "available_combustion_vehicle_count": 26,
            "electric_vehicle_ids": ["bev-1"],
            "combustion_vehicle_ids": ["ice-1"],
        },
        "target_records": [
            {
                "target_used_bev": 14,
                "target_used_ice": 18,
                "target_within_selected_inventory": True,
                "search_status": "optimal",
                "solver_status": "optimal",
                "final_disposition": "physically_feasible_stage2_candidate",
            }
        ],
        "feasible_used_powertrain_compositions": [
            {"used_bev": 13, "used_ice": 19},
            {"used_bev": 14, "used_ice": 18},
        ],
        "multiple_feasible_compositions_found": True,
        "all_adjacent_targets_certified_infeasible": False,
        "inventory_has_no_adjacent_composition": False,
        "unresolved_targets": [],
        "accepted_for_formal_composition_evidence": True,
        "blocking_reasons": [],
        "semantics": "fixture composition search evidence",
    }


def _case(
    run_dir: Path,
    *,
    role: str,
    control_hash: str,
    pv_hash: str,
    pv_values: list[float],
    total_cost: float,
    failed_checks: list[str] | None = None,
    artifact_contract_accepted: bool = True,
    terminal_run_state: str = "complete",
    comparison_requested: bool = True,
    mip_gap_target_met: bool = True,
    objective_preset: str = "scalar_total_cost_v1",
) -> None:
    service_date = "2025-08-05"
    pv_source_date = (
        service_date if role == "baseline" else "2025-08-10"
    )
    _write_json(
        run_dir / "comparison_case_manifest.json",
        {
            "comparison_requested": comparison_requested,
            "comparison_type": "same_service_date_pv_counterfactual",
            "comparison_role": role,
            "comparison_control_hash": control_hash,
            "comparison_control_payload": {"service_date": service_date},
            "pv_profile_hash": pv_hash,
            "pv_source_date": pv_source_date,
            "assignment_hash": "assignment-1",
            "physical_schedule_validated": True,
            "rolling_chain_accepted": True,
            "executed_day_accounting_eligible": True,
            "executed_total_cost_jpy": total_cost,
            "pv_generated_kwh": sum(pv_values),
            "grid_import_kwh": 10.0,
        },
    )
    _write_json(
        run_dir / "physical_schedule_validation.json",
        {"accepted": True},
    )
    _write_json(
        run_dir / "final_cost_reconciliation.json",
        {"status": "OK"},
    )
    _write_json(
        run_dir / "artifact_completeness.json",
        {
            "status": "OK" if artifact_contract_accepted else "ERROR",
            "accepted": artifact_contract_accepted,
        },
    )
    _write_json(run_dir / "manifest.json", {"run_state": terminal_run_state})
    _write_json(
        run_dir / "research_claim_scope.json",
        {
            "research_submission_ready": False,
            "teacher_release_status": "BLOCKED",
            "teacher_release_failed_checks": (
                failed_checks
                if failed_checks is not None
                else ["controlled_counterfactual_pair_not_verified"]
            ),
        },
    )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        {
            "source": "rolling_hourly_chain/executed_day_accounting.json",
            "accounting_total_cost_jpy": total_cost,
        },
    )
    _write_json(
        run_dir / "summary.json",
        {
            "trip_count_served": 264,
            "solver_objective_matches_accounting_total": (
                objective_preset != "research_lexicographic_v1"
            ),
            "used_powertrain_composition_search_accepted": True,
        },
    )
    _write_json(
        run_dir / "solver_objective_accounting_reconciliation.json",
        {
            "schema_version": "solver_objective_accounting_reconciliation_v1",
            "solver_objective_value_jpy": total_cost,
            "solver_objective_source": "optimization_result.objective_value",
            "canonical_accounting_total_jpy": total_cost,
            "canonical_accounting_source": "rolling_hourly_chain/executed_day_accounting.json",
            "difference_jpy": 0.0,
            "absolute_difference_jpy": 0.0,
            "tolerance_jpy": 1.0e-6,
            "numeric_values_available": True,
            "numeric_residual_within_tolerance": True,
            "objective_is_actual_cost": (
                objective_preset != "research_lexicographic_v1"
            ),
            "matches_canonical_accounting_total": (
                objective_preset != "research_lexicographic_v1"
            ),
            "canonical_cost_objective_value_jpy": total_cost,
            "canonical_cost_objective_source": (
                "solver_metadata.integrated_lexicographic_cost_objective_jpy"
                if objective_preset == "research_lexicographic_v1"
                else "optimization_result.objective_value"
            ),
            "canonical_cost_difference_jpy": 0.0,
            "canonical_cost_absolute_difference_jpy": 0.0,
            "canonical_cost_numeric_values_available": True,
            "canonical_cost_residual_within_tolerance": True,
            "canonical_cost_contract_applied": True,
            "canonical_cost_matches_accounting_total": True,
            "objective_semantics": (
                "lexicographic_vehicle_days_then_canonical_cost"
                if objective_preset == "research_lexicographic_v1"
                else "actual_cost"
            ),
        },
    )
    _write_json(
        run_dir / "stage1_used_powertrain_composition_search.json",
        _valid_composition_certificate(),
    )
    _write_json(
        run_dir / "solver_settings.json",
        {
            "has_feasible_incumbent": True,
            "mip_gap_target_met": mip_gap_target_met,
        },
    )
    _write_json(
        run_dir / "assignment_economic_audit.json",
        {
            "schema_version": "assignment_economic_audit_v1",
            "objective_preset": objective_preset,
        },
    )
    _write_json(
        run_dir / "effective_pv_profiles.json",
        {"forecast_by_depot": {"dep-1": pv_values}},
    )


def test_pair_manifest_proves_fixed_controls_and_exact_pv_difference(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )

    manifest = build_frontend_pv_pair_artifacts(
        baseline_run_dir=baseline,
        counterfactual_run_dir=counterfactual,
        output_dir=output_dir,
    )

    assert manifest["accepted_for_controlled_pv_sensitivity_comparison"] is True
    assert manifest["formal_research_submission_ready"] is True
    assert manifest["formal_release_failed_checks"] == []
    assert manifest["pv_difference"]["total_difference_kwh"] == pytest.approx(
        -2.5
    )
    assert manifest["assignment_hashes_equal"] is True
    assert (output_dir / "comparison_table.csv").is_file()
    assert (output_dir / "comparison_report.md").is_file()


def test_pair_manifest_accepts_declared_lexicographic_accounting_semantics(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    for run_dir, role, pv_hash, pv_values, total_cost in (
        (baseline, "baseline", "high-pv", [1.0, 2.0], 100.0),
        (
            counterfactual,
            "pv_curve_counterfactual",
            "low-pv",
            [0.2, 0.3],
            120.0,
        ),
    ):
        _case(
            run_dir,
            role=role,
            control_hash="fixed-controls",
            pv_hash=pv_hash,
            pv_values=pv_values,
            total_cost=total_cost,
            objective_preset="research_lexicographic_v1",
        )

    manifest = build_frontend_pv_pair_artifacts(
        baseline_run_dir=baseline,
        counterfactual_run_dir=counterfactual,
        output_dir=output_dir,
    )

    assert manifest["accepted_for_controlled_pv_sensitivity_comparison"] is True
    assert manifest["checks"][
        "baseline_solver_objective_accounting_semantics_valid"
    ] is True
    assert manifest["checks"]["objective_presets_match"] is True


def test_pair_manifest_rejects_lexicographic_cost_stage_mismatch(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    for run_dir, role, total_cost in (
        (baseline, "baseline", 100.0),
        (counterfactual, "pv_curve_counterfactual", 120.0),
    ):
        _case(
            run_dir,
            role=role,
            control_hash="fixed-controls",
            pv_hash=f"{role}-pv",
            pv_values=[1.0, 2.0],
            total_cost=total_cost,
            objective_preset="research_lexicographic_v1",
        )
    reconciliation_path = (
        counterfactual / "solver_objective_accounting_reconciliation.json"
    )
    reconciliation = json.loads(reconciliation_path.read_text())
    reconciliation["canonical_cost_matches_accounting_total"] = False
    _write_json(reconciliation_path, reconciliation)

    with pytest.raises(
        ValueError,
        match="counterfactual_solver_objective_accounting_semantics_valid",
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )


def test_pair_manifest_rejects_different_objective_presets(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
        objective_preset="research_lexicographic_v1",
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
        objective_preset="scalar_total_cost_v1",
    )

    with pytest.raises(ValueError, match="objective_presets_match"):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )


def test_pair_manifest_keeps_comparison_but_blocks_formal_ready_when_gap_missed(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
        mip_gap_target_met=False,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
        mip_gap_target_met=False,
    )

    manifest = build_frontend_pv_pair_artifacts(
        baseline_run_dir=baseline,
        counterfactual_run_dir=counterfactual,
        output_dir=output_dir,
    )

    assert manifest["accepted_for_controlled_pv_sensitivity_comparison"] is True
    assert manifest["formal_research_submission_ready"] is False
    assert manifest["failed_checks"] == []
    assert manifest["formal_release_failed_checks"] == [
        "baseline_requested_mip_gap_certified",
        "counterfactual_requested_mip_gap_certified",
    ]


def test_phase4_gap_certificate_replaces_stage1_composition_artifact(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    for run_dir, role, pv_hash, pv_values, total_cost in (
        (baseline, "baseline", "high-pv", [1.0, 2.0], 100.0),
        (
            counterfactual,
            "pv_curve_counterfactual",
            "low-pv",
            [0.2, 0.3],
            120.0,
        ),
    ):
        _case(
            run_dir,
            role=role,
            control_hash="fixed-controls",
            pv_hash=pv_hash,
            pv_values=pv_values,
            total_cost=total_cost,
        )
        (run_dir / "stage1_used_powertrain_composition_search.json").unlink()
        _write_json(
            run_dir / "solver_settings.json",
            {
                "executed_phase": "phase4_integrated",
                "supports_exact_milp": True,
                "has_feasible_incumbent": True,
                "mip_gap_target_met": True,
            },
        )

    manifest = build_frontend_pv_pair_artifacts(
        baseline_run_dir=baseline,
        counterfactual_run_dir=counterfactual,
        output_dir=output_dir,
    )

    assert manifest["checks"][
        "baseline_used_powertrain_composition_search_certified"
    ] is True
    assert manifest["checks"][
        "counterfactual_used_powertrain_composition_search_certified"
    ] is True


def test_pair_manifest_rejects_case_with_a_non_pair_release_blocker(
    tmp_path: Path,
) -> None:
    """Only the pending-pair blocker may be discharged by the pair itself."""

    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
        failed_checks=[
            "controlled_counterfactual_pair_not_verified",
            "final_cost_reconciliation_failed",
        ],
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )

    with pytest.raises(
        ValueError, match="baseline_case_base_release_gate_passes"
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    assert manifest["formal_research_submission_ready"] is False


def test_pair_manifest_rejects_objective_accounting_or_composition_failure(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )
    reconciliation = json.loads(
        (
            counterfactual
            / "solver_objective_accounting_reconciliation.json"
        ).read_text()
    )
    reconciliation.update(
        {
            "solver_objective_value_jpy": 100.0,
            "difference_jpy": -20.0,
            "absolute_difference_jpy": 20.0,
            "numeric_residual_within_tolerance": False,
            "matches_canonical_accounting_total": False,
        }
    )
    _write_json(
        counterfactual / "solver_objective_accounting_reconciliation.json",
        reconciliation,
    )
    certificate = _valid_composition_certificate()
    certificate.update(
        {
            "feasible_used_powertrain_compositions": [
                {"used_bev": 13, "used_ice": 19}
            ],
            "multiple_feasible_compositions_found": False,
            "accepted_for_formal_composition_evidence": False,
            "blocking_reasons": [
                "only_one_or_zero_physically_feasible_used_powertrain_composition"
            ],
        }
    )
    _write_json(
        counterfactual / "stage1_used_powertrain_composition_search.json",
        certificate,
    )

    with pytest.raises(
        ValueError,
        match=(
            "counterfactual_solver_objective_accounting_semantics_valid"
        ),
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    assert manifest["checks"][
        "counterfactual_used_powertrain_composition_search_certified"
    ] is False


def test_pair_manifest_rejects_true_summary_flags_without_evidence_artifacts(
    tmp_path: Path,
) -> None:
    """Summary booleans cannot substitute for numeric/certificate evidence."""

    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )
    (counterfactual / "solver_objective_accounting_reconciliation.json").unlink()
    (counterfactual / "stage1_used_powertrain_composition_search.json").unlink()

    with pytest.raises(
        ValueError,
        match=(
            "counterfactual_solver_objective_accounting_semantics_valid"
        ),
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    assert manifest["checks"][
        "counterfactual_used_powertrain_composition_search_certified"
    ] is False
    assert manifest["release_evidence_errors"]["counterfactual"][
        "solver_objective_accounting"
    ]


def test_pair_manifest_rejects_case_without_accepted_artifact_contract(
    tmp_path: Path,
) -> None:
    """A paired comparison cannot rehabilitate a failed terminal artifact gate."""

    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
        artifact_contract_accepted=False,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )

    with pytest.raises(
        ValueError, match="baseline_artifact_contract_accepted"
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    assert manifest["formal_research_submission_ready"] is False


def test_pair_manifest_rejects_case_without_complete_terminal_state(
    tmp_path: Path,
) -> None:
    """An accepted audit cannot override a terminal failure provenance state."""

    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0, 2.0],
        total_cost=100.0,
        terminal_run_state="reporting_finalization_failed",
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.2, 0.3],
        total_cost=120.0,
    )

    with pytest.raises(ValueError, match="baseline_terminal_run_complete"):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    manifest = json.loads((output_dir / "pair_manifest.json").read_text())
    assert manifest["formal_research_submission_ready"] is False


def test_pair_manifest_rejects_control_hash_mismatch(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="control-a",
        pv_hash="high-pv",
        pv_values=[1.0],
        total_cost=100.0,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="control-b",
        pv_hash="low-pv",
        pv_values=[0.1],
        total_cost=120.0,
    )

    with pytest.raises(ValueError, match="fixed_controls_match"):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )

    rejected = json.loads(
        (output_dir / "pair_manifest.json").read_text(encoding="utf-8")
    )
    assert rejected["accepted_for_controlled_pv_sensitivity_comparison"] is False


def test_pair_manifest_rejects_implicit_legacy_comparison(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    counterfactual = tmp_path / "counterfactual"
    output_dir = tmp_path / "pair"
    _case(
        baseline,
        role="baseline",
        control_hash="fixed-controls",
        pv_hash="high-pv",
        pv_values=[1.0],
        total_cost=100.0,
        comparison_requested=False,
    )
    _case(
        counterfactual,
        role="pv_curve_counterfactual",
        control_hash="fixed-controls",
        pv_hash="low-pv",
        pv_values=[0.1],
        total_cost=120.0,
    )

    with pytest.raises(
        ValueError, match="baseline_comparison_explicitly_requested"
    ):
        build_frontend_pv_pair_artifacts(
            baseline_run_dir=baseline,
            counterfactual_run_dir=counterfactual,
            output_dir=output_dir,
        )
