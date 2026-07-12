"""Align a target weather case to a reference case without replacing weather inputs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bff.services.weather_comparison import (
    align_scenario_overlay,
    align_simulation_config,
    comparison_mismatches,
    validate_weather_case_alignment,
)
from bff.store import output_paths, scenario_store


DEFAULT_REFERENCE_SCENARIO_ID = "771d115b-75b0-49f7-a7f0-25f259a2cd21"
DEFAULT_TARGET_SCENARIO_ID = "b23fd26c-1233-4c73-bb9e-bdb8b1584760"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Align weather-case controls while preserving the target date/PV inputs."
    )
    parser.add_argument("--reference-scenario-id", default=DEFAULT_REFERENCE_SCENARIO_ID)
    parser.add_argument("--target-scenario-id", default=DEFAULT_TARGET_SCENARIO_ID)
    parser.add_argument("--apply", action="store_true", help="Persist the aligned target and invalidate stale results.")
    args = parser.parse_args()

    reference = scenario_store.get_scenario_document_shallow(args.reference_scenario_id)
    target = scenario_store.get_scenario_document_shallow(args.target_scenario_id)
    reference_config = _mapping(reference.get("simulation_config"), "reference simulation_config")
    target_config = _mapping(target.get("simulation_config"), "target simulation_config")
    reference_overlay = _mapping(reference.get("scenario_overlay"), "reference scenario_overlay")
    target_overlay = _mapping(target.get("scenario_overlay"), "target scenario_overlay")

    before = {
        "simulation_config": comparison_mismatches(
            reference_config, target_config, config_label="simulation_config"
        ),
        "scenario_overlay": comparison_mismatches(
            reference_overlay, target_overlay, config_label="scenario_overlay"
        ),
    }
    aligned_config = align_simulation_config(reference_config, target_config)
    aligned_overlay = align_scenario_overlay(reference_overlay, target_overlay)
    validate_weather_case_alignment(
        reference_config,
        target_config,
        aligned_config,
        config_label="simulation_config",
    )
    validate_weather_case_alignment(
        reference_overlay,
        target_overlay,
        aligned_overlay,
        config_label="scenario_overlay",
    )
    after = {
        "simulation_config": comparison_mismatches(
            reference_config, aligned_config, config_label="simulation_config"
        ),
        "scenario_overlay": comparison_mismatches(
            reference_overlay, aligned_overlay, config_label="scenario_overlay"
        ),
    }
    if any(after.values()):
        raise RuntimeError(f"Alignment left control mismatches: {after}")

    if args.apply:
        scenario_store.replace_scenario_experiment_configuration(
            args.target_scenario_id,
            simulation_config=aligned_config,
            scenario_overlay=aligned_overlay,
        )

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_scenario_id": args.reference_scenario_id,
        "target_scenario_id": args.target_scenario_id,
        "applied": bool(args.apply),
        "before_control_mismatches": before,
        "after_control_mismatches": after,
        "target_weather_inputs": {
            key: aligned_config.get(key)
            for key in (
                "service_date",
                "service_dates",
                "pv_profile_id",
                "weather_proxy_forecast_path",
                "weather_proxy_station_id",
                "weather_proxy_station_name",
                "weather_reference_date",
                "solcast_proxy_issue_date",
            )
        },
    }
    output_path = output_paths.outputs_root() / "weather_comparison_alignment_audit.json"
    output_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is required")
    return dict(value)


if __name__ == "__main__":
    raise SystemExit(main())
