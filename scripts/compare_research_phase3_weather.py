"""Create a guarded, reproducible comparison of two Phase 3 weather runs.

The input summaries must be emitted by run_research_phase3_frontend_weather.
This utility rejects a comparison when a non-weather control, research
acceptance gate, or operational validation result differs.  It reports
feasible-schedule accounting effects only; it never labels a Phase 3
two-stage result as a global total-cost optimum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_PHASE = "phase3_two_stage"
EXPECTED_COST_SCOPE = "feasible_schedule_accounting_not_global_total_cost_optimum"
EXPECTED_TRIP_COUNT = 264
EXPECTED_TIMESTEP_MIN = 15
EXPECTED_PRICE_SLOT_COUNT = 96

# These are experimental controls, not weather inputs.  Any difference means
# the pair answers different research questions and must not be compared.
FIXED_CONTROL_FIELDS = (
    "git_sha",
    "service_date",
    "service_id",
    "calendar_service_contract",
    "phase",
    "time_limit_sec",
    "mip_gap",
    "random_seed",
    "postsolve_repair_enabled",
    "vehicle_soc_semantics",
    "weather_operation_policy_enabled",
    "weather_pv_forecast_applied",
    "weather_pv_forecast_skip_reason",
    "trip_count",
    "fleet",
    "expected_fleet",
    "timestep_min",
    "price_slot_count",
    "planning_horizon_hours",
    "energy_horizon_duration_min",
    "milp_max_successors_per_trip",
    "successor_pruning_enabled",
    "research_discretization",
    "trip_distance_audit",
    "clock_hour_grid_price_yen_per_kwh",
    "demand_charge_monthly_yen_per_kw",
    "demand_charge_horizon_yen_per_kw",
    "diesel_price_yen_per_l",
    "co2_price_yen_per_kg",
    "vehicle_usage_cost_jpy_per_used_bus",
    "minimum_used_bev_count",
    "cost_component_flags",
    "objective_weights",
    "grid_co2_kg_per_kwh",
    "pv_marginal_charge_cost_yen_per_kwh",
    "pv_curtail_penalty_yen_per_kwh",
    "initial_soc_policy",
    "initial_soc_source",
    "initial_soc_input_hash",
    "initial_soc_by_vehicle",
    "terminal_soc_policy",
    "research_fragment_policy",
    "charger_configuration",
    "charger_configuration_hash",
    "physical_charger_assignment_semantics",
    "implicit_home_depot_charger_compatibility_vehicle_ids",
    "vehicle_input_hash",
    "trip_input_hash",
    "stage1_energy_envelope_constraint_count",
    "stage1_energy_envelope_semantics",
    "stage1_time_indexed_soc_relaxation_constraint_count",
    "stage1_time_indexed_soc_relaxation_semantics",
)

# The labels and paths are weather provenance.  Every other differing key is
# rejected so that a later operational knob cannot silently enter this study.
ALLOWED_WEATHER_CONFIGURATION_FIELDS = frozenset(
    {"weather_operation_mode", "pv_profile_id", "weather_proxy_forecast_path"}
)
ALLOWED_PV_ASSET_FIELDS = frozenset(
    {"pv_case_id", "pv_generation_kwh", "pv_generation_hash"}
)
ALLOWED_WEATHER_OPERATION_PROFILE_FIELDS = frozenset({"operation_mode"})
VALIDATION_ZERO_FIELDS = (
    "unassigned_trip_count",
    "duplicate_trip_count",
    "vehicle_time_overlap_count",
    "infeasible_transition_count",
    "ev_soc_lower_violation_count",
    "ev_soc_upper_violation_count",
    "ev_soc_violation_count",
    "bess_soc_lower_violation_count",
    "bess_soc_upper_violation_count",
    "bess_soc_violation_count",
    "contract_power_violation_count",
    "charger_concurrency_violation_count",
)
FLOW_FIELDS = (
    "grid_to_bus_kwh",
    "grid_to_bess_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "bess_to_bus_kwh",
    "pv_generated_kwh",
    "pv_curtailed_kwh",
    "grid_import_kwh",
    "peak_grid_kw",
)
COST_FIELDS = (
    "total_cost",
    "electricity_cost",
    "grid_purchase_cost",
    "pv_to_bus_cost_jpy",
    "pv_to_bess_cost_jpy",
    "pv_curtail_cost_jpy",
    "bess_to_bus_cost_jpy",
    "demand_cost",
    "fuel_cost",
    "co2_cost",
    "vehicle_usage_cost",
)
ACCOUNTING_COMPONENT_FIELDS = (
    "electricity_cost",
    "demand_cost",
    "fuel_cost",
    "co2_cost",
    "vehicle_usage_cost",
)
STAGE1_ENERGY_PROXY_RESULT_FIELDS = (
    "external_charge_input_kwh",
    "pv_to_bus_kwh",
    "grid_to_bus_kwh",
    "bess_initial_to_bus_kwh",
    "objective_jpy",
)


class ComparisonContractError(ValueError):
    """The two artifacts cannot support a controlled research comparison."""


def build_weather_comparison(
    sunny_summary: Mapping[str, Any],
    rain_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a validated Phase 3 weather-comparison artifact.

    Raises:
        ComparisonContractError: A result is not research-valid or a fixed
            experimental control differs.
    """
    sunny = _require_mapping(sunny_summary, "sunny summary")
    rain = _require_mapping(rain_summary, "rain summary")
    _validate_accepted_case("sunny", sunny)
    _validate_accepted_case("rain", rain)
    _validate_fixed_controls(sunny, rain)
    energy_proxy_control_audit = _validate_stage1_energy_proxy_controls(
        sunny, rain
    )
    contract_control_audit = _validate_contract_power_controls(sunny, rain)
    weather_differences = _validate_weather_inputs(sunny, rain)

    return {
        "comparison_accepted": True,
        "comparison_scope": {
            "valid_for": (
                "Phase 3 feasible-schedule accounting and constraint-condition "
                "comparison"
            ),
            "not_valid_for": "global total-cost optimality claim",
            "reason": (
                "Phase 3 is a two-stage procedure; the accounting total is not "
                "its single integrated global objective."
            ),
        },
        "fixed_control_fields_checked": list(FIXED_CONTROL_FIELDS)
        + ["weather_configuration except weather provenance"]
        + ["weather_operation_profile except operation_mode label"]
        + ["depot_energy_assets except PV case/generation/hash"]
        + [
            "depot import limit and overage penalty "
            "(legacy summaries are explicitly marked)"
        ],
        "contract_power_control_audit": contract_control_audit,
        "stage1_energy_cost_proxy_control_audit": energy_proxy_control_audit,
        "allowed_weather_input_differences": weather_differences,
        "run_status": {"sunny": _run_status(sunny), "rain": _run_status(rain)},
        "effects": {
            "flows_kwh_or_kw": _metric_effects(
                sunny, rain, "flows_kwh_or_kw", FLOW_FIELDS
            ),
            "costs_jpy": _metric_effects(sunny, rain, "costs_jpy", COST_FIELDS),
            "stage_objectives": {
                field: _scalar_effect(sunny, rain, field)
                for field in (
                    "stage1_objective",
                    "stage1_best_bound",
                    "stage1_mip_gap_percent",
                    "stage2_objective",
                )
            },
            "stage1_energy_cost_proxy": _optional_metric_effects(
                sunny,
                rain,
                "stage1_energy_cost_proxy_result",
                STAGE1_ENERGY_PROXY_RESULT_FIELDS,
            ),
        },
    }


