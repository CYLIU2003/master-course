"""Summarize a completed native pair without solving or changing its evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(directory: Path) -> dict:
    state = read(directory / "state.json")
    if state.get("status") != "DIAGNOSTIC_COMPLETED":
        raise ValueError("Native comparison is not complete")
    if state.get("git_before") != state.get("git_after") or state["git_before"].get("dirty"):
        raise ValueError("Diagnostic code was not frozen")
    profiles = state.get("profiles", [])
    kind = state.get("comparison_kind", "charging_start")
    expected = {"charging_start": ["none", "fixed_assignment_binary"],
                "bound_focus": ["mip_focus_1", "mip_focus_3"]}.get(kind)
    if expected is None or [p["policy"] for p in profiles] != expected:
        raise ValueError("Expected the declared baseline and candidate")
    if kind == "bound_focus":
        preflight = read(directory / "preflight.json")
        if preflight.get("comparison_kind") != kind or preflight.get("comparison_policies") != expected:
            raise ValueError("Preflight comparison differs from terminal state")
        configs = preflight["declared_profile_configs"]
        baseline, candidate = configs[expected[0]], configs[expected[1]]
        if (baseline["stage2_gurobi_mip_focus"] != 1 or candidate["stage2_gurobi_mip_focus"] != 3
                or baseline["stage2_charging_start_policy"] != "none"
                or {**candidate, "stage2_gurobi_mip_focus": 1} != baseline):
            raise ValueError("Bound comparison changed another input control")
    hashes = {}
    models = []
    rows = []
    for profile in profiles:
        root = directory / profile["policy"]
        native = read(root / "native-models.json")
        if native != profile["native_models"] or not native:
            raise ValueError("Native evidence differs from terminal state")
        model_hashes = []
        for index, record in enumerate(native):
            path = root / f"model-{index}.mps"
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != record["mps_sha256"]:
                raise ValueError("Native model evidence changed")
            model_hashes.append(checksum)
        models.append(model_hashes)
        if kind == "bound_focus":
            expected_focus = 1 if profile["policy"] == "mip_focus_1" else 3
            for record in native:
                params = record["effective_parameters"]
                if params["MIPFocus"] != expected_focus:
                    raise ValueError("Native focus differs from declared profile")
            if rows:
                first_native = read(directory / expected[0] / "native-models.json")
                if [{**r["effective_parameters"], "MIPFocus": 1} for r in native] != [r["effective_parameters"] for r in first_native]:
                    raise ValueError("Native comparison changed another solver parameter")
        result = read(root / "result.json")
        if (result["feasible"], result["objective_value"]) != (profile["feasible"], profile["objective_value"]):
            raise ValueError("Result differs from comparison summary")
        rows.append({"policy": profile["policy"], "engine_feasible": profile["feasible"],
            "window_objective": profile["objective_value"], "call_wall_seconds": profile["wall_seconds"],
            "native_seconds": sum(r["Runtime"] for r in native),
            "shared_environment_cumulative_peak_gb": max(r["MaxMemUsed"] for r in native),
            "native_termination_status": [r["Status"] for r in native],
            "native_gap": [r["MIPGap"] for r in native],
            "native_objective": [r.get("ObjVal") for r in native],
            "native_bound": [r.get("ObjBound") for r in native],
            "effective_parameters": [r.get("effective_parameters") for r in native],
            "charging_start": result.get("solver_metadata", {}).get("stage2_charging_start")})
        for path in root.iterdir():
            if path.is_file():
                hashes[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if models[0] != models[1]:
        raise ValueError("Baseline and candidate native models differ")
    for name in ("state.json", "preflight.json"):
        hashes[name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    both_feasible = all(row["engine_feasible"] is True for row in rows)
    return {"scope": "same_native_model_saved_window_pair_not_weekly_execution",
        "comparison_kind": kind,
        "code": state["git_before"], "memory_budget_gib": state["memory_budget_gib"],
        "profiles": rows, "models_equal": True, "both_engine_feasible": both_feasible,
        "candidate_minus_baseline_window_objective": rows[1]["window_objective"] - rows[0]["window_objective"] if both_feasible else None,
        "candidate_minus_baseline_call_seconds": rows[1]["call_wall_seconds"] - rows[0]["call_wall_seconds"],
        "production_adoption": "NOT_AUTOMATIC_SINGLE_WINDOW_ONLY",
        "independent_weekly_physical_audit": "NOT_PERFORMED",
        "comparison_meaning": "Observed feasible candidate objectives, not proven optimal cost differences.",
        "warnings": ["Read each native termination status and gap separately; equal MPS does not prove optimality.",
            "engine_feasible=false means feasibility not established here, not a proof of mathematical infeasibility.",
            "MaxMemUsed is cumulative for the shared environment; do not infer per-policy memory savings."],
        "artifact_sha256": hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.directory)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: report[k] for k in ("models_equal", "both_engine_feasible",
        "candidate_minus_baseline_window_objective", "candidate_minus_baseline_call_seconds")}))


if __name__ == "__main__":
    main()
