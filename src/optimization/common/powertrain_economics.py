from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


_EPS = 1.0e-12


@dataclass(frozen=True)
class PowertrainMarginalCostAudit:
    """Transparent per-kilometre economics for BEV/ICE dispatch decisions.

    The audit deliberately separates traction-energy cost from fixed fleet cost.
    It is intended for scenario validation and research reporting; it must not be
    used as a hidden preference term in the optimisation objective.
    """

    electricity_price_jpy_per_kwh: float
    bev_energy_kwh_per_km: float
    bev_charge_efficiency: float
    diesel_price_jpy_per_litre: float
    ice_fuel_litre_per_km: float
    ice_co2_kg_per_litre: float
    grid_co2_kg_per_kwh: float
    co2_price_jpy_per_kg: float
    bev_grid_energy_cost_jpy_per_km: float
    ice_fuel_cost_jpy_per_km: float
    bev_grid_co2_kg_per_km: float
    ice_co2_kg_per_km: float
    bev_grid_co2_cost_jpy_per_km: float
    ice_co2_cost_jpy_per_km: float
    bev_total_marginal_cost_jpy_per_km: float
    ice_total_marginal_cost_jpy_per_km: float
    bev_minus_ice_jpy_per_km: float
    break_even_electricity_price_jpy_per_kwh: float
    required_co2_price_for_bev_break_even_jpy_per_kg: float | None
    nonnegative_co2_price_can_make_bev_break_even: bool
    bev_is_marginally_cheaper: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_powertrain_marginal_costs(
    *,
    electricity_price_jpy_per_kwh: float,
    bev_energy_kwh_per_km: float,
    bev_charge_efficiency: float,
    diesel_price_jpy_per_litre: float,
    ice_fuel_litre_per_km: float,
    ice_co2_kg_per_litre: float = 0.0,
    grid_co2_kg_per_kwh: float = 0.0,
    co2_price_jpy_per_kg: float = 0.0,
) -> PowertrainMarginalCostAudit:
    """Calculate comparable marginal operating costs for BEV and ICE buses.

    The BEV grid cost is based on energy purchased upstream of charging loss:

        price * traction_energy / charge_efficiency

    Carbon cost is added only when an explicit CO2 price is supplied.  PV/BESS
    marginal cost is intentionally excluded because it is time-dependent and is
    handled by the energy recourse model, not by this static audit.
    """

    electricity_price = _finite_nonnegative(
        electricity_price_jpy_per_kwh,
        "electricity_price_jpy_per_kwh",
    )
    bev_energy = _finite_positive(bev_energy_kwh_per_km, "bev_energy_kwh_per_km")
    efficiency = _finite_ratio(bev_charge_efficiency, "bev_charge_efficiency")
    diesel_price = _finite_nonnegative(
        diesel_price_jpy_per_litre,
        "diesel_price_jpy_per_litre",
    )
    ice_fuel = _finite_positive(ice_fuel_litre_per_km, "ice_fuel_litre_per_km")
    ice_co2 = _finite_nonnegative(ice_co2_kg_per_litre, "ice_co2_kg_per_litre")
    grid_co2 = _finite_nonnegative(grid_co2_kg_per_kwh, "grid_co2_kg_per_kwh")
    co2_price = _finite_nonnegative(co2_price_jpy_per_kg, "co2_price_jpy_per_kg")

    bev_grid_energy_cost = electricity_price * bev_energy / efficiency
    ice_fuel_cost = diesel_price * ice_fuel
    bev_grid_co2_per_km = grid_co2 * bev_energy / efficiency
    ice_co2_per_km = ice_co2 * ice_fuel
    bev_grid_co2_cost = bev_grid_co2_per_km * co2_price
    ice_co2_cost = ice_co2_per_km * co2_price
    bev_total = bev_grid_energy_cost + bev_grid_co2_cost
    ice_total = ice_fuel_cost + ice_co2_cost

    # Solve the equality of total marginal costs for electricity price.
    break_even_price = (
        (ice_total - bev_grid_co2_cost) * efficiency / bev_energy
    )

    # Solve the same equality for CO2 price at the supplied electricity price.
    # A negative solution means that no nonnegative carbon price can reverse
    # the ordering; this occurs when grid-powered BEV operation is both more
    # expensive and more carbon intensive per kilometre than ICE operation.
    co2_denominator = ice_co2_per_km - bev_grid_co2_per_km
    required_co2_price: float | None
    if abs(co2_denominator) <= _EPS:
        required_co2_price = None
    else:
        candidate = (
            bev_grid_energy_cost - ice_fuel_cost
        ) / co2_denominator
        required_co2_price = candidate if candidate >= 0.0 else None

    return PowertrainMarginalCostAudit(
        electricity_price_jpy_per_kwh=electricity_price,
        bev_energy_kwh_per_km=bev_energy,
        bev_charge_efficiency=efficiency,
        diesel_price_jpy_per_litre=diesel_price,
        ice_fuel_litre_per_km=ice_fuel,
        ice_co2_kg_per_litre=ice_co2,
        grid_co2_kg_per_kwh=grid_co2,
        co2_price_jpy_per_kg=co2_price,
        bev_grid_energy_cost_jpy_per_km=bev_grid_energy_cost,
        ice_fuel_cost_jpy_per_km=ice_fuel_cost,
        bev_grid_co2_kg_per_km=bev_grid_co2_per_km,
        ice_co2_kg_per_km=ice_co2_per_km,
        bev_grid_co2_cost_jpy_per_km=bev_grid_co2_cost,
        ice_co2_cost_jpy_per_km=ice_co2_cost,
        bev_total_marginal_cost_jpy_per_km=bev_total,
        ice_total_marginal_cost_jpy_per_km=ice_total,
        bev_minus_ice_jpy_per_km=bev_total - ice_total,
        break_even_electricity_price_jpy_per_kwh=break_even_price,
        required_co2_price_for_bev_break_even_jpy_per_kg=required_co2_price,
        nonnegative_co2_price_can_make_bev_break_even=(
            required_co2_price is not None
        ),
        bev_is_marginally_cheaper=bev_total <= ice_total + 1.0e-9,
    )


