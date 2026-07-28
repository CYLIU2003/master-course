"""Fail-closed comparison evidence for two frontend PV counterfactual runs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


_PAIR_PENDING_RELEASE_CHECK = "controlled_counterfactual_pair_not_verified"


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required comparison artifact is missing: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return dict(loaded)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pv_profile(run_dir: Path) -> dict[str, list[float]]:
    payload = _load_object(run_dir / "effective_pv_profiles.json")
    return {
        str(depot_id): [float(value or 0.0) for value in list(values or ())]
        for depot_id, values in dict(
            payload.get("forecast_by_depot") or {}
        ).items()
    }


def _pv_difference(
    baseline: Mapping[str, list[float]],
    counterfactual: Mapping[str, list[float]],
) -> dict[str, Any]:
    if set(baseline) != set(counterfactual):
        raise ValueError("PV profile depot sets differ between comparison cases")
    difference: dict[str, list[float]] = {}
    for depot_id in sorted(baseline):
        baseline_values = list(baseline[depot_id])
        counterfactual_values = list(counterfactual[depot_id])
        if len(baseline_values) != len(counterfactual_values):
            raise ValueError(
                f"PV profile length differs for depot {depot_id!r}"
            )
        difference[depot_id] = [
            counter - base
            for base, counter in zip(
                baseline_values, counterfactual_values, strict=True
            )
        ]
    return {
        "counterfactual_minus_baseline_kwh_by_slot": difference,
        "difference_hash": _canonical_hash(difference),
        "total_difference_kwh": sum(
            sum(values) for values in difference.values()
        ),
    }


def _case(run_dir: Path) -> dict[str, Any]:
    case_manifest = _load_object(run_dir / "comparison_case_manifest.json")
    physical = _load_object(run_dir / "physical_schedule_validation.json")
    reconciliation = _load_object(run_dir / "final_cost_reconciliation.json")
    artifact_completeness = _load_object(run_dir / "artifact_completeness.json")
    rolling_manifest = _load_object(run_dir / "manifest.json")
    claim_scope = _load_object(run_dir / "research_claim_scope.json")
    ledger = _load_object(run_dir / "graph" / "canonical_cost_ledger.json")
    summary = _load_object(run_dir / "summary.json")
    return {
        "run_dir": str(run_dir.resolve()),
        "case_manifest": case_manifest,
        "physical_validation": physical,
        "final_cost_reconciliation": reconciliation,
        "artifact_completeness": artifact_completeness,
        "rolling_manifest": rolling_manifest,
        "research_claim_scope": claim_scope,
        "canonical_cost_ledger": ledger,
        "summary": summary,
        "pv_profile": _pv_profile(run_dir),
    }


def _comparison_rows(
    baseline: Mapping[str, Any],
    counterfactual: Mapping[str, Any],
) -> list[dict[str, Any]]:
    baseline_manifest = dict(baseline["case_manifest"])
    counterfactual_manifest = dict(counterfactual["case_manifest"])
    metrics = (
        ("pv_generated_kwh", "kWh"),
        ("grid_import_kwh", "kWh"),
        ("executed_total_cost_jpy", "JPY"),
    )
    rows: list[dict[str, Any]] = []
    for metric, unit in metrics:
        baseline_value = float(baseline_manifest.get(metric, 0.0) or 0.0)
        counterfactual_value = float(
            counterfactual_manifest.get(metric, 0.0) or 0.0
        )
        rows.append(
            {
                "metric": metric,
                "unit": unit,
                "baseline": baseline_value,
                "counterfactual": counterfactual_value,
                "counterfactual_minus_baseline": (
                    counterfactual_value - baseline_value
                ),
                "difference_percent_of_baseline": (
                    None
                    if abs(baseline_value) <= 1.0e-12
                    else (counterfactual_value - baseline_value)
                    / baseline_value
                    * 100.0
                ),
            }
        )
    return rows


def _case_base_release_gate_passes(claim_scope: Mapping[str, Any]) -> bool:
    """Return whether a case is eligible to become ready through a valid pair.

    A standalone frontend case is intentionally blocked until its controlled
    counterpart has been verified. That single pending-pair check must not be
    circularly required to disappear before this builder can create the pair
    evidence. Any other release failure, or a diagnostic run, remains a hard
    rejection.
    """

    if claim_scope.get("diagnostic_only") is True:
        return False
    raw_failed_checks = claim_scope.get("teacher_release_failed_checks")
    if raw_failed_checks is None:
        raw_failed_checks = ()
    if not isinstance(raw_failed_checks, (list, tuple, set)):
        return False
    failed_checks = {
        str(check) for check in raw_failed_checks
    }
    if claim_scope.get("research_submission_ready") is True:
        return (
            claim_scope.get("teacher_release_status") == "READY"
            and not failed_checks
        )
    return (
        claim_scope.get("teacher_release_status") == "BLOCKED"
        and failed_checks == {_PAIR_PENDING_RELEASE_CHECK}
    )


def build_frontend_pv_pair_artifacts(
    *,
    baseline_run_dir: Path,
    counterfactual_run_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Build pair evidence and reject uncontrolled or internally invalid runs."""

    baseline_run_dir = Path(baseline_run_dir)
    counterfactual_run_dir = Path(counterfactual_run_dir)
    output_dir = Path(output_dir)
    baseline = _case(baseline_run_dir)
    counterfactual = _case(counterfactual_run_dir)
    baseline_manifest = dict(baseline["case_manifest"])
    counterfactual_manifest = dict(counterfactual["case_manifest"])
    baseline_control = dict(
        baseline_manifest.get("comparison_control_payload") or {}
    )
    counterfactual_control = dict(
        counterfactual_manifest.get("comparison_control_payload") or {}
    )
    checks = {
        "baseline_role_declared": (
            baseline_manifest.get("comparison_role") == "baseline"
        ),
        "counterfactual_role_declared": (
            counterfactual_manifest.get("comparison_role")
            == "pv_curve_counterfactual"
        ),
        "comparison_control_hashes_present": all(
            bool(str(item or "").strip())
            for item in (
                baseline_manifest.get("comparison_control_hash"),
                counterfactual_manifest.get("comparison_control_hash"),
            )
        ),
        "fixed_controls_match": (
            baseline_manifest.get("comparison_control_hash")
            == counterfactual_manifest.get("comparison_control_hash")
        ),
        "same_service_date": (
            baseline_control.get("service_date")
            == counterfactual_control.get("service_date")
        ),
        "pv_profile_hashes_present": all(
            bool(str(item or "").strip())
            for item in (
                baseline_manifest.get("pv_profile_hash"),
                counterfactual_manifest.get("pv_profile_hash"),
            )
        ),
        "pv_profiles_differ": (
            baseline_manifest.get("pv_profile_hash")
            != counterfactual_manifest.get("pv_profile_hash")
        ),
        "baseline_physical_schedule_valid": (
            dict(baseline["physical_validation"]).get("accepted") is True
        ),
        "counterfactual_physical_schedule_valid": (
            dict(counterfactual["physical_validation"]).get("accepted") is True
        ),
        "baseline_final_cost_reconciled": (
            dict(baseline["final_cost_reconciliation"]).get("status") == "OK"
        ),
        "counterfactual_final_cost_reconciled": (
            dict(counterfactual["final_cost_reconciliation"]).get("status")
            == "OK"
        ),
        "baseline_artifact_contract_accepted": (
            dict(baseline["artifact_completeness"]).get("status") == "OK"
            and dict(baseline["artifact_completeness"]).get("accepted") is True
        ),
        "counterfactual_artifact_contract_accepted": (
            dict(counterfactual["artifact_completeness"]).get("status") == "OK"
            and dict(counterfactual["artifact_completeness"]).get("accepted")
            is True
        ),
        "baseline_terminal_run_complete": (
            dict(baseline["rolling_manifest"]).get("run_state") == "complete"
        ),
        "counterfactual_terminal_run_complete": (
            dict(counterfactual["rolling_manifest"]).get("run_state")
            == "complete"
        ),
        "both_cost_ledgers_use_executed_rolling_day": all(
            dict(case["canonical_cost_ledger"]).get("source")
            == "rolling_hourly_chain/executed_day_accounting.json"
            for case in (baseline, counterfactual)
        ),
        "baseline_case_base_release_gate_passes": _case_base_release_gate_passes(
            dict(baseline["research_claim_scope"])
        ),
        "counterfactual_case_base_release_gate_passes": _case_base_release_gate_passes(
            dict(counterfactual["research_claim_scope"])
        ),
    }
    failed_checks = sorted(
        name for name, passed in checks.items() if passed is not True
    )
    pv_difference = _pv_difference(
        baseline["pv_profile"], counterfactual["pv_profile"]
    )
    rows = _comparison_rows(baseline, counterfactual)
    both_case_base_release_gates_pass = all(
        checks[name]
        for name in (
            "baseline_case_base_release_gate_passes",
            "counterfactual_case_base_release_gate_passes",
        )
    )
    accepted = not failed_checks
    payload = {
        "schema_version": "frontend_pv_pair_manifest_v1",
        "accepted_for_controlled_pv_sensitivity_comparison": accepted,
        "formal_research_submission_ready": bool(
            accepted and both_case_base_release_gates_pass
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "comparison_control_hash": baseline_manifest.get(
            "comparison_control_hash"
        )
        if checks["fixed_controls_match"]
        else None,
        "pv_difference": pv_difference,
        "assignment_hashes_equal": (
            baseline_manifest.get("assignment_hash")
            == counterfactual_manifest.get("assignment_hash")
        ),
        "cases": {
            "baseline": {
                "run_dir": baseline["run_dir"],
                **baseline_manifest,
            },
            "counterfactual": {
                "run_dir": counterfactual["run_dir"],
                **counterfactual_manifest,
            },
        },
        "comparison_table": rows,
        "claim_scope": (
            "controlled same-service-date PV-supply sensitivity"
            if accepted
            else "comparison rejected because required controls/evidence differ"
        ),
        "optimality_note": (
            "Pair acceptance does not establish integrated global optimality. "
            "Each run's result_claim_classification and MIP gaps remain binding."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pair_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "comparison_table.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "metric",
                "unit",
                "baseline",
                "counterfactual",
                "counterfactual_minus_baseline",
                "difference_percent_of_baseline",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    report_lines = [
        "# Frontend PV counterfactual comparison",
        "",
        (
            "- accepted_for_controlled_pv_sensitivity_comparison: "
            f"`{str(accepted).lower()}`"
        ),
        (
            "- formal_research_submission_ready: "
            f"`{str(bool(payload['formal_research_submission_ready'])).lower()}`"
        ),
        (
            "- comparison_control_hash: "
            f"`{payload.get('comparison_control_hash')}`"
        ),
        f"- PV difference hash: `{pv_difference['difference_hash']}`",
        (
            "- assignment hashes equal: "
            f"`{str(bool(payload['assignment_hashes_equal'])).lower()}`"
        ),
        "",
        "## Checks",
        "",
        *[
            f"- {name}: `{'PASS' if passed else 'FAIL'}`"
            for name, passed in checks.items()
        ],
        "",
        "## Comparison",
        "",
        "| Metric | Baseline | Counterfactual | Difference | Unit |",
        "|---|---:|---:|---:|---|",
        *[
            (
                f"| {row['metric']} | {row['baseline']:.9f} | "
                f"{row['counterfactual']:.9f} | "
                f"{row['counterfactual_minus_baseline']:.9f} | "
                f"{row['unit']} |"
            )
            for row in rows
        ],
        "",
        "> This comparison does not establish integrated global optimality.",
        "",
    ]
    (output_dir / "comparison_report.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )
    if failed_checks:
        raise ValueError(
            "Frontend PV pair comparison failed: " + ", ".join(failed_checks)
        )
    return payload
