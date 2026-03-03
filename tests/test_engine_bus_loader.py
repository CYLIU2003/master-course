"""
tests/test_engine_bus_loader.py

Unit tests for src/engine_bus_loader.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.engine_bus_loader import (
    DEFAULT_LIFETIME_YEAR,
    DEFAULT_OPERATION_DAYS_PER_YEAR,
    DEFAULT_RESIDUAL_VALUE_YEN,
    build_mixed_fleet_config,
    get_engine_bus_by_id,
    load_engine_bus_library,
)
from src.route_cost_simulator import SimConfig, TariffSpec, TripSpec, VehicleSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_ENTRIES = [
    {
        "vehicle_id": "test_coach_01",
        "vehicle_type": "engine_bus",
        "selection_mode": "representative",
        "manufacturer": "TestCo",
        "model_code": "TC-COACH",
        "bus_category": "coach_bus",
        "passenger_capacity": 40,
        "fuel_economy_km_per_L": 5.66,
        "diesel_consumption_L_per_km": 0.176678,
        "co2_g_per_km": 456.9,
    },
    {
        "vehicle_id": "test_route_02",
        "vehicle_type": "engine_bus",
        "selection_mode": "conservative",
        "manufacturer": "TestCo",
        "model_code": "TC-ROUTE",
        "bus_category": "route_bus",
        "passenger_capacity": 79,
        "fuel_economy_km_per_L": 5.38,
        "diesel_consumption_L_per_km": 0.185874,
        "co2_g_per_km": 480.7,
    },
]


@pytest.fixture
def sample_library_path(tmp_path: Path) -> Path:
    """Write a minimal library JSON to a temp file and return its path."""
    p = tmp_path / "library.json"
    p.write_text(json.dumps(_SAMPLE_ENTRIES), encoding="utf-8")
    return p


def make_ev_spec(vehicle_id: str = "ev_01") -> VehicleSpec:
    return VehicleSpec(
        vehicle_id=vehicle_id,
        vehicle_type="ev_bus",
        battery_capacity_kWh=300.0,
        usable_battery_capacity_kWh=270.0,
        initial_soc=1.0,
        energy_consumption_kWh_per_km_base=1.2,
        charging_power_max_kW=90.0,
        purchase_cost_yen=50_000_000,
        lifetime_year=12.0,
        operation_days_per_year=300.0,
    )


def make_trip(trip_id: str = "t01") -> TripSpec:
    return TripSpec(
        trip_id=trip_id,
        route_id="R1",
        start_time="08:00",
        end_time="09:00",
        distance_km=30.0,
    )


# ---------------------------------------------------------------------------
# load_engine_bus_library
# ---------------------------------------------------------------------------


class TestLoadEnginesBusLibrary:
    def test_returns_list(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        assert isinstance(result, list)

    def test_count_matches_json(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        assert len(result) == 2

    def test_all_vehicle_spec_instances(self, sample_library_path: Path):
        for spec in load_engine_bus_library(sample_library_path):
            assert isinstance(spec, VehicleSpec)

    def test_vehicle_type_is_engine_bus(self, sample_library_path: Path):
        for spec in load_engine_bus_library(sample_library_path):
            assert spec.vehicle_type == "engine_bus"

    def test_vehicle_ids_preserved(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        ids = {v.vehicle_id for v in result}
        assert ids == {"test_coach_01", "test_route_02"}

    def test_fuel_economy_preserved(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        coach = next(v for v in result if v.vehicle_id == "test_coach_01")
        assert abs(coach.fuel_economy_km_per_L - 5.66) < 1e-6

    def test_diesel_consumption_preserved(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        route = next(v for v in result if v.vehicle_id == "test_route_02")
        assert abs(route.diesel_consumption_L_per_km - 0.185874) < 1e-6

    def test_passenger_capacity_preserved(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        coach = next(v for v in result if v.vehicle_id == "test_coach_01")
        assert coach.passenger_capacity == 40

    def test_defaults_lifetime_year(self, sample_library_path: Path):
        for spec in load_engine_bus_library(sample_library_path):
            assert spec.lifetime_year == DEFAULT_LIFETIME_YEAR

    def test_defaults_operation_days(self, sample_library_path: Path):
        for spec in load_engine_bus_library(sample_library_path):
            assert spec.operation_days_per_year == DEFAULT_OPERATION_DAYS_PER_YEAR

    def test_defaults_residual_value(self, sample_library_path: Path):
        for spec in load_engine_bus_library(sample_library_path):
            assert spec.residual_value_yen == DEFAULT_RESIDUAL_VALUE_YEN

    def test_purchase_cost_coach_default(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        coach = next(v for v in result if v.vehicle_id == "test_coach_01")
        assert coach.purchase_cost_yen > 0

    def test_purchase_cost_route_default(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        route = next(v for v in result if v.vehicle_id == "test_route_02")
        assert route.purchase_cost_yen > 0

    def test_fuel_tank_capacity_coach(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        coach = next(v for v in result if v.vehicle_id == "test_coach_01")
        assert coach.fuel_tank_capacity_L > 0

    def test_fuel_tank_capacity_route(self, sample_library_path: Path):
        result = load_engine_bus_library(sample_library_path)
        route = next(v for v in result if v.vehicle_id == "test_route_02")
        assert route.fuel_tank_capacity_L > 0

    def test_coach_and_route_may_have_different_defaults(
        self, sample_library_path: Path
    ):
        result = load_engine_bus_library(sample_library_path)
        coach = next(v for v in result if v.vehicle_id == "test_coach_01")
        route = next(v for v in result if v.vehicle_id == "test_route_02")
        # Coach bus default purchase cost >= route bus default purchase cost
        assert coach.purchase_cost_yen >= route.purchase_cost_yen

    def test_default_library_path_exists(self):
        """The bundled library JSON must exist at its default path."""
        specs = load_engine_bus_library()
        assert len(specs) > 0

    def test_default_library_has_18_entries(self):
        specs = load_engine_bus_library()
        assert len(specs) == 18

    def test_default_library_all_engine_bus(self):
        for spec in load_engine_bus_library():
            assert spec.vehicle_type == "engine_bus"

    def test_diesel_derivation_post_init(self, sample_library_path: Path):
        """VehicleSpec.__post_init__ derives diesel_consumption if 0."""
        # Use an entry with fuel_economy only
        entry = [
            {
                "vehicle_id": "derived_01",
                "vehicle_type": "engine_bus",
                "bus_category": "route_bus",
                "passenger_capacity": 50,
                "fuel_economy_km_per_L": 4.0,
                "diesel_consumption_L_per_km": 0.0,
            }
        ]
        p = sample_library_path.parent / "derived_lib.json"
        p.write_text(json.dumps(entry), encoding="utf-8")
        result = load_engine_bus_library(p)
        assert len(result) == 1
        spec = result[0]
        assert abs(spec.diesel_consumption_L_per_km - 0.25) < 1e-6


# ---------------------------------------------------------------------------
# get_engine_bus_by_id
# ---------------------------------------------------------------------------


class TestGetEnginesBusByID:
    def test_found(self, sample_library_path: Path):
        spec = get_engine_bus_by_id("test_coach_01", sample_library_path)
        assert spec.vehicle_id == "test_coach_01"

    def test_not_found_raises_key_error(self, sample_library_path: Path):
        with pytest.raises(KeyError, match="nonexistent_id"):
            get_engine_bus_by_id("nonexistent_id", sample_library_path)

    def test_returns_vehicle_spec(self, sample_library_path: Path):
        spec = get_engine_bus_by_id("test_route_02", sample_library_path)
        assert isinstance(spec, VehicleSpec)

    def test_correct_fuel_economy(self, sample_library_path: Path):
        spec = get_engine_bus_by_id("test_route_02", sample_library_path)
        assert abs(spec.fuel_economy_km_per_L - 5.38) < 1e-6


# ---------------------------------------------------------------------------
# build_mixed_fleet_config
# ---------------------------------------------------------------------------


class TestBuildMixedFleetConfig:
    def test_returns_sim_config(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [make_ev_spec()],
            [make_trip()],
            library_path=sample_library_path,
        )
        assert isinstance(cfg, SimConfig)

    def test_fleet_contains_both_types(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [make_ev_spec("ev_A")],
            [make_trip()],
            library_path=sample_library_path,
        )
        types = {v.vehicle_type for v in cfg.fleet}
        assert "ev_bus" in types
        assert "engine_bus" in types

    def test_fleet_size(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01", "test_route_02"],
            [make_ev_spec("ev_A"), make_ev_spec("ev_B")],
            [make_trip()],
            library_path=sample_library_path,
        )
        assert len(cfg.fleet) == 4

    def test_ev_first_in_fleet(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [make_ev_spec("ev_A")],
            [make_trip()],
            library_path=sample_library_path,
        )
        assert cfg.fleet[0].vehicle_type == "ev_bus"
        assert cfg.fleet[1].vehicle_type == "engine_bus"

    def test_trips_preserved(self, sample_library_path: Path):
        trips = [make_trip("t01"), make_trip("t02")]
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            trips,
            library_path=sample_library_path,
        )
        assert len(cfg.trips) == 2

    def test_diesel_price_set(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            diesel_price_yen_per_L=170.0,
            library_path=sample_library_path,
        )
        assert cfg.diesel_price_yen_per_L == 170.0

    def test_label_set(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            label="my_test_scenario",
            library_path=sample_library_path,
        )
        assert cfg.label == "my_test_scenario"

    def test_default_tariff_if_none(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            library_path=sample_library_path,
        )
        assert isinstance(cfg.tariff, TariffSpec)

    def test_custom_tariff(self, sample_library_path: Path):
        tariff = TariffSpec(flat_price_yen_per_kWh=30.0)
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            tariff=tariff,
            library_path=sample_library_path,
        )
        assert cfg.tariff.flat_price_yen_per_kWh == 30.0

    def test_charger_limit_kwarg(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            charger_site_limit_kW=300.0,
            library_path=sample_library_path,
        )
        assert cfg.charger_site_limit_kW == 300.0

    def test_num_chargers_kwarg(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [],
            [make_trip()],
            num_chargers=5,
            library_path=sample_library_path,
        )
        assert cfg.num_chargers == 5

    def test_missing_engine_bus_id_raises(self, sample_library_path: Path):
        with pytest.raises(KeyError):
            build_mixed_fleet_config(
                ["does_not_exist"],
                [],
                [make_trip()],
                library_path=sample_library_path,
            )

    def test_empty_engine_bus_list(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            [],
            [make_ev_spec()],
            [make_trip()],
            library_path=sample_library_path,
        )
        assert len(cfg.fleet) == 1
        assert cfg.fleet[0].vehicle_type == "ev_bus"

    def test_delta_t_min(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            [],
            [],
            [],
            delta_t_min=60,
            library_path=sample_library_path,
        )
        assert cfg.delta_t_min == 60

    def test_time_horizon(self, sample_library_path: Path):
        cfg = build_mixed_fleet_config(
            [],
            [],
            [],
            time_horizon_hours=12.0,
            library_path=sample_library_path,
        )
        assert cfg.time_horizon_hours == 12.0

    def test_sim_config_can_run(self, sample_library_path: Path):
        """End-to-end: config produced by builder is runnable by RouteSimulator."""
        from src.route_cost_simulator import RouteSimulator

        ev = make_ev_spec("ev_run_01")
        trip = TripSpec(
            trip_id="t_run",
            route_id="R1",
            start_time="08:00",
            end_time="09:00",
            distance_km=30.0,
        )
        cfg = build_mixed_fleet_config(
            ["test_coach_01"],
            [ev],
            [trip],
            library_path=sample_library_path,
            delta_t_min=60,
        )
        sim = RouteSimulator(cfg)
        result = sim.run()
        assert result is not None
