from __future__ import annotations

from typing import Any, Dict

from src.optimization.common.energy_flow_accounting import normalize_pv_energy_breakdown


def canonical_cost_breakdown_json(*, problem, engine_result, scenario_id: str) -> Dict[str, Any]:
    breakdown = dict(engine_result.cost_breakdown or {})
    breakdown.update(normalize_pv_energy_breakdown(breakdown))
    grid_energy_cost = float(breakdown.get("grid_purchase_cost", 0.0) or 0.0)
    pv_self_consumption_cost = float(breakdown.get("pv_self_consumption_cost_jpy", 0.0) or 0.0)
    pv_marginal_charge_cost = float(
        breakdown.get(
            "pv_marginal_charge_cost_yen_per_kwh",
            getattr(problem, "metadata", {}).get("pv_marginal_charge_cost_yen_per_kwh", 0.0),
        )
        or 0.0
    )
    pv_curtail_penalty = float(
        breakdown.get(
            "pv_curtail_penalty_yen_per_kwh",
            getattr(problem, "metadata", {}).get("pv_curtail_penalty_yen_per_kwh", 0.0),
        )
        or 0.0
    )
    pv_curtail_cost = float(breakdown.get("pv_curtail_cost_jpy", 0.0) or 0.0)
    bess_discharge_cost = float(breakdown.get("bess_discharge_cost", 0.0) or 0.0)
    electricity_energy_cost = (
        grid_energy_cost
        + pv_self_consumption_cost
        + bess_discharge_cost
        + pv_curtail_cost
    )
    gross_cost = float(
        breakdown.get("total_cost")
        if breakdown.get("total_cost") is not None
        else engine_result.objective_value
        or 0.0
    )
    return {
        "scenario_id": scenario_id,
        "currency": "JPY",
        "total_cost": gross_cost,
        "gross_cost_jpy": gross_cost,
        "components": {
            "grid_energy_cost_jpy": grid_energy_cost,
            "pv_self_consumption_cost_jpy": pv_self_consumption_cost,
            "pv_marginal_charge_cost_yen_per_kwh": pv_marginal_charge_cost,
            "pv_curtail_penalty_yen_per_kwh": pv_curtail_penalty,
            "pv_curtail_cost_jpy": pv_curtail_cost,
            "bess_discharge_cost_jpy": bess_discharge_cost,
            "electricity_energy_cost": float(
                breakdown.get("electricity_cost", breakdown.get("electricity_cost_final", electricity_energy_cost))
                or electricity_energy_cost
            ),
            "electricity_total_cost_jpy": electricity_energy_cost,
            "propulsion_energy_cost": float(breakdown.get("energy_cost", 0.0) or 0.0),
            "fuel_cost_final": float(breakdown.get("fuel_cost_final", breakdown.get("fuel_cost", 0.0)) or 0.0),
            "fuel_cost_provisional": float(breakdown.get("fuel_cost_provisional", breakdown.get("provisional_ice_drive_cost", 0.0)) or 0.0),
            "fuel_cost_refueled": float(breakdown.get("fuel_cost_refueled", breakdown.get("realized_ice_refuel_cost", 0.0)) or 0.0),
            "fuel_cost_provisional_leftover": float(breakdown.get("fuel_cost_provisional_leftover", breakdown.get("leftover_ice_provisional_cost", 0.0)) or 0.0),
            "demand_charge_cost": float(breakdown.get("demand_cost", 0.0) or 0.0),
            "contract_overage_cost_jpy": float(breakdown.get("contract_overage_cost", 0.0) or 0.0),
            "diesel_cost": float(breakdown.get("fuel_cost", 0.0) or 0.0),
            "vehicle_fixed_cost": float(breakdown.get("vehicle_cost", 0.0) or 0.0),
            "vehicle_usage_cost_jpy": float(
                breakdown.get("vehicle_usage_cost", breakdown.get("vehicle_usage_cost_jpy", 0.0))
                or 0.0
            ),
            "vehicle_usage_cost_jpy_per_used_bus": float(
                breakdown.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0
            ),
            "used_vehicle_day_count": int(breakdown.get("used_vehicle_day_count", 0) or 0),
            "driver_cost": float(breakdown.get("driver_cost", 0.0) or 0.0),
            "co2_cost": float(breakdown.get("co2_cost", 0.0) or 0.0),
            "battery_degradation_cost": float(breakdown.get("degradation_cost", 0.0) or 0.0),
            "charger_operation_cost": 0.0,
            "pv_capex_daily_equivalent": float(breakdown.get("pv_asset_cost", 0.0) or 0.0),
            "ess_cost": float(breakdown.get("bess_asset_cost", 0.0) or 0.0),
            "unserved_trip_penalty": float(breakdown.get("unserved_penalty", 0.0) or 0.0),
            "return_leg_bonus": float(breakdown.get("return_leg_bonus", 0.0) or 0.0),
            "weather_strategy_objective_term_jpy_equivalent": float(
                breakdown.get("weather_strategy_objective_term_jpy_equivalent", 0.0) or 0.0
            ),
            "fuel_cost_final_source": str(breakdown.get("fuel_cost_final_source", "provisional_distance_based") or "provisional_distance_based"),
            "energy_cost_basis": str(
                breakdown.get("energy_cost_basis")
                or "realized_supply_plus_inventory_valuation"
            ),
            "energy_cash_purchase_cost_jpy": float(
                breakdown.get("energy_cash_purchase_cost_jpy", 0.0) or 0.0
            ),
            "energy_inventory_valuation_cost_jpy": float(
                breakdown.get("energy_inventory_valuation_cost_jpy", 0.0) or 0.0
            ),
            "ev_unreplenished_drive_energy_kwh": float(
                breakdown.get("ev_unreplenished_drive_energy_kwh", 0.0) or 0.0
            ),
            "ev_energy_inventory_balanced": bool(
                breakdown.get("ev_energy_inventory_balanced", False)
            ),
            "objective_is_actual_cost": bool(breakdown.get("objective_is_actual_cost", False)),
        },
        "meta": {
            "objective_mode": str((engine_result.solver_metadata or {}).get("objective_mode") or problem.scenario.objective_mode or "total_cost"),
            "solver_mode": str(getattr(getattr(engine_result, "mode", None), "value", "") or ""),
            "includes_pv": bool(problem.depot_energy_assets),
            "pv_marginal_charge_cost_yen_per_kwh": pv_marginal_charge_cost,
            "pv_curtail_penalty_yen_per_kwh": pv_curtail_penalty,
        },
    }


