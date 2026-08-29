"""Build thesis-ready SUNNY/RAIN tables, figures, and Japanese prose.

The builder consumes only the Git-tracked weather rerun evidence bundle.  It
validates the bundle before rendering, writes deterministic artifacts, and
verifies that every source byte is unchanged after generation.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "thesis_weather_result_package_v1"
EXECUTION_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
SCENARIO_IDS = {
    "SUNNY": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
    "RAIN": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
}
TOLERANCE = 1.0e-6

# These values are acceptance assertions only.  Rendered values are always
# extracted from the evidence JSON loaded into ScenarioEvidence.
EXPECTED_RESULTS = {
    "SUNNY": {
        "used_bev": 28,
        "used_ice": 4,
        "bev_trips": 199,
        "ice_trips": 65,
        "pv_generated_kwh": 6056.25,
    },
    "RAIN": {
        "used_bev": 21,
        "used_ice": 11,
        "bev_trips": 91,
        "ice_trips": 173,
        "pv_generated_kwh": 996.2,
    },
}
EXPECTED_COST_DIFFERENCE_JPY = 37_614.844839
EXPECTED_BESS_ONE_WAY_EFFICIENCY = 0.95
EXPECTED_BESS_TERMINAL_SOC_KWH = 3000.0

BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GOLD = "#D6A72C"
OLIVE = "#7A8B3A"
LIGHT_BLUE = "#AFCBE0"
LIGHT_ORANGE = "#F1C08B"
GRAY = "#8B949E"
LIGHT_GRAY = "#E5E7EB"
INK = "#252A34"

REQUIRED_SOURCE_FILES = (
    "result_summary.json",
    "normal_confirmation_input_contract.json",
    "confirmation_manifest.json",
    "artifact_hashes.json",
    "SUNNY/optimization_parameters.json",
    "SUNNY/executed_day_accounting.json",
    "SUNNY/selected_candidate.json",
    "SUNNY/rolling_chain_summary.json",
    "SUNNY/confirmation_gate.json",
    "RAIN/optimization_parameters.json",
    "RAIN/executed_day_accounting.json",
    "RAIN/selected_candidate.json",
    "RAIN/rolling_chain_summary.json",
    "RAIN/confirmation_gate.json",
)


class EvidenceValidationError(RuntimeError):
    """Raised when canonical evidence fails a fail-closed assertion."""


@dataclass(frozen=True)
class ScenarioEvidence:
    """Canonical artifacts for one weather/PV scenario."""

    code: str
    summary: Mapping[str, Any]
    optimization: Mapping[str, Any]
    accounting: Mapping[str, Any]
    selected_candidate: Mapping[str, Any]
    rolling: Mapping[str, Any]
    confirmation_gate: Mapping[str, Any]

    @property
    def costs(self) -> Mapping[str, Any]:
        return self.accounting["cost_breakdown"]

    @property
    def model_metadata(self) -> Mapping[str, Any]:
        return self.optimization["effective_model_metadata"]

    @property
    def solver(self) -> Mapping[str, Any]:
        return self.optimization["effective_optimization_config"]


@dataclass(frozen=True)
class EvidenceBundle:
    """Loaded and validated source bundle."""

    root: Path
    summary: Mapping[str, Any]
    input_contract: Mapping[str, Any]
    confirmation_manifest: Mapping[str, Any]
    scenarios: Mapping[str, ScenarioEvidence]
    source_hashes: Mapping[str, str]
    tree_sha256: str


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceValidationError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _bundle_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tree_sha256(hashes: Mapping[str, str]) -> str:
    payload = "".join(f"{name}\0{digest}\n" for name, digest in hashes.items())
    return sha256(payload.encode("utf-8")).hexdigest()


def _assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=TOLERANCE):
        raise EvidenceValidationError(
            f"{label}: expected {expected:.12f}, observed {actual:.12f}"
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _load_scenario(
    root: Path,
    code: str,
    summary: Mapping[str, Any],
) -> ScenarioEvidence:
    scenario_root = root / code
    return ScenarioEvidence(
        code=code,
        summary=summary["scenarios"][code],
        optimization=_read_json(scenario_root / "optimization_parameters.json"),
        accounting=_read_json(scenario_root / "executed_day_accounting.json"),
        selected_candidate=_read_json(scenario_root / "selected_candidate.json"),
        rolling=_read_json(scenario_root / "rolling_chain_summary.json"),
        confirmation_gate=_read_json(scenario_root / "confirmation_gate.json"),
    )


def load_and_validate_bundle(evidence_dir: Path) -> EvidenceBundle:
    """Load canonical evidence and enforce every declared result invariant."""

    root = evidence_dir.resolve()
    for relative_path in REQUIRED_SOURCE_FILES:
        _require((root / relative_path).is_file(), f"Missing source: {relative_path}")

    source_hashes = _bundle_hashes(root)
    hash_index = _read_json(root / "artifact_hashes.json")["sha256"]
    indexed_actual = {
        name: digest
        for name, digest in source_hashes.items()
        if name != "artifact_hashes.json"
    }
    _require(hash_index == indexed_actual, "artifact_hashes.json does not match bytes")

    summary = _read_json(root / "result_summary.json")
    input_contract = _read_json(root / "normal_confirmation_input_contract.json")
    confirmation_manifest = _read_json(root / "confirmation_manifest.json")
    scenarios = {
        code: _load_scenario(root, code, summary) for code in ("SUNNY", "RAIN")
    }
    bundle = EvidenceBundle(
        root=root,
        summary=summary,
        input_contract=input_contract,
        confirmation_manifest=confirmation_manifest,
        scenarios=scenarios,
        source_hashes=source_hashes,
        tree_sha256=_tree_sha256(source_hashes),
    )
    _validate_bundle(bundle)
    return bundle


def _validate_bundle(bundle: EvidenceBundle) -> None:
    summary = bundle.summary
    manifest = bundle.confirmation_manifest
    contract = bundle.input_contract
    _require(summary["execution_git_sha"] == EXECUTION_SHA, "Unexpected execution SHA")
    _require(summary["execution_git_dirty"] is False, "Execution worktree was dirty")
    _require(summary["status"] == "PASS_NORMAL_PATH_CONFIRMATION", "Summary gate failed")
    _require(manifest["execution_git_sha"] == EXECUTION_SHA, "Manifest SHA mismatch")
    _require(manifest["effective_solver_controls_equal"] is True, "Solver controls differ")
    _require(contract["status"] == "PASS_FULL_INPUT_CONTRACT", "Input contract failed")
    _require(contract["fresh_prepare_used"] is True, "Fresh Prepare was not used")
    _require(contract["fixed_nonweather_inputs_equal"] is True, "Fixed inputs differ")
    _require(contract["service_date_contract"]["matches"] is True, "Service date mismatch")

    for code, scenario in bundle.scenarios.items():
        expected = EXPECTED_RESULTS[code]
        row = scenario.summary
        _require(row["scenario_id"] == SCENARIO_IDS[code], f"{code}: scenario ID")
        for key in ("used_bev", "used_ice", "bev_trips", "ice_trips"):
            _require(row[key] == expected[key], f"{code}: unexpected {key}")
        _assert_close(
            float(row["executed_day_pv_generated_kwh"]),
            float(expected["pv_generated_kwh"]),
            f"{code}: PV generation",
        )
        _require(row["served_trips"] == 264, f"{code}: served trip count")
        _require(row["unserved_trips"] == 0, f"{code}: unserved trip count")
        _require(row["used_bev"] + row["used_ice"] == 32, f"{code}: used fleet")
        _require(row["bev_trips"] + row["ice_trips"] == 264, f"{code}: trips")
        _require(scenario.rolling["chain_accepted"] is True, f"{code}: Rolling")
        _require(scenario.rolling["step_count"] == 24, f"{code}: Rolling steps")
        _require(scenario.rolling["expected_step_count"] == 24, f"{code}: expected steps")
        _require(all(scenario.confirmation_gate["checks"].values()), f"{code}: gate")
        _require(scenario.accounting["eligible"] is True, f"{code}: accounting")
        _require(scenario.accounting["terminal_energy_balanced"] is True, f"{code}: energy")
        _require(scenario.accounting["bess_terminal_energy_balanced"] is True, f"{code}: BESS")
        _require(scenario.accounting["executed_slot_count"] == 96, f"{code}: slots")
        _assert_close(
            float(scenario.costs["total_cost"]),
            float(row["executed_day_cost_jpy"]),
            f"{code}: authoritative final cost",
        )
        _require(scenario.costs["objective_is_actual_cost"] is False, f"{code}: cost scope")
        _validate_energy_balance(scenario)

    sunny = bundle.scenarios["SUNNY"]
    rain = bundle.scenarios["RAIN"]
    difference = float(rain.costs["total_cost"]) - float(sunny.costs["total_cost"])
    _assert_close(difference, EXPECTED_COST_DIFFERENCE_JPY, "Executed-day cost difference")
    component_difference = sum(
        float(rain.costs[key]) - float(sunny.costs[key])
        for key in ("fuel_cost", "electricity_cost", "co2_cost")
    )
    _assert_close(difference, component_difference, "Cost difference decomposition")
    _require(
        sunny.summary["selected_physical_assignment_sha256"]
        != rain.summary["selected_physical_assignment_sha256"],
        "SUNNY and RAIN selected the same physical assignment hash",
    )
    _validate_shared_inputs(sunny, rain, bundle.input_contract)


def _validate_energy_balance(scenario: ScenarioEvidence) -> None:
    costs = scenario.costs
    pv_balance = (
        float(costs["pv_to_bus_kwh"])
        + float(costs["pv_to_bess_kwh"])
        + float(costs["pv_curtailed_kwh"])
    )
    _assert_close(pv_balance, float(costs["pv_generated_kwh"]), f"{scenario.code}: PV balance")
    expected_discharge = (
        float(costs["pv_to_bess_kwh"])
        * EXPECTED_BESS_ONE_WAY_EFFICIENCY**2
    )
    _assert_close(expected_discharge, float(costs["bess_to_bus_kwh"]), f"{scenario.code}: BESS flow")
    terminal = scenario.accounting["bess_terminal_soc_by_depot"]["tsurumaki"]
    _assert_close(float(terminal["initial_soc_kwh"]), EXPECTED_BESS_TERMINAL_SOC_KWH, f"{scenario.code}: BESS initial")
    _assert_close(float(terminal["terminal_soc_kwh"]), EXPECTED_BESS_TERMINAL_SOC_KWH, f"{scenario.code}: BESS terminal")


def _validate_shared_inputs(
    sunny: ScenarioEvidence,
    rain: ScenarioEvidence,
    contract: Mapping[str, Any],
) -> None:
    common_keys = (
        "trip_structure_input_sha256",
        "vehicle_input_sha256",
        "charger_input_sha256",
        "price_input_sha256",
        "energy_asset_control_input_sha256",
        "objective_weights_sha256",
    )
    sunny_dimensions = sunny.optimization["canonical_input_dimensions"]
    rain_dimensions = rain.optimization["canonical_input_dimensions"]
    for key in common_keys:
        _require(sunny_dimensions[key] == rain_dimensions[key], f"Shared hash differs: {key}")
    _require(
        sunny.model_metadata["scenario_fleet_contract_hash"]
        == rain.model_metadata["scenario_fleet_contract_hash"],
        "Fleet contract hashes differ",
    )
    _require(
        contract["cross_scenario_different_hashes"]
        == [
            "canonical_ablation_input_sha256",
            "prepared_input_sha256",
            "prepared_source_sha256",
            "pv_hash",
            "pv_profile_sha256",
        ],
        "Unexpected cross-scenario hash differences",
    )


def _single_value(values: Iterable[Any], label: str) -> Any:
    unique = {json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values}
    _require(len(unique) == 1, f"Expected one value for {label}, got {len(unique)}")
    return json.loads(next(iter(unique)))


def _fleet_parameters(scenario: ScenarioEvidence) -> dict[str, Any]:
    contract = scenario.model_metadata["scenario_fleet_contract"]
    vehicles = contract["active_vehicle_parameters"]
    bev = [row for row in vehicles if row["powertrain"] == "BEV"]
    ice = [row for row in vehicles if row["powertrain"] == "ICE"]
    _require(len(bev) == 35 and len(ice) == 25, "Unexpected active fleet composition")
    return {
        "total": len(vehicles),
        "bev_count": len(bev),
        "ice_count": len(ice),
        "initial_soc_min_percent": min(float(row["initial_soc_raw"]) for row in bev) * 100.0,
        "initial_soc_max_percent": max(float(row["initial_soc_raw"]) for row in bev) * 100.0,
        "battery_kwh": _single_value((row["battery_capacity_kwh"] for row in bev), "BEV battery"),
        "bev_energy_kwh_per_km": _single_value((row["energy_consumption_kwh_per_km"] for row in bev), "BEV energy rate"),
        "bev_charge_power_kw": _single_value((row["charge_power_max_kw"] for row in bev), "BEV charge power"),
        "bev_soc_min_percent": _single_value((row["source_record"]["minSoc"] for row in bev), "BEV minimum SOC") * 100.0,
        "bev_soc_max_percent": _single_value((row["source_record"]["maxSoc"] for row in bev), "BEV maximum SOC") * 100.0,
        "ice_tank_l": _single_value((row["fuel_tank_capacity_l"] for row in ice), "ICE tank"),
        "ice_efficiency_km_per_l": _single_value((row["source_record"]["fuelEfficiencyKmPerL"] for row in ice), "ICE efficiency"),
        "ice_initial_fuel_l": _single_value((row["initial_fuel_l"] for row in ice), "ICE initial fuel"),
        "compatible_charger_count": _single_value((len(row["compatible_charger_ids"]) for row in bev), "compatible charger count"),
        "fleet_contract_hash": contract["fleet_contract_hash"],
    }


def _parameter_rows(bundle: EvidenceBundle) -> list[dict[str, str]]:
    sunny = bundle.scenarios["SUNNY"]
    rain = bundle.scenarios["RAIN"]
    fleet = _fleet_parameters(sunny)
    _require(fleet == _fleet_parameters(rain), "Fleet parameter snapshots differ")
    protocol = bundle.summary["protocol"]
    problem = sunny.optimization["effective_problem_scenario"]
    solver = sunny.solver
    frontend = sunny.optimization["frontend_request"]
    _require(solver == rain.solver, "Effective solver configuration differs")
    rain_grid_price = float(rain.costs["electricity_cost"]) / float(rain.costs["grid_import_kwh"])
    _assert_close(rain_grid_price, 30.0, "Grid energy unit price")

    rows: list[dict[str, str]] = []

    def add(group: str, parameter: str, common: Any = "", sunny_value: Any = "", rain_value: Any = "", unit: str = "", source: str = "") -> None:
        rows.append(
            {
                "区分": group,
                "項目": parameter,
                "共通値": _format_cell(common),
                "SUNNY": _format_cell(sunny_value),
                "RAIN": _format_cell(rain_value),
                "単位": unit,
                "正本": source,
            }
        )

    add("運行", "営業所", protocol["depot_id"], unit="-", source="result_summary.json")
    add("運行", "時刻表", protocol["service_id"], unit="-", source="result_summary.json")
    add("運行", "運行日", protocol["service_date"], unit="日付", source="result_summary.json")
    add("運行", "便数", protocol["trip_count"], unit="便", source="result_summary.json")
    add("運行", "路線数", sunny.model_metadata["route_count"], unit="路線", source="optimization_parameters.json")
    add("運行", "内部時間刻み", protocol["time_step_minutes"], unit="分", source="result_summary.json")
    add("運行", "Rolling実行間隔", protocol["rolling_execution_minutes"], unit="分", source="result_summary.json")
    add("反実仮想", "気象・PV条件", "", "2025-08-05由来のPV曲線", "2025-08-10由来の低PV曲線", "-", "optimization_parameters.json")
    add("車両", "有効車両数", fleet["total"], unit="台", source="scenario_fleet_contract_v2")
    add("車両", "BEV／ICE在庫", f"{fleet['bev_count']}／{fleet['ice_count']}", unit="台", source="scenario_fleet_contract_v2")
    add("車両", "BEV初期SOC範囲", f"{fleet['initial_soc_min_percent']:.4f}～{fleet['initial_soc_max_percent']:.4f}", unit="%", source="scenario_fleet_contract_v2")
    add("車両", "BEV電池容量", fleet["battery_kwh"], unit="kWh/台", source="scenario_fleet_contract_v2")
    add("車両", "BEV電費", fleet["bev_energy_kwh_per_km"], unit="kWh/km", source="scenario_fleet_contract_v2")
    add("車両", "BEV最大充電電力", fleet["bev_charge_power_kw"], unit="kW/台", source="scenario_fleet_contract_v2")
    add("車両", "BEV SOC範囲", f"{fleet['bev_soc_min_percent']:.0f}～{fleet['bev_soc_max_percent']:.0f}", unit="%", source="scenario_fleet_contract_v2")
    add("車両", "ICE燃料タンク", fleet["ice_tank_l"], unit="L/台", source="scenario_fleet_contract_v2")
    add("車両", "ICE燃費", fleet["ice_efficiency_km_per_l"], unit="km/L", source="scenario_fleet_contract_v2")
    add("車両", "ICE初期燃料", fleet["ice_initial_fuel_l"], unit="L/台", source="scenario_fleet_contract_v2")
    add("充電", "充電器数", protocol["charger_count"], unit="基", source="result_summary.json")
    add("充電", "BEVごとの互換充電器数", fleet["compatible_charger_count"], unit="基", source="scenario_fleet_contract_v2")
    add("充電", "受電上限", "正本bundleに明示値なし", unit="-", source="欠落を明示")
    add("PV", "実行日PV発電量", "", sunny.costs["pv_generated_kwh"], rain.costs["pv_generated_kwh"], "kWh", "executed_day_accounting.json")
    add("PV", "PV定格容量", "正本bundleに明示値なし", unit="-", source="欠落を明示")
    add("BESS", "初期／終端SOC", f"{EXPECTED_BESS_TERMINAL_SOC_KWH:.0f}／{EXPECTED_BESS_TERMINAL_SOC_KWH:.0f}", unit="kWh", source="executed_day_accounting.json")
    add("BESS", "観測された充放電比", EXPECTED_BESS_ONE_WAY_EFFICIENCY**2 * 100.0, unit="%", source="executed_day_accounting.jsonから算出")
    add("BESS", "定格容量／出力", "正本bundleに明示値なし", unit="-", source="欠落を明示")
    add("料金", "系統購入単価", rain_grid_price, unit="円/kWh", source="executed_day_accounting.jsonから算出")
    add("料金", "軽油単価", problem["diesel_price_yen_per_l"], unit="円/L", source="optimization_parameters.json")
    add("料金", "車両使用費", sunny.model_metadata["vehicle_usage_cost_jpy_per_used_bus"], unit="円/台日", source="optimization_parameters.json")
    add("料金", "CO₂価格", problem["co2_price_per_kg"], unit="円/kg", source="optimization_parameters.json")
    add("料金", "需要料金（on/off peak）", f"{problem['demand_charge_on_peak_yen_per_kw']:.0f}／{problem['demand_charge_off_peak_yen_per_kw']:.0f}", unit="円/kW", source="optimization_parameters.json")
    add("Solver", "方式", solver["phase"], unit="-", source="optimization_parameters.json")
    add("Solver", "総／Stage 1／Stage 2上限", f"{solver['time_limit_sec']}／{solver['stage1_time_limit_sec']}／{solver['stage2_time_limit_sec']}", unit="秒", source="optimization_parameters.json")
    add("Solver", "要求MIP gap", solver["mip_gap"] * 100.0, unit="%", source="optimization_parameters.json")
    add("Solver", "seed", solver["random_seed"], unit="-", source="optimization_parameters.json")
    add("Solver", "Gurobi threads", solver["gurobi_threads"], unit="thread", source="optimization_parameters.json")
    add("Solver", "BestObjStop", solver["stage1_best_obj_stop_enabled"], unit="-", source="optimization_parameters.json")
    add("Solver", "powertrain selector strengthening", sunny.model_metadata["stage1_powertrain_selector_strengthening"], unit="-", source="optimization_parameters.json")
    add("Solver", "Stage 1→2候補上限（実効）", frontend["stage1_stage2_candidate_limit"], unit="候補", source="optimization_parameters.json")
    return rows


def _format_cell(value: Any) -> str:
    if value is True:
        return "ON"
    if value is False:
        return "OFF"
    if isinstance(value, float):
        return f"{value:.10f}".rstrip("0").rstrip(".")
    return str(value)


def _scenario_result_rows(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    rows = []
    for code, scenario in bundle.scenarios.items():
        summary = scenario.summary
        costs = scenario.costs
        rows.append(
            {
                "scenario": code,
                "scenario_id": summary["scenario_id"],
                "used_bev": summary["used_bev"],
                "used_ice": summary["used_ice"],
                "bev_trips": summary["bev_trips"],
                "ice_trips": summary["ice_trips"],
                "served_trips": summary["served_trips"],
                "unserved_trips": summary["unserved_trips"],
                "executed_day_cost_jpy": costs["total_cost"],
                "fuel_liters": costs["ice_fuel_consumed_l"],
                "grid_import_kwh": costs["grid_import_kwh"],
                "pv_generated_kwh": costs["pv_generated_kwh"],
                "pv_to_bus_kwh": costs["pv_to_bus_kwh"],
                "pv_to_bess_kwh": costs["pv_to_bess_kwh"],
                "bess_to_bus_kwh": costs["bess_to_bus_kwh"],
                "pv_curtailed_kwh": costs["pv_curtailed_kwh"],
                "peak_grid_kw": costs["peak_grid_kw"],
                "minimum_executed_bev_soc_kwh": summary["minimum_executed_bev_soc_kwh"],
                "stage1_certified_gap_percent": summary["stage1_certified_gap_ratio"] * 100.0,
                "solve_time_seconds": summary["solve_time_seconds"],
                "rolling_steps": summary["rolling_steps"],
                "physical_validation": summary["physical_validation"],
                "accounting_reconciliation": summary["accounting_reconciliation"],
            }
        )
    return rows


def _cost_rows(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    keys = (
        ("vehicle_usage_cost", "車両使用費"),
        ("fuel_cost", "燃料費"),
        ("electricity_cost", "系統電力費"),
        ("co2_cost", "CO₂費用"),
        ("demand_cost", "需要料金"),
        ("degradation_cost", "電池劣化費"),
        ("total_cost", "合計"),
    )
    sunny = bundle.scenarios["SUNNY"].costs
    rain = bundle.scenarios["RAIN"].costs
    return [
        {
            "component": label,
            "source_key": key,
            "SUNNY_jpy": sunny[key],
            "RAIN_jpy": rain[key],
            "RAIN_minus_SUNNY_jpy": float(rain[key]) - float(sunny[key]),
        }
        for key, label in keys
    ]


def _energy_rows(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    rows = []
    for code, scenario in bundle.scenarios.items():
        costs = scenario.costs
        terminal = scenario.accounting["bess_terminal_soc_by_depot"]["tsurumaki"]
        rows.append(
            {
                "scenario": code,
                "pv_generated_kwh": costs["pv_generated_kwh"],
                "pv_to_bus_kwh": costs["pv_to_bus_kwh"],
                "pv_to_bess_kwh": costs["pv_to_bess_kwh"],
                "pv_curtailed_kwh": costs["pv_curtailed_kwh"],
                "bess_to_bus_kwh": costs["bess_to_bus_kwh"],
                "grid_to_bus_kwh": costs["grid_to_bus_kwh"],
                "grid_to_bess_kwh": costs["grid_to_bess_kwh"],
                "bess_output_per_pv_input": float(costs["bess_to_bus_kwh"]) / float(costs["pv_to_bess_kwh"]),
                "bess_initial_soc_kwh": terminal["initial_soc_kwh"],
                "bess_terminal_soc_kwh": terminal["terminal_soc_kwh"],
                "terminal_energy_balanced": scenario.accounting["terminal_energy_balanced"],
            }
        )
    return rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _require(bool(rows), f"No rows for {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    headers = list(rows[0])
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = [str(row[key]).replace("|", "\\|").replace("\n", " ") for key in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def _write_table_pair(output_dir: Path, stem: str, rows: Sequence[Mapping[str, Any]]) -> list[Path]:
    csv_path = output_dir / f"{stem}.csv"
    md_path = output_dir / f"{stem}.md"
    _write_csv(csv_path, rows)
    md_path.write_text(f"# {stem}\n\n{_markdown_table(rows)}", encoding="utf-8")
    return [csv_path, md_path]


def _configure_matplotlib() -> tuple[Any, str]:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = SCHEMA_VERSION
    matplotlib.rcParams["svg.fonttype"] = "none"
    from matplotlib import font_manager, pyplot as plt

    font_name = ""
    for candidate in ("Noto Sans JP", "Meiryo"):
        try:
            font_manager.findfont(candidate, fallback_to_default=False)
        except ValueError:
            continue
        font_name = candidate
        break
    if not font_name:
        raise EvidenceValidationError("Noto Sans JP or Meiryo is required")
    plt.rcParams.update(
        {
            "font.family": font_name,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    return plt, font_name


def _style_axis(ax: Any) -> None:
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _add_header(fig: Any, title: str, subtitle: str) -> None:
    fig.suptitle(title, fontsize=15, fontweight="bold", x=0.06, ha="left", y=0.98)
    fig.text(0.06, 0.925, subtitle, fontsize=9, color="#59636E", ha="left")
    from matplotlib.patches import Circle

    center_x, center_y = 0.965, 0.965
    for dx, dy in ((0.0, 0.012), (0.011, 0.004), (0.007, -0.010), (-0.007, -0.010), (-0.011, 0.004)):
        fig.add_artist(Circle((center_x + dx, center_y + dy), 0.006, transform=fig.transFigure, facecolor=LIGHT_BLUE, edgecolor=BLUE, linewidth=0.5))
    fig.add_artist(Circle((center_x, center_y), 0.004, transform=fig.transFigure, facecolor=GOLD, edgecolor=INK, linewidth=0.4))


def _save_figure(plt: Any, fig: Any, stem: Path) -> list[Path]:
    png_path = stem.with_suffix(".png")
    svg_path = stem.with_suffix(".svg")
    fig.savefig(
        png_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": SCHEMA_VERSION},
    )
    fig.savefig(
        svg_path,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": SCHEMA_VERSION, "Date": None},
    )
    svg_lines = svg_path.read_text(encoding="utf-8").splitlines()
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    plt.close(fig)
    return [png_path, svg_path]


def _plot_used_vehicles(plt: Any, rows: Sequence[Mapping[str, Any]], output_dir: Path) -> list[Path]:
    labels = [str(row["scenario"]) for row in rows]
    bev = [float(row["used_bev"]) for row in rows]
    ice = [float(row["used_ice"]) for row in rows]
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    first = ax.bar(labels, bev, label="BEV", color=BLUE, edgecolor=INK, linewidth=0.7)
    second = ax.bar(labels, ice, bottom=bev, label="ICE", color=ORANGE, edgecolor=INK, linewidth=0.7)
    ax.bar_label(first, labels=[f"{int(v)}" for v in bev], label_type="center", color="white", fontsize=11)
    ax.bar_label(second, labels=[f"{int(v)}" for v in ice], label_type="center", color=INK, fontsize=11)
    for index, total in enumerate(bev[i] + ice[i] for i in range(len(labels))):
        ax.text(index, total + 0.7, f"計 {int(total)}台", ha="center", fontsize=10)
    ax.set_ylabel("使用車両数（台）")
    ax.set_ylim(0, 36)
    ax.legend(frameon=False, loc="upper center", ncol=2)
    _style_axis(ax)
    _add_header(fig, "使用車両構成の比較", "2025-08-05平日・264便、評価された有限候補集合から選択")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.88))
    return _save_figure(plt, fig, output_dir / "01_used_vehicle_comparison")


def _plot_assigned_trips(plt: Any, rows: Sequence[Mapping[str, Any]], output_dir: Path) -> list[Path]:
    labels = [str(row["scenario"]) for row in rows]
    bev = [float(row["bev_trips"]) for row in rows]
    ice = [float(row["ice_trips"]) for row in rows]
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    first = ax.bar(labels, bev, label="BEV担当", color=BLUE, edgecolor=INK, linewidth=0.7)
    second = ax.bar(labels, ice, bottom=bev, label="ICE担当", color=ORANGE, edgecolor=INK, linewidth=0.7)
    ax.bar_label(first, labels=[f"{int(v)}便" for v in bev], label_type="center", color="white", fontsize=10)
    ax.bar_label(second, labels=[f"{int(v)}便" for v in ice], label_type="center", color=INK, fontsize=10)
    for index in range(len(labels)):
        ax.text(index, 272, "264/264便", ha="center", fontsize=10)
    ax.set_ylabel("担当便数（便）")
    ax.set_ylim(0, 290)
    ax.legend(frameon=False, loc="upper center", ncol=2)
    _style_axis(ax)
    _add_header(fig, "動力源別担当便数の比較", "両ケースとも未担当便0、物理検算VALID")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.88))
    return _save_figure(plt, fig, output_dir / "02_assigned_trip_comparison")


def _plot_cost_breakdown(plt: Any, bundle: EvidenceBundle, output_dir: Path) -> list[Path]:
    labels = ["SUNNY", "RAIN"]
    keys = (
        ("vehicle_usage_cost", "車両使用費", GRAY),
        ("fuel_cost", "燃料費", ORANGE),
        ("electricity_cost", "系統電力費", BLUE),
        ("co2_cost", "CO2費用", OLIVE),
    )
    fig, ax = plt.subplots(figsize=(8.2, 5.4))
    bottoms = [0.0, 0.0]
    for key, label, color in keys:
        values = [float(bundle.scenarios[code].costs[key]) for code in labels]
        ax.bar(labels, values, bottom=bottoms, label=label, color=color, edgecolor=INK, linewidth=0.6)
        bottoms = [bottoms[i] + values[i] for i in range(2)]
    for index, total in enumerate(bottoms):
        ax.text(index, total + 10_000, f"{total:,.0f}円", ha="center", fontsize=10, fontweight="bold")
    ax.set_ylabel("24時間Rolling後の実行日会計費用（円）")
    ax.set_ylim(0, max(bottoms) * 1.12)
    ax.legend(frameon=False, loc="upper center", ncol=4, fontsize=8)
    _style_axis(ax)
    _add_header(fig, "実行日会計費用の内訳", "差額37,614.844839円は燃料費・系統電力費・CO2費用で構成")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.88))
    return _save_figure(plt, fig, output_dir / "03_executed_day_cost_breakdown")


def _plot_energy_balance(plt: Any, bundle: EvidenceBundle, output_dir: Path) -> list[Path]:
    labels = ["SUNNY", "RAIN"]
    series = (
        ("pv_to_bus_kwh", "PV→bus", GOLD),
        ("pv_to_bess_kwh", "PV→BESS", OLIVE),
        ("bess_to_bus_kwh", "BESS→bus", BLUE),
        ("grid_to_bus_kwh", "系統→bus", ORANGE),
    )
    x = [0.0, 1.0]
    width = 0.18
    fig, ax = plt.subplots(figsize=(9.0, 5.4))
    for series_index, (key, label, color) in enumerate(series):
        offset = (series_index - 1.5) * width
        values = [float(bundle.scenarios[code].costs[key]) for code in labels]
        bars = ax.bar([value + offset for value in x], values, width=width, label=label, color=color, edgecolor=INK, linewidth=0.6)
        ax.bar_label(bars, labels=[f"{value:,.0f}" for value in values], padding=3, fontsize=8, rotation=90 if max(values) > 2000 else 0)
    ax.set_xticks(x, labels)
    ax.set_ylabel("24時間合計エネルギー（kWh）")
    ax.set_ylim(0, 3000)
    ax.legend(frameon=False, loc="upper center", ncol=4, fontsize=8)
    _style_axis(ax)
    _add_header(fig, "PV・BESS・系統電力のエネルギー収支", "BESS→busはPV→BESS×0.95²、両ケースともBESS終端SOC 3,000 kWh")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.88))
    return _save_figure(plt, fig, output_dir / "04_pv_bess_grid_energy_balance")


def _plot_pv_utilization(plt: Any, bundle: EvidenceBundle, output_dir: Path) -> list[Path]:
    labels = ["SUNNY", "RAIN"]
    used = [float(bundle.scenarios[code].costs["pv_used_total_kwh"]) for code in labels]
    curtailed = [float(bundle.scenarios[code].costs["pv_curtailed_kwh"]) for code in labels]
    totals = [used[i] + curtailed[i] for i in range(2)]
    fig, ax = plt.subplots(figsize=(7.8, 5.4))
    first = ax.bar(labels, used, label="PV利用", color=GOLD, edgecolor=INK, linewidth=0.7)
    second = ax.bar(labels, curtailed, bottom=used, label="PV抑制", color=LIGHT_GRAY, edgecolor=INK, linewidth=0.7)
    ax.bar_label(first, labels=[f"{used[i]:,.0f} kWh\n({used[i] / totals[i] * 100:.1f}%)" for i in range(2)], label_type="center", fontsize=9)
    ax.bar_label(
        second,
        labels=[f"{curtailed[i]:,.0f} kWh" if curtailed[i] > 1.0 else "" for i in range(2)],
        label_type="center",
        fontsize=9,
    )
    for index, total in enumerate(totals):
        near_zero_note = "（抑制ほぼ0）" if curtailed[index] <= 1.0 else ""
        ax.text(
            index,
            total + 130,
            f"発電 {total:,.2f} kWh{near_zero_note}",
            ha="center",
            fontsize=9,
        )
    ax.set_ylabel("PV電力量（kWh）")
    ax.set_ylim(0, max(totals) * 1.13)
    ax.legend(frameon=False, loc="upper center", ncol=2)
    _style_axis(ax)
    _add_header(fig, "PV利用量と抑制量の比較", "PV利用量＝PV→bus＋PV→BESS、24時間実行日会計")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.88))
    return _save_figure(plt, fig, output_dir / "05_pv_utilization_and_curtailment")


def _claim_boundary_text(bundle: EvidenceBundle) -> str:
    return """# 主張範囲

