from collections import Counter

from bff.routers.optimization import _rebuild_dispatch_artifacts
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def main() -> None:
    _rebuild_dispatch_artifacts(SCENARIO_ID, SERVICE_ID, DEPOT_ID)

    scenario = store.get_scenario_document_shallow(SCENARIO_ID)
    scenario["trips"] = store.get_field(SCENARIO_ID, "trips") or []
    scenario["duties"] = store.get_field(SCENARIO_ID, "duties") or []
    scenario["blocks"] = store.get_field(SCENARIO_ID, "blocks") or []
    scenario["timetable_rows"] = store.get_field(SCENARIO_ID, "timetable_rows") or []

    data, _ = build_problem_data_from_scenario(
        scenario,
        depot_id=DEPOT_ID,
        service_id=SERVICE_ID,
        mode="mode_milp_only",
        use_existing_duties=False,
        analysis_scope=store.get_dispatch_scope(SCENARIO_ID),
    )

    vehicle_counter = Counter(v.vehicle_id for v in data.vehicles)
    task_counter = Counter(t.task_id for t in data.tasks)

    vehicle_dups = [k for k, v in vehicle_counter.items() if v > 1]
    task_dups = [k for k, v in task_counter.items() if v > 1]

    print("vehicles:", len(data.vehicles), "duplicate_id_count:", len(vehicle_dups))
    print("tasks:", len(data.tasks), "duplicate_id_count:", len(task_dups))
    print("sample_vehicle_dups:", vehicle_dups[:10])
    print("sample_task_dups:", task_dups[:10])


if __name__ == "__main__":
    main()
