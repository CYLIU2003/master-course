"""Reporting-only derivatives for a verified M0--M3 day-ahead comparison."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


REPORTING_SCHEMA_VERSION = "thesis_day_ahead_ablation_reporting_v1"
EFFECT_PAIRS = (
    ("M0_TO_M1", "M0", "M1", "charging_and_bess_on_rule_dispatch"),
    ("M2_TO_M3", "M2", "M3", "charging_and_bess_on_optimized_dispatch"),
    ("M1_TO_M3", "M1", "M3", "dispatch_integration_with_energy_optimization"),
    ("M0_TO_M3", "M0", "M3", "complete_method_effect"),
)


def validate_ready_comparison(payload: Mapping[str, Any]) -> None:
    """Fail closed unless the comparison payload is intact and research-ready."""

    declared_sha = str(payload.get("payload_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    actual_sha = _payload_sha(unsigned)
    if not declared_sha or declared_sha != actual_sha:
        raise ValueError("Comparison payload SHA-256 is missing or invalid")
    if payload.get("status") != "READY_FOR_DAY_AHEAD_METHOD_COMPARISON":
        raise ValueError("Reporting requires a READY day-ahead comparison")
    if payload.get("research_conclusion_eligible") is not True:
        raise ValueError("Comparison is not eligible for research conclusions")
    if payload.get("comparison_scope") != "same_canonical_problem_day_ahead":
        raise ValueError("Comparison scope is not the canonical day-ahead problem")
    if payload.get("rolling_costs_mixed_into_comparison") is not False:
        raise ValueError("Rolling values must not be mixed into this comparison")
    if list(payload.get("failed_checks") or []):
        raise ValueError("Comparison still contains failed checks")
    raw_methods = list(payload.get("methods") or [])
    method_ids = [
        str(method.get("method_id") or "")
        for method in raw_methods
        if isinstance(method, Mapping)
    ]
    if method_ids != ["M0", "M1", "M2", "M3"]:
        raise ValueError("Comparison does not contain ordered M0--M3 methods")
    methods = _methods_by_id(payload)
    if not all(
        method.get("day_ahead_comparison_eligible") is True
        for method in methods.values()
    ):
        raise ValueError("At least one method is not day-ahead comparable")


def comparison_effect_rows(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return predeclared method-effect contrasts from canonical comparison data."""

    validate_ready_comparison(payload)
    methods = _methods_by_id(payload)
    rows: list[dict[str, Any]] = []
    for effect_id, baseline_id, comparison_id, interpretation in EFFECT_PAIRS:
        baseline = _method_metrics(methods[baseline_id])
        comparison = _method_metrics(methods[comparison_id])
        row: dict[str, Any] = {
            "effect_id": effect_id,
            "baseline_method_id": baseline_id,
            "comparison_method_id": comparison_id,
            "interpretation": interpretation,
        }
        for metric, baseline_value in baseline.items():
            comparison_value = comparison[metric]
            row[f"baseline_{metric}"] = baseline_value
            row[f"comparison_{metric}"] = comparison_value
            row[f"delta_{metric}"] = comparison_value - baseline_value
        row["delta_total_cost_percent"] = _percent_delta(
            baseline["total_cost_jpy"],
            comparison["total_cost_jpy"],
        )
        row["delta_total_co2_percent"] = _percent_delta(
            baseline["total_co2_kg"],
            comparison["total_co2_kg"],
        )
        rows.append(row)
    return rows


def render_comparison_markdown(
    payload: Mapping[str, Any],
    *,
    method_rows: Sequence[Mapping[str, Any]],
    effect_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Render a compact advisor-facing report from verified comparison rows."""

    validate_ready_comparison(payload)
    lines = [
        "# M0--M3 day-ahead method comparison",
        "",
        f"- status: `{payload.get('status')}`",
        f"- source Git SHA: `{payload.get('git_sha')}`",
        f"- prepared input: `{payload.get('prepared_input_id')}`",
        f"- prepared source SHA-256: `{payload.get('prepared_source_sha256')}`",
        f"- canonical input SHA-256: `{payload.get('canonical_ablation_input_sha256')}`",
        "- scope: same-input day-ahead comparison; Rolling costs are excluded",
        "",
        "## Method results",
        "",
        "| Method | BEV/ICE buses | BEV/ICE trips | Total cost (JPY) | CO2 (kg) | Grid (kWh) | PV used (kWh) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in method_rows:
        lines.append(
            "| {method_id} | {used_bev_count}/{used_ice_count} | "
            "{bev_trip_count}/{ice_trip_count} | {total_cost_jpy:,.1f} | "
            "{total_co2_kg:,.1f} | {grid_import_kwh:,.1f} | {pv_used_total_kwh:,.1f} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Predeclared contrasts",
            "",
            "| Contrast | Cost delta (JPY) | Cost delta (%) | CO2 delta (kg) | BEV-trip delta |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in effect_rows:
        lines.append(
            "| {baseline_method_id} -> {comparison_method_id} | "
            "{delta_total_cost_jpy:+,.1f} | {delta_total_cost_percent:+.2f}% | "
            "{delta_total_co2_kg:+,.1f} | {delta_bev_trip_count:+d} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "Negative cost/CO2 deltas indicate a reduction. M1 and M3 are explicit frontend solver runs; M0 and M2 are deterministic rule adapters evaluated with the same canonical day-ahead ledger.",
            "",
            "This report does not convert the comparison into a Rolling or global-optimality claim. Source solver quality remains exactly as recorded in each run.",
            "",
        ]
    )
    return "\n".join(lines)


def method_reporting_rows(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the stable fields used by the report figures and tables."""

    validate_ready_comparison(payload)
    rows: list[dict[str, Any]] = []
    for method in list(payload.get("methods") or []):
        metrics = _method_metrics(method)
        rows.append(
            {
                "method_id": str(method.get("method_id") or ""),
                "label": str(method.get("label") or ""),
                **metrics,
            }
        )
    return rows


def _methods_by_id(
    payload: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    methods = {
        str(method.get("method_id") or ""): method
        for method in list(payload.get("methods") or [])
        if isinstance(method, Mapping)
    }
    return {
        method_id: methods[method_id]
        for method_id in ("M0", "M1", "M2", "M3")
        if method_id in methods
    }


def _method_metrics(method: Mapping[str, Any]) -> dict[str, float | int]:
    cost = dict(method.get("cost_breakdown") or {})
    return {
        "used_bev_count": int(method.get("used_bev_count") or 0),
        "used_ice_count": int(method.get("used_ice_count") or 0),
        "bev_trip_count": int(method.get("bev_trip_count") or 0),
        "ice_trip_count": int(method.get("ice_trip_count") or 0),
        "total_cost_jpy": float(cost.get("total_cost") or 0.0),
        "total_co2_kg": float(cost.get("total_co2_kg") or 0.0),
        "grid_import_kwh": float(cost.get("grid_import_kwh") or 0.0),
        "pv_used_total_kwh": float(cost.get("pv_used_total_kwh") or 0.0),
        "pv_to_bus_kwh": float(cost.get("pv_to_bus_kwh") or 0.0),
        "pv_to_bess_kwh": float(cost.get("pv_to_bess_kwh") or 0.0),
        "bess_to_bus_kwh": float(cost.get("bess_to_bus_kwh") or 0.0),
    }


def _percent_delta(baseline: float, comparison: float) -> float:
    if abs(baseline) <= 1e-12:
        return 0.0
    return (comparison - baseline) / baseline * 100.0


def _payload_sha(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