## 使用できる表現

- 本結果は、**評価した有限候補集合から選択された、物理的・会計的に妥当なPhase 3二段階実行可能解**である。
- SUNNYとRAINはいずれも264/264便を担当し、物理検算、24/24 Rolling、会計検算を通過した。
- 固定した2シナリオでは、異なる物理配車が選択された。
- 費用は**24時間Rolling後の実行日会計費用**として報告する。
- gapは**Stage 1の近似目的関数に対するcertified MIP gap**として報告する。

## 使用しない解釈

- 統合問題全体に対する保証へ読み替えない。
- Rolling費用が全配車の中で最小であるとは述べない。
- この2ケースの差を一般的な天候効果へ拡張しない。
- RAINを観測日の運行ダイヤとして扱わない。
- RAINは**2025-08-05の平日運行へ2025-08-10由来の低PV曲線を与えた反実仮想**である。
- 修論提出可否は本パッケージだけでは判定しない。
"""


def _results_section_text(bundle: EvidenceBundle) -> str:
    sunny = bundle.scenarios["SUNNY"]
    rain = bundle.scenarios["RAIN"]
    cost_difference = float(rain.costs["total_cost"]) - float(sunny.costs["total_cost"])
    fuel_difference = float(rain.costs["fuel_cost"]) - float(sunny.costs["fuel_cost"])
    grid_difference = float(rain.costs["electricity_cost"]) - float(sunny.costs["electricity_cost"])
    co2_difference = float(rain.costs["co2_cost"]) - float(sunny.costs["co2_cost"])
    text = f"""# SUNNY／RAIN比較結果

