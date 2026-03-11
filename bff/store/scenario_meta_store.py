from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def scenario_path(store_dir: Path, scenario_id: str) -> Path:
    return store_dir / f"{scenario_id}.json"


def artifact_dir(store_dir: Path, scenario_id: str) -> Path:
    return store_dir / scenario_id


def default_refs(store_dir: Path, scenario_id: str) -> Dict[str, str]:
    base = artifact_dir(store_dir, scenario_id)
    return {
        "masterData": str(base / "master_data.sqlite"),
        "artifactStore": str(base / "artifacts.sqlite"),
        "timetableRows": str(base / "timetable_rows.json"),
        "stopTimetables": str(base / "stop_timetables.json"),
        "tripSet": str(base / "trip_set.parquet"),
        "graph": str(base / "graph.json"),
        "blocks": str(base / "blocks.parquet"),
        "duties": str(base / "duties.parquet"),
        "dispatchPlan": str(base / "dispatch_plan.json"),
        "simulationResult": str(base / "simulation_result.json"),
        "optimizationResult": str(base / "optimization_result.json"),
    }


def load_meta(store_dir: Path, scenario_id: str) -> Dict[str, Any]:
    path = scenario_path(store_dir, scenario_id)
    if not path.exists():
        raise KeyError(scenario_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_meta(store_dir: Path, scenario_id: str, payload: Dict[str, Any]) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir(store_dir, scenario_id).mkdir(parents=True, exist_ok=True)
    scenario_path(store_dir, scenario_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
