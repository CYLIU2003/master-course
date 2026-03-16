"""
result_exporter.py — CSV / JSON / Markdown / Excel 出力

仕様書 §13, §14.7 担当:
  - summary.json            (§13.1.1)
  - vehicle_schedule.csv    (§13.1.2)
  - charging_schedule.csv   (§13.1.3)
  - site_power_balance.csv  (§13.1.4)
  - experiment_report.md    (§13.1.5)
  - results.xlsx            (Excel multi-sheet export)
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_schema import ProblemData
from .milp_model import MILPResult
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_grid_price
from .simulator import SimulationResult


def _to_scalar_metric(value: Any) -> float:
    if isinstance(value, dict):
        numeric_values = []
        for raw in value.values():
            try:
                numeric_values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not numeric_values:
            return 0.0
        return sum(numeric_values) / len(numeric_values)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _make_run_dir(output_root: str | Path) -> Path:
    """output/run_yyyymmdd_hhmm/ ディレクトリを作成して返す"""
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    run_dir = Path(output_root) / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def export_all(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    output_root: str | Path = "output",
    run_label: Optional[str] = None,
) -> Path:
    """
    全出力ファイルを一括生成する。

    Returns
    -------
    Path
        出力ディレクトリ
    """
    run_dir = _make_run_dir(output_root)

    export_summary_json(run_dir, milp_result, sim_result, run_label)
    export_vehicle_schedule(run_dir, data, ms, dp, milp_result)
    export_charging_schedule(run_dir, ms, milp_result)
    export_site_power_balance(run_dir, ms, milp_result, sim_result, data)
    export_experiment_report(run_dir, data, ms, milp_result, sim_result, run_label)
    export_targeted_trips(run_dir, data, milp_result)
    export_trip_type_counts(run_dir, data)
    export_cost_breakdown_detail(run_dir, sim_result)
    export_co2_breakdown(run_dir, data, ms, dp, milp_result, sim_result)
    export_vehicle_timelines(run_dir, data, ms, dp, milp_result)
    export_objective_breakdown(run_dir, milp_result, sim_result)
    export_simulation_conditions(run_dir, data, dp)
    try:
        export_excel(data, ms, dp, milp_result, sim_result, run_dir, run_label)
    except ImportError:
        pass  # openpyxl 未インストール時はスキップ

    return run_dir


# ---------------------------------------------------------------------------
# §13.1.1 summary.json
# ---------------------------------------------------------------------------


def export_summary_json(
    run_dir: Path,
    milp: MILPResult,
    sim: SimulationResult,
    run_label: Optional[str] = None,
) -> None:
    summary = {
        "run_label": run_label or "",
        "timestamp": datetime.now().isoformat(),
        "status": milp.status,
        "objective_value": milp.objective_value,
        "mip_gap": milp.mip_gap,
        "solve_time_sec": milp.solve_time_sec,
        "infeasibility_info": milp.infeasibility_info,
        "cost_breakdown": {
            "total_operating_cost": sim.total_operating_cost,
            "electricity_cost": sim.total_energy_cost,
            "demand_charge": sim.total_demand_charge,
            "fuel_cost": sim.total_fuel_cost,
            "degradation_cost": sim.total_degradation_cost,
        },
        "kpi": {
            "served_task_ratio": sim.served_task_ratio,
            "unserved_tasks": sim.unserved_tasks,
            "total_grid_kwh": sim.total_grid_kwh,
            "total_pv_kwh": sim.total_pv_kwh,
            "pv_self_consumption_ratio": sim.pv_self_consumption_ratio,
            "peak_demand_kw": sim.peak_demand_kw,
            "total_co2_kg": sim.total_co2_kg,
            "soc_min_kwh": sim.soc_min_kwh,
            "soc_violations": sim.soc_violations,
            "vehicle_utilization": sim.vehicle_utilization,
            "charger_utilization": sim.charger_utilization,
        },
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def _normalize_direction(direction: Optional[str]) -> str:
    value = str(direction or "").strip().lower()
    if value in {"outbound", "out", "up", "0"}:
        return "outbound"
    if value in {"inbound", "in", "down", "1"}:
        return "inbound"
    return "unknown"


def _variant_bucket(variant: Optional[str]) -> str:
    value = str(variant or "").strip().lower()
    if value in {"main", "main_outbound", "main_inbound"}:
        return "main"
    if value == "short_turn":
        return "short_turn"
    if value in {"depot_in", "depot_out"}:
        return value
    return "unknown"


def export_targeted_trips(run_dir: Path, data: ProblemData, milp: MILPResult) -> None:
    served = {task_id for tasks in milp.assignment.values() for task_id in tasks}
    rows: List[Dict[str, Any]] = []
    for task in data.tasks:
        rows.append(
            {
                "task_id": task.task_id,
                "route_id": task.route_id or "",
                "service_id": task.service_id or "",
                "direction": _normalize_direction(task.direction),
                "route_variant_type": task.route_variant_type or "unknown",
                "origin": task.origin,
                "destination": task.destination,
                "start_time_idx": task.start_time_idx,
                "end_time_idx": task.end_time_idx,
                "distance_km": task.distance_km,
                "served": task.task_id in served,
            }
        )

    payload = {
        "targeted_task_count": len(data.tasks),
        "served_task_count": len(served),
        "unserved_task_count": max(len(data.tasks) - len(served), 0),
        "tasks": rows,
    }
    with open(run_dir / "targeted_trips.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _write_csv(run_dir / "targeted_trips.csv", rows)


def export_trip_type_counts(run_dir: Path, data: ProblemData) -> None:
    counts = {
        "main_outbound": 0,
        "main_inbound": 0,
        "short_turn_outbound": 0,
        "short_turn_inbound": 0,
        "depot_out": 0,
        "depot_in": 0,
        "unknown": 0,
    }
    by_route: Dict[str, int] = defaultdict(int)

    for task in data.tasks:
        direction = _normalize_direction(task.direction)
        variant = _variant_bucket(task.route_variant_type)
        route_id = task.route_id or "(unknown_route)"
        by_route[route_id] += 1

        if variant == "main":
            key = f"main_{direction}" if direction in {"outbound", "inbound"} else "unknown"
        elif variant == "short_turn":
            key = (
                f"short_turn_{direction}"
                if direction in {"outbound", "inbound"}
                else "unknown"
            )
        elif variant in {"depot_out", "depot_in"}:
            key = variant
        else:
            key = "unknown"
        counts[key] = counts.get(key, 0) + 1

    payload = {
        "total_task_count": len(data.tasks),
        "counts": counts,
        "counts_by_route": dict(sorted(by_route.items())),
    }
    with open(run_dir / "trip_type_counts.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _write_csv(
        run_dir / "trip_type_counts.csv",
        [{"bucket": key, "count": value} for key, value in counts.items()],
    )


def export_cost_breakdown_detail(run_dir: Path, sim: SimulationResult) -> None:
    rows = [
        {"component": "total_operating_cost", "yen": sim.total_operating_cost},
        {"component": "electricity_cost", "yen": sim.total_energy_cost},
        {"component": "demand_charge", "yen": sim.total_demand_charge},
        {"component": "vehicle_fixed_cost", "yen": sim.total_vehicle_fixed_cost},
        {"component": "driver_cost", "yen": sim.total_driver_cost},
        {"component": "fuel_cost", "yen": sim.total_fuel_cost},
        {"component": "degradation_cost", "yen": sim.total_degradation_cost},
    ]
    with open(run_dir / "cost_breakdown_detail.json", "w", encoding="utf-8") as f:
        json.dump({"cost_breakdown": rows}, f, ensure_ascii=False, indent=2)
    _write_csv(run_dir / "cost_breakdown_detail.csv", rows)


def export_co2_breakdown(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
    sim: SimulationResult,
) -> None:
    co2_ice = 0.0
    for vehicle_id in ms.K_ICE:
        vehicle = dp.vehicle_lut.get(vehicle_id)
        if vehicle is None:
            continue
        for task_id in milp.assignment.get(vehicle_id, []):
            co2_ice += vehicle.co2_emission_coeff * dp.task_fuel_ice.get(task_id, 0.0)

    has_grid_co2_factor = any(
        value > 0.0
        for site_map in dp.grid_co2_factor.values()
        for value in site_map.values()
    )
    co2_grid = max(sim.total_co2_kg - co2_ice, 0.0) if has_grid_co2_factor else None

    payload = {
        "total_co2_kg": sim.total_co2_kg,
        "engine_bus_co2_kg": round(co2_ice, 4),
        "power_generation_co2_kg": round(co2_grid, 4) if co2_grid is not None else None,
        "power_generation_co2_note": (
            "Calculated from grid CO2 factors"
            if co2_grid is not None
            else "Not implemented yet (grid CO2 factor unavailable)"
        ),
    }
    with open(run_dir / "co2_breakdown.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _write_csv(
        run_dir / "co2_breakdown.csv",
        [
            {"component": "engine_bus_co2_kg", "value": payload["engine_bus_co2_kg"]},
            {"component": "power_generation_co2_kg", "value": payload["power_generation_co2_kg"]},
            {"component": "total_co2_kg", "value": payload["total_co2_kg"]},
        ],
    )


def export_vehicle_timelines(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
) -> None:
    def _slot_to_minute(slot_idx: int) -> int:
        return int(round(float(slot_idx) * float(data.delta_t_min)))

    def _minute_to_hhmm(total_minute: int) -> str:
        minute = int(total_minute) % (24 * 60)
        return f"{minute // 60:02d}:{minute % 60:02d}"

    def _direction_label(direction: Optional[str]) -> str:
        normalized = _normalize_direction(direction)
        return normalized if normalized != "unknown" else ""

    def _service_label(task: Any) -> str:
        route_id = (getattr(task, "route_id", None) or "").strip()
        direction = _direction_label(getattr(task, "direction", None))
        variant = (getattr(task, "route_variant_type", None) or "").strip()
        parts = [part for part in [route_id, direction, variant] if part]
        if parts:
            return " | ".join(parts)
        origin = getattr(task, "origin", "")
        destination = getattr(task, "destination", "")
        return f"{origin} -> {destination}".strip()

    def _enrich_event(vehicle_id: str, event: Dict[str, Any], event_seq: int) -> Dict[str, Any]:
        start_idx = int(event.get("start_time_idx", 0) or 0)
        end_idx = int(event.get("end_time_idx", 0) or 0)
        start_min = _slot_to_minute(start_idx)
        end_min = _slot_to_minute(end_idx)
        duration_slots = max(end_idx - start_idx, 0)
        duration_min = max(end_min - start_min, 0)
        event_type = str(event.get("event_type", ""))
        if event_type == "service":
            activity_group = "operation"
        elif event_type == "deadhead":
            activity_group = "deadhead"
        elif event_type == "charging":
            activity_group = "charging"
        else:
            activity_group = "other"

        row = {
            "vehicle_id": vehicle_id,
            "event_id": f"{vehicle_id}:{event_seq:04d}",
            "event_seq": event_seq,
            "event_type": event_type,
            "activity_group": activity_group,
            "gantt_lane": vehicle_id,
            "start_time_idx": start_idx,
            "end_time_idx": end_idx,
            "duration_slots": duration_slots,
            "duration_min": duration_min,
            "start_minute": start_min,
            "end_minute": end_min,
            "start_hhmm": _minute_to_hhmm(start_min),
            "end_hhmm": _minute_to_hhmm(end_min),
            "task_id": event.get("task_id") or "",
            "route_id": event.get("route_id") or "",
            "direction": _direction_label(event.get("direction")),
            "route_variant_type": event.get("route_variant_type") or "",
            "service_id": event.get("service_id") or "",
            "service_label": event.get("service_label") or "",
            "origin": event.get("origin") or "",
            "destination": event.get("destination") or "",
            "from_task_id": event.get("from_task_id") or "",
            "to_task_id": event.get("to_task_id") or "",
            "from_route_id": event.get("from_route_id") or "",
            "to_route_id": event.get("to_route_id") or "",
            "deadhead_time_slot": event.get("deadhead_time_slot") or 0,
            "deadhead_distance_km": event.get("deadhead_distance_km") or 0.0,
            "charger_id": event.get("charger_id") or "",
            "avg_power_kw": event.get("avg_power_kw") or 0.0,
            "distance_km": event.get("distance_km") or 0.0,
            "timeline_note": event.get("timeline_note") or "",
        }
        return row

    timeline_by_vehicle: Dict[str, List[Dict[str, Any]]] = {}
    csv_rows: List[Dict[str, Any]] = []

    for vehicle_id in ms.K_ALL:
        events: List[Dict[str, Any]] = []
        assigned = sorted(
            milp.assignment.get(vehicle_id, []),
            key=lambda task_id: dp.task_lut.get(task_id).start_time_idx if dp.task_lut.get(task_id) else 0,
        )

        previous_task_id: Optional[str] = None
        for task_id in assigned:
            task = dp.task_lut.get(task_id)
            if task is None:
                continue

            if previous_task_id is not None:
                dh_slots = dp.deadhead_time_slot.get(previous_task_id, {}).get(task_id, 0)
                if dh_slots > 0:
                    prev_task = dp.task_lut.get(previous_task_id)
                    deadhead_event = {
                        "event_type": "deadhead",
                        "from_task_id": previous_task_id,
                        "to_task_id": task_id,
                        "from_route_id": getattr(prev_task, "route_id", None),
                        "to_route_id": task.route_id,
                        "timeline_note": "between services",
                        "start_time_idx": max(task.start_time_idx - dh_slots, 0),
                        "end_time_idx": task.start_time_idx,
                        "deadhead_time_slot": dh_slots,
                        "deadhead_distance_km": dp.deadhead_distance_km.get(previous_task_id, {}).get(task_id, 0.0),
                    }
                    events.append(deadhead_event)

            service_event = {
                "event_type": "service",
                "task_id": task_id,
                "route_id": task.route_id,
                "direction": task.direction,
                "route_variant_type": task.route_variant_type,
                "service_id": task.service_id,
                "service_label": _service_label(task),
                "origin": task.origin,
                "destination": task.destination,
                "start_time_idx": task.start_time_idx,
                "end_time_idx": task.end_time_idx,
                "distance_km": task.distance_km,
            }
            events.append(service_event)
            previous_task_id = task_id

        for charger_id, flags in milp.charge_schedule.get(vehicle_id, {}).items():
            powers = milp.charge_power_kw.get(vehicle_id, {}).get(charger_id, [0.0] * len(flags))
            start_idx: Optional[int] = None
            power_sum = 0.0
            power_count = 0
            for idx, flag in enumerate(flags):
                active = idx < len(powers) and (flag > 0 or powers[idx] > 1e-6)
                if active and start_idx is None:
                    start_idx = idx
                if active:
                    power_sum += float(powers[idx]) if idx < len(powers) else 0.0
                    power_count += 1
                if not active and start_idx is not None:
                    events.append(
                        {
                            "event_type": "charging",
                            "charger_id": charger_id,
                            "start_time_idx": start_idx,
                            "end_time_idx": idx,
                            "avg_power_kw": (power_sum / power_count) if power_count else 0.0,
                            "timeline_note": "plug-in charging",
                        }
                    )
                    start_idx = None
                    power_sum = 0.0
                    power_count = 0
            if start_idx is not None:
                events.append(
                    {
                        "event_type": "charging",
                        "charger_id": charger_id,
                        "start_time_idx": start_idx,
                        "end_time_idx": len(flags),
                        "avg_power_kw": (power_sum / power_count) if power_count else 0.0,
                        "timeline_note": "plug-in charging",
                    }
                )

        events.sort(key=lambda event: (event.get("start_time_idx", 0), event.get("event_type", "")))
        enriched_events: List[Dict[str, Any]] = []
        for seq, event in enumerate(events, start=1):
            enriched = _enrich_event(vehicle_id, event, seq)
            enriched_events.append(enriched)
            csv_rows.append(enriched)

        timeline_by_vehicle[vehicle_id] = enriched_events

    with open(run_dir / "vehicle_timelines.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "timeline_schema_version": "2.0",
                "delta_t_min": data.delta_t_min,
                "vehicle_timelines": timeline_by_vehicle,
                "vehicle_gantt_rows": csv_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    _write_csv(run_dir / "vehicle_timelines.csv", csv_rows)
    _write_csv(run_dir / "vehicle_timeline_gantt.csv", csv_rows)


def export_objective_breakdown(run_dir: Path, milp: MILPResult, sim: SimulationResult) -> None:
    breakdown = dict(milp.obj_breakdown or {})
    if not breakdown:
        breakdown = {
            "electricity_cost": sim.total_energy_cost,
            "demand_charge": sim.total_demand_charge,
            "fuel_cost": sim.total_fuel_cost,
            "degradation_cost": sim.total_degradation_cost,
            "vehicle_fixed_cost": sim.total_vehicle_fixed_cost,
            "driver_cost": sim.total_driver_cost,
        }
    with open(run_dir / "objective_breakdown.json", "w", encoding="utf-8") as f:
        json.dump({"objective_breakdown": breakdown}, f, ensure_ascii=False, indent=2)
    _write_csv(
        run_dir / "objective_breakdown.csv",
        [{"term": key, "value": value} for key, value in breakdown.items()],
    )


def export_simulation_conditions(run_dir: Path, data: ProblemData, dp: DerivedParams) -> None:
    vehicle_rows: List[Dict[str, Any]] = []
    for vehicle in data.vehicles:
        vehicle_rows.append(
            {
                "vehicle_id": vehicle.vehicle_id,
                "vehicle_type": vehicle.vehicle_type,
                "fixed_use_cost_yen": vehicle.fixed_use_cost,
                "fuel_cost_coeff_yen_per_liter": vehicle.fuel_cost_coeff,
                "battery_degradation_cost_coeff_yen_per_kwh": vehicle.battery_degradation_cost_coeff,
                "co2_emission_coeff_kg_per_liter": vehicle.co2_emission_coeff,
            }
        )

    vehicle_cost_summary: Dict[str, Dict[str, float]] = {}
    for row in vehicle_rows:
        vtype = str(row["vehicle_type"])
        bucket = vehicle_cost_summary.setdefault(
            vtype,
            {
                "count": 0.0,
                "avg_fixed_use_cost_yen": 0.0,
                "avg_fuel_cost_coeff_yen_per_liter": 0.0,
                "avg_battery_degradation_cost_coeff_yen_per_kwh": 0.0,
            },
        )
        bucket["count"] += 1.0
        bucket["avg_fixed_use_cost_yen"] += float(row["fixed_use_cost_yen"])
        bucket["avg_fuel_cost_coeff_yen_per_liter"] += float(row["fuel_cost_coeff_yen_per_liter"])
        bucket["avg_battery_degradation_cost_coeff_yen_per_kwh"] += float(
            row["battery_degradation_cost_coeff_yen_per_kwh"]
        )

    for bucket in vehicle_cost_summary.values():
        count = bucket["count"] if bucket["count"] > 0 else 1.0
        bucket["avg_fixed_use_cost_yen"] = bucket["avg_fixed_use_cost_yen"] / count
        bucket["avg_fuel_cost_coeff_yen_per_liter"] = (
            bucket["avg_fuel_cost_coeff_yen_per_liter"] / count
        )
        bucket["avg_battery_degradation_cost_coeff_yen_per_kwh"] = (
            bucket["avg_battery_degradation_cost_coeff_yen_per_kwh"] / count
        )

    tou_rows: List[Dict[str, Any]] = []
    for site_id, by_time in dp.grid_price.items():
        for time_idx in sorted(by_time.keys()):
            tou_rows.append(
                {
                    "site_id": site_id,
                    "time_idx": time_idx,
                    "grid_energy_price_yen_per_kwh": by_time.get(time_idx, 0.0),
                    "sell_back_price_yen_per_kwh": dp.sell_back_price.get(site_id, {}).get(time_idx, 0.0),
                    "base_load_kw": dp.base_load_kw.get(site_id, {}).get(time_idx, 0.0),
                    "grid_co2_factor_kg_per_kwh": dp.grid_co2_factor.get(site_id, {}).get(time_idx, 0.0),
                }
            )

    price_values = [float(row["grid_energy_price_yen_per_kwh"]) for row in tou_rows]
    electricity_price_summary = {
        "has_tou_price_table": len(tou_rows) > 0,
        "time_slot_count": len(price_values),
        "grid_energy_price_min_yen_per_kwh": min(price_values) if price_values else None,
        "grid_energy_price_max_yen_per_kwh": max(price_values) if price_values else None,
        "grid_energy_price_avg_yen_per_kwh": (
            sum(price_values) / len(price_values) if price_values else None
        ),
    }

    contract_rows: List[Dict[str, Any]] = []
    for site in data.sites:
        contract_rows.append(
            {
                "site_id": site.site_id,
                "site_type": site.site_type,
                "contract_demand_limit_kw": site.contract_demand_limit_kw,
                "grid_import_limit_kw": site.grid_import_limit_kw,
                "site_transformer_limit_kw": site.site_transformer_limit_kw,
            }
        )

    payload = {
        "timestamp": datetime.now().isoformat(),
        "time_settings": {
            "delta_t_min": data.delta_t_min,
            "num_periods": data.num_periods,
            "planning_horizon_hours": data.planning_horizon_hours,
        },
        "flags": {
            "enable_pv": data.enable_pv,
            "enable_v2g": data.enable_v2g,
            "enable_demand_charge": data.enable_demand_charge,
            "enable_battery_degradation": data.enable_battery_degradation,
            "allow_partial_service": data.allow_partial_service,
        },
        "unit_prices_and_costs": {
            "vehicle_introduction_cost_source": "vehicle.fixed_use_cost",
            "fuel_unit_price_source": "vehicle.fuel_cost_coeff",
            "battery_degradation_unit_price_source": "vehicle.battery_degradation_cost_coeff",
            "co2_price_per_kg": data.co2_price_per_kg,
            "demand_charge_rate_per_kw": data.demand_charge_rate_per_kw,
            "electricity_price_summary": electricity_price_summary,
        },
        "demand_and_contract_conditions": {
            "demand_charge_rate_per_kw": data.demand_charge_rate_per_kw,
            "objective_weight_demand_charge_cost": data.objective_weights.get(
                "demand_charge_cost", 0.0
            ),
            "contract_limit_penalty_multiplier": data.objective_weights.get(
                "contract_limit_penalty_multiplier"
            ),
            "contract_limit_penalty_note": (
                "If null, no explicit penalty multiplier is configured in objective_weights"
            ),
            "contract_limits_by_site": contract_rows,
        },
        "extensible_coefficients": {
            "objective_weights": dict(data.objective_weights),
            "big_m": {
                "BIG_M_ASSIGN": data.BIG_M_ASSIGN,
                "BIG_M_CHARGE": data.BIG_M_CHARGE,
                "BIG_M_SOC": data.BIG_M_SOC,
                "EPSILON": data.EPSILON,
            },
        },
        "vehicle_costs": vehicle_rows,
        "vehicle_cost_summary_by_type": vehicle_cost_summary,
        "tou_prices": tou_rows,
    }

    with open(run_dir / "simulation_conditions.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _write_csv(run_dir / "simulation_conditions_vehicle_costs.csv", vehicle_rows)
    _write_csv(run_dir / "simulation_conditions_tou_prices.csv", tou_rows)
    _write_csv(run_dir / "simulation_conditions_contract_limits.csv", contract_rows)


# ---------------------------------------------------------------------------
# §13.1.2 vehicle_schedule.csv
# ---------------------------------------------------------------------------


def export_vehicle_schedule(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
) -> None:
    rows = []
    for k in ms.K_ALL:
        assigned = milp.assignment.get(k, [])
        if assigned:
            for r_id in assigned:
                task = dp.task_lut.get(r_id)
                rows.append(
                    {
                        "vehicle_id": k,
                        "vehicle_type": dp.vehicle_lut[k].vehicle_type,
                        "task_id": r_id,
                        "start_time_idx": task.start_time_idx if task else "",
                        "end_time_idx": task.end_time_idx if task else "",
                        "origin": task.origin if task else "",
                        "destination": task.destination if task else "",
                        "distance_km": task.distance_km if task else "",
                        "energy_kwh_bev": task.energy_required_kwh_bev if task else "",
                    }
                )
        else:
            rows.append(
                {
                    "vehicle_id": k,
                    "vehicle_type": dp.vehicle_lut[k].vehicle_type,
                    "task_id": "(unassigned)",
                    "start_time_idx": "",
                    "end_time_idx": "",
                    "origin": "",
                    "destination": "",
                    "distance_km": "",
                    "energy_kwh_bev": "",
                }
            )

    _write_csv(run_dir / "vehicle_schedule.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.3 charging_schedule.csv
# ---------------------------------------------------------------------------


def export_charging_schedule(
    run_dir: Path,
    ms: ModelSets,
    milp: MILPResult,
) -> None:
    rows = []
    for k in ms.K_BEV:
        soc_series = milp.soc_series.get(k, [])
        for c in ms.C:
            pwr_series = milp.charge_power_kw.get(k, {}).get(c, [0.0] * len(ms.T))
            z_series = milp.charge_schedule.get(k, {}).get(c, [0] * len(ms.T))
            for t_idx in ms.T:
                soc_val = soc_series[t_idx] if t_idx < len(soc_series) else ""
                rows.append(
                    {
                        "vehicle_id": k,
                        "charger_id": c,
                        "time_idx": t_idx,
                        "z_charge": z_series[t_idx] if t_idx < len(z_series) else 0,
                        "p_charge_kw": pwr_series[t_idx]
                        if t_idx < len(pwr_series)
                        else 0.0,
                        "soc_kwh": soc_val,
                    }
                )

    _write_csv(run_dir / "charging_schedule.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.4 site_power_balance.csv
# ---------------------------------------------------------------------------


def export_site_power_balance(
    run_dir: Path,
    ms: ModelSets,
    milp: MILPResult,
    sim: SimulationResult,
    data: ProblemData,
) -> None:
    rows = []
    for site_id in ms.I_CHARGE:
        grid_series = milp.grid_import_kw.get(site_id, [0.0] * len(ms.T))
        pv_series = milp.pv_used_kw.get(site_id, [0.0] * len(ms.T))
        for t_idx in ms.T:
            rows.append(
                {
                    "site_id": site_id,
                    "time_idx": t_idx,
                    "grid_import_kw": grid_series[t_idx]
                    if t_idx < len(grid_series)
                    else 0.0,
                    "pv_used_kw": pv_series[t_idx] if t_idx < len(pv_series) else 0.0,
                    "peak_demand_kw": milp.peak_demand_kw.get(site_id, 0.0),
                }
            )

    _write_csv(run_dir / "site_power_balance.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.5 experiment_report.md
# ---------------------------------------------------------------------------


def export_experiment_report(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    milp: MILPResult,
    sim: SimulationResult,
    run_label: Optional[str] = None,
) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 実験レポート — {run_label or ts}",
        "",
        "## 条件一覧",
        f"- 実行日時: {ts}",
        f"- 車両数 BEV: {len(ms.K_BEV)}, ICE: {len(ms.K_ICE)}",
        f"- タスク数: {len(ms.R)}",
        f"- 充電器数: {len(ms.C)}",
        f"- 時間刻み: {data.delta_t_min:.0f} 分 ({data.num_periods} スロット)",
        f"- PV 有効: {data.enable_pv}",
        f"- V2G 有効: {data.enable_v2g}",
        f"- デマンド料金有効: {data.enable_demand_charge}",
        "",
        "## ソルバー結果",
        f"- ステータス: **{milp.status}**",
        f"- 目的関数値: {milp.objective_value}",
        f"- MIP ギャップ: {milp.mip_gap}",
        f"- 計算時間: {milp.solve_time_sec:.2f} 秒",
        "",
        "## 目的関数内訳",
        f"| 項目 | 値 [円] |",
        f"|------|---------|",
        f"| 電力量料金 | {sim.total_energy_cost:,.0f} |",
        f"| デマンド料金 | {sim.total_demand_charge:,.0f} |",
        f"| 燃料費 | {sim.total_fuel_cost:,.0f} |",
        f"| 電池劣化 | {sim.total_degradation_cost:,.0f} |",
        f"| **合計** | **{sim.total_operating_cost:,.0f}** |",
        "",
        "## 主要 KPI",
        f"- タスク担当率: {sim.served_task_ratio * 100:.1f} %",
        f"- 未担当タスク: {sim.unserved_tasks or 'なし'}",
        f"- 系統受電量: {sim.total_grid_kwh:.2f} kWh",
        f"- PV 利用量: {sim.total_pv_kwh:.2f} kWh",
        f"- PV 自家消費率: {sim.pv_self_consumption_ratio * 100:.1f} %",
        f"- ピーク需要: {sim.peak_demand_kw:.2f} kW",
        f"- CO2 排出: {sim.total_co2_kg:.2f} kg",
        f"- 最低 SOC: {sim.soc_min_kwh:.2f} kWh",
        f"- SOC 違反: {len(sim.soc_violations)} 件",
        "",
        "## infeasible 情報",
        milp.infeasibility_info or "なし",
        "",
        "---",
        "*本レポートは result_exporter.py により自動生成されました。*",
    ]
    with open(run_dir / "experiment_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Excel multi-sheet export (openpyxl)
# ---------------------------------------------------------------------------


def export_excel(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    run_dir: Path,
    run_label: Optional[str] = None,
) -> Path:
    """
    openpyxl を使い、results.xlsx を run_dir 内に生成する。

    シート構成
    ----------
    Summary          : KPI サマリー（縦持ちキー/値テーブル）
    KPIs             : 10 KPI 一覧（数値）
    VehicleSchedule  : vehicle_schedule.csv と同内容
    ChargingSchedule : charging_schedule.csv と同内容（先頭 10,000 行）
    SitePowerBalance : site_power_balance.csv と同内容

    Returns
    -------
    Path
        生成した xlsx ファイルのパス
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ImportError(
            "Excel エクスポートには openpyxl が必要です: pip install openpyxl"
        ) from exc

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # デフォルトシートを削除

    # ---- ヘルパー: シートにテーブルを書く -----------------------------------
    def _write_sheet(
        ws: "openpyxl.worksheet.worksheet.Worksheet",
        headers: List[str],
        rows_data: List[List[Any]],
        freeze: bool = True,
    ) -> None:
        header_fill = PatternFill(fill_type="solid", fgColor="1F5C99")
        header_font = Font(bold=True, color="FFFFFF")
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for row_idx, row_vals in enumerate(rows_data, 2):
            for col_idx, val in enumerate(row_vals, 1):
                ws.cell(row=row_idx, column=col_idx, value=val)
        # 列幅自動調整（最大 40 文字）
        for col_idx, h in enumerate(headers, 1):
            col_letter = get_column_letter(col_idx)
            max_len = max(
                len(str(h)),
                max((len(str(r[col_idx - 1])) for r in rows_data if r), default=0),
            )
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)
        if freeze:
            ws.freeze_panes = "A2"

    # ---- Sheet 1: Summary --------------------------------------------------
    ws_sum = wb.create_sheet("Summary")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_rows: List[List[Any]] = [
        ["実行ラベル", run_label or ""],
        ["生成日時", ts],
        ["ステータス", milp_result.status],
        ["目的関数値 [円]", milp_result.objective_value],
        ["MIP ギャップ", milp_result.mip_gap],
        ["計算時間 [秒]", round(milp_result.solve_time_sec, 3)],
        ["BEV 台数", len(ms.K_BEV)],
        ["ICE 台数", len(ms.K_ICE)],
        ["タスク数", len(ms.R)],
        ["充電器数", len(ms.C)],
        ["時間刻み [分]", data.delta_t_min],
        ["時間スロット数", data.num_periods],
        ["PV 有効", data.enable_pv],
        ["V2G 有効", data.enable_v2g],
        ["デマンド料金有効", data.enable_demand_charge],
        ["--- コスト内訳 ---", ""],
        ["電力量料金 [円]", round(sim_result.total_energy_cost, 0)],
        ["デマンド料金 [円]", round(sim_result.total_demand_charge, 0)],
        ["燃料費 [円]", round(sim_result.total_fuel_cost, 0)],
        ["電池劣化費 [円]", round(sim_result.total_degradation_cost, 0)],
        ["運行コスト合計 [円]", round(sim_result.total_operating_cost, 0)],
    ]
    _write_sheet(ws_sum, ["項目", "値"], summary_rows)

    # ---- Sheet 2: KPIs -----------------------------------------------------
    ws_kpi = wb.create_sheet("KPIs")
    charger_utilization = _to_scalar_metric(sim_result.charger_utilization)

    unserved_tasks_value = sim_result.unserved_tasks
    if isinstance(unserved_tasks_value, list):
        unmet_trips = len(unserved_tasks_value)
    else:
        unmet_trips = int(unserved_tasks_value or 0)

    kpi_rows: List[List[Any]] = [
        ["objective_value", milp_result.objective_value],
        ["total_energy_cost", round(sim_result.total_energy_cost, 2)],
        ["total_demand_charge", round(sim_result.total_demand_charge, 2)],
        ["total_fuel_cost", round(sim_result.total_fuel_cost, 2)],
        [
            "vehicle_fixed_cost",
            round(getattr(sim_result, "vehicle_fixed_cost", 0.0), 2),
        ],
        ["unmet_trips", unmet_trips],
        ["soc_min_margin_kwh", round(getattr(sim_result, "soc_min_kwh", 0.0), 3)],
        ["charger_utilization", round(charger_utilization, 4)],
        ["peak_grid_power_kw", round(sim_result.peak_demand_kw, 2)],
        ["solve_time_sec", round(milp_result.solve_time_sec, 3)],
    ]
    _write_sheet(ws_kpi, ["KPI", "値"], kpi_rows)

    # ---- Sheet 3: VehicleSchedule ------------------------------------------
    ws_vs = wb.create_sheet("VehicleSchedule")
    vs_headers = [
        "vehicle_id",
        "vehicle_type",
        "task_id",
        "start_time_idx",
        "end_time_idx",
        "origin",
        "destination",
        "distance_km",
        "energy_kwh_bev",
    ]
    vs_rows: List[List[Any]] = []
    for k in ms.K_ALL:
        assigned = milp_result.assignment.get(k, [])
        if assigned:
            for r_id in assigned:
                task = dp.task_lut.get(r_id)
                vs_rows.append(
                    [
                        k,
                        dp.vehicle_lut[k].vehicle_type,
                        r_id,
                        task.start_time_idx if task else "",
                        task.end_time_idx if task else "",
                        task.origin if task else "",
                        task.destination if task else "",
                        task.distance_km if task else "",
                        task.energy_required_kwh_bev if task else "",
                    ]
                )
        else:
            vs_rows.append(
                [
                    k,
                    dp.vehicle_lut[k].vehicle_type,
                    "(unassigned)",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    _write_sheet(ws_vs, vs_headers, vs_rows)

    # ---- Sheet 4: ChargingSchedule (先頭 10,000 行に制限) ------------------
    ws_cs = wb.create_sheet("ChargingSchedule")
    cs_headers = [
        "vehicle_id",
        "charger_id",
        "time_idx",
        "z_charge",
        "p_charge_kw",
        "soc_kwh",
    ]
    cs_rows: List[List[Any]] = []
    MAX_CS_ROWS = 10_000
    for k in ms.K_BEV:
        if len(cs_rows) >= MAX_CS_ROWS:
            break
        soc_series = milp_result.soc_series.get(k, [])
        for c in ms.C:
            if len(cs_rows) >= MAX_CS_ROWS:
                break
            pwr_series = milp_result.charge_power_kw.get(k, {}).get(
                c, [0.0] * len(ms.T)
            )
            z_series = milp_result.charge_schedule.get(k, {}).get(c, [0] * len(ms.T))
            for t_idx in ms.T:
                if len(cs_rows) >= MAX_CS_ROWS:
                    break
                soc_val = soc_series[t_idx] if t_idx < len(soc_series) else ""
                cs_rows.append(
                    [
                        k,
                        c,
                        t_idx,
                        z_series[t_idx] if t_idx < len(z_series) else 0,
                        pwr_series[t_idx] if t_idx < len(pwr_series) else 0.0,
                        soc_val,
                    ]
                )
    _write_sheet(ws_cs, cs_headers, cs_rows)

    # ---- Sheet 5: SitePowerBalance -----------------------------------------
    ws_sp = wb.create_sheet("SitePowerBalance")
    sp_headers = [
        "site_id",
        "time_idx",
        "grid_import_kw",
        "pv_used_kw",
        "peak_demand_kw",
    ]
    sp_rows: List[List[Any]] = []
    for site_id in ms.I_CHARGE:
        grid_series = milp_result.grid_import_kw.get(site_id, [0.0] * len(ms.T))
        pv_series = milp_result.pv_used_kw.get(site_id, [0.0] * len(ms.T))
        for t_idx in ms.T:
            sp_rows.append(
                [
                    site_id,
                    t_idx,
                    grid_series[t_idx] if t_idx < len(grid_series) else 0.0,
                    pv_series[t_idx] if t_idx < len(pv_series) else 0.0,
                    milp_result.peak_demand_kw.get(site_id, 0.0),
                ]
            )
    _write_sheet(ws_sp, sp_headers, sp_rows)

    # ---- 保存 --------------------------------------------------------------
    out_path = run_dir / "results.xlsx"
    wb.save(out_path)
    return out_path


def export_excel_bytes(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    run_label: Optional[str] = None,
) -> bytes:
    """
    results.xlsx をファイルに保存せず bytes として返す。
    Streamlit の st.download_button に直接渡せる。

    Parameters
    ----------
    data, ms, dp, milp_result, sim_result : 各パイプライン出力
    run_label : 任意のラベル文字列

    Returns
    -------
    bytes
        xlsx バイナリデータ
    """
    import io
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = _Path(tmp)
        xlsx_path = export_excel(
            data, ms, dp, milp_result, sim_result, tmp_path, run_label
        )
        return xlsx_path.read_bytes()