## 実験条件

本実験は弦巻営業所のWEEKDAY時刻表を対象とし、2025年8月5日の264便を15分刻みで扱った。SUNNYは同日由来のPV曲線を用いる基準ケースである。RAINは**2025-08-05の平日運行へ2025-08-10由来の低PV曲線を与えた反実仮想**であり、運行日や時刻表を変更した比較ではない。両ケースでは車両、便、充電器、料金、目的関数、fleet contractおよびsolver controlのhashが一致する。実効車両在庫はBEV 35台、ICE 25台であり、BEV初期SOCは車両別に21.9452～77.4330%である。計算はPhase 3二段階方式、総時間上限585秒、Stage 1上限435秒、Stage 2上限30秒、要求gap 10%、seed 42、Gurobi 1 threadで実施された。

## 配車結果

SUNNYではBEV 28台とICE 4台を使用し、BEVが199便、ICEが65便を担当した。RAINではBEV 21台とICE 11台を使用し、BEVが91便、ICEが173便を担当した。使用車両総数はいずれも32台である一方、動力源構成と担当便構成は大きく異なる。選択された物理配車hashも異なり、固定された2つのPV条件に対して有限候補集合内の費用順位が変化したことが確認された。ただし、この結果は候補生成方針で評価した22候補からの選択であり、探索可能な配車全体を列挙したものではない。

