"""
src/dispatch/pipeline.py

TimetableDispatchPipeline: façade that orchestrates the full dispatch workflow.

Pipeline steps (in order):
1. Validate context inputs (non-empty trip list, etc.)
2. Build feasibility graph for each requested vehicle type.
3. Generate greedy duties per vehicle type.
4. Validate every generated duty.
5. Return consolidated results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .dispatcher import DispatchGenerator
from .graph_builder import ConnectionGraphBuilder
from .models import DispatchContext, ValidationResult, VehicleDuty
from .validator import DutyValidator


@dataclass
class PipelineResult:
    """Consolidated output of one pipeline run."""

    service_date: str
    vehicle_type: str
    duties: List[VehicleDuty]
    graph: Dict[str, List[str]]  # adjacency list
    validation: Dict[str, ValidationResult]  # duty_id → result
    uncovered_trip_ids: List[str] = field(default_factory=list)
    duplicate_trip_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return (
            all(v.valid for v in self.validation.values())
            and not self.uncovered_trip_ids
            and not self.duplicate_trip_ids
        )

    @property
    def invalid_duties(self) -> List[str]:
        return [did for did, v in self.validation.items() if not v.valid]


class TimetableDispatchPipeline:
    """
    Orchestrates: context → graph → duties → validation → PipelineResult.

    Usage::

        pipeline = TimetableDispatchPipeline()
        result = pipeline.run(context, vehicle_type="BEV")
    """

    def __init__(self) -> None:
        self._graph_builder = ConnectionGraphBuilder()
        self._dispatcher = DispatchGenerator()
        self._validator = DutyValidator()

    def run(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> PipelineResult:
        """Execute the full pipeline for a single vehicle type."""
        warnings: List[str] = []

        # Step 1 — basic context validation
        if not context.trips:
            warnings.append("DispatchContext contains no trips; result will be empty.")

        eligible = [t for t in context.trips if vehicle_type in t.allowed_vehicle_types]
        if not eligible:
            warnings.append(
                f"No trips allow vehicle type '{vehicle_type}'; "
                "no duties will be generated."
            )

        # Step 2 — build feasibility graph
        graph = self._graph_builder.build(context, vehicle_type)

        # Step 3 — generate greedy duties
        duties = self._dispatcher.generate_greedy_duties_from_graph(
            context,
            vehicle_type,
            graph,
        )

        # Step 4 — validate every duty
        validation: Dict[str, ValidationResult] = {}
        for duty in duties:
            validation[duty.duty_id] = self._validator.validate_vehicle_duty(
                duty, context
            )

        # Step 5 — warn about any validation failures
        for duty_id, result in validation.items():
            if not result.valid:
                for err in result.errors:
                    warnings.append(f"[{duty_id}] {err}")

        # Step 6 — coverage / uniqueness across all eligible trips
        eligible_trip_ids = {
            t.trip_id for t in context.trips if vehicle_type in t.allowed_vehicle_types
        }
        assigned_trip_ids: List[str] = []
        for duty in duties:
            assigned_trip_ids.extend(duty.trip_ids)

        assigned_once = set(assigned_trip_ids)
        uncovered_trip_ids = sorted(eligible_trip_ids - assigned_once)

        seen: set[str] = set()
        duplicate_trip_ids: List[str] = []
        for trip_id in assigned_trip_ids:
            if trip_id in seen:
                duplicate_trip_ids.append(trip_id)
            seen.add(trip_id)

        if uncovered_trip_ids:
            warnings.append(
                "Uncovered trips detected for "
                f"vehicle_type='{vehicle_type}': {', '.join(uncovered_trip_ids)}"
            )
        if duplicate_trip_ids:
            warnings.append(
                "Duplicate trip assignments detected for "
                f"vehicle_type='{vehicle_type}': {', '.join(sorted(set(duplicate_trip_ids)))}"
            )

        return PipelineResult(
            service_date=context.service_date,
            vehicle_type=vehicle_type,
            duties=duties,
            graph=graph,
            validation=validation,
            uncovered_trip_ids=uncovered_trip_ids,
            duplicate_trip_ids=sorted(set(duplicate_trip_ids)),
            warnings=warnings,
        )

    def run_all_types(
        self,
        context: DispatchContext,
        vehicle_types: Optional[List[str]] = None,
    ) -> Dict[str, PipelineResult]:
        """
        Run the pipeline for multiple vehicle types.
        If *vehicle_types* is None, uses all types from context.vehicle_profiles.
        """
        types = vehicle_types or list(context.vehicle_profiles.keys())
        return {vt: self.run(context, vt) for vt in types}
