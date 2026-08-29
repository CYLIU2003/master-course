"""Capture exact Prepared-input parameter sources for thesis reporting.

The published review bundle intentionally contains only a compact subset of
the raw run.  This command copies the two exact run-input snapshots and their
provenance manifests into a small Git-trackable supplement, then records the
parameter values and hashes used by the thesis result builder.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "thesis_weather_parameter_sources_v1"
EXECUTION_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
SCENARIO_IDS = {
    "SUNNY": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
    "RAIN": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
}
ASSET_FIELDS = (
    "pv_capacity_kw",
    "bess_enabled",
    "bess_energy_kwh",
    "bess_power_kw",
    "bess_initial_soc_kwh",
    "bess_soc_min_kwh",
    "bess_soc_max_kwh",
    "bess_charge_efficiency",
    "bess_discharge_efficiency",
    "bess_terminal_soc_target_kwh",
)


class ParameterSourceError(RuntimeError):
    """Raised when raw Prepared-input provenance is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParameterSourceError(message)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"Expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }


def extract_parameter_values(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Extract effective depot energy parameters from one run-input snapshot."""

    persisted = snapshot["persisted_scenario"]
    charger_sites = persisted["charger_sites"]
    _require(len(charger_sites) == 1, "Expected exactly one charger site")
    charger_site = charger_sites[0]
    _require(charger_site["id"] == "tsurumaki", "Unexpected charger-site ID")

    overlay_assets = persisted["scenario_overlay"]["depot_energy_assets"]["tsurumaki"]
    simulation_assets = persisted["simulation_config"]["depot_energy_assets"]
    _require(len(simulation_assets) == 1, "Expected exactly one simulation energy asset")
    simulation_asset = simulation_assets[0]
    _require(simulation_asset["depot_id"] == "tsurumaki", "Unexpected energy-asset depot")

    for field in ASSET_FIELDS:
        _require(field in overlay_assets, f"Missing overlay energy parameter: {field}")
        _require(field in simulation_asset, f"Missing simulation energy parameter: {field}")
        _require(
            overlay_assets[field] == simulation_asset[field],
            f"Overlay/simulation mismatch for {field}",
        )

    return {
        "grid_import_limit_kw": charger_site["grid_import_limit_kw"],
        **{field: overlay_assets[field] for field in ASSET_FIELDS},
    }


def _capture_one(
    code: str,
    run_dir: Path,
    output_dir: Path,
    published_summary: Mapping[str, Any],
) -> dict[str, Any]:
    source_snapshot = run_dir / "scenario_input_snapshot.json"
    source_manifest = run_dir / "run_input_manifest.json"
    _require(source_snapshot.is_file(), f"{code}: missing {source_snapshot}")
    _require(source_manifest.is_file(), f"{code}: missing {source_manifest}")

    snapshot = _read_json(source_snapshot)
    manifest = _read_json(source_manifest)
    summary = published_summary["scenarios"][code]
    snapshot_hash = _sha256(source_snapshot)

    _require(snapshot["scenario_id"] == SCENARIO_IDS[code], f"{code}: snapshot scenario ID")
    _require(manifest["scenario_id"] == SCENARIO_IDS[code], f"{code}: manifest scenario ID")
    _require(manifest["prepared_input_id"] == summary["prepared_input_id"], f"{code}: Prepared ID")
    _require(
        manifest["prepared_source_sha256"] == summary["prepared_input_sha256"],
        f"{code}: Prepared source SHA",
    )
    _require(manifest["git_sha"] == EXECUTION_SHA, f"{code}: execution SHA")
    _require(manifest["git_dirty"] is False, f"{code}: dirty execution")
    _require(
        manifest["artifacts"]["scenario_input_snapshot.json"]["sha256"] == snapshot_hash,
        f"{code}: snapshot hash not sealed by run manifest",
    )
    _require(
        manifest["artifacts"]["scenario_input_snapshot.json"]["size_bytes"]
        == source_snapshot.stat().st_size,
        f"{code}: snapshot size not sealed by run manifest",
    )

    target_root = output_dir / code
    target_root.mkdir(parents=True, exist_ok=True)
    target_snapshot = target_root / "scenario_input_snapshot.json"
    target_manifest = target_root / "run_input_manifest.json"
    target_snapshot.write_bytes(source_snapshot.read_bytes())
    target_manifest.write_bytes(source_manifest.read_bytes())
    _require(_sha256(target_snapshot) == snapshot_hash, f"{code}: copied snapshot differs")
    _require(_sha256(target_manifest) == _sha256(source_manifest), f"{code}: copied manifest differs")

    return {
        "scenario_id": snapshot["scenario_id"],
        "published_run_directory": summary["run_directory"],
        "prepared_input_id": manifest["prepared_input_id"],
        "prepared_source_sha256": manifest["prepared_source_sha256"],
        "scenario_input_snapshot_sha256": snapshot_hash,
        "scenario_input_snapshot_size_bytes": source_snapshot.stat().st_size,
        "run_input_manifest_sha256": _sha256(source_manifest),
        "parameters": extract_parameter_values(snapshot),
    }


def capture_parameter_sources(
    evidence_dir: Path,
    sunny_run_dir: Path,
    rain_run_dir: Path,
    output_dir: Path,
) -> Path:
    """Validate and capture the two exact run-input parameter sources."""

    published_summary = _read_json(evidence_dir.resolve() / "result_summary.json")
    target = output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "SUNNY": _capture_one("SUNNY", sunny_run_dir.resolve(), target, published_summary),
        "RAIN": _capture_one("RAIN", rain_run_dir.resolve(), target, published_summary),
    }
    _require(
        scenarios["SUNNY"]["parameters"] == scenarios["RAIN"]["parameters"],
        "SUNNY/RAIN fixed energy-asset parameters differ",
    )

    manifest_path = target / "parameter_source_manifest.json"
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_EXACT_PARAMETER_SOURCE_CAPTURE",
        "execution_git_sha": published_summary["execution_git_sha"],
        "source_semantics": (
            "Exact byte copies of scenario_input_snapshot.json and "
            "run_input_manifest.json from the two published fresh runs"
        ),
        "scenarios": scenarios,
        "shared_parameters": scenarios["SUNNY"]["parameters"],
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    hash_path = target / "artifact_hashes.json"
    hash_path.write_text(
        json.dumps(
            {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(target)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--sunny-run-dir", type=Path, required=True)
    parser.add_argument("--rain-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = capture_parameter_sources(
        args.evidence_dir,
        args.sunny_run_dir,
        args.rain_run_dir,
        args.output_dir,
    )
    print(manifest_path)
    print("PASS_EXACT_PARAMETER_SOURCE_CAPTURE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
