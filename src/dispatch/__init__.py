"""
src/dispatch/__init__.py

Public API for the timetable-driven dispatch planning module.
"""

from .models import (
    DispatchContext,
    ConnectionResult,
    DispatchPlan,
    DeadheadRule,
    DutyLeg,
    Trip,
    TurnaroundRule,
    ValidationResult,
    VehicleBlock,
    VehicleDuty,
    VehicleProfile,
    hhmm_to_min,
)
from .feasibility import FeasibilityEngine
from .graph_builder import ConnectionGraphBuilder
from .dispatcher import DispatchGenerator
from .validator import DutyValidator
from .pipeline import TimetableDispatchPipeline, PipelineResult
try:
    from .context_builder import load_dispatch_context_from_csv
except ModuleNotFoundError:  # pragma: no cover - optional dependency (pandas)
    load_dispatch_context_from_csv = None

from .problemdata_adapter import (
    DispatchTravelBuildReport,
    build_travel_connections_via_dispatch,
)

__all__ = [
    # models
    "DispatchContext",
    "ConnectionResult",
    "DispatchPlan",
    "DeadheadRule",
    "DutyLeg",
    "Trip",
    "TurnaroundRule",
    "ValidationResult",
    "VehicleBlock",
    "VehicleDuty",
    "VehicleProfile",
    "hhmm_to_min",
    # engines
    "FeasibilityEngine",
    "ConnectionGraphBuilder",
    "DispatchGenerator",
    "DutyValidator",
    "load_dispatch_context_from_csv",
    "DispatchTravelBuildReport",
    "build_travel_connections_via_dispatch",
    # pipeline
    "TimetableDispatchPipeline",
    "PipelineResult",
]
