from __future__ import annotations

import pytest

from src.optimization.common.powertrain_economics import (
    audit_candidate_powertrain_diversity,
    audit_powertrain_marginal_costs,
)


def test_flat_30_yen_tariff_is_not_bev_advantage_with_current_bus_inputs() -> None:
    audit = audit_powertrain_marginal_costs(
        electricity_price_jpy_per_kwh=30.0,
        bev_energy_kwh_per_km=1.316,
        bev_charge_efficiency=0.95,
        diesel_price_jpy_per_litre=150.0,
        ice_fuel_litre_per_km=1.0 / 4.52,
        ice_co2_kg_per_litre=2.585895,
        grid_co2_kg_per_kwh=0.0,
        co2_price_jpy_per_kg=0.0,
    )

    assert audit.bev_grid_energy_cost_jpy_per_km == pytest.approx(41.5578947)
    assert audit.ice_fuel_cost_jpy_per_km == pytest.approx(33.1858407)
    assert audit.break_even_electricity_price_jpy_per_kwh == pytest.approx(23.956344)
    assert audit.bev_is_marginally_cheaper is False
    assert audit.required_co2_price_for_bev_break_even_jpy_per_kg == pytest.approx(
        14.6338827
    )


def test_explicit_carbon_price_can_make_bev_marginally_cheaper_for_clean_grid() -> None:
    audit = audit_powertrain_marginal_costs(
        electricity_price_jpy_per_kwh=30.0,
        bev_energy_kwh_per_km=1.316,
        bev_charge_efficiency=0.95,
        diesel_price_jpy_per_litre=150.0,
        ice_fuel_litre_per_km=1.0 / 4.52,
        ice_co2_kg_per_litre=2.585895,
        grid_co2_kg_per_kwh=0.0,
        co2_price_jpy_per_kg=15.0,
    )

    assert audit.bev_is_marginally_cheaper is True
    assert audit.bev_minus_ice_jpy_per_km < 0.0
    assert audit.nonnegative_co2_price_can_make_bev_break_even is True


def test_current_grid_factor_has_no_nonnegative_carbon_break_even() -> None:
    audit = audit_powertrain_marginal_costs(
        electricity_price_jpy_per_kwh=30.0,
        bev_energy_kwh_per_km=1.316,
        bev_charge_efficiency=0.95,
        diesel_price_jpy_per_litre=150.0,
        ice_fuel_litre_per_km=1.0 / 4.52,
        ice_co2_kg_per_litre=2.585895,
        grid_co2_kg_per_kwh=0.5,
        co2_price_jpy_per_kg=1.0,
    )

    assert audit.bev_grid_co2_kg_per_km == pytest.approx(0.692631579)
    assert audit.ice_co2_kg_per_km == pytest.approx(0.572100664)
    assert audit.required_co2_price_for_bev_break_even_jpy_per_kg is None
    assert audit.nonnegative_co2_price_can_make_bev_break_even is False
    assert audit.bev_is_marginally_cheaper is False


def test_candidate_diversity_detects_frozen_fleet_composition() -> None:
    audit = audit_candidate_powertrain_diversity(
        [
            {"used_bev": 13, "used_ice": 19, "bev_trips": 43, "ice_trips": 221},
            {"used_bev": 13, "used_ice": 19, "bev_trips": 44, "ice_trips": 220},
        ]
    )

    assert audit["powertrain_fleet_count_frozen"] is True
    assert audit["fleet_composition_search_verified"] is False
    assert audit["distinct_trip_powertrain_split_count"] == 2


def test_candidate_diversity_accepts_count_changing_candidates() -> None:
    audit = audit_candidate_powertrain_diversity(
        [
            {"used_bev": 13, "used_ice": 19, "bev_trips": 44, "ice_trips": 220},
            {"used_bev": 14, "used_ice": 18, "bev_trips": 57, "ice_trips": 207},
        ]
    )

    assert audit["powertrain_fleet_count_frozen"] is False
    assert audit["fleet_composition_search_verified"] is True


def test_invalid_charge_efficiency_fails_closed() -> None:
    with pytest.raises(ValueError, match="bev_charge_efficiency"):
        audit_powertrain_marginal_costs(
            electricity_price_jpy_per_kwh=30.0,
            bev_energy_kwh_per_km=1.316,
            bev_charge_efficiency=0.0,
            diesel_price_jpy_per_litre=150.0,
            ice_fuel_litre_per_km=1.0 / 4.52,
        )
