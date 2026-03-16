from pathlib import Path
from bff.store import scenario_store, scenario_meta_store, trip_store
from bff.store.scenario_store import _STORE_DIR, _refs_for_scenario, _SQLITE_SCALAR_ARTIFACT_FIELDS, _artifact_store_path

orig_set_field = scenario_store.set_field

def patched_set_field(scenario_id: str, field: str, value: any, *, invalidate_dispatch: bool = False) -> None:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    
    if field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
        db_path = _artifact_store_path(refs)
        trip_store.save_scalar(db_path, field, value)
    elif field == "optimization_audit":
        doc = scenario_store._load_shallow(scenario_id)
        doc[field] = value
        scenario_store._save_master_only(doc, invalidate_dispatch=invalidate_dispatch)
    else:
        orig_set_field(scenario_id, field, value, invalidate_dispatch=invalidate_dispatch)
        
scenario_store.set_field = patched_set_field
