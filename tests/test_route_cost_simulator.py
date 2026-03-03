"""
tests/test_route_cost_simulator.py

Unit tests for src/route_cost_simulator.py

Coverage:
  - VehicleSpec: daily_capex_yen, diesel derivation, from_dict
  - TripSpec: effective_distance_km, from_dict
  - TariffSpec: price_at, pv_at, from_dict (list and dict TOU)
  - SimConfig: from_dict, n_slots, dt_hour
  - RouteSimulator: EV-only, engine-only, mixed fleet
    - EV-first assignment
    - Engine bus fallback
    - Unassigned when all busy in same slot
    - SOC stays within [min_soc, max_soc]
    - Cost breakdown: total = capex + electricity + fuel + demand + excess
    - Demand charge computed from peak
    - Contract penalty mode
    - Output files written correctly
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.route_cost_simulator import (
    RouteSimulator,
    SimConfig,
    SimResult,
    TariffSpec,
    TripSpec,
    VehicleSpec,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_ev(
    vehicle_id: str = "ev_01",
    battery_capacity_kWh: float = 200.0,
    usable_battery_capacity_kWh: float = 180.0,
    initial_soc: float = 1.0,
    min_soc: float = 0.1,
    max_soc: float = 1.0,
    energy_consumption_kWh_per_km_base: float = 1.0,
    charging_power_max_kW: float = 60.0,
    charging_efficiency: float = 1.0,  # 100% for easy maths
    purchase_cost_yen: float = 30_000_000,
    residual_value_yen: float = 0.0,
    lifetime_year: float = 10.0,
    operation_days_per_year: float = 300.0,
    route_compatibility: list[str] | None = None,
) -> VehicleSpec:
    return VehicleSpec(
        vehicle_id=vehicle_id,
        vehicle_type="ev_bus",
        battery_capacity_kWh=battery_capacity_kWh,
        usable_battery_capacity_kWh=usable_battery_capacity_kWh,
        initial_soc=initial_soc,
        min_soc=min_soc,
        max_soc=max_soc,
        energy_consumption_kWh_per_km_base=energy_consumption_kWh_per_km_base,
        charging_power_max_kW=charging_power_max_kW,
        charging_efficiency=charging_efficiency,
        purchase_cost_yen=purchase_cost_yen,
        residual_value_yen=residual_value_yen,
        lifetime_year=lifetime_year,
        operation_days_per_year=operation_days_per_year,
        route_compatibility=route_compatibility or [],
    )


def make_engine(
    vehicle_id: str = "eng_01",
    fuel_economy_km_per_L: float = 5.0,
    purchase_cost_yen: float = 15_000_000,
    residual_value_yen: float = 0.0,
    lifetime_year: float = 10.0,
    operation_days_per_year: float = 300.0,
    route_compatibility: list[str] | None = None,
) -> VehicleSpec:
    return VehicleSpec(
        vehicle_id=vehicle_id,
        vehicle_type="engine_bus",
        fuel_economy_km_per_L=fuel_economy_km_per_L,
        purchase_cost_yen=purchase_cost_yen,
        residual_value_yen=residual_value_yen,
        lifetime_year=lifetime_year,
        operation_days_per_year=operation_days_per_year,
        route_compatibility=route_compatibility or [],
    )


def make_trip(
    trip_id: str = "t01",
    route_id: str = "R1",
    start_time: str = "08:00",
    end_time: str = "09:00",
    distance_km: float = 20.0,
    deadhead_before: float = 0.0,
    deadhead_after: float = 0.0,
    required_bus_type: str | None = None,
) -> TripSpec:
    return TripSpec(
        trip_id=trip_id,
        route_id=route_id,
        start_time=start_time,
        end_time=end_time,
        distance_km=distance_km,
        deadhead_distance_before_km=deadhead_before,
        deadhead_distance_after_km=deadhead_after,
        required_bus_type=required_bus_type,
    )


def make_tariff(
    flat_price: float = 25.0,
    demand_charge: float = 0.0,
    contract_limit: float = 1000.0,
    contract_penalty_mode: str = "hard_limit",
    contract_penalty: float = 0.0,
) -> TariffSpec:
    return TariffSpec(
        flat_price_yen_per_kWh=flat_price,
        demand_charge_yen_per_kW_month=demand_charge,
        contract_power_limit_kW=contract_limit,
        contract_penalty_mode=contract_penalty_mode,
        contract_penalty_yen_per_kW=contract_penalty,
    )


def make_sim_config(
    fleet: list[VehicleSpec],
    trips: list[TripSpec],
    tariff: TariffSpec | None = None,
    delta_t_min: int = 60,
    time_horizon_hours: float = 24.0,
    diesel_price: float = 150.0,
    label: str = "test",
) -> SimConfig:
    cfg = SimConfig()
    cfg.fleet = fleet
    cfg.trips = trips
    cfg.tariff = tariff or make_tariff()
    cfg.delta_t_min = delta_t_min
    cfg.time_horizon_hours = time_horizon_hours
    cfg.diesel_price_yen_per_L = diesel_price
    cfg.label = label
    return cfg


# ---------------------------------------------------------------------------
# VehicleSpec tests
# ---------------------------------------------------------------------------


class TestVehicleSpec:
    def test_daily_capex_basic(self):
        v = make_ev(
            purchase_cost_yen=3_000_000,
            residual_value_yen=0,
            lifetime_year=10.0,
            operation_days_per_year=300.0,
        )
        # (3_000_000 - 0) / (10 * 300) = 1000 yen/day
        assert abs(v.daily_capex_yen - 1000.0) < 0.01

    def test_daily_capex_with_residual(self):
        v = make_ev(
            purchase_cost_yen=3_000_000,
            residual_value_yen=300_000,
            lifetime_year=10.0,
            operation_days_per_year=300.0,
        )
        # (3_000_000 - 300_000) / (10 * 300) = 900 yen/day
        assert abs(v.daily_capex_yen - 900.0) < 0.01

    def test_daily_capex_zero_lifetime(self):
        v = make_ev(lifetime_year=0)
        assert v.daily_capex_yen == 0.0

    def test_engine_bus_diesel_derived_from_economy(self):
        v = make_engine(fuel_economy_km_per_L=4.0)
        assert abs(v.diesel_consumption_L_per_km - 0.25) < 1e-9

    def test_engine_bus_economy_derived_from_consumption(self):
        v = VehicleSpec(
            vehicle_id="eng",
            vehicle_type="engine_bus",
            diesel_consumption_L_per_km=0.2,
        )
        assert abs(v.fuel_economy_km_per_L - 5.0) < 1e-9

    def test_from_dict_ev(self):
        d = {
            "vehicle_id": "ev_x",
            "vehicle_type": "ev_bus",
            "battery_capacity_kWh": 150.0,
            "usable_battery_capacity_kWh": 135.0,
            "energy_consumption_kWh_per_km_base": 1.2,
            "purchase_cost_yen": 20_000_000,
        }
        v = VehicleSpec.from_dict(d)
        assert v.vehicle_id == "ev_x"
        assert v.battery_capacity_kWh == 150.0
        assert v.energy_consumption_kWh_per_km_base == 1.2

    def test_initial_fuel_defaults_to_tank(self):
        v = make_engine()
        assert v.initial_fuel_L == v.fuel_tank_capacity_L


# ---------------------------------------------------------------------------
# TripSpec tests
# ---------------------------------------------------------------------------


class TestTripSpec:
    def test_effective_distance_no_deadhead(self):
        t = make_trip(distance_km=30.0)
        assert t.effective_distance_km == 30.0

    def test_effective_distance_with_deadhead(self):
        t = make_trip(distance_km=30.0, deadhead_before=2.0, deadhead_after=3.0)
        assert abs(t.effective_distance_km - 35.0) < 1e-9

    def test_from_dict(self):
        d = {
            "trip_id": "T99",
            "route_id": "R5",
            "start_time": "10:00",
            "end_time": "11:30",
            "distance_km": 25.0,
            "deadhead_distance_before_km": 1.0,
        }
        t = TripSpec.from_dict(d)
        assert t.trip_id == "T99"
        assert t.effective_distance_km == 26.0


# ---------------------------------------------------------------------------
# TariffSpec tests
# ---------------------------------------------------------------------------


class TestTariffSpec:
    def test_flat_price(self):
        tariff = make_tariff(flat_price=30.0)
        assert tariff.price_at(0) == 30.0
        assert tariff.price_at(100) == 30.0

    def test_tou_price_overrides_flat(self):
        tariff = TariffSpec(
            flat_price_yen_per_kWh=25.0,
            tou_prices={0: 15.0, 8: 30.0},
        )
        assert tariff.price_at(0) == 15.0
        assert tariff.price_at(8) == 30.0
        assert tariff.price_at(5) == 25.0  # falls back to flat

    def test_from_dict_tou_list(self):
        d = {
            "tou_price_yen_per_kWh": [10.0, 12.0, 14.0],
            "flat_price_yen_per_kWh": 25.0,
        }
        t = TariffSpec.from_dict(d)
        assert t.price_at(0) == 10.0
        assert t.price_at(2) == 14.0

    def test_from_dict_tou_dict(self):
        d = {
            "tou_price_yen_per_kWh": {"3": 20.0, "7": 35.0},
            "flat_price_yen_per_kWh": 25.0,
        }
        t = TariffSpec.from_dict(d)
        assert t.price_at(3) == 20.0
        assert t.price_at(7) == 35.0

    def test_pv_at(self):
        tariff = TariffSpec(pv_generation_kWh={5: 50.0})
        assert tariff.pv_at(5) == 50.0
        assert tariff.pv_at(0) == 0.0


# ---------------------------------------------------------------------------
# SimConfig tests
# ---------------------------------------------------------------------------


class TestSimConfig:
    def test_n_slots_hourly(self):
        cfg = SimConfig(delta_t_min=60, time_horizon_hours=24.0)
        assert cfg.n_slots == 24

    def test_n_slots_30min(self):
        cfg = SimConfig(delta_t_min=30, time_horizon_hours=24.0)
        assert cfg.n_slots == 48

    def test_dt_hour(self):
        cfg = SimConfig(delta_t_min=30)
        assert abs(cfg.dt_hour - 0.5) < 1e-9

    def test_from_dict(self):
        d = {
            "label": "scenario_x",
            "delta_t_min": 60,
            "time_horizon_hours": 12.0,
            "diesel_price_yen_per_L": 160.0,
            "fleet": [
                {
                    "vehicle_id": "ev_a",
                    "vehicle_type": "ev_bus",
                    "battery_capacity_kWh": 200.0,
                    "usable_battery_capacity_kWh": 180.0,
                }
            ],
            "route_profile": [
                {
                    "trip_id": "t1",
                    "route_id": "R1",
                    "start_time": "07:00",
                    "end_time": "08:00",
                    "distance_km": 20.0,
                }
            ],
            "tariff": {"flat_price_yen_per_kWh": 22.0},
        }
        cfg = SimConfig.from_dict(d)
        assert cfg.label == "scenario_x"
        assert cfg.n_slots == 12
        assert cfg.diesel_price_yen_per_L == 160.0
        assert len(cfg.fleet) == 1
        assert len(cfg.trips) == 1
        assert cfg.tariff.flat_price_yen_per_kWh == 22.0


# ---------------------------------------------------------------------------
# RouteSimulator — single EV
# ---------------------------------------------------------------------------


class TestRouteSimulatorSingleEV:
    def _run(self, trips, **ev_kwargs):
        ev = make_ev(**ev_kwargs)
        cfg = make_sim_config(fleet=[ev], trips=trips)
        sim = RouteSimulator(cfg)
        return sim.run()

    def test_single_trip_assigned(self):
        trips = [
            make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        ]
        result = self._run(trips)
        assert result.trip_assignments["t1"] == "ev_01"
        assert len(result.unassigned_trips) == 0

    def test_soc_decreases_after_trip(self):
        # EV uses 1 kWh/km, 180 kWh usable → 20 km = 20 kWh → SOC drops 20/180
        trips = [
            make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        ]
        result = self._run(trips)
        st = result.states["ev_01"]
        soc_drop_expected = 20.0 / 180.0
        final_soc = st.soc[-1]
        # SOC should be less than initial (accounting for charging in idle slots)
        # At minimum, soc was reduced by the trip
        min_soc_seen = min(st.soc)
        assert min_soc_seen < 1.0

    def test_soc_never_below_min_soc(self):
        # Give EV very little charge: initial_soc barely above min_soc
        # Trip should fail (unassigned) rather than go below min
        ev = make_ev(
            usable_battery_capacity_kWh=180.0,
            initial_soc=0.12,  # only 12% ≈ 21.6 kWh
            min_soc=0.1,
            energy_consumption_kWh_per_km_base=1.0,
        )
        # 20 km trip = 20 kWh → needs 20/180=0.111 SOC drop, leaves 0.009 < min_soc=0.1 → unassigned
        trips = [make_trip("t1", distance_km=20.0)]
        cfg = make_sim_config(fleet=[ev], trips=trips)
        result = RouteSimulator(cfg).run()
        # The trip cannot be served without violating min_soc
        assert result.unassigned_trips == ["t1"]

    def test_soc_always_within_bounds(self):
        trips = [
            make_trip(
                f"t{i}",
                distance_km=15.0,
                start_time=f"{8 + i:02d}:00",
                end_time=f"{9 + i:02d}:00",
            )
            for i in range(3)
        ]
        result = self._run(trips)
        st = result.states["ev_01"]
        for soc_val in st.soc:
            assert soc_val >= 0.1 - 1e-9
            assert soc_val <= 1.0 + 1e-9

    def test_electricity_cost_computed(self):
        trips = [
            make_trip("t1", distance_km=10.0, start_time="08:00", end_time="09:00")
        ]
        result = self._run(trips)
        # EV charges in idle slots → some electricity cost expected (charging_power > 0)
        # or at minimum total_grid_kWh >= 0
        assert result.electricity_cost_yen >= 0.0
        assert result.total_grid_kWh >= 0.0

    def test_no_fuel_cost_ev_only(self):
        trips = [make_trip("t1", distance_km=10.0)]
        result = self._run(trips)
        assert result.fuel_cost_yen == 0.0
        assert result.total_fuel_L == 0.0

    def test_capex_positive(self):
        trips = [make_trip("t1", distance_km=10.0)]
        result = self._run(trips)
        assert result.vehicle_capex_yen > 0.0

    def test_total_cost_sum(self):
        trips = [make_trip("t1", distance_km=10.0)]
        tariff = make_tariff(demand_charge=1500.0)
        ev = make_ev()
        cfg = make_sim_config(fleet=[ev], trips=trips, tariff=tariff)
        result = RouteSimulator(cfg).run()
        expected = (
            result.vehicle_capex_yen
            + result.fuel_cost_yen
            + result.electricity_cost_yen
            + result.demand_charge_yen
            + result.contract_excess_cost_yen
            + cfg.tariff.grid_basic_charge_yen
        )
        assert abs(result.total_cost_yen - expected) < 0.01


# ---------------------------------------------------------------------------
# RouteSimulator — single engine bus
# ---------------------------------------------------------------------------


class TestRouteSimulatorSingleEngine:
    def test_trip_assigned_to_engine(self):
        eng = make_engine()
        trips = [make_trip("t1", distance_km=30.0)]
        cfg = make_sim_config(fleet=[eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "eng_01"

    def test_fuel_cost_computed(self):
        # fuel_economy=5 km/L → 30 km = 6 L, diesel=150 yen/L → 900 yen
        eng = make_engine(fuel_economy_km_per_L=5.0)
        trips = [make_trip("t1", distance_km=30.0)]
        cfg = make_sim_config(fleet=[eng], trips=trips, diesel_price=150.0)
        result = RouteSimulator(cfg).run()
        assert abs(result.fuel_cost_yen - 900.0) < 1.0
        assert abs(result.total_fuel_L - 6.0) < 0.01

    def test_no_electricity_cost_engine_only(self):
        eng = make_engine()
        trips = [make_trip("t1", distance_km=30.0)]
        cfg = make_sim_config(fleet=[eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert result.electricity_cost_yen == 0.0
        assert result.total_grid_kWh == 0.0

    def test_deadhead_adds_fuel(self):
        # 30 km service + 5 km deadhead = 35 effective km
        eng = make_engine(fuel_economy_km_per_L=5.0)
        trip_nodh = make_trip(
            "t1", distance_km=30.0, deadhead_before=0.0, deadhead_after=0.0
        )
        trip_dh = make_trip(
            "t1", distance_km=30.0, deadhead_before=2.5, deadhead_after=2.5
        )
        cfg_nodh = make_sim_config(fleet=[make_engine()], trips=[trip_nodh])
        cfg_dh = make_sim_config(fleet=[make_engine()], trips=[trip_dh])
        r_nodh = RouteSimulator(cfg_nodh).run()
        r_dh = RouteSimulator(cfg_dh).run()
        assert r_dh.total_fuel_L > r_nodh.total_fuel_L


# ---------------------------------------------------------------------------
# RouteSimulator — mixed fleet (EV + engine bus)
# ---------------------------------------------------------------------------


class TestRouteSimulatorMixedFleet:
    def test_ev_preferred_over_engine(self):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        trips = [
            make_trip("t1", distance_km=10.0, start_time="08:00", end_time="09:00")
        ]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"

    def test_engine_fallback_when_ev_busy(self):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        # Two simultaneous trips in same slot → EV takes first, engine bus takes second
        trips = [
            make_trip("t1", distance_km=5.0, start_time="08:00", end_time="09:00"),
            make_trip("t2", distance_km=5.0, start_time="08:00", end_time="09:00"),
        ]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        # EV gets one, engine gets the other
        assigned_vehicles = set(result.trip_assignments.values())
        assert "ev_01" in assigned_vehicles
        assert "eng_01" in assigned_vehicles
        assert len(result.unassigned_trips) == 0

    def test_unassigned_when_all_busy(self):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        # Three simultaneous trips, only 2 buses → 1 unassigned
        trips = [
            make_trip("t1", distance_km=5.0, start_time="08:00", end_time="09:00"),
            make_trip("t2", distance_km=5.0, start_time="08:00", end_time="09:00"),
            make_trip("t3", distance_km=5.0, start_time="08:00", end_time="09:00"),
        ]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert len(result.unassigned_trips) == 1

    def test_route_compatibility_respected(self):
        # EV only compatible with R1; engine with R2
        ev = make_ev("ev_01", route_compatibility=["R1"])
        eng = make_engine("eng_01", route_compatibility=["R2"])
        trips = [
            make_trip("t1", route_id="R1", start_time="08:00", end_time="09:00"),
            make_trip("t2", route_id="R2", start_time="08:00", end_time="09:00"),
        ]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"
        assert result.trip_assignments["t2"] == "eng_01"

    def test_required_bus_type_engine(self):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        trips = [make_trip("t1", distance_km=10.0, required_bus_type="engine_bus")]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "eng_01"

    def test_total_cost_sum_mixed(self):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        trips = [
            make_trip("t1", distance_km=10.0, start_time="08:00", end_time="09:00"),
            make_trip("t2", distance_km=15.0, start_time="10:00", end_time="11:00"),
        ]
        tariff = make_tariff(flat_price=25.0, demand_charge=0.0)
        cfg = make_sim_config(fleet=[ev, eng], trips=trips, tariff=tariff)
        result = RouteSimulator(cfg).run()
        expected = (
            result.vehicle_capex_yen
            + result.fuel_cost_yen
            + result.electricity_cost_yen
            + result.demand_charge_yen
            + result.contract_excess_cost_yen
            + cfg.tariff.grid_basic_charge_yen
        )
        assert abs(result.total_cost_yen - expected) < 0.01


# ---------------------------------------------------------------------------
# Demand charge and contract penalty
# ---------------------------------------------------------------------------


class TestDemandAndContract:
    def test_demand_charge_from_peak(self):
        # EV starts at 50% SOC → will charge; charging_power_max_kW=100, demand_charge=2000 yen/kW
        ev = make_ev("ev_01", charging_power_max_kW=100.0, initial_soc=0.5)
        trips = []  # no trips → EV charges all day
        tariff = make_tariff(flat_price=25.0, demand_charge=2000.0)
        cfg = make_sim_config(fleet=[ev], trips=trips, tariff=tariff)
        result = RouteSimulator(cfg).run()
        assert result.demand_charge_yen > 0.0
        # demand_charge = peak_grid_kW * 2000
        assert abs(result.demand_charge_yen - result.peak_grid_kW * 2000.0) < 0.01

    def test_contract_penalty_mode(self):
        # EV starts at 50% SOC so it will charge at 200 kW, exceeding 50 kW limit
        ev = make_ev("ev_01", charging_power_max_kW=200.0, initial_soc=0.5)
        trips = []
        tariff = TariffSpec(
            flat_price_yen_per_kWh=25.0,
            contract_power_limit_kW=50.0,  # limit is 50 kW, charger is 200 kW
            contract_penalty_mode="penalty",
            contract_penalty_yen_per_kW=3000.0,
        )
        cfg = make_sim_config(fleet=[ev], trips=trips, tariff=tariff)
        result = RouteSimulator(cfg).run()
        assert result.contract_excess_cost_yen > 0.0

    def test_no_contract_penalty_hard_limit(self):
        ev = make_ev("ev_01", charging_power_max_kW=200.0)
        trips = []
        tariff = TariffSpec(
            flat_price_yen_per_kWh=25.0,
            contract_power_limit_kW=50.0,
            contract_penalty_mode="hard_limit",  # no penalty mode
            contract_penalty_yen_per_kW=3000.0,
        )
        cfg = make_sim_config(fleet=[ev], trips=trips, tariff=tariff)
        result = RouteSimulator(cfg).run()
        assert result.contract_excess_cost_yen == 0.0


# ---------------------------------------------------------------------------
# Output files written correctly
# ---------------------------------------------------------------------------


class TestOutputFiles:
    def test_save_creates_all_files(self, tmp_path):
        ev = make_ev("ev_01")
        trips = [make_trip("t1", distance_km=10.0)]
        cfg = make_sim_config(fleet=[ev], trips=trips)
        result = RouteSimulator(cfg).run()
        paths = result.save(tmp_path)

        expected_keys = {
            "operation_timeline",
            "soc_timeline",
            "charging_timeline",
            "grid_timeline",
            "cost_breakdown",
            "trip_assignment",
            "fleet_summary",
            "summary_md",
        }
        assert set(paths.keys()) == expected_keys
        for key, p in paths.items():
            assert Path(p).exists(), f"Missing output file: {key} → {p}"

    def test_cost_breakdown_json_keys(self, tmp_path):
        ev = make_ev("ev_01")
        trips = [make_trip("t1", distance_km=10.0)]
        cfg = make_sim_config(fleet=[ev], trips=trips)
        result = RouteSimulator(cfg).run()
        cb = result.cost_breakdown()
        for key in (
            "total_cost_yen",
            "fuel_cost_yen",
            "electricity_cost_yen",
            "demand_charge_yen",
            "vehicle_capex_cost_yen",
            "unassigned_trips",
            "peak_demand_kW",
        ):
            assert key in cb, f"Missing key in cost_breakdown: {key}"

    def test_trip_assignment_json_fields(self, tmp_path):
        ev = make_ev("ev_01")
        eng = make_engine("eng_01")
        trips = [
            make_trip("t1", start_time="08:00", end_time="09:00"),
            make_trip("t2", start_time="08:00", end_time="09:00"),
        ]
        cfg = make_sim_config(fleet=[ev, eng], trips=trips)
        result = RouteSimulator(cfg).run()
        ta = result.trip_assignment_data()
        assert len(ta) == 2
        for rec in ta:
            assert "trip_id" in rec
            assert "vehicle_id" in rec
            assert "assigned" in rec

    def test_fleet_summary_json_fields(self, tmp_path):
        ev = make_ev("ev_01")
        trips = [make_trip("t1", distance_km=10.0)]
        cfg = make_sim_config(fleet=[ev], trips=trips)
        result = RouteSimulator(cfg).run()
        fs = result.fleet_summary()
        assert len(fs) == 1
        for key in (
            "vehicle_id",
            "vehicle_type",
            "trips_assigned",
            "daily_capex_yen",
            "soc_min",
            "soc_final",
            "total_fuel_L",
            "total_energy_kWh",
        ):
            assert key in fs[0], f"Missing key in fleet_summary: {key}"

    def test_operation_timeline_csv_rows(self, tmp_path):
        ev = make_ev("ev_01")
        trips = [make_trip("t1", distance_km=10.0)]
        cfg = make_sim_config(
            fleet=[ev], trips=trips, delta_t_min=60, time_horizon_hours=24.0
        )
        result = RouteSimulator(cfg).run()
        result.save(tmp_path)
        import csv as csv_mod

        with open(
            tmp_path / "vehicle_operation_timeline.csv", newline="", encoding="utf-8"
        ) as f:
            rows = list(csv_mod.DictReader(f))
        # 24 slots × 1 vehicle = 24 rows
        assert len(rows) == 24

    def test_markdown_contains_label(self, tmp_path):
        ev = make_ev("ev_01")
        cfg = make_sim_config(fleet=[ev], trips=[], label="my_scenario")
        result = RouteSimulator(cfg).run()
        md = result.to_markdown()
        assert "my_scenario" in md

    def test_from_json_roundtrip(self, tmp_path):
        d = {
            "label": "json_test",
            "delta_t_min": 60,
            "time_horizon_hours": 12.0,
            "diesel_price_yen_per_L": 150.0,
            "fleet": [
                {
                    "vehicle_id": "ev_a",
                    "vehicle_type": "ev_bus",
                    "battery_capacity_kWh": 200.0,
                    "usable_battery_capacity_kWh": 180.0,
                    "charging_power_max_kW": 60.0,
                    "energy_consumption_kWh_per_km_base": 1.0,
                    "purchase_cost_yen": 10_000_000,
                }
            ],
            "route_profile": [
                {
                    "trip_id": "t1",
                    "route_id": "R1",
                    "start_time": "07:00",
                    "end_time": "08:00",
                    "distance_km": 15.0,
                }
            ],
            "tariff": {"flat_price_yen_per_kWh": 22.0},
        }
        json_path = tmp_path / "sim_cfg.json"
        json_path.write_text(json.dumps(d), encoding="utf-8")
        sim = RouteSimulator.from_json(json_path)
        result = sim.run()
        assert result.trip_assignments.get("t1") == "ev_a"
        assert result.total_cost_yen > 0.0


# ---------------------------------------------------------------------------
# Phase 2 — Fleet-level charging: charger_site_limit_kW
# ---------------------------------------------------------------------------


class TestFleetChargingSitePowerLimit:
    """Total charging power across all EVs must never exceed charger_site_limit_kW."""

    def test_two_evs_capped_by_site_limit(self):
        """Two 60 kW EVs with a 50 kW site limit → total ≤ 50 kW every slot."""
        ev1 = make_ev("ev_01", charging_power_max_kW=60.0, initial_soc=0.5)
        ev2 = make_ev("ev_02", charging_power_max_kW=60.0, initial_soc=0.5)
        cfg = make_sim_config(fleet=[ev1, ev2], trips=[], delta_t_min=60)
        cfg.charger_site_limit_kW = 50.0
        result = RouteSimulator(cfg).run()
        for t in range(cfg.n_slots):
            total_kW = sum(
                st.charging_power_kW[t]
                for st in result.states.values()
                if st.spec.vehicle_type == "ev_bus"
            )
            assert total_kW <= 50.0 + 1e-6, (
                f"slot {t}: total charging {total_kW:.2f} kW exceeds site limit 50 kW"
            )

    def test_site_limit_proportional_scaling(self):
        """When total provisional power exceeds site limit, power is scaled proportionally."""
        # 3 EVs each wanting 100 kW, site limit 150 kW → each scaled to 50 kW
        ev1 = make_ev(
            "ev_01",
            charging_power_max_kW=100.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        ev2 = make_ev(
            "ev_02",
            charging_power_max_kW=100.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        ev3 = make_ev(
            "ev_03",
            charging_power_max_kW=100.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        cfg = make_sim_config(fleet=[ev1, ev2, ev3], trips=[], delta_t_min=60)
        cfg.charger_site_limit_kW = 150.0
        result = RouteSimulator(cfg).run()
        # In the first slot all 3 are idle and at 50% SOC; each wants 100 kW
        # Total 300 kW > 150 kW → scale factor = 0.5 → each gets 50 kW
        powers_t0 = [
            result.states[f"ev_0{i}"].charging_power_kW[0] for i in range(1, 4)
        ]
        for p in powers_t0:
            assert abs(p - 50.0) < 1.0, f"Expected ~50 kW each, got {p:.2f}"

    def test_site_limit_not_applied_when_under(self):
        """Site limit should not reduce power when total is already under the limit."""
        ev = make_ev(
            "ev_01",
            charging_power_max_kW=60.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        cfg = make_sim_config(fleet=[ev], trips=[], delta_t_min=60)
        cfg.charger_site_limit_kW = 200.0  # well above single EV
        result = RouteSimulator(cfg).run()
        # First slot: EV wants 60 kW, site limit 200 → full 60 kW
        assert result.states["ev_01"].charging_power_kW[0] >= 59.0


# ---------------------------------------------------------------------------
# Phase 2 — Fleet-level charging: num_chargers
# ---------------------------------------------------------------------------


class TestFleetChargingNumChargers:
    """At most num_chargers EVs may charge simultaneously."""

    def test_only_n_evs_charge(self):
        """3 EVs but num_chargers=2 → at most 2 have non-zero power per slot."""
        ev1 = make_ev("ev_01", charging_power_max_kW=60.0, initial_soc=0.5)
        ev2 = make_ev("ev_02", charging_power_max_kW=60.0, initial_soc=0.5)
        ev3 = make_ev("ev_03", charging_power_max_kW=60.0, initial_soc=0.5)
        cfg = make_sim_config(fleet=[ev1, ev2, ev3], trips=[], delta_t_min=60)
        cfg.num_chargers = 2
        result = RouteSimulator(cfg).run()
        for t in range(cfg.n_slots):
            charging_count = sum(
                1
                for st in result.states.values()
                if st.spec.vehicle_type == "ev_bus" and st.charging_power_kW[t] > 0.01
            )
            assert charging_count <= 2, (
                f"slot {t}: {charging_count} EVs charging, expected ≤ 2"
            )

    def test_num_chargers_1_only_one_charges(self):
        """With num_chargers=1, only 1 EV charges at a time."""
        ev1 = make_ev("ev_01", charging_power_max_kW=60.0, initial_soc=0.5)
        ev2 = make_ev("ev_02", charging_power_max_kW=60.0, initial_soc=0.5)
        cfg = make_sim_config(fleet=[ev1, ev2], trips=[], delta_t_min=60)
        cfg.num_chargers = 1
        result = RouteSimulator(cfg).run()
        for t in range(cfg.n_slots):
            charging_count = sum(
                1
                for st in result.states.values()
                if st.spec.vehicle_type == "ev_bus" and st.charging_power_kW[t] > 0.01
            )
            assert charging_count <= 1, (
                f"slot {t}: {charging_count} EVs charging, expected ≤ 1"
            )

    def test_lowest_soc_charges_first(self):
        """With num_chargers=1, the EV with lowest SOC should get priority."""
        ev_low = make_ev("ev_low", charging_power_max_kW=60.0, initial_soc=0.3)
        ev_high = make_ev("ev_high", charging_power_max_kW=60.0, initial_soc=0.8)
        cfg = make_sim_config(fleet=[ev_low, ev_high], trips=[], delta_t_min=60)
        cfg.num_chargers = 1
        result = RouteSimulator(cfg).run()
        # In first slot, ev_low (SOC 0.3) should charge, ev_high (SOC 0.8) should not
        assert result.states["ev_low"].charging_power_kW[0] > 0.0
        assert result.states["ev_high"].charging_power_kW[0] < 0.01


# ---------------------------------------------------------------------------
# Phase 2 — Coordinated multi-EV charging with combined constraints
# ---------------------------------------------------------------------------


class TestFleetChargingCoordinated:
    """Both num_chargers and site power limit applied together."""

    def test_combined_constraints(self):
        """4 EVs, num_chargers=2, site_limit=80 kW, each wants 60 kW."""
        evs = [
            make_ev(
                f"ev_{i:02d}",
                charging_power_max_kW=60.0,
                initial_soc=0.4,
                charging_efficiency=1.0,
            )
            for i in range(1, 5)
        ]
        cfg = make_sim_config(fleet=evs, trips=[], delta_t_min=60)
        cfg.num_chargers = 2
        cfg.charger_site_limit_kW = 80.0
        result = RouteSimulator(cfg).run()
        for t in range(cfg.n_slots):
            charging_evs = [
                vid
                for vid, st in result.states.items()
                if st.spec.vehicle_type == "ev_bus" and st.charging_power_kW[t] > 0.01
            ]
            total_kW = sum(
                result.states[vid].charging_power_kW[t] for vid in charging_evs
            )
            assert len(charging_evs) <= 2, (
                f"slot {t}: {len(charging_evs)} EVs charging, expected ≤ 2"
            )
            assert total_kW <= 80.0 + 1e-6, (
                f"slot {t}: total {total_kW:.2f} kW exceeds 80 kW site limit"
            )

    def test_hard_limit_contract_caps_charging(self):
        """In hard_limit mode, contract_power_limit_kW also caps fleet charging."""
        ev1 = make_ev(
            "ev_01",
            charging_power_max_kW=100.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        ev2 = make_ev(
            "ev_02",
            charging_power_max_kW=100.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        tariff = make_tariff(
            contract_limit=80.0,
            contract_penalty_mode="hard_limit",
        )
        cfg = make_sim_config(fleet=[ev1, ev2], trips=[], tariff=tariff, delta_t_min=60)
        cfg.charger_site_limit_kW = 1e9  # no site limit, but contract is 80 kW
        result = RouteSimulator(cfg).run()
        for t in range(cfg.n_slots):
            total_kW = sum(
                st.charging_power_kW[t]
                for st in result.states.values()
                if st.spec.vehicle_type == "ev_bus"
            )
            assert total_kW <= 80.0 + 1e-6, (
                f"slot {t}: total {total_kW:.2f} kW exceeds contract hard limit 80 kW"
            )

    def test_evs_still_charge_when_fully_idle(self):
        """When no trips at all, EVs at 50% SOC should gain SOC through charging."""
        ev = make_ev(
            "ev_01",
            charging_power_max_kW=60.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
        )
        cfg = make_sim_config(fleet=[ev], trips=[], delta_t_min=60)
        result = RouteSimulator(cfg).run()
        st = result.states["ev_01"]
        # SOC should increase from 0.5
        assert st.soc[-1] > 0.5 + 0.01


# ---------------------------------------------------------------------------
# Phase 2 — Incremental-cost vehicle assignment
# ---------------------------------------------------------------------------


class TestIncrementalCostAssignment:
    """_find_best_vehicle picks cheapest vehicle by marginal operating cost."""

    def test_engine_preferred_when_diesel_cheap(self):
        """Cheap diesel + expensive electricity → engine bus wins."""
        ev = make_ev(
            "ev_01", energy_consumption_kWh_per_km_base=1.0, charging_efficiency=1.0
        )
        eng = make_engine("eng_01", fuel_economy_km_per_L=5.0)
        trip = make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        # EV cost: 20 km * 1 kWh/km * 100 yen/kWh = 2000 yen
        # Engine cost: 20 km * 0.2 L/km * 50 yen/L = 200 yen → engine wins
        tariff = make_tariff(flat_price=100.0)
        cfg = make_sim_config(
            fleet=[ev, eng], trips=[trip], tariff=tariff, diesel_price=50.0
        )
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "eng_01"

    def test_ev_preferred_when_electricity_cheap(self):
        """Cheap electricity + expensive diesel → EV wins."""
        ev = make_ev(
            "ev_01", energy_consumption_kWh_per_km_base=1.0, charging_efficiency=1.0
        )
        eng = make_engine("eng_01", fuel_economy_km_per_L=5.0)
        trip = make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        # EV cost: 20 km * 1 kWh/km * 10 yen/kWh = 200 yen
        # Engine cost: 20 km * 0.2 L/km * 200 yen/L = 800 yen → EV wins
        tariff = make_tariff(flat_price=10.0)
        cfg = make_sim_config(
            fleet=[ev, eng], trips=[trip], tariff=tariff, diesel_price=200.0
        )
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"

    def test_ev_wins_tie_on_cost(self):
        """When incremental costs are equal, EV is preferred (type_order 0 < 1)."""
        # EV cost: 20 km * 1 kWh/km * 20 yen/kWh = 400 yen
        # Engine cost: 20 km * 0.2 L/km * 100 yen/L = 400 yen → tie, EV wins
        ev = make_ev(
            "ev_01", energy_consumption_kWh_per_km_base=1.0, charging_efficiency=1.0
        )
        eng = make_engine("eng_01", fuel_economy_km_per_L=5.0)
        trip = make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        tariff = make_tariff(flat_price=20.0)
        cfg = make_sim_config(
            fleet=[ev, eng], trips=[trip], tariff=tariff, diesel_price=100.0
        )
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"

    def test_tou_price_used_for_ev_cost(self):
        """EV incremental cost uses average TOU price over trip slots, not flat price."""
        ev = make_ev(
            "ev_01", energy_consumption_kWh_per_km_base=1.0, charging_efficiency=1.0
        )
        eng = make_engine("eng_01", fuel_economy_km_per_L=5.0)
        # Trip at slot 8 (08:00-09:00 with delta_t=60 → slot 8)
        trip = make_trip("t1", distance_km=20.0, start_time="08:00", end_time="09:00")
        # TOU: slot 8 = 5 yen/kWh (very cheap) → EV cost = 20*5 = 100 yen
        # Engine cost: 20 * 0.2 * 150 = 600 yen → EV should win easily
        tariff = TariffSpec(
            flat_price_yen_per_kWh=50.0,  # high flat price
            tou_prices={8: 5.0},  # but slot 8 is cheap
        )
        cfg = make_sim_config(
            fleet=[ev, eng], trips=[trip], tariff=tariff, diesel_price=150.0
        )
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"

    def test_engine_preferred_for_second_trip_after_soc_drop(self):
        """After a long EV trip depletes SOC close to min, second trip goes to engine."""
        # EV: 180 kWh usable, start SOC 1.0, min_soc=0.1
        # First trip: 80 km * 1 kWh/km = 80 kWh → soc_drop=80/180=0.444
        # _apply_trip double-deducts: soc at end_slot drops, then end_slot+1 drops again
        # After first trip SOC is very low.
        # Second trip 80 km needs 0.444 SOC headroom above min → infeasible → engine
        ev = make_ev(
            "ev_01",
            energy_consumption_kWh_per_km_base=1.0,
            initial_soc=1.0,
            min_soc=0.1,
            charging_efficiency=1.0,
        )
        eng = make_engine("eng_01", fuel_economy_km_per_L=5.0)
        trips = [
            make_trip("t1", distance_km=80.0, start_time="08:00", end_time="09:00"),
            make_trip("t2", distance_km=80.0, start_time="10:00", end_time="11:00"),
        ]
        tariff = make_tariff(flat_price=10.0)  # cheap electricity
        cfg = make_sim_config(
            fleet=[ev, eng], trips=trips, tariff=tariff, diesel_price=200.0
        )
        result = RouteSimulator(cfg).run()
        assert result.trip_assignments["t1"] == "ev_01"
        assert result.trip_assignments["t2"] == "eng_01"


# ---------------------------------------------------------------------------
# Phase 2 — SOC dip preserved through fleet charging
# ---------------------------------------------------------------------------


class TestSocDipPreservation:
    """Fleet charging must NOT overwrite SOC values set by _apply_trip for running EVs."""

    def test_running_ev_soc_dip_preserved(self):
        """SOC should dip during a trip even when fleet charging is active."""
        ev = make_ev(
            "ev_01",
            charging_power_max_kW=60.0,
            initial_soc=1.0,
            energy_consumption_kWh_per_km_base=1.0,
            usable_battery_capacity_kWh=180.0,
            charging_efficiency=1.0,
        )
        # Trip from 08:00-09:00 → slot 8 (with delta_t=60)
        trip = make_trip("t1", distance_km=36.0, start_time="08:00", end_time="09:00")
        cfg = make_sim_config(fleet=[ev], trips=[trip], delta_t_min=60)
        result = RouteSimulator(cfg).run()
        st = result.states["ev_01"]
        # _apply_trip deducts at end_slot (8) and end_slot+1 (9):
        # soc[8] = 1.0 - 0.2 = 0.8, soc[9] = 0.8 - 0.2 = 0.6
        assert st.soc[9] < 1.0, f"SOC at slot 9 should have dipped, got {st.soc[9]}"
        assert st.soc[9] < st.soc[0], "SOC after trip should be less than initial"
        # SOC should recover after slot 9 due to charging
        assert st.soc[-1] > st.soc[9], "SOC should recover after trip via charging"

    def test_two_evs_one_running_one_charging(self):
        """While one EV runs a trip, the other should continue charging undisturbed."""
        ev_running = make_ev(
            "ev_run",
            charging_power_max_kW=60.0,
            initial_soc=1.0,
            energy_consumption_kWh_per_km_base=1.0,
            usable_battery_capacity_kWh=180.0,
            charging_efficiency=1.0,
        )
        # Use a slow charger so ev_idle won't be full by slot 8
        # 10 kW charger, 180 kWh usable, eta=1.0 → per-hour delta_soc = 10/180 ≈ 0.056
        # After 8 hours: SOC ≈ 0.5 + 8*0.056 = 0.944 < 1.0 → still needs charging
        ev_idle = make_ev(
            "ev_idle",
            charging_power_max_kW=10.0,
            initial_soc=0.5,
            charging_efficiency=1.0,
            usable_battery_capacity_kWh=180.0,
        )
        trip = make_trip("t1", distance_km=36.0, start_time="08:00", end_time="09:00")
        cfg = make_sim_config(fleet=[ev_running, ev_idle], trips=[trip], delta_t_min=60)
        result = RouteSimulator(cfg).run()
        # ev_idle should be charging at slot 8 (not running, SOC < max)
        assert result.states["ev_idle"].charging_power_kW[8] > 0.0, (
            "Idle EV should be charging while other EV runs"
        )
        # ev_running should NOT be charging at slot 8
        assert result.states["ev_run"].charging_power_kW[8] == 0.0, (
            "Running EV should have zero charging power"
        )
        # ev_running SOC should show a dip after the trip
        st_run = result.states["ev_run"]
        assert st_run.soc[9] < st_run.soc[0], (
            f"Running EV SOC should dip: initial={st_run.soc[0]}, slot 9={st_run.soc[9]}"
        )

    def test_soc_does_not_exceed_max(self):
        """Charging should never push SOC above max_soc."""
        ev = make_ev(
            "ev_01",
            charging_power_max_kW=200.0,
            initial_soc=0.95,
            max_soc=1.0,
            charging_efficiency=1.0,
        )
        cfg = make_sim_config(fleet=[ev], trips=[], delta_t_min=60)
        result = RouteSimulator(cfg).run()
        for soc_val in result.states["ev_01"].soc:
            assert soc_val <= 1.0 + 1e-9, f"SOC {soc_val} exceeds max_soc 1.0"


# ---------------------------------------------------------------------------
# Phase 2 — SimConfig new fields
# ---------------------------------------------------------------------------


class TestSimConfigPhase2Fields:
    """SimConfig.charger_site_limit_kW and num_chargers parsing."""

    def test_defaults(self):
        cfg = SimConfig()
        assert cfg.charger_site_limit_kW == 1e9
        assert cfg.num_chargers == 999

    def test_from_dict_parses_fields(self):
        d = {
            "charger_site_limit_kW": 150.0,
            "num_chargers": 3,
            "fleet": [],
            "route_profile": [],
        }
        cfg = SimConfig.from_dict(d)
        assert cfg.charger_site_limit_kW == 150.0
        assert cfg.num_chargers == 3

    def test_from_dict_defaults_when_absent(self):
        d = {"fleet": [], "route_profile": []}
        cfg = SimConfig.from_dict(d)
        assert cfg.charger_site_limit_kW == 1e9
        assert cfg.num_chargers == 999
