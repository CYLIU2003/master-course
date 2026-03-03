"""
route_cost_simulator.py

Route-profile-driven mixed fleet (EV + engine bus) simulator.

Implements §21 Phase 1 of AGENTS_ev_route_cost.md:
  - Read route profile (list of trips with distance / time)
  - Assign trips to vehicles (EV-first greedy)
  - Track EV SOC slot-by-slot; track engine bus fuel consumption
  - Compute TOU electricity cost + fuel cost + vehicle capex (daily)
  - Produce 4 CSV timeseries + 3 JSON summaries + 1 Markdown summary

Principle: "運行が先、コストはその運行から自然に出る"
(Operation first; cost derives naturally from the operation.)

Usage:
    from src.route_cost_simulator import RouteSimulator, SimConfig
    sim = RouteSimulator.from_json("path/to/sim_config.json")
    result = sim.run()
    result.save(output_dir)
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes for inputs
# ---------------------------------------------------------------------------


@dataclass
class VehicleSpec:
    """Unified vehicle specification for EV or engine bus."""

    vehicle_id: str
    vehicle_type: str  # "ev_bus" | "engine_bus"
    depot_id: str = "depot_01"
    passenger_capacity: int = 70
    route_compatibility: list[str] = field(default_factory=list)  # [] = any route

    # EV-only fields
    battery_capacity_kWh: float = 0.0
    usable_battery_capacity_kWh: float = 0.0
    initial_soc: float = 1.0
    min_soc: float = 0.1
    max_soc: float = 1.0
    energy_consumption_kWh_per_km_base: float = 1.0
    charging_power_max_kW: float = 0.0
    charging_efficiency: float = 0.95

    # Engine bus fields
    fuel_economy_km_per_L: float = 0.0
    diesel_consumption_L_per_km: float = 0.0
    fuel_tank_capacity_L: float = 200.0
    initial_fuel_L: float | None = None  # defaults to fuel_tank_capacity_L

    # Cost fields
    purchase_cost_yen: float = 0.0
    residual_value_yen: float = 0.0
    lifetime_year: float = 12.0
    operation_days_per_year: float = 300.0

    def __post_init__(self) -> None:
        # Derive diesel_consumption from fuel_economy if not provided
        if self.vehicle_type == "engine_bus":
            if self.diesel_consumption_L_per_km <= 0 and self.fuel_economy_km_per_L > 0:
                self.diesel_consumption_L_per_km = 1.0 / self.fuel_economy_km_per_L
            elif (
                self.fuel_economy_km_per_L <= 0 and self.diesel_consumption_L_per_km > 0
            ):
                self.fuel_economy_km_per_L = 1.0 / self.diesel_consumption_L_per_km
        if self.initial_fuel_L is None:
            self.initial_fuel_L = self.fuel_tank_capacity_L

    @property
    def daily_capex_yen(self) -> float:
        denom = self.lifetime_year * self.operation_days_per_year
        if denom <= 0:
            return 0.0
        return (self.purchase_cost_yen - self.residual_value_yen) / denom

    @classmethod
    def from_dict(cls, d: dict) -> "VehicleSpec":
        # Only pass fields that exist in the dataclass
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class TripSpec:
    """A single revenue service trip."""

    trip_id: str
    route_id: str
    start_time: str  # "HH:MM" or "HH:MM:SS"
    end_time: str
    distance_km: float
    deadhead_distance_before_km: float = 0.0
    deadhead_distance_after_km: float = 0.0
    required_bus_type: str | None = None  # "ev_bus" | "engine_bus" | None (any)
    elevation_factor: float = 1.0
    load_factor: float = 1.0
    start_terminal: str = ""
    end_terminal: str = ""

    @property
    def effective_distance_km(self) -> float:
        return (
            self.deadhead_distance_before_km
            + self.distance_km
            + self.deadhead_distance_after_km
        )

    @classmethod
    def from_dict(cls, d: dict) -> "TripSpec":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class TariffSpec:
    """TOU electricity tariff and contract conditions."""

    # tou_prices: mapping from time-slot index (0-based) to yen/kWh
    # If empty, flat_price_yen_per_kWh is used.
    tou_prices: dict[int, float] = field(default_factory=dict)
    flat_price_yen_per_kWh: float = 25.0
    demand_charge_yen_per_kW_month: float = 0.0
    contract_power_limit_kW: float = 1000.0
    contract_penalty_mode: str = "hard_limit"  # "hard_limit" | "penalty"
    contract_penalty_yen_per_kW: float = 0.0
    pv_generation_kWh: dict[int, float] = field(default_factory=dict)
    cost_time_basis: str = "daily"  # "daily" | "monthly"
    grid_basic_charge_yen: float = 0.0

    def price_at(self, slot: int) -> float:
        return self.tou_prices.get(slot, self.flat_price_yen_per_kWh)

    def pv_at(self, slot: int) -> float:
        return self.pv_generation_kWh.get(slot, 0.0)

    @classmethod
    def from_dict(cls, d: dict) -> "TariffSpec":
        obj = cls()
        obj.flat_price_yen_per_kWh = d.get("flat_price_yen_per_kWh", 25.0)
        obj.demand_charge_yen_per_kW_month = d.get(
            "demand_charge_yen_per_kW_month", 0.0
        )
        obj.contract_power_limit_kW = d.get("contract_power_limit_kW", 1000.0)
        obj.contract_penalty_mode = d.get("contract_penalty_mode", "hard_limit")
        obj.contract_penalty_yen_per_kW = d.get("contract_penalty_yen_per_kW", 0.0)
        obj.cost_time_basis = d.get("cost_time_basis", "daily")
        obj.grid_basic_charge_yen = d.get("grid_basic_charge_yen", 0.0)
        # TOU prices: may be given as list (one per slot) or dict
        tou_raw = d.get("tou_price_yen_per_kWh", {})
        if isinstance(tou_raw, list):
            obj.tou_prices = {i: v for i, v in enumerate(tou_raw)}
        elif isinstance(tou_raw, dict):
            obj.tou_prices = {int(k): float(v) for k, v in tou_raw.items()}
        # PV generation
        pv_raw = d.get("pv_generation_kWh", {})
        if isinstance(pv_raw, list):
            obj.pv_generation_kWh = {i: v for i, v in enumerate(pv_raw)}
        elif isinstance(pv_raw, dict):
            obj.pv_generation_kWh = {int(k): float(v) for k, v in pv_raw.items()}
        return obj


@dataclass
class SimConfig:
    """Top-level simulation configuration."""

    delta_t_min: int = 30  # time resolution in minutes
    time_horizon_hours: float = 24.0
    diesel_price_yen_per_L: float = 150.0
    fleet: list[VehicleSpec] = field(default_factory=list)
    trips: list[TripSpec] = field(default_factory=list)
    tariff: TariffSpec = field(default_factory=TariffSpec)
    label: str = "unnamed"
    # Charger infrastructure limits (Phase 2)
    charger_site_limit_kW: float = 1e9  # max total charging power at site
    num_chargers: int = 999  # max number of EVs charging simultaneously

    @property
    def n_slots(self) -> int:
        return math.ceil(self.time_horizon_hours * 60 / self.delta_t_min)

    @property
    def dt_hour(self) -> float:
        return self.delta_t_min / 60.0

    @classmethod
    def from_dict(cls, d: dict) -> "SimConfig":
        cfg = cls()
        cfg.delta_t_min = int(d.get("delta_t_min", 30))
        cfg.time_horizon_hours = float(d.get("time_horizon_hours", 24.0))
        cfg.diesel_price_yen_per_L = float(d.get("diesel_price_yen_per_L", 150.0))
        cfg.label = d.get("label", "unnamed")
        cfg.charger_site_limit_kW = float(d.get("charger_site_limit_kW", 1e9))
        cfg.num_chargers = int(d.get("num_chargers", 999))
        cfg.fleet = [VehicleSpec.from_dict(v) for v in d.get("fleet", [])]
        cfg.trips = [TripSpec.from_dict(t) for t in d.get("route_profile", [])]
        tariff_raw = d.get("tariff", {})
        cfg.tariff = TariffSpec.from_dict(tariff_raw if tariff_raw else {})
        return cfg
        return cfg

    @classmethod
    def from_json(cls, path: str | Path) -> "SimConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------


def _parse_time_min(t: str) -> int:
    """Parse "HH:MM" or "HH:MM:SS" → minutes from midnight."""
    parts = t.strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m


def _slot_of(minute: int, delta_t_min: int) -> int:
    return minute // delta_t_min


def _slots_occupied(trip: TripSpec, delta_t_min: int) -> list[int]:
    """Return all time slots (inclusive) occupied by this trip."""
    start_min = _parse_time_min(trip.start_time)
    end_min = _parse_time_min(trip.end_time)
    if end_min <= start_min:
        end_min += 24 * 60  # next day wrap
    s = _slot_of(start_min, delta_t_min)
    e = _slot_of(max(end_min - 1, start_min), delta_t_min)
    return list(range(s, e + 1))


# ---------------------------------------------------------------------------
# Vehicle runtime state
# ---------------------------------------------------------------------------


@dataclass
class VehicleState:
    spec: VehicleSpec
    # per-slot arrays (length = n_slots)
    soc: list[float] = field(default_factory=list)
    charging_power_kW: list[float] = field(default_factory=list)
    energy_used_kWh: list[float] = field(default_factory=list)
    fuel_used_L: list[float] = field(default_factory=list)
    is_running: list[bool] = field(default_factory=list)
    # accumulated
    total_fuel_L: float = 0.0
    total_energy_kWh: float = 0.0
    # assignments
    assigned_trips: list[str] = field(default_factory=list)

    @classmethod
    def init(cls, spec: VehicleSpec, n_slots: int) -> "VehicleState":
        st = cls(spec=spec)
        if spec.vehicle_type == "ev_bus":
            init_soc = spec.initial_soc
        else:
            init_soc = 0.0
        st.soc = [init_soc] * (n_slots + 1)
        st.charging_power_kW = [0.0] * n_slots
        st.energy_used_kWh = [0.0] * n_slots
        st.fuel_used_L = [0.0] * n_slots
        st.is_running = [False] * n_slots
        return st


# ---------------------------------------------------------------------------
# Main simulator
# ---------------------------------------------------------------------------


class RouteSimulator:
    """
    Deterministic greedy route-profile simulator.

    Trip assignment:
      1. Sort trips by start_time.
      2. For each trip, find available vehicles (not currently running, route-compatible,
         sufficient SOC/fuel). Prefer EV over engine bus.
      3. Apply trip: deduct SOC or fuel; mark slots as running.
      4. After all trips assigned, simulate EV charging in idle slots.
    """

    def __init__(self, config: SimConfig) -> None:
        self.cfg = config
        self.states: dict[str, VehicleState] = {
            v.vehicle_id: VehicleState.init(v, config.n_slots) for v in config.fleet
        }

    @classmethod
    def from_json(cls, path: str | Path) -> "RouteSimulator":
        return cls(SimConfig.from_json(path))

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> "SimResult":
        cfg = self.cfg
        states = self.states

        # Sort trips by start_time
        sorted_trips = sorted(cfg.trips, key=lambda t: _parse_time_min(t.start_time))

        trip_assignments: dict[str, str | None] = {}  # trip_id → vehicle_id
        unassigned: list[str] = []

        # --- Trip assignment ---
        for trip in sorted_trips:
            occupied_slots = _slots_occupied(trip, cfg.delta_t_min)
            candidate = self._find_best_vehicle(trip, occupied_slots, states)
            if candidate is None:
                trip_assignments[trip.trip_id] = None
                unassigned.append(trip.trip_id)
                continue

            trip_assignments[trip.trip_id] = candidate.spec.vehicle_id
            candidate.assigned_trips.append(trip.trip_id)
            self._apply_trip(trip, candidate, occupied_slots)

        # --- Fleet-level coordinated EV charging ---
        self._simulate_fleet_charging(states)

        # --- Aggregate timeseries ---
        n = cfg.n_slots
        total_charging_kW = [0.0] * n
        for st in states.values():
            if st.spec.vehicle_type == "ev_bus":
                for t in range(n):
                    total_charging_kW[t] += st.charging_power_kW[t]

        # Net grid power (subtract PV)
        net_grid_kW = [
            max(0.0, total_charging_kW[t] - cfg.tariff.pv_at(t)) for t in range(n)
        ]
        net_grid_kWh = [net_grid_kW[t] * cfg.dt_hour for t in range(n)]

        # --- Costs ---
        electricity_cost = sum(
            net_grid_kWh[t] * cfg.tariff.price_at(t) for t in range(n)
        )
        total_fuel_L = sum(st.total_fuel_L for st in states.values())
        fuel_cost = total_fuel_L * cfg.diesel_price_yen_per_L

        peak_grid_kW = max(net_grid_kW) if net_grid_kW else 0.0
        demand_charge = peak_grid_kW * cfg.tariff.demand_charge_yen_per_kW_month

        # Contract excess cost
        contract_excess_cost = 0.0
        if cfg.tariff.contract_penalty_mode == "penalty":
            max_excess = max(
                max(0.0, net_grid_kW[t] - cfg.tariff.contract_power_limit_kW)
                for t in range(n)
            )
            contract_excess_cost = max_excess * cfg.tariff.contract_penalty_yen_per_kW

        vehicle_capex = sum(st.spec.daily_capex_yen for st in states.values())
        total_cost = (
            vehicle_capex
            + fuel_cost
            + electricity_cost
            + demand_charge
            + contract_excess_cost
            + cfg.tariff.grid_basic_charge_yen
        )

        return SimResult(
            cfg=cfg,
            states=states,
            trip_assignments=trip_assignments,
            unassigned_trips=unassigned,
            total_charging_kW=total_charging_kW,
            net_grid_kW=net_grid_kW,
            net_grid_kWh=net_grid_kWh,
            electricity_cost_yen=electricity_cost,
            fuel_cost_yen=fuel_cost,
            demand_charge_yen=demand_charge,
            contract_excess_cost_yen=contract_excess_cost,
            vehicle_capex_yen=vehicle_capex,
            total_cost_yen=total_cost,
            peak_grid_kW=peak_grid_kW,
            total_fuel_L=total_fuel_L,
            total_grid_kWh=sum(net_grid_kWh),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_best_vehicle(
        self,
        trip: TripSpec,
        occupied_slots: list[int],
        states: dict[str, VehicleState],
    ) -> VehicleState | None:
        """Return the cheapest feasible vehicle (incremental cost comparison).

        EV incremental cost  = trip_kWh * average TOU price over trip slots.
        Engine incremental cost = effective_distance * L/km * diesel_price.
        Lowest incremental cost wins; within ties, EVs preferred.
        """
        candidates: list[tuple[float, int, VehicleState]] = []
        # type_order: 0 = ev_bus (preferred on tie), 1 = engine_bus
        cfg = self.cfg

        for vid, st in states.items():
            spec = st.spec
            # route compatibility check
            if (
                spec.route_compatibility
                and trip.route_id not in spec.route_compatibility
            ):
                continue
            # required bus type check
            if trip.required_bus_type and spec.vehicle_type != trip.required_bus_type:
                continue
            # availability: no overlap with running slots
            if any(st.is_running[s] for s in occupied_slots if s < len(st.is_running)):
                continue

            if spec.vehicle_type == "ev_bus":
                # Check SOC feasibility
                start_slot = occupied_slots[0] if occupied_slots else 0
                soc_at_start = (
                    st.soc[start_slot] if start_slot < len(st.soc) else st.soc[0]
                )
                energy_needed = (
                    trip.effective_distance_km
                    * spec.energy_consumption_kWh_per_km_base
                    * trip.elevation_factor
                    * trip.load_factor
                )
                soc_drop = (
                    energy_needed / spec.usable_battery_capacity_kWh
                    if spec.usable_battery_capacity_kWh > 0
                    else 0.0
                )
                if soc_at_start - soc_drop < spec.min_soc:
                    continue
                # EV incremental cost = trip_kWh * avg TOU price over trip slots
                if occupied_slots:
                    avg_price = sum(
                        cfg.tariff.price_at(s) for s in occupied_slots
                    ) / len(occupied_slots)
                else:
                    avg_price = cfg.tariff.flat_price_yen_per_kWh
                inc_cost = energy_needed * avg_price
                candidates.append((inc_cost, 0, st))
            else:
                # Engine bus incremental cost = distance * L/km * diesel_price
                if spec.diesel_consumption_L_per_km <= 0:
                    continue
                fuel_L = trip.effective_distance_km * spec.diesel_consumption_L_per_km
                inc_cost = fuel_L * cfg.diesel_price_yen_per_L
                candidates.append((inc_cost, 1, st))

        if not candidates:
            return None
        # Sort by (incremental_cost, type_order) — cheapest first; EV wins on tie
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    def _apply_trip(
        self,
        trip: TripSpec,
        st: VehicleState,
        occupied_slots: list[int],
    ) -> None:
        """Apply trip energy consumption to vehicle state."""
        spec = st.spec
        n = self.cfg.n_slots
        effective_dist = trip.effective_distance_km

        for s in occupied_slots:
            if s >= n:
                continue
            st.is_running[s] = True

        if spec.vehicle_type == "ev_bus":
            energy_kWh = (
                effective_dist
                * spec.energy_consumption_kWh_per_km_base
                * trip.elevation_factor
                * trip.load_factor
            )
            # Distribute energy evenly across occupied slots
            per_slot = energy_kWh / max(len(occupied_slots), 1)
            for s in occupied_slots:
                if s >= n:
                    continue
                st.energy_used_kWh[s] += per_slot

            # Update SOC: deduct at end_slot + 1
            end_slot = occupied_slots[-1] if occupied_slots else 0
            soc_drop = (
                energy_kWh / spec.usable_battery_capacity_kWh
                if spec.usable_battery_capacity_kWh > 0
                else 0.0
            )
            # Propagate SOC from end_slot onward
            for s in range(end_slot, n + 1):
                st.soc[s] = max(
                    spec.min_soc,
                    st.soc[end_slot] - soc_drop if s == end_slot else st.soc[s],
                )
            # Actually set end_slot soc
            st.soc[end_slot + 1] = max(spec.min_soc, st.soc[end_slot] - soc_drop)
            # Propagate forward
            for s in range(end_slot + 2, n + 1):
                st.soc[s] = st.soc[s - 1]

            st.total_energy_kWh += energy_kWh

        else:
            fuel_L = effective_dist * spec.diesel_consumption_L_per_km
            per_slot = fuel_L / max(len(occupied_slots), 1)
            for s in occupied_slots:
                if s >= n:
                    continue
                st.fuel_used_L[s] += per_slot
            st.total_fuel_L += fuel_L

    def _simulate_fleet_charging(self, states: dict[str, VehicleState]) -> None:
        """Coordinated fleet-level charging respecting site infrastructure limits.

        Per time slot:
        1. Gather all idle EVs, sort by SOC ascending (lowest-first priority).
        2. Select up to ``cfg.num_chargers`` vehicles.
        3. Compute provisional per-vehicle power (min of charger max, SOC headroom).
        4. If total exceeds ``cfg.charger_site_limit_kW`` or contract hard-limit,
           scale down proportionally.
        5. Update SOC for all EVs simultaneously.
        """
        cfg = self.cfg
        n = cfg.n_slots
        dt = cfg.dt_hour

        site_limit = cfg.charger_site_limit_kW
        max_chargers = cfg.num_chargers
        contract_limit = cfg.tariff.contract_power_limit_kW
        hard_limit = site_limit
        if cfg.tariff.contract_penalty_mode == "hard_limit":
            hard_limit = min(hard_limit, contract_limit)

        ev_states = {
            vid: st for vid, st in states.items() if st.spec.vehicle_type == "ev_bus"
        }

        for t in range(n):
            # Identify idle EVs at this slot
            idle_evs: list[tuple[float, str, VehicleState]] = []
            for vid, st in ev_states.items():
                if st.is_running[t]:
                    continue
                soc_t = st.soc[t]
                if soc_t >= st.spec.max_soc:
                    continue
                idle_evs.append((soc_t, vid, st))

            if not idle_evs:
                # No EVs need charging — propagate SOC for non-running EVs only
                for vid, st in ev_states.items():
                    if not st.is_running[t] and t + 1 <= n:
                        st.soc[t + 1] = st.soc[t]
                continue

            # Sort by SOC ascending (lowest-first priority)
            idle_evs.sort(key=lambda x: x[0])
            selected = idle_evs[:max_chargers]

            # Compute provisional per-vehicle power
            provisional: dict[str, float] = {}
            for _soc, vid, st in selected:
                spec = st.spec
                soc_headroom = spec.max_soc - st.soc[t]
                energy_max_by_soc = soc_headroom * spec.usable_battery_capacity_kWh
                energy_max_by_power = spec.charging_power_max_kW * dt
                energy_charged = min(energy_max_by_soc, energy_max_by_power)
                provisional[vid] = energy_charged / dt if dt > 0 else 0.0

            # Enforce site-level power limit
            total_p = sum(provisional.values())
            if total_p > hard_limit and total_p > 0:
                scale = hard_limit / total_p
                for vid in provisional:
                    provisional[vid] *= scale

            # Apply charging power and update SOC for idle EVs only.
            # Running EVs keep their SOC as set by _apply_trip.
            for vid, st in ev_states.items():
                if st.is_running[t]:
                    # Running — SOC already set by _apply_trip; don't overwrite
                    st.charging_power_kW[t] = 0.0
                    continue
                power = provisional.get(vid, 0.0)
                st.charging_power_kW[t] = power
                spec = st.spec
                delta_soc = (
                    (power * spec.charging_efficiency * dt)
                    / spec.usable_battery_capacity_kWh
                    if spec.usable_battery_capacity_kWh > 0
                    else 0.0
                )
                if t + 1 <= n:
                    st.soc[t + 1] = min(spec.max_soc, st.soc[t] + delta_soc)

    def _simulate_charging(self, st: VehicleState) -> None:
        """Legacy single-vehicle charging (kept for backward compatibility)."""
        spec = st.spec
        n = self.cfg.n_slots
        dt = self.cfg.dt_hour

        for t in range(n):
            if st.is_running[t]:
                continue
            soc_t = st.soc[t]
            if soc_t >= spec.max_soc:
                continue
            # How much can we charge this slot?
            soc_headroom = spec.max_soc - soc_t
            energy_max_by_soc = soc_headroom * spec.usable_battery_capacity_kWh
            energy_max_by_power = spec.charging_power_max_kW * dt
            energy_charged = min(energy_max_by_soc, energy_max_by_power)
            actual_power_kW = energy_charged / dt if dt > 0 else 0.0

            st.charging_power_kW[t] = actual_power_kW
            delta_soc = (
                (actual_power_kW * spec.charging_efficiency * dt)
                / spec.usable_battery_capacity_kWh
                if spec.usable_battery_capacity_kWh > 0
                else 0.0
            )
            st.soc[t + 1] = min(spec.max_soc, st.soc[t] + delta_soc)
            # Propagate
            for s in range(t + 2, n + 1):
                st.soc[s] = st.soc[s - 1]


# ---------------------------------------------------------------------------
# Result container + output writers
# ---------------------------------------------------------------------------


@dataclass
class SimResult:
    cfg: SimConfig
    states: dict[str, VehicleState]
    trip_assignments: dict[str, str | None]
    unassigned_trips: list[str]
    total_charging_kW: list[float]
    net_grid_kW: list[float]
    net_grid_kWh: list[float]
    electricity_cost_yen: float
    fuel_cost_yen: float
    demand_charge_yen: float
    contract_excess_cost_yen: float
    vehicle_capex_yen: float
    total_cost_yen: float
    peak_grid_kW: float
    total_fuel_L: float
    total_grid_kWh: float

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def _slot_label(self, t: int) -> str:
        """Return "HH:MM" label for slot t."""
        minutes = t * self.cfg.delta_t_min
        h, m = divmod(minutes % (24 * 60), 60)
        return f"{h:02d}:{m:02d}"

    # ------------------------------------------------------------------
    # CSV outputs
    # ------------------------------------------------------------------

    def _write_operation_timeline(self, path: Path) -> None:
        rows = []
        n = self.cfg.n_slots
        for vid, st in self.states.items():
            for t in range(n):
                rows.append(
                    {
                        "slot": t,
                        "time": self._slot_label(t),
                        "vehicle_id": vid,
                        "vehicle_type": st.spec.vehicle_type,
                        "is_running": int(st.is_running[t]),
                        "soc": round(st.soc[t], 4)
                        if st.spec.vehicle_type == "ev_bus"
                        else "",
                        "charging_power_kW": round(st.charging_power_kW[t], 3),
                        "energy_used_kWh": round(st.energy_used_kWh[t], 4),
                        "fuel_used_L": round(st.fuel_used_L[t], 4),
                    }
                )
        _write_csv(
            path,
            [
                "slot",
                "time",
                "vehicle_id",
                "vehicle_type",
                "is_running",
                "soc",
                "charging_power_kW",
                "energy_used_kWh",
                "fuel_used_L",
            ],
            rows,
        )

    def _write_soc_timeline(self, path: Path) -> None:
        n = self.cfg.n_slots
        ev_states = {
            vid: st
            for vid, st in self.states.items()
            if st.spec.vehicle_type == "ev_bus"
        }
        if not ev_states:
            path.write_text("slot,time\n", encoding="utf-8")
            return
        headers = ["slot", "time"] + list(ev_states.keys())
        rows = []
        for t in range(n + 1):
            row: dict[str, Any] = {
                "slot": t,
                "time": self._slot_label(t) if t < n else "24:00",
            }
            for vid, st in ev_states.items():
                row[vid] = round(st.soc[t], 4)
            rows.append(row)
        _write_csv(path, headers, rows)

    def _write_charging_timeline(self, path: Path) -> None:
        n = self.cfg.n_slots
        ev_states = {
            vid: st
            for vid, st in self.states.items()
            if st.spec.vehicle_type == "ev_bus"
        }
        headers = ["slot", "time", "total_charging_kW"] + list(ev_states.keys())
        rows = []
        for t in range(n):
            row: dict[str, Any] = {
                "slot": t,
                "time": self._slot_label(t),
                "total_charging_kW": round(self.total_charging_kW[t], 3),
            }
            for vid, st in ev_states.items():
                row[vid] = round(st.charging_power_kW[t], 3)
            rows.append(row)
        _write_csv(path, headers, rows)

    def _write_grid_timeline(self, path: Path) -> None:
        n = self.cfg.n_slots
        rows = []
        for t in range(n):
            rows.append(
                {
                    "slot": t,
                    "time": self._slot_label(t),
                    "total_charging_kW": round(self.total_charging_kW[t], 3),
                    "pv_kW": round(self.cfg.tariff.pv_at(t), 3),
                    "net_grid_kW": round(self.net_grid_kW[t], 3),
                    "net_grid_kWh": round(self.net_grid_kWh[t], 4),
                    "tou_price_yen_per_kWh": self.cfg.tariff.price_at(t),
                }
            )
        _write_csv(
            path,
            [
                "slot",
                "time",
                "total_charging_kW",
                "pv_kW",
                "net_grid_kW",
                "net_grid_kWh",
                "tou_price_yen_per_kWh",
            ],
            rows,
        )

    # ------------------------------------------------------------------
    # JSON outputs
    # ------------------------------------------------------------------

    def cost_breakdown(self) -> dict:
        return {
            "label": self.cfg.label,
            "time_basis": self.cfg.tariff.cost_time_basis,
            "delta_t_min": self.cfg.delta_t_min,
            "vehicle_capex_cost_yen": round(self.vehicle_capex_yen, 0),
            "fuel_cost_yen": round(self.fuel_cost_yen, 0),
            "electricity_cost_yen": round(self.electricity_cost_yen, 0),
            "demand_charge_yen": round(self.demand_charge_yen, 0),
            "contract_excess_cost_yen": round(self.contract_excess_cost_yen, 0),
            "grid_basic_charge_yen": self.cfg.tariff.grid_basic_charge_yen,
            "total_cost_yen": round(self.total_cost_yen, 0),
            "peak_demand_kW": round(self.peak_grid_kW, 2),
            "total_grid_purchase_kWh": round(self.total_grid_kWh, 2),
            "total_fuel_consumption_L": round(self.total_fuel_L, 2),
            "unassigned_trips": len(self.unassigned_trips),
        }

    def trip_assignment_data(self) -> list[dict]:
        result = []
        trip_map = {t.trip_id: t for t in self.cfg.trips}
        for tid, vid in self.trip_assignments.items():
            t = trip_map.get(tid)
            result.append(
                {
                    "trip_id": tid,
                    "vehicle_id": vid,
                    "route_id": t.route_id if t else None,
                    "start_time": t.start_time if t else None,
                    "end_time": t.end_time if t else None,
                    "effective_distance_km": round(t.effective_distance_km, 3)
                    if t
                    else None,
                    "assigned": vid is not None,
                }
            )
        return result

    def fleet_summary(self) -> list[dict]:
        result = []
        for vid, st in self.states.items():
            spec = st.spec
            ev_soc_min = min(st.soc) if spec.vehicle_type == "ev_bus" else None
            ev_soc_final = st.soc[-1] if spec.vehicle_type == "ev_bus" else None
            ev_energy = (
                sum(
                    st.charging_power_kW[t] * self.cfg.dt_hour
                    for t in range(self.cfg.n_slots)
                )
                if spec.vehicle_type == "ev_bus"
                else 0.0
            )
            result.append(
                {
                    "vehicle_id": vid,
                    "vehicle_type": spec.vehicle_type,
                    "bus_category": getattr(spec, "bus_category", None),
                    "trips_assigned": len(st.assigned_trips),
                    "total_fuel_L": round(st.total_fuel_L, 3),
                    "total_energy_kWh": round(st.total_energy_kWh, 3),
                    "total_charging_kWh": round(ev_energy, 3),
                    "soc_min": round(ev_soc_min, 4) if ev_soc_min is not None else None,
                    "soc_final": round(ev_soc_final, 4)
                    if ev_soc_final is not None
                    else None,
                    "daily_capex_yen": round(spec.daily_capex_yen, 0),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Markdown summary
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        cb = self.cost_breakdown()
        lines = [
            f"# Route Cost Simulation Summary: {self.cfg.label}",
            "",
            "## Simulation Settings",
            f"- Time resolution: {self.cfg.delta_t_min} min",
            f"- Horizon: {self.cfg.time_horizon_hours} hours ({self.cfg.n_slots} slots)",
            f"- Diesel price: ¥{self.cfg.diesel_price_yen_per_L}/L",
            f"- Flat TOU rate: ¥{self.cfg.tariff.flat_price_yen_per_kWh}/kWh",
            "",
            "## Fleet",
            "",
            "| vehicle_id | type | trips | fuel_L | energy_kWh | soc_min | capex_yen/day |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for fs in self.fleet_summary():
            lines.append(
                f"| {fs['vehicle_id']} "
                f"| {fs['vehicle_type']} "
                f"| {fs['trips_assigned']} "
                f"| {fs['total_fuel_L']:.2f} "
                f"| {fs['total_energy_kWh']:.2f} "
                f"| {fs['soc_min'] if fs['soc_min'] is not None else '—'} "
                f"| {fs['daily_capex_yen']:,.0f} |"
            )
        lines += [
            "",
            "## Trip Assignments",
            "",
            "| trip_id | vehicle_id | route_id | start | end | distance_km |",
            "|---|---|---|---|---|---:|",
        ]
        for ta in self.trip_assignment_data():
            lines.append(
                f"| {ta['trip_id']} "
                f"| {ta['vehicle_id'] or '**UNASSIGNED**'} "
                f"| {ta['route_id']} "
                f"| {ta['start_time']} "
                f"| {ta['end_time']} "
                f"| {ta['effective_distance_km']:.2f} |"
            )
        lines += [
            "",
            "## Cost Breakdown",
            "",
            f"| Item | Amount (¥) |",
            f"|---|---:|",
            f"| Vehicle capex (daily) | {cb['vehicle_capex_cost_yen']:,.0f} |",
            f"| Fuel cost | {cb['fuel_cost_yen']:,.0f} |",
            f"| Electricity cost (TOU) | {cb['electricity_cost_yen']:,.0f} |",
            f"| Demand charge | {cb['demand_charge_yen']:,.0f} |",
            f"| Contract excess | {cb['contract_excess_cost_yen']:,.0f} |",
            f"| Grid basic charge | {cb['grid_basic_charge_yen']:,.0f} |",
            f"| **Total cost** | **{cb['total_cost_yen']:,.0f}** |",
            "",
            f"- Peak grid demand: {cb['peak_demand_kW']:.1f} kW",
            f"- Total grid purchase: {cb['total_grid_purchase_kWh']:.1f} kWh",
            f"- Total fuel consumption: {cb['total_fuel_consumption_L']:.1f} L",
            f"- Unassigned trips: {cb['unassigned_trips']}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Save all outputs
    # ------------------------------------------------------------------

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        # CSV timeseries
        p = out / "vehicle_operation_timeline.csv"
        self._write_operation_timeline(p)
        paths["operation_timeline"] = p

        p = out / "vehicle_soc_timeline.csv"
        self._write_soc_timeline(p)
        paths["soc_timeline"] = p

        p = out / "charging_power_timeline.csv"
        self._write_charging_timeline(p)
        paths["charging_timeline"] = p

        p = out / "grid_power_timeline.csv"
        self._write_grid_timeline(p)
        paths["grid_timeline"] = p

        # JSON summaries
        p = out / "cost_breakdown.json"
        p.write_text(
            json.dumps(self.cost_breakdown(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths["cost_breakdown"] = p

        p = out / "trip_assignment.json"
        p.write_text(
            json.dumps(self.trip_assignment_data(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths["trip_assignment"] = p

        p = out / "fleet_summary.json"
        p.write_text(
            json.dumps(self.fleet_summary(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths["fleet_summary"] = p

        # Markdown
        p = out / "simulation_summary.md"
        p.write_text(self.to_markdown(), encoding="utf-8")
        paths["summary_md"] = p

        return paths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
