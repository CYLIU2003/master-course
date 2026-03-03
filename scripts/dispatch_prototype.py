"""
scripts/dispatch_prototype.py

End-to-end runnable demonstration of the TimetableDispatchPipeline.

Scenario:
- 5 revenue trips on service date 2024-06-01
- Stops: A (depot), B (city centre), C (airport)
- Vehicle type: BEV (electric bus)
- Two clusters of trips that can chain within a single duty;
  one trip that requires a deadhead to connect.

Run from repo root:
    python scripts/dispatch_prototype.py
"""

from __future__ import annotations

from src.dispatch import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TimetableDispatchPipeline,
    TurnaroundRule,
    VehicleProfile,
)


# ---------------------------------------------------------------------------
# Build a small DispatchContext manually
# ---------------------------------------------------------------------------

TRIPS = [
    Trip(
        trip_id="T1",
        route_id="R1",
        origin="A",
        destination="B",
        departure_time="07:00",
        arrival_time="07:30",
        distance_km=15.0,
        allowed_vehicle_types=("BEV",),
    ),
    Trip(
        trip_id="T2",
        route_id="R1",
        origin="B",
        destination="A",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=15.0,
        allowed_vehicle_types=("BEV",),
    ),
    Trip(
        trip_id="T3",
        route_id="R1",
        origin="A",
        destination="B",
        departure_time="09:00",
        arrival_time="09:30",
        distance_km=15.0,
        allowed_vehicle_types=("BEV",),
    ),
    Trip(
        trip_id="T4",
        route_id="R2",
        origin="A",
        destination="C",
        departure_time="07:15",
        arrival_time="08:00",
        distance_km=30.0,
        allowed_vehicle_types=("BEV",),
    ),
    Trip(
        trip_id="T5",
        route_id="R2",
        origin="C",
        destination="A",
        departure_time="09:00",
        arrival_time="09:45",
        distance_km=30.0,
        allowed_vehicle_types=("BEV",),
    ),
]

TURNAROUND_RULES = {
    "A": TurnaroundRule(stop_id="A", min_turnaround_min=10),
    "B": TurnaroundRule(stop_id="B", min_turnaround_min=15),
    "C": TurnaroundRule(stop_id="C", min_turnaround_min=20),
}

# Deadhead from B (city centre) to A (depot): 10 min
# Deadhead from C (airport) to A (depot): 15 min
DEADHEAD_RULES = {
    ("B", "A"): DeadheadRule(from_stop="B", to_stop="A", travel_time_min=10),
    ("A", "B"): DeadheadRule(from_stop="A", to_stop="B", travel_time_min=10),
    ("C", "A"): DeadheadRule(from_stop="C", to_stop="A", travel_time_min=15),
    ("A", "C"): DeadheadRule(from_stop="A", to_stop="C", travel_time_min=20),
}

VEHICLE_PROFILES = {
    "BEV": VehicleProfile(
        vehicle_type="BEV",
        battery_capacity_kwh=300.0,
        energy_consumption_kwh_per_km=1.8,
    ),
}

context = DispatchContext(
    service_date="2024-06-01",
    trips=TRIPS,
    turnaround_rules=TURNAROUND_RULES,
    deadhead_rules=DEADHEAD_RULES,
    vehicle_profiles=VEHICLE_PROFILES,
    default_turnaround_min=10,
)


# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------


def main() -> None:
    pipeline = TimetableDispatchPipeline()
    result = pipeline.run(context, vehicle_type="BEV")

    # --- Connection graph ---
    print("=" * 60)
    print("CONNECTION GRAPH (feasible edges, BEV)")
    print("=" * 60)
    for node, successors in sorted(result.graph.items()):
        print(f"  {node}  →  {successors if successors else '(no successors)'}")

    # --- Generated duties ---
    print()
    print("=" * 60)
    print(f"GENERATED DUTIES  ({len(result.duties)} vehicle(s) required)")
    print("=" * 60)
    for duty in result.duties:
        print(f"\n  Duty: {duty.duty_id}  [{duty.vehicle_type}]")
        for i, leg in enumerate(duty.legs):
            t = leg.trip
            dh = (
                f"  (deadhead {leg.deadhead_from_prev_min} min)"
                if leg.deadhead_from_prev_min
                else ""
            )
            print(
                f"    Leg {i + 1}: {t.trip_id}  {t.origin} → {t.destination}"
                f"  {t.departure_time}–{t.arrival_time}{dh}"
            )

    # --- Validation results ---
    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    for duty_id, vr in result.validation.items():
        status = "PASS" if vr.valid else "FAIL"
        print(f"  {duty_id}: {status}")
        for err in vr.errors:
            print(f"    ERROR: {err}")

    # --- Warnings ---
    if result.warnings:
        print()
        print("WARNINGS:")
        for w in result.warnings:
            print(f"  ! {w}")

    # --- Summary ---
    print()
    print("=" * 60)
    trips_covered = sum(len(d.legs) for d in result.duties)
    print(
        f"Summary: {len(result.duties)} duties, "
        f"{trips_covered}/{len(TRIPS)} trips covered, "
        f"all_valid={result.all_valid}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
