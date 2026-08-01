from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.optimization.common.powertrain_economics import (
    audit_candidate_powertrain_diversity,
    audit_powertrain_marginal_costs,
)


DEFAULT_BEV_CHARGE_EFFICIENCY = 0.95


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether a sunny/rainy flat-tariff pair genuinely explores "
            "BEV/ICE fleet composition and whether BEV use is economically "
            "favoured by the supplied marginal-cost inputs."
        )
    )
    parser.add_argument("sunny_run", type=Path)
    parser.add_argument("rainy_run", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/powertrain_pair_audit"),
    )
    args = parser.parse_args()

    sunny = audit_run(args.sunny_run, role="sunny")
    rainy = audit_run(args.rainy_run, role="rainy")
    pair = build_pair_audit(sunny, rainy)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "powertrain_pair_audit.json"
    md_path = args.output_dir / "powertrain_pair_audit.md"
    json_path.write_text(
        json.dumps(pair, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(pair), encoding="utf-8")

    print(json_path)
    print(md_path)
    return 2 if pair["release_blocked"] else 0


def audit_run(run_dir: Path, *, role: str) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    required = [
        "kpi_summary.json",
        "simulation_conditions_tou_prices.csv",
        "simulation_conditions_vehicle_costs.csv",
        "stage1_stage2_candidate_evaluation.csv",
        "scenario_input_snapshot.json",
        "code_provenance.json",
    ]
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{run_dir}: missing required artifacts: {', '.join(missing)}"
        )

    kpi = _load_json(run_dir / "kpi_summary.json")
    code_provenance = _load_json(run_dir / "code_provenance.json")
    snapshot = _load_json(run_dir / "scenario_input_snapshot.json")
    price_rows = _read_csv(run_dir / "simulation_conditions_tou_prices.csv")
    vehicle_rows = _read_csv(run_dir / "simulation_conditions_vehicle_costs.csv")
    candidate_rows = _read_csv(run_dir / "stage1_stage2_candidate_evaluation.csv")

    electricity_prices = sorted(
        {
            _float(row.get("grid_energy_price_yen_per_kwh"))
            for row in price_rows
        }
    )
    demand_weights = sorted(
        {_float(row.get("demand_charge_weight")) for row in price_rows}
    )
    grid_co2_factors = sorted(
        {_float(row.get("grid_co2_factor_kg_per_kwh")) for row in price_rows}
    )
    if len(electricity_prices) != 1:
        raise ValueError(
            f"{run_dir}: expected one flat electricity price, got {electricity_prices}"
        )

    persisted = _persisted_scenario(snapshot)
    active_parameters = _active_vehicle_parameters(snapshot)
    bev_energy = _first_numeric(
        row.get("energy_consumption_kwh_per_km")
        for row in active_parameters
        if str(row.get("powertrain") or row.get("vehicle_type") or "").upper()
        == "BEV"
    )
    ice_fuel = _first_numeric(
        row.get("fuel_consumption_l_per_km")
        for row in active_parameters
        if str(row.get("powertrain") or row.get("vehicle_type") or "").upper()
        == "ICE"
    )
    if bev_energy is None or ice_fuel is None:
        bev_energy, ice_fuel = _fallback_vehicle_consumption(persisted)

    diesel_price = _first_numeric(
        _float_or_none(row.get("fuel_cost_coeff_yen_per_liter"))
        for row in vehicle_rows
        if str(row.get("vehicle_type") or "").upper() == "ICE"
    )
    ice_co2 = _first_numeric(
        _float_or_none(row.get("co2_emission_coeff_kg_per_liter"))
        for row in vehicle_rows
        if str(row.get("vehicle_type") or "").upper() == "ICE"
    )
    if diesel_price is None:
        raise ValueError(f"{run_dir}: ICE fuel price was not found")

    co2_price = _nested_first_numeric(
        persisted,
        (
            ("scenario_overlay", "cost_coefficients", "co2_price_per_kg"),
            ("simulation_config", "co2_price_per_kg"),
        ),
        default=0.0,
    )
    charge_efficiency = _nested_first_numeric(
        persisted,
        (
            ("simulation_config", "bev_charge_efficiency"),
            ("scenario_overlay", "charging_constraints", "charge_efficiency"),
        ),
        default=DEFAULT_BEV_CHARGE_EFFICIENCY,
    )
    grid_co2 = grid_co2_factors[0] if len(grid_co2_factors) == 1 else 0.0

    economics = audit_powertrain_marginal_costs(
        electricity_price_jpy_per_kwh=electricity_prices[0],
        bev_energy_kwh_per_km=bev_energy,
        bev_charge_efficiency=charge_efficiency,
        diesel_price_jpy_per_litre=diesel_price,
        ice_fuel_litre_per_km=ice_fuel,
        ice_co2_kg_per_litre=ice_co2 or 0.0,
        grid_co2_kg_per_kwh=grid_co2,
        co2_price_jpy_per_kg=co2_price,
    )
    diversity = audit_candidate_powertrain_diversity(candidate_rows)

    objective_matches = bool(kpi.get("solver_objective_matches_accounting_total"))
    objective_is_actual_cost = bool(kpi.get("objective_is_actual_cost"))
    used_vehicle_count = _optional_int(kpi.get("used_vehicle_count")) or 0
    usage_cost = _float_or_none(kpi.get("vehicle_usage_cost_jpy")) or 0.0
    usage_cost_per_vehicle = usage_cost / used_vehicle_count if used_vehicle_count else 0.0

    blockers: list[str] = []
    if diversity["powertrain_fleet_count_frozen"]:
        blockers.append("candidate_powertrain_fleet_count_frozen")
    if not objective_matches:
        blockers.append("solver_accounting_objective_mismatch")
    if not objective_is_actual_cost:
        blockers.append("objective_is_not_actual_cost")

    return {
        "role": role,
        "run_dir": str(run_dir),
        "git_sha": code_provenance.get("git_sha"),
        "git_dirty": code_provenance.get("git_dirty"),
        "flat_electricity_prices_jpy_per_kwh": electricity_prices,
        "demand_charge_weights": demand_weights,
        "economics": economics.to_dict(),
        "candidate_diversity": diversity,
        "kpi": {
            key: kpi.get(key)
            for key in (
                "total_cost_jpy",
                "objective_value_jpy",
                "objective_is_actual_cost",
                "solver_objective_matches_accounting_total",
                "electricity_cost_jpy",
                "fuel_cost_jpy",
                "vehicle_usage_cost_jpy",
                "used_vehicle_count",
                "bev_trip_count",
                "ice_trip_count",
                "grid_import_total_kwh",
                "pv_generated_kwh",
                "total_co2_kg",
            )
        },
        "vehicle_usage_cost_jpy_per_used_vehicle_inferred": usage_cost_per_vehicle,
        "release_blockers": blockers,
        "release_blocked": bool(blockers),
    }