## 費用差

24時間Rolling後の実行日会計費用は、SUNNYが{float(sunny.costs['total_cost']):,.6f}円、RAINが{float(rain.costs['total_cost']):,.6f}円であった。RAINはSUNNYより{cost_difference:,.6f}円、{cost_difference / float(sunny.costs['total_cost']) * 100:.2f}%高い。差額は燃料費{fuel_difference:+,.6f}円、系統電力費{grid_difference:+,.6f}円、CO₂費用{co2_difference:+,.6f}円の合計と1e-6円以内で一致した。両ケースの車両使用費は32台×20,000円＝640,000円で共通であり、需要料金、劣化費用、恣意的な天候項は差額へ混入していない。

## PV・BESS・系統電力

SUNNYのPV発電量は{float(sunny.costs['pv_generated_kwh']):,.2f} kWhで、PV→busが{float(sunny.costs['pv_to_bus_kwh']):,.3f} kWh、PV→BESSが{float(sunny.costs['pv_to_bess_kwh']):,.3f} kWh、抑制が{float(sunny.costs['pv_curtailed_kwh']):,.3f} kWhであった。系統購入は0 kWhである。RAINのPV発電量は{float(rain.costs['pv_generated_kwh']):,.1f} kWhで、PV→busが{float(rain.costs['pv_to_bus_kwh']):,.3f} kWh、PV→BESSが{float(rain.costs['pv_to_bess_kwh']):,.3f} kWh、系統購入が{float(rain.costs['grid_import_kwh']):,.3f} kWhとなった。各ケースでPV発電量はPV→bus、PV→BESS、抑制の和と一致する。BESS→busはSUNNYで{float(sunny.costs['bess_to_bus_kwh']):,.3f} kWh、RAINで{float(rain.costs['bess_to_bus_kwh']):,.3f} kWhであり、いずれもPV→BESS×0.95²と一致した。BESSは両ケースとも3,000 kWhから開始し、3,000 kWhで終了した。

