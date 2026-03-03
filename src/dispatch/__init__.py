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
    # pipeline
    "TimetableDispatchPipeline",
    "PipelineResult",
]
