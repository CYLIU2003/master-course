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


def _case(
    run_dir: Path,
    *,
    role: str,
    control_hash: str,
    pv_hash: str,
    pv_values: list[float],
    total_cost: float,
) -> None:
    _write_json(
        run_dir / "comparison_case_manifest.json",
        {
            "comparison_role": role,
            "comparison_control_hash": control_hash,
            "comparison_control_payload": {"service_date": "2025-08-05"},
            "pv_profile_hash": pv_hash,
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
        run_dir / "research_claim_scope.json",
        {"research_submission_ready": False},
    )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        {
            "source": "rolling_hourly_chain/executed_day_accounting.json",
            "accounting_total_cost_jpy": total_cost,
        },
    )
    _write_json(run_dir / "summary.json", {"trip_count_served": 264})
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
    assert manifest["formal_research_submission_ready"] is False
    assert manifest["pv_difference"]["total_difference_kwh"] == pytest.approx(
        -2.5
    )
    assert manifest["assignment_hashes_equal"] is True
    assert (output_dir / "comparison_table.csv").is_file()
    assert (output_dir / "comparison_report.md").is_file()


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
