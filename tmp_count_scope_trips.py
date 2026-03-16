import json
from bff.store import scenario_store as store
from bff.mappers.scenario_to_problemdata import _collect_trips_for_scope

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"

scenario = store.get_scenario_document(SCENARIO_ID)
scope = store.get_dispatch_scope(SCENARIO_ID)

rows = {}
for sid in ["WEEKDAY", "SAT", "SUN_HOL", "SAT_HOL", "SUN", "HOLIDAY"]:
    trips_scoped = _collect_trips_for_scope(scenario, DEPOT_ID, sid, analysis_scope=scope)
    trips_depot_only = _collect_trips_for_scope(scenario, DEPOT_ID, sid, analysis_scope=None)
    rows[sid] = {
        "with_scope": len(trips_scoped),
        "depot_only": len(trips_depot_only),
    }

with open("tmp_count_scope_trips.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)

print("wrote tmp_count_scope_trips.json")
