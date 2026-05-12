from __future__ import annotations

import pytest

from src.preprocess.emission_factor_loader import lookup_ice_emission_factor


def test_emission_factor_loader_prefers_vehicle_catalog_values() -> None:
    factor = lookup_ice_emission_factor("2KG-LV290N4")

    assert factor is not None
    assert factor["co2EmissionKgPerL"] == 2.67
    assert factor["fuelConsumptionLPerKm"] == 0.1869
    assert factor["fuelEfficiencyKmPerL"] == 5.35


def test_emission_factor_loader_falls_back_to_engine_library() -> None:
    factor = lookup_ice_emission_factor("2DG-RU2AHDA")

    assert factor is not None
    assert factor["fuelConsumptionLPerKm"] == 0.176678
    assert factor["fuelEfficiencyKmPerL"] == 5.66
    assert factor["co2EmissionKgPerL"] == pytest.approx(
        (456.92932862190816 / 1000.0) / 0.176678,
        rel=1.0e-6,
    )

