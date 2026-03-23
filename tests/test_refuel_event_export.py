from datetime import date

from src.data_schema import ProblemData, Vehicle
from src.milp_model import MILPResult
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params
from src.result_exporter import _build_refuel_event_rows


def test_build_refuel_event_rows_sorted_and_fields() -> None:
    data = ProblemData(
        vehicles=[
            Vehicle(vehicle_id="ice-b", vehicle_type="ICE", home_depot="dep-2", fuel_tank_capacity=160.0),
            Vehicle(vehicle_id="ice-a", vehicle_type="ICE", home_depot="dep-1", fuel_tank_capacity=160.0),
        ],
        tasks=[],
        num_periods=8,
        delta_t_hour=0.5,
    )
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    milp = MILPResult(status="FEASIBLE")
    milp.refuel_schedule_l = {
        "ice-a": [0.0, 5.0, 0.0, 0.0],
        "ice-b": [0.0, 0.0, 6.5, 0.0],
    }

    rows = _build_refuel_event_rows(
        data,
        ms,
        dp,
        milp,
        scenario_id="s-1",
        base_date=date(2026, 3, 23),
        planning_start_time="05:00",
    )

    assert len(rows) == 2
    assert rows[0]["vehicle_id"] == "ice-a"
    assert rows[0]["vehicle_type"] == "ICE"
    assert rows[0]["depot_id"] == "dep-1"
    assert "route_band_id" in rows[0]
    assert "route_band_label" in rows[0]
    assert rows[0]["time_hhmm"] == "05:30"
    assert rows[0]["refuel_liters"] == 5.0
    assert rows[1]["vehicle_id"] == "ice-b"
    assert rows[1]["vehicle_type"] == "ICE"
    assert rows[1]["time_hhmm"] == "06:00"
