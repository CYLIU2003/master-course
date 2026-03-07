"""
src.preprocess.scenario_generator — 不確実性シナリオ生成

spec_v3 §6.3 / agent_route_editable §4.3 (mode_uncertainty_eval)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.schemas.route_entities import GeneratedTrip
from src.schemas.trip_entities import ScenarioTripEnergy
from src.preprocess.energy_model import apply_energy_uncertainty


@dataclass
class ScenarioParams:
    """シナリオ生成パラメータ。"""
    n_scenarios: int = 10
    seed: int = 42
    # 変動範囲 (uniform distribution)
    energy_multiplier_range: tuple = (0.85, 1.15)    # ±15%
    travel_time_multiplier_range: tuple = (0.90, 1.20)  # +10–20%
    congestion_shift_range: tuple = (-0.2, 0.5)
    temp_range_c: tuple = (5.0, 35.0)
    load_multiplier_range: tuple = (0.5, 1.0)


def generate_scenarios(
    trips: List[GeneratedTrip],
    vehicle_type_id: str,
    params: Optional[ScenarioParams] = None,
) -> List[ScenarioTripEnergy]:
    """各 trip × scenario の ScenarioTripEnergy リストを生成する。

    Parameters
    ----------
    trips : List[GeneratedTrip]
    vehicle_type_id : str
    params : ScenarioParams

    Returns
    -------
    List[ScenarioTripEnergy]
    """
    if params is None:
        params = ScenarioParams()

    rng = random.Random(params.seed)
    samples: List[ScenarioTripEnergy] = []

    for omega in range(params.n_scenarios):
        scenario_id = f"omega_{omega:04d}"

        em = rng.uniform(*params.energy_multiplier_range)
        tm = rng.uniform(*params.travel_time_multiplier_range)
        cong_shift = rng.uniform(*params.congestion_shift_range)
        temp = rng.uniform(*params.temp_range_c)
        load_m = rng.uniform(*params.load_multiplier_range)
        rain = rng.random() < 0.2  # 20% chance of rain

        for trip in trips:
            base_energy = trip.estimated_energy_kwh_bev or 0.0
            base_fuel = trip.estimated_fuel_l_ice or 0.0
            base_runtime = trip.scheduled_runtime_min or 0.0

            energy = apply_energy_uncertainty(base_energy, em, tm)
            fuel = round(base_fuel * em, 4)
            runtime = round(base_runtime * tm, 2)

            sample = ScenarioTripEnergy(
                trip_id=trip.trip_id,
                vehicle_type_id=vehicle_type_id,
                scenario_id=scenario_id,
                travel_time_multiplier=round(tm, 4),
                energy_multiplier=round(em, 4),
                congestion_index_shift=round(cong_shift, 4),
                ambient_temp_c=round(temp, 1),
                passenger_load_multiplier=round(load_m, 4),
                rainfall_flag=rain,
                energy_kwh=energy,
                fuel_l=fuel,
                runtime_min=runtime,
                energy_breakdown={
                    "base": round(base_energy, 4),
                    "energy_multiplier": round(em, 4),
                    "scenario_adjustment": round(energy - base_energy, 4),
                },
            )
            samples.append(sample)

    return samples


def apply_scenario_to_trips(
    trips: List[GeneratedTrip],
    scenario: Dict[str, ScenarioTripEnergy],
) -> List[GeneratedTrip]:
    """シナリオサンプルの値を GeneratedTrip に上書きした新リストを返す。

    Parameters
    ----------
    trips : List[GeneratedTrip]
    scenario : Dict[trip_id, ScenarioTripEnergy]

    Returns
    -------
    List[GeneratedTrip]  (shallow copy with energy values overwritten)
    """
    import copy
    result: List[GeneratedTrip] = []
    for trip in trips:
        s = scenario.get(trip.trip_id)
        if s is None:
            result.append(trip)
            continue
        t_copy = copy.copy(trip)
        if s.energy_kwh is not None:
            t_copy.estimated_energy_kwh_bev = s.energy_kwh
        if s.fuel_l is not None:
            t_copy.estimated_fuel_l_ice = s.fuel_l
        if s.runtime_min is not None:
            t_copy.scheduled_runtime_min = s.runtime_min
        t_copy.energy_breakdown = s.energy_breakdown.copy()
        result.append(t_copy)
    return result
