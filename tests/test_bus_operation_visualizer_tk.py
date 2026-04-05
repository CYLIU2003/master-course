from __future__ import annotations

from pathlib import Path

from tools.bus_operation_visualizer_tk import _load_bundle


def test_load_bundle_supports_current_gantt_schema_with_state_and_iso_times(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260405_1713"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "vehicle_timeline_gantt.csv").write_text(
        "\n".join(
            [
                "vehicle_id,state,start_time,end_time,duration_min",
                "veh-1,service,2026-04-05T05:57:00,2026-04-05T06:22:00,25.0",
                "veh-1,deadhead,2026-04-05T06:22:00,2026-04-05T06:35:00,13.0",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "vehicle_schedule.csv").write_text(
        "\n".join(
            [
                "vehicle_id,vehicle_type,task_id",
                "veh-1,BEV,trip-1",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "charging_schedule.csv").write_text(
        "vehicle_id,time_idx,p_charge_kw,z_charge,charger_id\n",
        encoding="utf-8",
    )
    (run_dir / "refuel_events.csv").write_text(
        "vehicle_id,vehicle_type,depot_id,route_band_id,route_band_label,slot_index,event_time,time_hhmm,refuel_liters\n",
        encoding="utf-8",
    )

    bundle = _load_bundle(run_dir)

    assert len(bundle.events) == 2
    assert bundle.vehicle_types == {"veh-1": "BEV"}
    assert bundle.events["event_type"].tolist() == ["service", "deadhead"]
    assert bundle.events["start_minute"].tolist() == [357, 382]
    assert bundle.events["end_minute"].tolist() == [382, 395]