def cost_breakdown(
    result_payload: Dict[str, Any], sim_payload: Dict[str, Any] | None
) -> Dict[str, float]:
    obj_breakdown = dict(result_payload.get("obj_breakdown") or {})
    obj_breakdown.update(normalize_pv_energy_breakdown(obj_breakdown))
    sim_values = dict(sim_payload or {})

    def first_float(*values: Any, default: float = 0.0) -> float:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return float(default)

    explicit_fuel_cost = (
        obj_breakdown.get("fuel_cost")
        if obj_breakdown.get("fuel_cost") is not None
        else obj_breakdown.get("total_fuel_cost")
    )
    fuel_cost_provisional = first_float(
        sim_values.get("fuel_cost_provisional_jpy"),
        obj_breakdown.get("fuel_cost_provisional"),
        obj_breakdown.get("provisional_ice_drive_cost"),
    )
    fuel_cost_refueled = first_float(
        sim_values.get("fuel_cost_refueled_jpy"),
        sim_values.get("fuel_cost_realized_jpy"),
        obj_breakdown.get("fuel_cost_refueled"),
        obj_breakdown.get("fuel_cost_realized"),
        obj_breakdown.get("realized_ice_refuel_cost"),
    )
    fuel_cost_leftover = first_float(
        sim_values.get("fuel_cost_provisional_leftover_jpy"),
        obj_breakdown.get("fuel_cost_provisional_leftover"),
        obj_breakdown.get("leftover_ice_provisional_cost"),
    )
    fuel_cost = first_float(
        sim_values.get("total_fuel_cost"),
        sim_values.get("fuel_cost_final_jpy"),
        explicit_fuel_cost,
        obj_breakdown.get("fuel_cost_final"),
        fuel_cost_refueled + fuel_cost_leftover,
    )
    total_cost_value = (
        sim_values.get("total_operating_cost")
        if sim_values.get("total_operating_cost") is not None
        else obj_breakdown.get("total_cost")
    )
    provisional_energy = float(
        sim_values.get("electricity_cost_provisional_jpy", 0.0)
        or 0.0
    )
    charged_energy = float(
        sim_values.get("electricity_cost_charged_jpy", 0.0)
        or 0.0
    )
    aggregate_energy_source = float(obj_breakdown.get("energy_cost", 0.0) or 0.0)
    if sim_values.get("total_energy_cost") is not None:
        final_energy_cost = float(sim_values.get("total_energy_cost") or 0.0)
    elif obj_breakdown.get("electricity_cost") is not None:
        final_energy_cost = float(obj_breakdown.get("electricity_cost") or 0.0)
    elif obj_breakdown.get("electricity_cost_final") is not None:
        final_energy_cost = float(obj_breakdown.get("electricity_cost_final") or 0.0)
    elif explicit_fuel_cost is not None:
        final_energy_cost = max(aggregate_energy_source - fuel_cost, 0.0)
    else:
        final_energy_cost = float(aggregate_energy_source or charged_energy or 0.0)
    provisional_leftover = float(
        (sim_payload or {}).get("electricity_cost_provisional_leftover_jpy", 0.0)
        or obj_breakdown.get("electricity_cost_provisional_leftover")
        or max(provisional_energy - final_energy_cost, 0.0)
    )
    ice_co2_kg = first_float(
        obj_breakdown.get("ice_co2_kg"),
        obj_breakdown.get("ice_bus_co2_kg"),
        obj_breakdown.get("engine_bus_co2_kg"),
    )
    grid_electricity_co2_kg = first_float(
        obj_breakdown.get("grid_electricity_co2_kg"),
        obj_breakdown.get("power_generation_co2_kg"),
    )
    pv_operational_co2_kg = first_float(
        obj_breakdown.get("pv_operational_co2_kg"),
        obj_breakdown.get("pv_co2_kg"),
    )
    bess_storage_operational_co2_kg = first_float(
        obj_breakdown.get("bess_storage_operational_co2_kg"),
    )
    component_co2_kg = (
        ice_co2_kg
        + grid_electricity_co2_kg
        + pv_operational_co2_kg
        + bess_storage_operational_co2_kg
    )
    reported_co2_kg = first_float(
        (sim_payload or {}).get("total_co2_kg"),
        obj_breakdown.get("total_co2_kg"),
        default=component_co2_kg,
    )
    aggregate_energy_cost = final_energy_cost + fuel_cost
    return {
        "energy_cost": aggregate_energy_cost,
        "electricity_cost": final_energy_cost,
        "electricity_cost_final": final_energy_cost,
        "electricity_cost_provisional": provisional_energy,
        "electricity_cost_charged": charged_energy,
        "electricity_cost_provisional_leftover": provisional_leftover,
        "demand_charge": float(
            (sim_payload or {}).get("total_demand_charge", obj_breakdown.get("demand_charge_cost", 0.0))
            or obj_breakdown.get("demand_cost", 0.0)
            or 0.0
        ),
        "total_demand_charge": float(
            (sim_payload or {}).get("total_demand_charge", obj_breakdown.get("demand_charge_cost", 0.0))
            or obj_breakdown.get("demand_cost", 0.0)
            or 0.0
        ),
        "vehicle_cost": float(
            (sim_payload or {}).get("total_vehicle_fixed_cost", obj_breakdown.get("vehicle_cost", 0.0))
            or 0.0
        ),
        "vehicle_usage_cost": float(
            obj_breakdown.get("vehicle_usage_cost", obj_breakdown.get("vehicle_usage_cost_jpy", 0.0))
            or 0.0
        ),
        "vehicle_usage_cost_jpy": float(
            obj_breakdown.get("vehicle_usage_cost", obj_breakdown.get("vehicle_usage_cost_jpy", 0.0))
            or 0.0
        ),
        "vehicle_usage_cost_jpy_per_used_bus": float(
            obj_breakdown.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0
        ),
        "used_vehicle_day_count": int(obj_breakdown.get("used_vehicle_day_count", 0) or 0),
        "driver_cost": float(
            (sim_payload or {}).get("total_driver_cost", obj_breakdown.get("driver_cost", 0.0))
            or 0.0
        ),
        "deadhead_cost": float(obj_breakdown.get("deadhead_cost", 0.0) or 0.0),
        "fuel_cost": fuel_cost,
        "fuel_cost_final": fuel_cost,
        "fuel_cost_provisional": fuel_cost_provisional,
        "fuel_cost_refueled": fuel_cost_refueled,
        "fuel_cost_realized": fuel_cost_refueled,
        "fuel_cost_provisional_leftover": fuel_cost_leftover,
        "total_fuel_cost": fuel_cost,
        "battery_degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "total_degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "grid_purchase_cost": float(obj_breakdown.get("grid_purchase_cost", 0.0) or 0.0),
        "pv_self_consumption_cost_jpy": float(
            obj_breakdown.get("pv_self_consumption_cost_jpy", 0.0) or 0.0
        ),
        "pv_marginal_charge_cost_yen_per_kwh": float(
            obj_breakdown.get("pv_marginal_charge_cost_yen_per_kwh", 0.0) or 0.0
        ),
        "pv_curtail_cost_jpy": float(
            obj_breakdown.get("pv_curtail_cost_jpy", 0.0) or 0.0
        ),
        "bess_discharge_cost": float(obj_breakdown.get("bess_discharge_cost", 0.0) or 0.0),
        "grid_import_kwh": float(obj_breakdown.get("grid_import_kwh", 0.0) or 0.0),
        "peak_grid_kw": float(obj_breakdown.get("peak_grid_kw", 0.0) or 0.0),
        "grid_to_bus_kwh": float(obj_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bus_kwh": float(obj_breakdown.get("pv_to_bus_kwh", 0.0) or 0.0),
        "bess_to_bus_kwh": float(obj_breakdown.get("bess_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bess_kwh": float(obj_breakdown.get("pv_to_bess_kwh", 0.0) or 0.0),
        "grid_to_bess_kwh": float(obj_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0),
        "pv_curtail_kwh": float(obj_breakdown.get("pv_curtail_kwh", obj_breakdown.get("pv_curtailed_kwh", 0.0)) or 0.0),
        "contract_over_limit_kwh": float(obj_breakdown.get("contract_over_limit_kwh", 0.0) or 0.0),
        "contract_overage_cost": float(obj_breakdown.get("contract_overage_cost", 0.0) or 0.0),
        "stationary_battery_degradation_cost": float(
            obj_breakdown.get("stationary_battery_degradation_cost", 0.0) or 0.0
        ),
        "pv_asset_cost": float(obj_breakdown.get("pv_asset_cost", 0.0) or 0.0),
        "bess_asset_cost": float(obj_breakdown.get("bess_asset_cost", 0.0) or 0.0),
        "total_cost_with_assets": float(obj_breakdown.get("total_cost_with_assets", 0.0) or 0.0),
        "co2_cost": float(obj_breakdown.get("emission_cost", 0.0) or obj_breakdown.get("co2_cost", 0.0) or 0.0),
        "penalty_unserved": float(obj_breakdown.get("unserved_penalty", 0.0) or 0.0),
        "return_leg_bonus": float(obj_breakdown.get("return_leg_bonus", 0.0) or 0.0),
        "weather_strategy_objective_term_jpy_equivalent": float(
            obj_breakdown.get("weather_strategy_objective_term_jpy_equivalent", 0.0) or 0.0
        ),
        "ice_co2_kg": ice_co2_kg,
        "ice_bus_co2_kg": ice_co2_kg,
        "engine_bus_co2_kg": ice_co2_kg,
        "grid_electricity_co2_kg": grid_electricity_co2_kg,
        "power_generation_co2_kg": grid_electricity_co2_kg,
        "pv_operational_co2_kg": pv_operational_co2_kg,
        "pv_co2_kg": pv_operational_co2_kg,
        "bess_storage_operational_co2_kg": bess_storage_operational_co2_kg,
        "total_co2_kg": reported_co2_kg,
        "total_cost": float(
            total_cost_value
            if total_cost_value is not None
            else result_payload.get("objective_value", 0.0)
            or 0.0
        ),
    }