def build_pair_audit(sunny: Mapping[str, Any], rainy: Mapping[str, Any]) -> dict[str, Any]:
    blockers = sorted(
        set(sunny.get("release_blockers", ()))
        | set(rainy.get("release_blockers", ()))
    )
    sunny_kpi = dict(sunny.get("kpi") or {})
    rainy_kpi = dict(rainy.get("kpi") or {})
    same_used_composition = (
        (sunny.get("candidate_diversity") or {}).get("used_powertrain_compositions")
        == (rainy.get("candidate_diversity") or {}).get("used_powertrain_compositions")
    )
    same_selected_trip_split = (
        sunny_kpi.get("bev_trip_count") == rainy_kpi.get("bev_trip_count")
        and sunny_kpi.get("ice_trip_count") == rainy_kpi.get("ice_trip_count")
    )
    return {
        "schema_version": "powertrain_pair_audit_v1",
        "sunny": sunny,
        "rainy": rainy,
        "pair": {
            "same_candidate_used_powertrain_compositions": same_used_composition,
            "same_selected_trip_powertrain_split": same_selected_trip_split,
            "delta_total_cost_jpy": _difference(
                rainy_kpi.get("total_cost_jpy"), sunny_kpi.get("total_cost_jpy")
            ),
            "delta_grid_import_kwh": _difference(
                rainy_kpi.get("grid_import_total_kwh"),
                sunny_kpi.get("grid_import_total_kwh"),
            ),
            "delta_bev_trip_count": _difference(
                rainy_kpi.get("bev_trip_count"), sunny_kpi.get("bev_trip_count")
            ),
        },
        "release_blockers": blockers,
        "release_blocked": bool(blockers),
        "required_model_changes": [
            "Add one used[v,day] activation binary and charge vehicle-day cost once in Stage 1.",
            "Include assignment-linked BEV energy recourse or a certified lower-bound approximation in Stage 1.",
            "Generate count-changing candidates by constraining used-BEV count above and below the incumbent.",
            "Require at least two feasible used-BEV/used-ICE compositions before claiming endogenous fleet choice.",
            "Block research release when solver objective and canonical accounting total do not match.",
            "Use an explicit carbon/externality scenario rather than a hidden BEV preference coefficient.",
        ],
    }