def render_markdown_report(comparison: Mapping[str, Any]) -> str:
    """Render a compact Japanese report from a validated comparison artifact."""
    result = _require_mapping(comparison, "comparison")
    statuses = _require_mapping(result.get("run_status"), "comparison run_status")
    sunny_status = _require_mapping(statuses.get("sunny"), "sunny run status")
    rain_status = _require_mapping(statuses.get("rain"), "rain run status")
    effects = _require_mapping(result.get("effects"), "comparison effects")
    cost_effects = _require_mapping(effects.get("costs_jpy"), "cost effects")
    flow_effects = _require_mapping(effects.get("flows_kwh_or_kw"), "flow effects")
    proxy_effects = _require_mapping(
        effects.get("stage1_energy_cost_proxy"),
        "Stage 1 energy-cost proxy effects",
    )
    scope = _require_mapping(result.get("comparison_scope"), "comparison scope")
    weather_inputs = _require_mapping(
        result.get("allowed_weather_input_differences"), "weather input differences"
    )
    contract_audit = _require_mapping(
        result.get("contract_power_control_audit"), "contract power control audit"
    )

    lines = [
        "# Phase 3 晴天・雨天の比較結果",
        "",
        "この比較は、受理済みの Phase 3 可行スケジュールを対象にした"
        "会計値・制約条件の比較です。総コストの大域最適性は主張しません。",
        "",
        "## 比較契約",
        "",
        f"- 比較受理: {bool(result.get('comparison_accepted'))}",
        f"- 比較できる範囲: {scope.get('valid_for')}",
        f"- 比較できない主張: {scope.get('not_valid_for')}",
        f"- 理由: {scope.get('reason')}",
        "",
        "PV case / PV発電量 / PVハッシュ、サービス日、シナリオ識別子、"
        "weather provenance 以外の固定条件は、一つでも異なると本レポートを生成しません。",
    ]
    if not bool(contract_audit.get("exported")):
        lines.extend(
            [
                "",
                "- 注意: このlegacy summaryには契約電力上限のraw値が未出力である。"
                "比較前に記録済みgit SHAのsource/input auditで確認する。",
            ]
        )
    lines.extend(
        [
            "",
            "## 実行・可行性",
            "",
            "| 項目 | 晴天 | 雨天 |",
            "| --- | ---: | ---: |",
            _markdown_row("サービス日", sunny_status.get("service_date"), rain_status.get("service_date")),
            _markdown_row("全便担当", _trip_coverage(sunny_status), _trip_coverage(rain_status)),
            _markdown_row("使用車両数", sunny_status.get("used_vehicle_count"), rain_status.get("used_vehicle_count")),
            _markdown_row("最大 fragment 数", sunny_status.get("max_fragments_observed"), rain_status.get("max_fragments_observed")),
            _markdown_row("Stage 1 status", sunny_status.get("stage1_solver_status"), rain_status.get("stage1_solver_status")),
            _markdown_row("Stage 1 実行時間 [s]", _format_number(sunny_status.get("stage1_runtime_seconds")), _format_number(rain_status.get("stage1_runtime_seconds"))),
            _markdown_row("Stage 1 MIP gap [%]", _format_number(sunny_status.get("stage1_mip_gap_percent")), _format_number(rain_status.get("stage1_mip_gap_percent"))),
            _markdown_row("Stage 2 status", sunny_status.get("stage2_solver_status"), rain_status.get("stage2_solver_status")),
            _markdown_row("Stage 2 実行時間 [s]", _format_number(sunny_status.get("stage2_runtime_seconds")), _format_number(rain_status.get("stage2_runtime_seconds"))),
            "",
            "## 会計総額と主加算項の差（雨天 − 晴天）",
            "",
            "| 項目 [JPY] | 晴天 | 雨天 | 差分 | 晴天比 [%] |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        _metric_rows(
            cost_effects,
            (
                "total_cost",
                "electricity_cost",
                "demand_cost",
                "fuel_cost",
                "co2_cost",
                "vehicle_usage_cost",
            ),
        )
    )
    lines.extend(
        [
            "",
            "## 電力フロー由来の補助コスト指標（雨天 − 晴天）",
            "",
            "以下は電力源の追跡用であり、会計総額には electricity_cost として一度だけ反映します。"
            "この表の各行を会計総額へ重ねて加算してはいけません。",
            "",
            "| 項目 [JPY] | 晴天 | 雨天 | 差分 | 晴天比 [%] |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        _metric_rows(
            cost_effects,
            (
                "grid_purchase_cost",
                "pv_to_bus_cost_jpy",
                "pv_to_bess_cost_jpy",
                "pv_curtail_cost_jpy",
                "bess_to_bus_cost_jpy",
            ),
        )
    )
    lines.extend(
        [
            "",
            "## 電力・PV・BESSフロー差（雨天 − 晴天）",
            "",
            "| 項目 [kWh / kW] | 晴天 | 雨天 | 差分 | 晴天比 [%] |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        _metric_rows(
            flow_effects,
            (
                "pv_generated_kwh",
                "pv_to_bus_kwh",
                "pv_to_bess_kwh",
                "bess_to_bus_kwh",
                "grid_import_kwh",
                "peak_grid_kw",
            ),
        )
    )
    if bool(proxy_effects.get("exported")):
        proxy_metrics = _require_mapping(
            proxy_effects.get("metrics"), "Stage 1 energy-cost proxy metrics"
        )
        lines.extend(
            [
                "",
                "## Stage 1 集約充電費用代理（雨天 − 晴天）",
                "",
                "この値は割当探索へ天候別PV量を伝える下界代理です。"
                "Stage 2の時刻別充電費用・会計総額ではありません。",
                "",
                "| 項目 | 晴天 | 雨天 | 差分 | 晴天比 [%] |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        lines.extend(_metric_rows(proxy_metrics, STAGE1_ENERGY_PROXY_RESULT_FIELDS))
    lines.extend(
        [
            "",
            "## 解釈上の注意",
            "",
            "- 両ケースは全便担当、SOC・充電器・契約電力・BESSの独立検証を通過しています。",
            "- Stage 1 は両ケースで time-limit 終了です。よって、同じ入力制約下で得た"
            "可行解の比較であり、車両割当の最適性差を主張するものではありません。",
            "- 晴天/雨天で異なる weather_operation_mode は weather provenance として保存しています。"
            "export済みの有効 profile はラベル以外を一致照合します。本成果物だけから、"
            "ラベルを独立したコスト・SOC制御効果と解釈してはいけません。",
            "- 設定した 1500 秒は実行上限です。二段階モデルは Stage ごとに上限を配分するため、"
            "常に 1500 秒を使い切るわけではありません。",
            "",
            "## 許容した天候入力差",
            "",
            "~~~json",
            json.dumps(weather_inputs, ensure_ascii=False, indent=2, sort_keys=True),
            "~~~",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_accepted_case(case: str, summary: Mapping[str, Any]) -> None:
    _expect(case, "phase", summary.get("phase"), EXPECTED_PHASE)
    _expect(case, "trip_count", summary.get("trip_count"), EXPECTED_TRIP_COUNT)
    _expect(case, "timestep_min", summary.get("timestep_min"), EXPECTED_TIMESTEP_MIN)
    _expect(
        case,
        "price_slot_count",
        summary.get("price_slot_count"),
        EXPECTED_PRICE_SLOT_COUNT,
    )
    fleet = _require_mapping(summary.get("fleet"), f"{case}.fleet")
    expected_fleet = _require_mapping(
        summary.get("expected_fleet"), f"{case}.expected_fleet"
    )
    if dict(fleet) != dict(expected_fleet):
        raise ComparisonContractError(
            f"{case}.fleet must match its declared expected_fleet: "
            f"fleet={dict(fleet)}, expected={dict(expected_fleet)}"
        )
    time_limit = _finite_number(
        summary.get("time_limit_sec"), f"{case}.time_limit_sec"
    )
    mip_gap = _finite_number(summary.get("mip_gap"), f"{case}.mip_gap")
    _finite_number(summary.get("random_seed"), f"{case}.random_seed")
    if time_limit <= 0.0:
        raise ComparisonContractError(f"{case}.time_limit_sec must be positive")
    if not 0.0 <= mip_gap < 1.0:
        raise ComparisonContractError(f"{case}.mip_gap must be in [0, 1)")
    _expect(case, "feasible", summary.get("feasible"), True)
    _expect(case, "research_run_accepted", summary.get("research_run_accepted"), True)
    _expect(
        case,
        "research_feasibility_eligible",
        summary.get("research_feasibility_eligible"),
        True,
    )
    _expect(
        case,
        "research_cost_kpi_eligible",
        summary.get("research_cost_kpi_eligible"),
        True,
    )
    _expect(
        case,
        "research_accounting_cost_eligible",
        summary.get("research_accounting_cost_eligible"),
        True,
    )
    _expect(
        case,
        "research_cost_optimality_eligible",
        summary.get("research_cost_optimality_eligible"),
        False,
    )
    _expect(
        case,
        "solver_objective_matches_accounting_total",
        summary.get("solver_objective_matches_accounting_total"),
        False,
    )
    _expect(
        case,
        "cost_comparison_scope",
        summary.get("cost_comparison_scope"),
        EXPECTED_COST_SCOPE,
    )
    _expect(case, "git_dirty", summary.get("git_dirty"), False)

    trip_count = _finite_number(summary.get("trip_count"), f"{case}.trip_count")
    served_count = _finite_number(
        summary.get("trip_count_served"), f"{case}.trip_count_served"
    )
    unserved_count = _finite_number(
        summary.get("trip_count_unserved"), f"{case}.trip_count_unserved"
    )
    if trip_count != served_count or not math.isclose(unserved_count, 0.0):
        raise ComparisonContractError(
            f"{case} must serve every trip exactly once: "
            f"trip_count={trip_count}, served={served_count}, unserved={unserved_count}"
        )
    fragments = _finite_number(
        summary.get("max_fragments_observed"), f"{case}.max_fragments_observed"
    )
    if fragments > 1.0:
        raise ComparisonContractError(
            f"{case}.max_fragments_observed must be <= 1, got {fragments}"
        )

    metrics = _require_mapping(
        summary.get("validation_metrics"), f"{case}.validation_metrics"
    )
    _expect(
        case,
        "validation_metrics.all_required_validation_checks_passed",
        metrics.get("all_required_validation_checks_passed"),
        True,
    )
    for field in VALIDATION_ZERO_FIELDS:
        value = _finite_number(
            metrics.get(field), f"{case}.validation_metrics.{field}"
        )
        if not math.isclose(value, 0.0):
            raise ComparisonContractError(
                f"{case}.validation_metrics.{field} must be zero, got {value}"
            )
    terminal_deviation = _finite_number(
        metrics.get("bess_terminal_soc_deviation_kwh"),
        f"{case}.validation_metrics.bess_terminal_soc_deviation_kwh",
    )
    terminal_tolerance = _finite_number(
        metrics.get("bess_terminal_soc_tolerance_kwh"),
        f"{case}.validation_metrics.bess_terminal_soc_tolerance_kwh",
    )
    if abs(terminal_deviation) > terminal_tolerance:
        raise ComparisonContractError(
            f"{case} BESS terminal deviation exceeds tolerance: "
            f"{terminal_deviation} > {terminal_tolerance}"
        )

    costs = _require_mapping(summary.get("costs_jpy"), f"{case}.costs_jpy")
    accounting_total = _finite_number(
        summary.get("accounting_total_cost_jpy"), f"{case}.accounting_total_cost_jpy"
    )
    reported_total = _finite_number(
        costs.get("total_cost"), f"{case}.costs_jpy.total_cost"
    )
    if not math.isclose(accounting_total, reported_total, abs_tol=1e-6):
        raise ComparisonContractError(
            f"{case} accounting_total_cost_jpy differs from costs_jpy.total_cost: "
            f"{accounting_total} != {reported_total}"
        )
    component_total = sum(
        _finite_number(costs.get(field), f"{case}.costs_jpy.{field}")
        for field in ACCOUNTING_COMPONENT_FIELDS
    )
    if not math.isclose(component_total, reported_total, abs_tol=1e-6):
        raise ComparisonContractError(
            f"{case} costs_jpy components differ from total_cost: "
            f"{component_total} != {reported_total}"
        )


def _validate_fixed_controls(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> None:
    for field in FIXED_CONTROL_FIELDS:
        sunny_value = _required_field(sunny, field, "sunny")
        rain_value = _required_field(rain, field, "rain")
        if sunny_value != rain_value:
            raise ComparisonContractError(
                f"Fixed control differs at {field}: "
                f"sunny={_short_json(sunny_value)}, rain={_short_json(rain_value)}"
            )


def _validate_stage1_energy_proxy_controls(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> dict[str, Any]:
    """Require identical proxy policy while retaining legacy comparisons."""
    field = "stage1_energy_cost_proxy_configuration"
    sunny_present = field in sunny
    rain_present = field in rain
    if not sunny_present and not rain_present:
        return {
            "exported": False,
            "legacy_summary_note": (
                "Stage 1 energy-cost proxy metadata is absent from both "
                "summaries; these artifacts predate the weather-aware "
                "assignment-cost proxy."
            ),
        }
    if sunny_present != rain_present:
        raise ComparisonContractError(
            f"{field} must be present in both summaries or neither"
        )
    sunny_configuration = _require_mapping(
        sunny.get(field), f"sunny.{field}"
    )
    rain_configuration = _require_mapping(rain.get(field), f"rain.{field}"
    )
    if sunny_configuration != rain_configuration:
        raise ComparisonContractError(
            f"Fixed control differs at {field}: "
            f"sunny={_short_json(sunny_configuration)}, "
            f"rain={_short_json(rain_configuration)}"
        )
    return {"exported": True, "configuration": dict(sunny_configuration)}


def _validate_contract_power_controls(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> dict[str, Any]:
    """Require a matched contract-power audit, with an explicit legacy path."""
    fields = (
        "depot_import_limit_kw_by_depot",
        "depot_import_limit_semantics",
        "contract_overage_penalty_yen_per_kwh",
    )
    sunny_present = [field in sunny for field in fields]
    rain_present = [field in rain for field in fields]
    if not any(sunny_present) and not any(rain_present):
        return {
            "exported": False,
            "legacy_summary_note": (
                "Contract import limit and overage penalty are absent from both "
                "summaries; audit the recorded git SHA before interpretation."
            ),
        }
    if not all(sunny_present) or not all(rain_present):
        raise ComparisonContractError(
            "Contract-power controls must be present in both summaries or neither"
        )
    for field in fields:
        sunny_value = _required_field(sunny, field, "sunny")
        rain_value = _required_field(rain, field, "rain")
        if sunny_value != rain_value:
            raise ComparisonContractError(
                f"Fixed contract-power control differs at {field}: "
                f"sunny={_short_json(sunny_value)}, rain={_short_json(rain_value)}"
            )
    return {
        "exported": True,
        "depot_import_limit_kw_by_depot": sunny["depot_import_limit_kw_by_depot"],
        "depot_import_limit_semantics": sunny["depot_import_limit_semantics"],
        "contract_overage_penalty_yen_per_kwh": sunny[
            "contract_overage_penalty_yen_per_kwh"
        ],
    }


def _validate_weather_inputs(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> dict[str, Any]:
    sunny_weather = _require_mapping(
        sunny.get("weather_configuration"), "sunny.weather_configuration"
    )
    rain_weather = _require_mapping(
        rain.get("weather_configuration"), "rain.weather_configuration"
    )
    sunny_assets = _require_mapping(
        sunny.get("depot_energy_assets"), "sunny.depot_energy_assets"
    )
    rain_assets = _require_mapping(
        rain.get("depot_energy_assets"), "rain.depot_energy_assets"
    )
    if set(sunny_assets) != set(rain_assets):
        raise ComparisonContractError(
            "Fixed depot set differs: "
            f"sunny={sorted(sunny_assets)}, rain={sorted(rain_assets)}"
        )
    return {
        "case_identity": {"sunny": _case_identity(sunny), "rain": _case_identity(rain)},
        "weather_configuration": _allowed_differences(
            sunny_weather,
            rain_weather,
            ALLOWED_WEATHER_CONFIGURATION_FIELDS,
            "weather_configuration",
        ),
        "weather_operation_profile": _validate_weather_operation_profile(
            sunny,
            rain,
        ),
        "stage1_energy_cost_proxy_weather_input": (
            _validate_stage1_energy_proxy_weather_input(sunny, rain)
        ),
        "pv_assets": {
            depot_id: _allowed_differences(
                _require_mapping(
                    sunny_assets[depot_id], f"sunny.depot_energy_assets.{depot_id}"
                ),
                _require_mapping(
                    rain_assets[depot_id], f"rain.depot_energy_assets.{depot_id}"
                ),
                ALLOWED_PV_ASSET_FIELDS,
                f"depot_energy_assets.{depot_id}",
            )
            for depot_id in sorted(sunny_assets)
        },
    }


def _validate_stage1_energy_proxy_weather_input(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> dict[str, Any]:
    field = "stage1_energy_cost_proxy_weather_input"
    sunny_present = field in sunny
    rain_present = field in rain
    if not sunny_present and not rain_present:
        return {"exported": False}
    if sunny_present != rain_present:
        raise ComparisonContractError(
            f"{field} must be present in both summaries or neither"
        )
    return {
        "exported": True,
        "differences": _allowed_differences(
            _require_mapping(sunny.get(field), f"sunny.{field}"),
            _require_mapping(rain.get(field), f"rain.{field}"),
            frozenset({"pv_available_kwh_by_depot"}),
            field,
        ),
    }


def _validate_weather_operation_profile(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare effective profile knobs while allowing only their provenance label.

    Summaries created before this audit field was introduced are retained as
    legacy artifacts. They remain comparable only because their git SHA
    identifies source that was independently audited; future summaries must
    export the profile.
    """
    sunny_profile = sunny.get("weather_operation_profile", _MISSING)
    rain_profile = rain.get("weather_operation_profile", _MISSING)
    if sunny_profile is _MISSING and rain_profile is _MISSING:
        return {
            "exported": False,
            "legacy_summary_note": (
                "Effective profile is absent from both summaries; audit the "
                "recorded git SHA before interpreting weather_operation_mode."
            ),
        }
    if sunny_profile is _MISSING or rain_profile is _MISSING:
        raise ComparisonContractError(
            "weather_operation_profile must be present in both summaries or neither"
        )
    return {
        "exported": True,
        "differences": _allowed_differences(
            _require_mapping(sunny_profile, "sunny.weather_operation_profile"),
            _require_mapping(rain_profile, "rain.weather_operation_profile"),
            ALLOWED_WEATHER_OPERATION_PROFILE_FIELDS,
            "weather_operation_profile",
        ),
    }


def _allowed_differences(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
    allowed_fields: frozenset[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for field in sorted(set(sunny) | set(rain)):
        sunny_value = sunny.get(field, _MISSING)
        rain_value = rain.get(field, _MISSING)
        if sunny_value == rain_value:
            continue
        if field not in allowed_fields:
            raise ComparisonContractError(
                f"Fixed control differs at {label}.{field}: "
                f"sunny={_short_json(sunny_value)}, rain={_short_json(rain_value)}"
            )
        differences[field] = {
            "sunny": None if sunny_value is _MISSING else sunny_value,
            "rain": None if rain_value is _MISSING else rain_value,
        }
    return differences


def _metric_effects(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
    container: str,
    fields: Sequence[str],
) -> dict[str, dict[str, float | None]]:
    sunny_values = _require_mapping(sunny.get(container), f"sunny.{container}")
    rain_values = _require_mapping(rain.get(container), f"rain.{container}")
    return {
        field: _numeric_effect(
            _finite_number(sunny_values.get(field), f"sunny.{container}.{field}"),
            _finite_number(rain_values.get(field), f"rain.{container}.{field}"),
        )
        for field in fields
    }


def _optional_metric_effects(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
    container: str,
    fields: Sequence[str],
) -> dict[str, Any]:
    sunny_present = container in sunny
    rain_present = container in rain
    if not sunny_present and not rain_present:
        return {"exported": False}
    if sunny_present != rain_present:
        raise ComparisonContractError(
            f"{container} must be present in both summaries or neither"
        )
    return {
        "exported": True,
        "metrics": _metric_effects(sunny, rain, container, fields),
    }


def _scalar_effect(
    sunny: Mapping[str, Any],
    rain: Mapping[str, Any],
    field: str,
) -> dict[str, float | None]:
    return _numeric_effect(
        _finite_number(sunny.get(field), f"sunny.{field}"),
        _finite_number(rain.get(field), f"rain.{field}"),
    )


def _numeric_effect(sunny: float, rain: float) -> dict[str, float | None]:
    difference = rain - sunny
    return {
        "sunny": sunny,
        "rain": rain,
        "rain_minus_sunny": difference,
        "percent_change_from_sunny": (
            None
            if math.isclose(sunny, 0.0, abs_tol=1e-12)
            else difference / abs(sunny) * 100.0
        ),
    }


def _run_status(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: summary.get(field)
        for field in (
            "case_name",
            "scenario_id",
            "service_date",
            "trip_count",
            "trip_count_served",
            "trip_count_unserved",
            "used_vehicle_count",
            "max_fragments_observed",
            "solver_status",
            "stage1_solver_status",
            "stage1_runtime_seconds",
            "stage1_mip_gap_percent",
            "stage2_solver_status",
            "stage2_runtime_seconds",
            "research_run_accepted",
            "research_feasibility_eligible",
        )
    }


def _case_identity(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: summary.get(field)
        for field in (
            "case_name",
            "scenario_id",
            "prepared_input_id",
            "prepared_input_sha256",
            "service_date",
            "experiment_hash",
        )
    }


def _expect(case: str, field: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ComparisonContractError(
            f"{case}.{field} must be {_short_json(expected)}, got {_short_json(actual)}"
        )


def _required_field(
    summary: Mapping[str, Any],
    field: str,
    case: str,
) -> Any:
    if field not in summary:
        raise ComparisonContractError(f"{case}.{field} is required")
    return summary[field]


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonContractError(f"{label} must be a mapping")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComparisonContractError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ComparisonContractError(f"{label} must be finite")
    return number


def _short_json(value: Any) -> str:
    rendered = json.dumps(
        None if value is _MISSING else value,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )
    return rendered if len(rendered) <= 240 else rendered[:237] + "..."


def _markdown_row(label: str, sunny: Any, rain: Any) -> str:
    return f"| {label} | {sunny} | {rain} |"


def _trip_coverage(status: Mapping[str, Any]) -> str:
    return f"{status.get('trip_count_served')} / {status.get('trip_count')}"


def _metric_rows(
    effects: Mapping[str, Any],
    fields: Sequence[str],
) -> list[str]:
    rows: list[str] = []
    for field in fields:
        effect = _require_mapping(effects.get(field), f"effect {field}")
        rows.append(
            "| "
            + field
            + " | "
            + _format_number(effect.get("sunny"))
            + " | "
            + _format_number(effect.get("rain"))
            + " | "
            + _format_number(effect.get("rain_minus_sunny"))
            + " | "
            + _format_number(effect.get("percent_change_from_sunny"))
            + " |"
        )
    return rows


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):,.3f}"
    return str(value)


def _load_summary(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ComparisonContractError(f"Could not read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ComparisonContractError(f"Invalid JSON in {path}: {error}") from error
    return _require_mapping(payload, f"summary {path}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest(
    case: str,
    summary_path: Path,
    summary: Mapping[str, Any],
) -> None:
    manifest_path = summary_path.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ComparisonContractError(
            f"{case} is missing required manifest: {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonContractError(
            f"{case} manifest cannot be read: {error}"
        ) from error
    manifest = _require_mapping(manifest, f"{case}.manifest")
    _expect(case, "manifest.schema", manifest.get("schema"), "research_run_manifest_v1")
    _expect(case, "manifest.run_state", manifest.get("run_state"), "complete")
    artifacts = _require_mapping(
        manifest.get("artifacts"), f"{case}.manifest.artifacts"
    )
    artifact_root = manifest_path.parent.resolve()
    if summary_path.resolve() != artifact_root / "summary.json":
        raise ComparisonContractError(
            f"{case} summary must be the manifest-pinned summary.json in its run directory"
        )
    for artifact_name, raw_record in artifacts.items():
        record = _require_mapping(
            raw_record, f"{case}.manifest.artifacts.{artifact_name}"
        )
        artifact_path = (artifact_root / str(artifact_name)).resolve()
        if artifact_path.parent != artifact_root or not artifact_path.is_file():
            raise ComparisonContractError(
                f"{case} manifest artifact is missing or outside its run directory: "
                f"{artifact_name}"
            )
        _expect(
            case,
            f"manifest.artifacts.{artifact_name}.sha256",
            record.get("sha256"),
            _file_sha256(artifact_path),
        )
        _expect(
            case,
            f"manifest.artifacts.{artifact_name}.size_bytes",
            record.get("size_bytes"),
            artifact_path.stat().st_size,
        )
    if "summary.json" not in artifacts:
        raise ComparisonContractError(
            f"{case} manifest must include summary.json"
        )
    controls = _require_mapping(
        manifest.get("declared_controls"),
        f"{case}.manifest.declared_controls",
    )
    for field, declared_value in controls.items():
        if field in summary and summary.get(field) != declared_value:
            raise ComparisonContractError(
                f"{case}.{field} differs from its manifest declaration: "
                f"summary={summary.get(field)!r}, manifest={declared_value!r}"
            )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


_MISSING = object()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunny-summary", type=Path, required=True)
    parser.add_argument("--rain-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        sunny_summary = _load_summary(args.sunny_summary)
        rain_summary = _load_summary(args.rain_summary)
        _validate_manifest("sunny", args.sunny_summary, sunny_summary)
        _validate_manifest("rain", args.rain_summary, rain_summary)
        comparison = build_weather_comparison(
            sunny_summary,
            rain_summary,
        )
    except ComparisonContractError as error:
        print(error, file=sys.stderr)
        return 2

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output = dict(comparison)
    output["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    output["source_summary_paths"] = {
        "sunny": str(args.sunny_summary.resolve()),
        "rain": str(args.rain_summary.resolve()),
    }
    _write_json(output_dir / "weather_comparison.json", output)
    (output_dir / "weather_comparison_report.md").write_text(
        render_markdown_report(output),
        encoding="utf-8",
    )
    print(output_dir / "weather_comparison.json")
    print(output_dir / "weather_comparison_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
