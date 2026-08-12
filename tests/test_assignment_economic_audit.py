from __future__ import annotations

from types import SimpleNamespace

import pytest

from bff.routers.optimization import _assignment_economic_audit_payload


def test_assignment_economic_audit_uses_charge_efficiency_and_excludes_initial_bess() -> None:
    problem = SimpleNamespace(
        price_slots=(
            SimpleNamespace(grid_buy_yen_per_kwh=30.0),
        ),
        vehicles=(
            SimpleNamespace(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                energy_consumption_kwh_per_km=1.316,
            ),
            SimpleNamespace(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                fuel_consumption_l_per_km=0.2212389,
            ),
        ),
        vehicle_types=(),
        scenario=SimpleNamespace(diesel_price_yen_per_l=150.0),
    )
    audit = _assignment_economic_audit_payload(
        canonical_problem=problem,
        optimization_result={
            "solver_metadata": {
                "stage1_time_indexed_energy_recourse_configuration": {
                    "semantics": (
                        "slot_level_assignment_coupled_continuous_energy_recourse"
                    ),
                    "stage2_authority": "fixed_assignment_binary_dispatch",
                },
                "stage1_time_indexed_energy_recourse_weather_input": {
                    "pv_available_kwh_by_depot": {"depot": 614.709375},
                },
                "stage1_time_indexed_energy_recourse_result": {
                    "pv_to_bus_kwh": 50.0,
                    "pv_to_bess_kwh": 100.0,
                    "bess_to_bus_kwh": 90.25,
                    "grid_to_bus_kwh": 20.0,
                    "grid_to_bess_kwh": 5.0,
                },
                "stage1_stage2_candidate_evaluation": [
                    {"bev_trips": 43},
                ],
                "stage1_stage2_selected_candidate_index": 1,
            },
            "summary": {"trip_count_by_type": {"BEV": 43, "ICE": 221}},
        },
    )

    assert audit["bev_grid_marginal_cost_jpy_per_km"] == pytest.approx(
        1.316 / 0.95 * 30.0
    )
    assert audit["ice_marginal_cost_jpy_per_km"] == pytest.approx(
        0.2212389 * 150.0
    )
    assert audit["grid_energy_break_even_jpy_per_kwh"] == pytest.approx(
        (0.2212389 * 150.0) * 0.95 / 1.316
    )
    assert audit["renewable_budget_kwh"] is None
    assert audit["gross_pv_available_kwh"] == pytest.approx(614.709375)
    assert audit["renewable_energy_allocated_in_stage1_kwh"] == pytest.approx(
        150.0
    )
    assert audit["initial_bess_inventory_counted_as_free_kwh"] == 0.0
    assert audit["stage1_bev_trip_count"] == 43
    assert audit["stage2_bev_trip_count"] == 43


def test_assignment_economic_audit_resolves_canonical_type_ids() -> None:
    """Marginal-cost audit must use powertrain_type, not a type-id spelling."""

    problem = SimpleNamespace(
        price_slots=(SimpleNamespace(grid_buy_yen_per_kwh=30.0),),
        vehicles=(
            SimpleNamespace(
                vehicle_id="bev-1",
                vehicle_type="BYD_K8",
                energy_consumption_kwh_per_km=None,
            ),
            SimpleNamespace(
                vehicle_id="ice-1",
                vehicle_type="DIESEL_LARGE",
                fuel_consumption_l_per_km=None,
            ),
        ),
        vehicle_types=(
            SimpleNamespace(
                vehicle_type_id="BYD_K8",
                powertrain_type="BEV",
                energy_consumption_kwh_per_km=1.316,
            ),
            SimpleNamespace(
                vehicle_type_id="DIESEL_LARGE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=0.2212389,
            ),
        ),
        scenario=SimpleNamespace(diesel_price_yen_per_l=150.0),
    )

    audit = _assignment_economic_audit_payload(
        canonical_problem=problem,
        optimization_result={},
    )

    assert audit["bev_grid_marginal_cost_jpy_per_km"] == pytest.approx(
        1.316 / 0.95 * 30.0
    )
    assert audit["ice_marginal_cost_jpy_per_km"] == pytest.approx(
        0.2212389 * 150.0
    )
    assert audit["grid_energy_break_even_jpy_per_kwh"] == pytest.approx(
        (0.2212389 * 150.0) * 0.95 / 1.316
    )


def test_assignment_economic_audit_keeps_pv_input_without_an_incumbent() -> None:
    """A failed Phase-4 solve must not make the input PV curve look empty."""

    problem = SimpleNamespace(
        price_slots=(),
        vehicles=(),
        vehicle_types=(),
        scenario=SimpleNamespace(diesel_price_yen_per_l=150.0),
        depot_energy_assets={
            "depot": SimpleNamespace(
                pv_enabled=True,
                pv_generation_kwh_by_slot=(0.0, 35.7, 155.55, 0.0),
            ),
            "disabled": SimpleNamespace(
                pv_enabled=False,
                pv_generation_kwh_by_slot=(999.0,),
            ),
        },
    )

    audit = _assignment_economic_audit_payload(
        canonical_problem=problem,
        optimization_result={
            "solver_metadata": {
                "has_feasible_incumbent": False,
                "stage1_time_indexed_energy_recourse_weather_input": {},
                "stage1_time_indexed_energy_recourse_result": {},
            },
        },
    )

    assert audit["gross_pv_available_kwh"] == pytest.approx(191.25)
    assert audit["renewable_energy_allocated_in_stage1_kwh"] == 0.0
    assert audit["grid_energy_allocated_in_stage1_kwh"] == 0.0


def test_assignment_economic_audit_uses_phase4_integrated_source_flows() -> None:
    problem = SimpleNamespace(
        price_slots=(SimpleNamespace(grid_buy_yen_per_kwh=30.0),),
        vehicles=(),
        vehicle_types=(),
        scenario=SimpleNamespace(diesel_price_yen_per_l=150.0),
        depot_energy_assets={},
    )

    audit = _assignment_economic_audit_payload(
        canonical_problem=problem,
        optimization_result={
            "solver_metadata": {
                "assignment_energy_coupling_mode": (
                    "phase4_integrated_slot_energy_recourse"
                ),
            },
            "cost_breakdown": {
                "pv_to_bus_kwh": 10.0,
                "pv_to_bess_kwh": 20.0,
                "bess_to_bus_kwh": 15.0,
                "grid_to_bus_kwh": 2.0,
                "grid_to_bess_kwh": 3.0,
            },
            "summary": {},
        },
    )

    assert audit["assignment_energy_coupling_mode"] == (
        "phase4_integrated_slot_energy_recourse"
    )
    assert audit["renewable_energy_allocated_in_stage1_kwh"] == 30.0
    assert audit["grid_energy_allocated_in_stage1_kwh"] == 5.0
    assert audit["stage1_source_flows_kwh"]["bess_to_bus_kwh"] == 15.0


def test_assignment_economic_audit_uses_canonical_objective_preset_fallback() -> None:
    problem = SimpleNamespace(
        price_slots=(),
        vehicles=(),
        vehicle_types=(),
        scenario=SimpleNamespace(diesel_price_yen_per_l=150.0),
        depot_energy_assets={},
        metadata={"objective_preset": "research_lexicographic_v1"},
    )

    audit = _assignment_economic_audit_payload(
        canonical_problem=problem,
        optimization_result={"solver_metadata": {}},
    )

    assert audit["objective_preset"] == "research_lexicographic_v1"
