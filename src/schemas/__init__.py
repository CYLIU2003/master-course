"""
src.schemas — route / fleet / trip エンティティ定義

spec_v3 §2 に準拠したデータモデル。
"""

from .route_entities import (
    Route,
    Terminal,
    Stop,
    Segment,
    RouteVariant,
    TimetablePattern,
    ServiceCalendarRow,
    GeneratedTrip,
    DeadheadArc,
)
from .fleet_entities import VehicleType, VehicleInstance
from .trip_entities import ScenarioTripEnergy
from .duty_entities import (
    DutyLeg,
    VehicleDuty,
    DutyChargingSlot,
    DutyAssignmentConfig,
)

__all__ = [
    "Route", "Terminal", "Stop", "Segment",
    "RouteVariant", "TimetablePattern", "ServiceCalendarRow",
    "GeneratedTrip", "DeadheadArc",
    "VehicleType", "VehicleInstance",
    "ScenarioTripEnergy",
    "DutyLeg", "VehicleDuty", "DutyChargingSlot", "DutyAssignmentConfig",
]
