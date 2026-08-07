from types import SimpleNamespace

from bff.routers.optimization import (
    _powertrain_marginal_cost_audit_payload,
    _trip_powertrain_cost_comparison_rows,
)
from test_powertrain_marginal_cost_audit import _problem


def test_trip_powertrain_comparison_has_required_columns_and_fails_closed() -> None:
    problem = _problem()
    problem.trips = (
        SimpleNamespace(
            trip_id="trip-1",
            distance_km=10.0,
            departure_min=6 * 60 + 15,
        ),
    )
    audit = _powertrain_marginal_cost_audit_payload(problem)

    rows = _trip_powertrain_cost_comparison_rows(problem, audit)

    assert len(rows) == 1
    row = rows[0]
    required = {
        "trip_id",
        "distance_km",
        "departure_time",
        "ice_fuel_cost_jpy",
        "ice_co2_cost_jpy",
        "bev_energy_kwh",
        "bev_grid_cost_jpy",
        "bev_pv_direct_cost_jpy",
        "bev_pv_bess_cost_jpy",
        "available_pv_bess_energy_at_relevant_slots",
        "charging_feasible",
        "cheapest_powertrain",
        "cost_difference_jpy",
    }
    assert required.issubset(row)
    assert row["departure_time"] == "06:15"
    assert row["available_pv_bess_energy_at_relevant_slots"] is None
    assert row["charging_feasible"] == (
        "UNRESOLVED_REQUIRES_DUTY_CHARGER_SOC_CONTEXT"
    )
    assert row["cheapest_powertrain"] == "ICE_GRID_ONLY"
