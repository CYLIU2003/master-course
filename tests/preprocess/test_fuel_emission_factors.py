"""Diesel CO2 factor: one sourced value, derived from the statutory table."""

import pytest

from bff.services.ice_vehicle_reference import apply_ice_reference_defaults
from src.optimization.common.problem import OptimizationScenario
from src.fuel_emission_factors import (
    DIESEL_CO2_KG_PER_L, DIESEL_CO2_KG_PER_L_EXACT, DIESEL_CO2_SOURCE, diesel_co2_g_per_km,
)
from src.scenario_overlay import CostConfig


def test_factor_is_the_statutory_product_rounded_to_published_precision():
    assert DIESEL_CO2_KG_PER_L_EXACT == pytest.approx(38.0 * 0.0188 * 44 / 12)
    assert DIESEL_CO2_KG_PER_L_EXACT == pytest.approx(2.61947, abs=1e-5)
    assert DIESEL_CO2_KG_PER_L == round(DIESEL_CO2_KG_PER_L_EXACT, 2) == 2.62
    assert DIESEL_CO2_SOURCE['boundary'] == 'tank_to_wheel_combustion_co2_scope1'


def test_operation_co2_per_km_uses_the_stated_fuel_efficiency():
    assert diesel_co2_g_per_km(4.52) == pytest.approx(2620 / 4.52)
    with pytest.raises(ValueError):
        diesel_co2_g_per_km(0)


def test_scenario_and_problem_defaults_use_the_sourced_factor():
    assert CostConfig().ice_co2_kg_per_l == DIESEL_CO2_KG_PER_L
    assert OptimizationScenario.__dataclass_fields__['ice_co2_kg_per_l'].default == DIESEL_CO2_KG_PER_L


def test_ice_reference_fills_fuel_factor_without_backing_it_out_of_catalog_g_per_km():
    filled = apply_ice_reference_defaults({'type': 'ICE', 'modelCode': '2KG-MP38FK'})
    assert filled['co2EmissionKgPerL'] == DIESEL_CO2_KG_PER_L
    # The catalog g/km (computed with the old 2.58 factor) is kept only as a reference.
    assert filled['co2EmissionGPerKm'] == 572.0


def test_explicit_vehicle_factor_is_never_overwritten():
    kept = apply_ice_reference_defaults({'type': 'ICE', 'modelCode': '2KG-MP38FK', 'co2EmissionKgPerL': 2.5})
    assert kept['co2EmissionKgPerL'] == 2.5