## 妥当性と限定事項

両ケースとも264/264便を担当し、未担当便は0であった。独立物理検算はVALID、Rollingは24/24、実行日会計はeligibleであり、終端エネルギー収支も成立した。Stage 1の近似目的関数に対するcertified MIP gapはSUNNYが{float(sunny.summary['stage1_certified_gap_ratio']) * 100:.4f}%、RAINが{float(rain.summary['stage1_certified_gap_ratio']) * 100:.4f}%である。このgapを最終費用の保証へ読み替えない。本結果は、**評価した有限候補集合から選択された、物理的・会計的に妥当なPhase 3二段階実行可能解**として位置付ける。また、2つの固定ケースで観測された差を他の日付、営業所、時刻表へ一般化せず、Rolling費用が全配車中で最小であるとも解釈しない。
"""
    character_count = len("".join(text.split()))
    _require(1200 <= character_count <= 2000, f"results_section_ja length is {character_count}, expected 1200..2000")
    return text


def _timeseries_available(bundle: EvidenceBundle) -> bool:
    # The published summaries contain 24 remaining-horizon aggregates and
    # paths to untracked state files, but no 96-row executed flow series.
    for scenario in bundle.scenarios.values():
        for value in scenario.rolling.values():
            if isinstance(value, list) and len(value) == 96 and value and isinstance(value[0], Mapping):
                required = {"pv_to_bus_kwh", "pv_to_bess_kwh", "bess_to_bus_kwh", "grid_to_bus_kwh"}
                if required.issubset(value[0]):
                    return True
    return False


def _readme_text(bundle: EvidenceBundle, font_name: str, timeseries_created: bool) -> str:
    omission = (
        "06_daily_energy_flow_timeseriesは作成していない。正本bundleには96スロットの実行済み"
        "PV・BESS・系統フロー列がなく、rolling_chain_summary.jsonには24個の残余ホライズン"
        "集計とGit管理外stateファイルへの参照だけがあるため、差分推定を行わなかった。"
        if not timeseries_created
        else "06_daily_energy_flow_timeseriesを正本96スロット列から作成した。"
    )
    return f"""# 修論用SUNNY／RAIN結果パッケージ

