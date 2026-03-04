"""
tests/test_data_loader_dispatch_preprocess.py

Ensures load_problem_data can rebuild travel connections through dispatch preprocess.
"""

import json
from pathlib import Path

from src.data_loader import load_problem_data


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_problem_data_rebuilds_connections_when_missing(tmp_path: Path):
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    _write(
        tmp_path / "data" / "vehicles.csv",
        "vehicle_id,vehicle_type,home_depot\nBEV_1,BEV,depot_A\n",
    )
    _write(
        tmp_path / "data" / "tasks.csv",
        "task_id,start_time_idx,end_time_idx,origin,destination,distance_km,energy_required_kwh_bev,fuel_required_liter_ice,required_vehicle_type,demand_cover,penalty_unserved\n"
        "T1,0,2,depot_A,terminal_B,10,5,0,,true,10000\n"
        "T2,3,5,terminal_B,depot_A,10,5,0,,true,10000\n",
    )
    _write(
        tmp_path / "data" / "chargers.csv",
        "charger_id,site_id,power_max_kw,efficiency,power_min_kw\n"
        "C1,depot_A,50,0.95,0\n",
    )
    _write(
        tmp_path / "data" / "sites.csv",
        "site_id,site_type,grid_import_limit_kw,contract_demand_limit_kw,site_transformer_limit_kw\n"
        "depot_A,depot,500,500,500\n"
        "terminal_B,terminal,500,500,500\n",
    )

    cfg = {
        "time_step_min": 15,
        "num_periods": 16,
        "planning_horizon_hours": 4.0,
        "paths": {
            "vehicles_csv": "data/vehicles.csv",
            "tasks_csv": "data/tasks.csv",
            "chargers_csv": "data/chargers.csv",
            "sites_csv": "data/sites.csv",
        },
        "dispatch_preprocess": {
            "enabled": True,
            "default_turnaround_min": 0,
            "rebuild_when_missing": True,
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    data = load_problem_data(cfg_path)

    assert len(data.travel_connections) == 2
    by_pair = {(c.from_task_id, c.to_task_id): c for c in data.travel_connections}
    assert by_pair[("T1", "T2")].can_follow is True
    assert by_pair[("T2", "T1")].can_follow is False

    report = getattr(data, "_dispatch_preprocess_report", None)
    assert report is not None
    assert report.trip_count == 2
