"""
src/dispatch/__init__.py

Public API for the timetable-driven dispatch planning module.
"""

from .models import (
    DispatchContext,
    ConnectionResult,
    DeadheadRule,
    DutyLeg,
    Trip,
    TurnaroundRule,
    ValidationResult,
    VehicleDuty,
    VehicleProfile,
    hhmm_to_min,
)
from .feasibility import FeasibilityEngine
from .graph_builder import ConnectionGraphBuilder
from .dispatcher import DispatchGenerator
from .validator import DutyValidator
from .pipeline import TimetableDispatchPipeline, PipelineResult
from .context_builder import load_dispatch_context_from_csv
from .odpt_adapter import supplement_context_from_odpt
from .problemdata_adapter import (
    DispatchTravelBuildReport,
    build_travel_connections_via_dispatch,
)

__all__ = [
    # models
    "DispatchContext",
    "ConnectionResult",
    "DeadheadRule",
    "DutyLeg",
    "Trip",
    "TurnaroundRule",
    "ValidationResult",
    "VehicleDuty",
    "VehicleProfile",
    "hhmm_to_min",
    # engines
    "FeasibilityEngine",
    "ConnectionGraphBuilder",
    "DispatchGenerator",
    "DutyValidator",
    "load_dispatch_context_from_csv",
    "supplement_context_from_odpt",
    "DispatchTravelBuildReport",
    "build_travel_connections_via_dispatch",
    # pipeline
    "TimetableDispatchPipeline",
    "PipelineResult",
]
