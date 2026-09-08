"""Derive advisor-facing evidence from sealed executed results, without solving."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_thesis_weather_result_package import load_and_validate_bundle
from tools.thesis_authoring.build_authoring_evidence import (
    SCENARIOS, build_executed_power_series, load_json, require_close,
    require_equal, sha256_file, write_json,
)
from tools.thesis_authoring.build_progress_explanation import (
    charging_by_slot, dispatch_rows, dispatch_statistics,
)


def derive(target: Path) -> dict:
    """Validate frozen lineage and reconstruct only executed hourly prefixes."""
    bundle = load_and_validate_bundle(ROOT / "docs/evidence/weather_dispatch_rerun_bb0c005")
    target.mkdir(parents=True, exist_ok=True)
    sources: dict[str, str] = {}

    def bind(path: Path) -> None:
        sources[path.relative_to(ROOT).as_posix()] = sha256_file(path)

    for rel in bundle.source_hashes:
        bind(bundle.root / rel)
    for rel in bundle.parameter_source_hashes:
        bind(bundle.parameter_source_root / rel)
    result = {"execution_sha": "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d",
              "solver_runs": 0, "scenarios": {}}
    for name, expected in SCENARIOS.items():
        run = ROOT / expected["run_dir"]
        power = build_executed_power_series(ROOT, name, target)
        chain_path = run / "rolling_hourly_chain/rolling_chain_summary.json"
        chain = load_json(chain_path)
        require_equal(chain, dict(bundle.scenarios[name].rolling), "sealed chain")
        bind(chain_path)
        prepared_path = ROOT / "output/prepared_inputs" / expected["scenario_id"] / (expected["prepared_input_id"] + ".json")
        require_equal(sha256_file(prepared_path), expected["prepared_source_sha256"], "prepared hash")
        prepared = load_json(prepared_path)
        bind(prepared_path)
        canonical_path = run / "canonical_solver_result.json"
        require_equal(sha256_file(canonical_path), chain["day_ahead_result_sha256"], "canonical hash")
        canonical = load_json(canonical_path)
        bind(canonical_path)
        assignments = dispatch_rows(prepared, canonical["vehicle_paths"], name)
        raw_charges, soc = [], defaultdict(dict)
        for item in power["raw_hourly_solver_results"]:
            raw_path = ROOT / item["path"]
            bind(raw_path)
            raw = load_json(raw_path)
            start, stop = item["executed_start_slot"], item["executed_stop_slot_exclusive"]
            for charge in raw["charging_schedule"]:
                if start <= charge["slot_index"] < stop:
                    raw_charges.append({**charge, "energy_kwh": charge["charge_kw"] * .25})
            for vehicle, values in raw["vehicle_soc_kwh_by_vehicle_slot"].items():
                for slot, value in values.items():
                    if start <= int(slot) < stop:
                        soc[vehicle][int(slot)] = value
        charges = charging_by_slot(raw_charges, bundle.shared_parameters["charger_ids"])
        rows = [{**flow, **charge} for flow, charge in zip(power["rows"], charges)]
        for row in rows:
            require_close(row["charging_kw"] * .25, row["bev_charging_load_kwh"], "charging reconciliation")
        by_vehicle = defaultdict(lambda: [0.0] * 96)
        for charge in raw_charges:
            by_vehicle[charge["vehicle_id"]][charge["slot_index"]] += charge["charge_kw"]
        # Maximum received energy is a reproducible explanatory example, not an average bus.
        example_id = max(by_vehicle, key=lambda vehicle: (sum(by_vehicle[vehicle]), vehicle))
        vehicle = next(v for v in prepared["vehicles"] if v["id"] == example_id)
        require_equal(len(soc[example_id]), 96, "example SOC coverage")
        # BEV slots are START states, unlike BESS's END states. The 24:00 BEV
        # state is serialized separately as the last hourly terminal metadata.
        terminal_soc = raw["solver_metadata"]["vehicle_terminal_soc_kwh_by_vehicle"]
        example = {"vehicle_id": example_id, "selection_rule": "maximum executed charging energy",
                   "charging_kw": by_vehicle[example_id],
                   "soc_kwh": [soc[example_id][i] for i in range(96)] + [terminal_soc[example_id]],
                   "soc_semantics": "slot-start states 0..95 plus final metadata at 24:00",
                   "trips": [r for r in assignments if r["vehicle_id"] == example_id]}
        require_close(example["soc_kwh"][0], vehicle["batteryKwh"] * vehicle["initialSoc"], "example initial")
        require_close(example["soc_kwh"][-1], example["soc_kwh"][0], "example terminal")
        vehicle_by_id = {v["id"]: v for v in prepared["vehicles"]}
        exceedances = []
        for vehicle_id, values in soc.items():
            specification = vehicle_by_id[vehicle_id]
            cap, upper = specification["batteryKwh"], specification["maxSoc"]
            for slot, value in values.items():
                if value > cap * upper + 1e-6:
                    exceedances.append({"vehicle_id": vehicle_id, "slot_index": slot,
                        "soc_kwh": value, "soc_percent": value / cap * 100,
                        "prepared_upper_kwh": cap * upper, "excess_kwh": value-cap*upper})
        account_path = run / "rolling_hourly_chain/executed_day_accounting.json"
        account = load_json(account_path)
        require_equal(account, chain["executed_day_accounting"], "unique final ledger")
        bind(account_path)
        elapsed = [step["elapsed_seconds"] for step in chain["steps"]]
        result["scenarios"][name] = {"slots": rows, "example": example,
            "dispatch": dispatch_statistics(assignments), "accounting": account,
            "rolling_elapsed_seconds": elapsed, "rolling_elapsed_sum_seconds": sum(elapsed),
            "rolling_solver_seconds": [step["stage2_runtime_seconds"] for step in chain["steps"]],
            "prepared_soc_upper_audit": {"status": "FAIL" if exceedances else "PASS",
                "exceedance_count": len(exceedances), "affected_vehicle_count": len({r["vehicle_id"] for r in exceedances}),
                "maximum_soc_percent": max(value / vehicle_by_id[v]["batteryKwh"] * 100 for v, values in soc.items() for value in values.values()),
                "exceedances": exceedances},
            "bess_min_kwh": min([3000] + [r["bess_soc_end_kwh"] for r in rows]),
            "bess_max_kwh": max([3000] + [r["bess_soc_end_kwh"] for r in rows])}
    for relative in ["tools/thesis_authoring/build_urabe_review_data.py", "tools/thesis_authoring/build_authoring_evidence.py",
                     "tools/thesis_authoring/build_progress_explanation.py", "scripts/build_thesis_weather_result_package.py",
                     "先行文献/No06.pdf", "先行文献/No63.pdf",
                     "outcome/2026-09-06_speaker_notes/progress_differences_integrated_20260906.pptx"]:
        bind(ROOT / relative)
    result["source_sha256"] = sources
    result["research_use_status"] = "DIAGNOSTIC: NOT USED FOR RESEARCH CONCLUSIONS"
    result["blocking_reasons"] = ["PREPARED_MAX_SOC_NOT_ENFORCED_IN_FROZEN_STAGE2", "EXISTING_AUTHORING_SOURCE_HASH_MISMATCH", "INDEPENDENT_REVIEW_AND_RELEASE_APPROVAL_PENDING"]
    write_json(target / "review_data.json", result)
    return result


if __name__ == "__main__":
    data = derive(ROOT / "outcome/2026-09-07_urabe_progress_review/analysis")
    print(json.dumps({name: {key: value for key, value in scenario.items() if key in
        ("bess_min_kwh", "bess_max_kwh", "rolling_elapsed_sum_seconds", "dispatch")}
        for name, scenario in data["scenarios"].items()}, ensure_ascii=False, indent=2))
