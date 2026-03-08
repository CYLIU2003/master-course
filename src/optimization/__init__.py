"""
Shared optimization engines built on top of the timetable-first dispatch core.
"""

from .common.builder import ProblemBuilder
from .common.evaluator import CostBreakdown, CostEvaluator
from .common.feasibility import FeasibilityChecker, FeasibilityReport
from .common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    ChargingSlot,
    EnergyPriceSlot,
    IncumbentSnapshot,
    LockedOperation,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    OptimizationObjectiveWeights,
    OperatorStats,
    OptimizationScenario,
    PVSlot,
    ProblemDepot,
    ProblemRoute,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
    SolutionState,
)
from .common.result import ResultSerializer
from .engine import OptimizationEngine

__all__ = [
    "AssignmentPlan",
    "CanonicalOptimizationProblem",
    "ChargerDefinition",
    "ChargingSlot",
    "CostBreakdown",
    "CostEvaluator",
    "EnergyPriceSlot",
    "FeasibilityChecker",
    "FeasibilityReport",
    "IncumbentSnapshot",
    "LockedOperation",
    "OptimizationConfig",
    "OptimizationEngine",
    "OptimizationEngineResult",
    "OptimizationMode",
    "OptimizationObjectiveWeights",
    "OperatorStats",
    "OptimizationScenario",
    "PVSlot",
    "ProblemBuilder",
    "ProblemDepot",
    "ProblemRoute",
    "ProblemTrip",
    "ProblemVehicle",
    "ProblemVehicleType",
    "ResultSerializer",
    "SolutionState",
]
