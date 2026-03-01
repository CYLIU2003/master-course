"""src.preprocess パッケージ"""
from .route_builder import validate_route_network, build_variant_segments, summarize_route_statistics
from .timetable_generator import generate_departure_times, expand_service_calendar
from .trip_generator import generate_trip_from_variant, generate_all_trips
from .energy_model import estimate_trip_energy_bev, estimate_segment_energy_bev, apply_energy_uncertainty
from .fuel_model import estimate_trip_fuel_ice, estimate_trip_fuel_hev
from .deadhead_builder import build_deadhead_arcs, build_can_follow_matrix
from .scenario_generator import generate_scenarios, apply_scenario_to_trips
from .duty_loader import load_vehicle_duties, validate_duties, build_duty_trip_mapping, build_trip_duty_mapping, identify_charging_opportunities
from .trip_converter import (
    convert_trips_to_tasks, convert_deadhead_arcs_to_connections,
    convert_vehicle_types_to_vehicles, build_vehicle_task_compat,
    build_vehicle_charger_compat, build_problem_data_from_generated,
)
from .passenger_load import load_passenger_load_profile, build_load_factor_map, apply_load_factor_to_trips, compute_demand_kpi
from .tariff_loader import load_tariff_csv, build_electricity_prices_from_tariff, load_fare_table, estimate_trip_revenue, compute_route_profitability

__all__ = [
    "validate_route_network", "build_variant_segments", "summarize_route_statistics",
    "generate_departure_times", "expand_service_calendar",
    "generate_trip_from_variant", "generate_all_trips",
    "estimate_trip_energy_bev", "estimate_segment_energy_bev", "apply_energy_uncertainty",
    "estimate_trip_fuel_ice", "estimate_trip_fuel_hev",
    "build_deadhead_arcs", "build_can_follow_matrix",
    "generate_scenarios", "apply_scenario_to_trips",
    # duty_loader
    "load_vehicle_duties", "validate_duties", "build_duty_trip_mapping",
    "build_trip_duty_mapping", "identify_charging_opportunities",
    # trip_converter
    "convert_trips_to_tasks", "convert_deadhead_arcs_to_connections",
    "convert_vehicle_types_to_vehicles", "build_vehicle_task_compat",
    "build_vehicle_charger_compat", "build_problem_data_from_generated",
    # passenger_load
    "load_passenger_load_profile", "build_load_factor_map",
    "apply_load_factor_to_trips", "compute_demand_kpi",
    # tariff_loader
    "load_tariff_csv", "build_electricity_prices_from_tariff",
    "load_fare_table", "estimate_trip_revenue", "compute_route_profitability",
]