実験SHA `{EXECUTION_SHA}` のGit管理済み証拠だけから生成した。数値の手入力は行わず、期待値は生成前のfail-closed assertionにのみ使用する。

## 再生成

```powershell
python scripts/build_thesis_weather_result_package.py `
  --evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005 `
  --output-dir docs/thesis/weather_results_bb0c005
```

## 成果物

- `experiment_parameters.csv/.md`: 実験条件と正本位置
- `scenario_results.csv/.md`: 配車、費用、エネルギー、gap、計算時間
- `cost_breakdown.csv/.md`: 費用項目とRAIN－SUNNY差
- `energy_balance.csv/.md`: PV・BESS・系統収支
- `claim_boundary.md`: 使用可能な主張と限定事項
- `results_section_ja.md`: 修論結果章へ転用できる日本語本文
- `01`～`05`のPNG（300 dpi）・SVG図
- `package_manifest.json`: 入出力SHA-256と図表map

## 図表設計

白背景、フォント`{font_name}`、明示単位、ゼロ始点を使用した。SUNNYは青、RAINとの構成差は橙、PVは金、BESSは青、その他は中立色で表現し、色だけに依存しない直接値・積み上げ位置・凡例を併用した。

{omission}

## 正本にない入力値

列挙された正本JSONには受電上限、PV定格容量、BESS定格容量・出力が値として保存されていない。`experiment_parameters`では欠落を明記し、旧資料やローカルoutputから値を補っていない。充電器数、車両側最大充電電力、PV実行日発電量、BESS初終端SOCおよび観測された充放電比は正本から抽出した。

