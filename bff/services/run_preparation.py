from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


log = logging.getLogger("run_prep")


@dataclass
class RunPreparation:
    scenario_id: str
    dataset_version: str
    scenario_hash: str
    solver_input_path: Optional[Path]
    scope_summary: dict
    prepared_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.solver_input_path is not None


_prep_cache: dict[tuple[str, str, str], RunPreparation] = {}


def _scenario_hash(scenario_dict: dict) -> str:
    canonical = json.dumps(scenario_dict, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def get_or_build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
) -> RunPreparation:
    scenario_id = str(scenario.get("id") or scenario.get("scenario_id") or "unknown")
    dataset_version = str(scenario.get("datasetVersion") or scenario.get("dataset_version") or "unknown")
    scenario_hash = _scenario_hash(scenario)
    cache_key = (scenario_id, dataset_version, scenario_hash)

    if cache_key in _prep_cache:
        cached = _prep_cache[cache_key]
        if cached.is_valid:
            log.debug("run_prep cache HIT: %s %s", scenario_id, scenario_hash)
            return cached
        log.debug("run_prep cache INVALID: %s", scenario_id)

    log.info("Building run preparation for scenario %s (hash=%s)", scenario_id, scenario_hash)
    prep = _build_run_preparation(scenario, built_dir, scenarios_dir, routes_df, scenario_hash)
    _prep_cache[cache_key] = prep
    return prep


def _build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
    scenario_hash: str,
) -> RunPreparation:
    scenario_id = str(scenario.get("id") or scenario.get("scenario_id") or "unknown")
    dataset_version = str(scenario.get("datasetVersion") or scenario.get("dataset_version") or "unknown")
    try:
        from src.runtime_scope import load_scoped_timetables, load_scoped_trips, resolve_scope

        overlay = dict(scenario.get("scenarioOverlay") or scenario.get("scenario_overlay") or {})
        scope = resolve_scope(overlay, routes_df)
        trips_df = load_scoped_trips(built_dir, scope)
        timetables_df = load_scoped_timetables(built_dir, scope)

        solver_input = {
            "scenario_id": scenario_id,
            "dataset_version": dataset_version,
            "scenario_hash": scenario_hash,
            "depot_ids": scope.depot_ids,
            "route_ids": scope.route_ids,
            "random_seed": scenario.get("randomSeed") or scenario.get("random_seed") or 42,
            "trip_count": len(trips_df),
            "timetable_row_count": len(timetables_df),
        }
        scenario_dir = scenarios_dir / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        solver_input_path = scenario_dir / "solver_input.json"
        solver_input_path.write_text(
            json.dumps(solver_input, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            solver_input_path=solver_input_path,
            scope_summary={
                "depot_ids": scope.depot_ids,
                "route_ids": scope.route_ids,
                "trip_count": len(trips_df),
            },
        )
    except Exception as exc:
        log.error("run_preparation failed for %s: %s", scenario_id, exc)
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            solver_input_path=None,
            scope_summary={},
            error=str(exc),
        )


def invalidate_scenario(scenario_id: str) -> None:
    keys = [key for key in _prep_cache if key[0] == scenario_id]
    for key in keys:
        del _prep_cache[key]
    if keys:
        log.info("Invalidated %s run_prep cache entries for %s", len(keys), scenario_id)
