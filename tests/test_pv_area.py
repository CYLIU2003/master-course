from __future__ import annotations

import pytest

from src.optimization.common.pv_area import estimate_depot_pv_area_from_capacity


def test_reverse_estimate_from_rated_output_uses_declared_units() -> None:
    estimate = estimate_depot_pv_area_from_capacity(
        120.0,
        usable_area_ratio=0.35,
        panel_power_density_kw_m2=0.20,
    )

    assert estimate.capacity_kw == 120.0
    assert estimate.required_installable_area_m2 == 600.0
    assert estimate.estimated_depot_area_m2 == pytest.approx(1714.2857142857142)
    assert (
        estimate.required_installable_area_m2
        * estimate.panel_power_density_kw_m2
    ) == estimate.capacity_kw


def test_reverse_estimate_clamps_negative_capacity_to_zero() -> None:
    estimate = estimate_depot_pv_area_from_capacity(-1.0)

    assert estimate.capacity_kw == 0.0
    assert estimate.required_installable_area_m2 == 0.0
    assert estimate.estimated_depot_area_m2 == 0.0