def audit_candidate_powertrain_diversity(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit whether the candidate pool actually explores fleet composition.

    A weather comparison cannot support a claim about endogenous BEV/ICE fleet
    choice when every Stage-1/Stage-2 candidate has the same used-BEV and
    used-ICE counts.  Trip-level swaps are useful, but they are not equivalent
    to fleet-composition search.
    """

    compositions: set[tuple[int, int]] = set()
    trip_splits: set[tuple[int, int]] = set()
    valid_rows = 0
    for row in rows:
        used_bev = _optional_int(row.get("used_bev"))
        used_ice = _optional_int(row.get("used_ice"))
        bev_trips = _optional_int(row.get("bev_trips"))
        ice_trips = _optional_int(row.get("ice_trips"))
        if used_bev is not None and used_ice is not None:
            compositions.add((used_bev, used_ice))
            valid_rows += 1
        if bev_trips is not None and ice_trips is not None:
            trip_splits.add((bev_trips, ice_trips))

    composition_count = len(compositions)
    return {
        "candidate_row_count": len(rows),
        "candidate_rows_with_fleet_counts": valid_rows,
        "distinct_used_powertrain_composition_count": composition_count,
        "used_powertrain_compositions": [
            {"used_bev": bev, "used_ice": ice}
            for bev, ice in sorted(compositions)
        ],
        "distinct_trip_powertrain_split_count": len(trip_splits),
        "trip_powertrain_splits": [
            {"bev_trips": bev, "ice_trips": ice}
            for bev, ice in sorted(trip_splits)
        ],
        "powertrain_fleet_count_frozen": bool(rows) and composition_count <= 1,
        "fleet_composition_search_verified": composition_count >= 2,
    }


def _finite_positive(value: float, field_name: str) -> float:
    parsed = _finite(value, field_name)
    if parsed <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _finite_nonnegative(value: float, field_name: str) -> float:
    parsed = _finite(value, field_name)
    if parsed < 0.0:
        raise ValueError(f"{field_name} must be nonnegative")
    return parsed


def _finite_ratio(value: float, field_name: str) -> float:
    parsed = _finite(value, field_name)
    if not 0.0 < parsed <= 1.0:
        raise ValueError(f"{field_name} must be within (0, 1]")
    return parsed


def _finite(value: float, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
