from types import SimpleNamespace

import pytest

from bff.routers.optimization import _powertrain_marginal_cost_audit_payload


def _problem(*, grid_price: float = 30.0, co2_price: float = 0.0):
    vehicle_types = (
        SimpleNamespace(
            vehicle_type_id="bev-type",
            powertrain_type="BEV",
            energy_consumption_kwh_per_km=1.316,
        ),
        SimpleNamespace(
            vehicle_type_id="ice-type",
            powertrain_type="ICE",
            fuel_consumption_l_per_km=1.0 / 4.52,
            co2_emission_kg_per_l=2.585895,
        ),
    )
    return SimpleNamespace(
        vehicle_types=vehicle_types,
        vehicles=(
            SimpleNamespace(
                vehicle_type="bev-type",
                energy_consumption_kwh_per_km=1.316,
            ),
            SimpleNamespace(
                vehicle_type="ice-type",
                fuel_consumption_l_per_km=1.0 / 4.52,
            ),
        ),
        price_slots=(
            SimpleNamespace(
                grid_buy_yen_per_kwh=grid_price,
                co2_factor=0.5,
            ),
        ),
        scenario=SimpleNamespace(
            diesel_price_yen_per_l=150.0,
            co2_price_per_kg=co2_price,
            ice_co2_kg_per_l=2.585895,
        ),
        depot_energy_assets={
            "depot": SimpleNamespace(
                bess_enabled=True,
                bess_charge_efficiency=0.95,
                bess_discharge_efficiency=0.95,
                bess_cycle_cost_yen_per_kwh=0.0,
                bess_initial_soc_kwh=3000.0,
                bess_terminal_soc_target_kwh=3000.0,
            )
        },
        metadata={
            "pv_marginal_charge_cost_yen_per_kwh": 0.0,
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "vehicle_usage_cost_semantics": "unclassified",
            "vehicle_usage_cost_semantics_classified": False,
        },
    )


def test_grid_only_marginal_cost_prefers_ice_at_30_jpy() -> None:
    audit = _powertrain_marginal_cost_audit_payload(_problem())
    costs = audit["marginal_costs_jpy_per_km"]

    assert audit["status"] == "OK"
    assert costs["bev_grid"] == pytest.approx(1.316 / 0.95 * 30.0)
    assert costs["ice_total"] == pytest.approx((1.0 / 4.52) * 150.0)
    assert costs["bev_grid"] > costs["ice_total"]
    assert audit["grid_only_cheapest_powertrain"] == "ICE"
    assert audit["economic_claim_blocked"] is True


def test_tariff_below_break_even_reverses_energy_cost_ordering() -> None:
    audit = _powertrain_marginal_cost_audit_payload(
        _problem(grid_price=20.0)
    )
    costs = audit["marginal_costs_jpy_per_km"]

    assert costs["bev_grid"] < costs["ice_total"]
    assert audit["grid_only_cheapest_powertrain"] == "BEV"


def test_pv_bess_formula_does_not_credit_initial_inventory() -> None:
    audit = _powertrain_marginal_cost_audit_payload(_problem())

    assert audit["marginal_costs_jpy_per_km"]["bev_pv_bess"] == 0.0
    assert "bess_initial_soc_kwh" not in audit["coefficients"]