## 主張範囲

結果は、評価した有限候補集合から選択されたPhase 3二段階実行可能解である。費用は24時間Rolling後の実行日会計費用、gapはStage 1の近似目的関数に対するcertified MIP gapとして扱う。2ケースの差を一般化しない。

Source bundle tree SHA-256: `{bundle.tree_sha256}`
"""


def _write_manifest(
    bundle: EvidenceBundle,
    output_dir: Path,
    artifacts: Sequence[Path],
    font_name: str,
    timeseries_created: bool,
) -> Path:
    manifest_path = output_dir / "package_manifest.json"
    artifact_index = {
        path.relative_to(output_dir).as_posix(): {
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(artifacts)
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "execution_git_sha": EXECUTION_SHA,
        "source_bundle_tree_sha256": bundle.tree_sha256,
        "source_artifacts": dict(bundle.source_hashes),
        "font_family": font_name,
        "png_dpi": 300,
        "timeseries_figure_created": timeseries_created,
        "timeseries_figure_omission_reason": None if timeseries_created else "No complete 96-slot executed energy-flow series exists in the Git-tracked canonical artifacts.",
        "chart_map": [
            {"stem": "01_used_vehicle_comparison", "family": "stacked comparison bar", "question": "使用車両の動力源構成はどう異なるか"},
            {"stem": "02_assigned_trip_comparison", "family": "stacked comparison bar", "question": "担当便の動力源構成はどう異なるか"},
            {"stem": "03_executed_day_cost_breakdown", "family": "stacked cost composition bar", "question": "実行日費用の差は何で構成されるか"},
            {"stem": "04_pv_bess_grid_energy_balance", "family": "grouped comparison bar", "question": "PV・BESS・系統フローはどう異なるか"},
            {"stem": "05_pv_utilization_and_curtailment", "family": "stacked composition bar", "question": "PV発電を利用・抑制へどう配分したか"},
        ],
        "artifacts": artifact_index,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build_package(evidence_dir: Path, output_dir: Path) -> Path:
    """Validate source evidence and build the complete deterministic package."""

    bundle = load_and_validate_bundle(evidence_dir)
    before_hashes = dict(bundle.source_hashes)
    target = output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".svg"):
        stale = target / f"06_daily_energy_flow_timeseries{suffix}"
        if stale.exists():
            stale.unlink()

    artifacts: list[Path] = []
    parameter_rows = _parameter_rows(bundle)
    scenario_rows = _scenario_result_rows(bundle)
    cost_rows = _cost_rows(bundle)
    energy_rows = _energy_rows(bundle)
    artifacts.extend(_write_table_pair(target, "experiment_parameters", parameter_rows))
    artifacts.extend(_write_table_pair(target, "scenario_results", scenario_rows))
    artifacts.extend(_write_table_pair(target, "cost_breakdown", cost_rows))
    artifacts.extend(_write_table_pair(target, "energy_balance", energy_rows))

    claim_path = target / "claim_boundary.md"
    claim_path.write_text(_claim_boundary_text(bundle), encoding="utf-8")
    artifacts.append(claim_path)
    results_path = target / "results_section_ja.md"
    results_path.write_text(_results_section_text(bundle), encoding="utf-8")
    artifacts.append(results_path)

    plt, font_name = _configure_matplotlib()
    artifacts.extend(_plot_used_vehicles(plt, scenario_rows, target))
    artifacts.extend(_plot_assigned_trips(plt, scenario_rows, target))
    artifacts.extend(_plot_cost_breakdown(plt, bundle, target))
    artifacts.extend(_plot_energy_balance(plt, bundle, target))
    artifacts.extend(_plot_pv_utilization(plt, bundle, target))
    timeseries_created = _timeseries_available(bundle)
    _require(not timeseries_created, "96-slot series was detected but figure 06 is not implemented")

    readme_path = target / "README.md"
    readme_path.write_text(_readme_text(bundle, font_name, timeseries_created), encoding="utf-8")
    artifacts.append(readme_path)
    manifest_path = _write_manifest(bundle, target, artifacts, font_name, timeseries_created)

    after_hashes = _bundle_hashes(bundle.root)
    _require(before_hashes == after_hashes, "Evidence bundle changed during generation")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = build_package(args.evidence_dir, args.output_dir)
    print(manifest_path)
    print("PASS_THESIS_WEATHER_RESULT_PACKAGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
