"""
src/dispatch/validator.py

DutyValidator: post-hoc validation of a VehicleDuty produced by any dispatcher.

Checks performed:
1. Empty duty guard — a duty must contain at least one leg.
2. Vehicle type constraint — every trip must allow the duty's vehicle_type.
3. Location continuity — consecutive trip endpoints must match or have a
   deadhead rule (same rule as FeasibilityEngine).
4. Time continuity — hard constraint: arrival(i) + turnaround + deadhead
   <= departure(j) for every consecutive pair.
"""

from __future__ import annotations

from .feasibility import FeasibilityEngine
from .models import DispatchContext, ValidationResult, VehicleDuty


class DutyValidator:
    """Validates a VehicleDuty against the DispatchContext rules."""

    def __init__(self) -> None:
        self._engine = FeasibilityEngine()

    def validate_vehicle_duty(
        self,
        duty: VehicleDuty,
        context: DispatchContext,
    ) -> ValidationResult:
        """
        Return a ValidationResult.  All errors are collected (not short-circuit)
        so callers can see the full picture in one pass.
        """
        errors: list[str] = []

        # --- 1. Empty duty ---
        if not duty.legs:
            return ValidationResult.fail("Duty has no legs (empty duty)")

        # --- 2. Vehicle type per trip ---
        for leg in duty.legs:
            if duty.vehicle_type not in leg.trip.allowed_vehicle_types:
                errors.append(
                    f"Trip '{leg.trip.trip_id}' does not allow vehicle type "
                    f"'{duty.vehicle_type}' (allowed: {leg.trip.allowed_vehicle_types})"
                )

        # --- 3 & 4. Consecutive pair checks ---
        for i in range(len(duty.legs) - 1):
            trip_i = duty.legs[i].trip
            trip_j = duty.legs[i + 1].trip

            result = self._engine.can_connect(
                trip_i, trip_j, context, duty.vehicle_type
            )
            if not result.feasible:
                errors.append(
                    f"Connection from trip '{trip_i.trip_id}' to "
                    f"'{trip_j.trip_id}' is infeasible: {result.reason}"
                )

        if errors:
            return ValidationResult.fail(*errors)
        return ValidationResult.ok()