def render_markdown(audit: Mapping[str, Any]) -> str:
    sunny = dict(audit["sunny"])
    rainy = dict(audit["rainy"])
    sunny_e = dict(sunny["economics"])
    rainy_e = dict(rainy["economics"])
    pair = dict(audit["pair"])

    lines = [
        "# Flat-tariff BEV/ICE pair audit",
        "",
        f"**Release status:** {'BLOCKED' if audit['release_blocked'] else 'PASS'}",
        "",
        "## Marginal economics",
        "",
        "| Metric | Sunny | Rainy |",
        "|---|---:|---:|",
        f"| Grid electricity price [JPY/kWh] | {sunny_e['electricity_price_jpy_per_kwh']:.3f} | {rainy_e['electricity_price_jpy_per_kwh']:.3f} |",
        f"| BEV grid cost [JPY/km] | {sunny_e['bev_total_marginal_cost_jpy_per_km']:.3f} | {rainy_e['bev_total_marginal_cost_jpy_per_km']:.3f} |",
        f"| ICE cost [JPY/km] | {sunny_e['ice_total_marginal_cost_jpy_per_km']:.3f} | {rainy_e['ice_total_marginal_cost_jpy_per_km']:.3f} |",
        f"| Break-even electricity price [JPY/kWh] | {sunny_e['break_even_electricity_price_jpy_per_kwh']:.3f} | {rainy_e['break_even_electricity_price_jpy_per_kwh']:.3f} |",
        "",
        "At the supplied flat tariff, grid-powered BEV operation is not automatically cheaper than ICE operation. "
        "Removing the demand charge changes peak-power economics, not this per-kilometre comparison.",
        "",
        "## Candidate search coverage",
        "",
        "| Metric | Sunny | Rainy |",
        "|---|---:|---:|",
        f"| Candidate rows | {sunny['candidate_diversity']['candidate_row_count']} | {rainy['candidate_diversity']['candidate_row_count']} |",
        f"| Distinct used-BEV/used-ICE compositions | {sunny['candidate_diversity']['distinct_used_powertrain_composition_count']} | {rainy['candidate_diversity']['distinct_used_powertrain_composition_count']} |",
        f"| Fleet count frozen | {sunny['candidate_diversity']['powertrain_fleet_count_frozen']} | {rainy['candidate_diversity']['powertrain_fleet_count_frozen']} |",
        "",
        "Trip-level powertrain swaps do not verify fleet-composition optimisation when every candidate uses the same BEV/ICE counts.",
        "",
        "## Pair deltas",
        "",
        f"- Total cost: {pair['delta_total_cost_jpy']:+.3f} JPY (rainy - sunny)",
        f"- Grid import: {pair['delta_grid_import_kwh']:+.3f} kWh",
        f"- BEV trips: {pair['delta_bev_trip_count']:+.0f}",
        "",
        "## Release blockers",
        "",
    ]
    lines.extend(f"- `{item}`" for item in audit["release_blockers"])
    lines.extend(["", "## Required model changes", ""])
    lines.extend(f"1. {item}" for item in audit["required_model_changes"])
    lines.append("")
    return "\n".join(lines)


def _persisted_scenario(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    value = snapshot.get("persisted_scenario")
    if isinstance(value, Mapping):
        return value
    return snapshot


def _active_vehicle_parameters(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    effective = snapshot.get("effective_configuration")
    if not isinstance(effective, Mapping):
        return []
    simulation = effective.get("simulation_config")
    if not isinstance(simulation, Mapping):
        return []
    contract = simulation.get("scenario_fleet_contract")
    if not isinstance(contract, Mapping):
        return []
    rows = contract.get("active_vehicle_parameters")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _fallback_vehicle_consumption(
    persisted: Mapping[str, Any],
) -> tuple[float, float]:
    vehicles = persisted.get("vehicles")
    if not isinstance(vehicles, list):
        raise ValueError("scenario does not contain vehicle parameters")
    bev_energy: float | None = None
    ice_fuel: float | None = None
    for row in vehicles:
        if not isinstance(row, Mapping):
            continue
        powertrain = str(row.get("vehicleType") or row.get("type") or "").upper()
        if powertrain == "BEV" and bev_energy is None:
            bev_energy = _float_or_none(row.get("energyConsumption"))
        if powertrain == "ICE" and ice_fuel is None:
            efficiency = _float_or_none(row.get("fuelEfficiencyKmPerL"))
            if efficiency and efficiency > 0.0:
                ice_fuel = 1.0 / efficiency
    if bev_energy is None or ice_fuel is None:
        raise ValueError("BEV/ICE consumption parameters were not found")
    return bev_energy, ice_fuel


def _nested_first_numeric(
    mapping: Mapping[str, Any],
    paths: Iterable[tuple[str, ...]],
    *,
    default: float,
) -> float:
    for path in paths:
        current: Any = mapping
        for part in path:
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        parsed = _float_or_none(current)
        if parsed is not None:
            return parsed
    return default


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _first_numeric(values: Iterable[Any]) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _float(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        raise ValueError(f"expected numeric value, got {value!r}")
    return parsed


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def _difference(a: Any, b: Any) -> float:
    return (_float_or_none(a) or 0.0) - (_float_or_none(b) or 0.0)


if __name__ == "__main__":
    raise SystemExit(main())
