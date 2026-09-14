"""Bounded search diagnostics on the unchanged, persisted November Stage 2."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import sys

BASE = Path("C:/master-course/output/monthly_fair_weeks_20260914")
FROZEN = Path("C:/master-course-worktrees/shibu21-23-monthly-budget-20260914")
INPUT = BASE / "november_budget_diagnosis_20260915"
OUT = BASE / "november_search_diagnosis_20260915"
EXPECTED_SHA = "fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8"
MPS_SHA = "117211e8cb4811426ba15b1e1b6431cfff6dee6bb6c7b8d5e8f65af7013b0eaf"
PICKLE_SHA = "7b94496ee4738ed64178adcdd694a075401a5e8d6c2788b255bfdb667e9d7dbf"
sys.path.insert(0, str(FROZEN))
sys.path.insert(1, str(BASE))
import gurobipy as gp
from november_budget_diagnosis_20260915 import snapshot, clean_json, source_state
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import validate_physical_event_schedule
from src.optimization.common.result import ResultSerializer
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def save(name, value):
    (OUT / name).write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lp_diagnostic():
    with gp.read(str(INPUT / "full_stage2_120s.mps")) as original:
        binary_names = {v.VarName for v in original.getVars() if v.VType == gp.GRB.BINARY}
        with original.relax() as model:
            model.read(str(INPUT / "full_stage2_120s.prm"))
            model.Params.TimeLimit = 120
            model.Params.Method = 1
            model.Params.OutputFlag = 1
            model.Params.LogToConsole = 0
            model.Params.LogFile = str(OUT / "lp_relaxation.log")
            model.optimize()
            result = snapshot(model)
            result["interpretation"] = "RELAXATION_ONLY_NOT_A_BUS_OPERATING_PLAN"
            if model.SolCount:
                fractional = [v for v in model.getVars() if v.VarName in binary_names and abs(v.X - round(v.X)) > 1e-9]
                result["fractional_original_binaries"] = len(fractional)
                result["fractional_families"] = dict(Counter(v.VarName.split("[")[0] for v in fractional))
                result["fractional_examples"] = [{"name": v.VarName, "value": v.X} for v in fractional[:20]]
            if model.Status == gp.GRB.INFEASIBLE:
                model.computeIIS()
                model.write(str(OUT / "lp_infeasible.ilp"))
            save("lp_relaxation.json", result)
            return result


def mip_diagnostic(name, controls, captured):
    problem, config, plan, kwargs = captured
    metadata = {key: value for key, value in problem.metadata.items()
                if key not in {"_stage2_feedback_global_deadline_monotonic", "_stage2_feedback_global_started_monotonic"}}
    metadata["phase3_diagnostics_dir"] = str(OUT / (name + "_failure"))
    problem = replace(problem, metadata=metadata)
    config = replace(config, stage2_time_limit_sec=120)
    original_optimize = gp.Model.optimize
    native = {}

    def optimize(model, *args, **kwargs):
        if model.ModelName != "thesis_stage2_charging_dispatch":
            return original_optimize(model, *args, **kwargs)
        assert not args and not kwargs, "Unexpected production callback"
        assert not native, "Unexpected multiple main Stage 2 models"
        for key, value in controls.items():
            model.setParam(key, value)
        model.Params.OutputFlag = 1
        model.Params.LogToConsole = 0
        model.Params.LogFile = str(OUT / (name + ".log"))
        model.update()
        path = OUT / (name + ".mps")
        model.write(str(path))
        assert digest(path) == MPS_SHA, "Diagnostic changed model coefficients/constraints"
        first = []
        def callback(m, where):
            if where == gp.GRB.Callback.MIPSOL and not first:
                first.append(float(m.cbGet(gp.GRB.Callback.RUNTIME)))
        original_optimize(model, callback)
        native.update(snapshot(model), mip_focus=int(model.Params.MIPFocus), method=int(model.Params.Method),
                      first_incumbent_seconds=first[0] if first else None, mps_sha256=digest(path))
        if model.SolCount:
            model.write(str(OUT / (name + ".sol")))
        save(name + "_native.json", native)

    gp.Model.optimize = optimize
    try:
        outcome, result_plan = GurobiMILPAdapter()._solve_thesis_stage2_charging_dispatch(problem, config, plan, **kwargs)
    finally:
        gp.Model.optimize = original_optimize
    serialized = ResultSerializer.serialize_plan(result_plan)
    save(name + "_plan.json", serialized)
    physical = None
    errors = []
    if outcome.has_feasible_incumbent:
        validation = FeasibilityChecker().evaluate(problem, result_plan)
        errors = list(validation.errors)
        physical = validate_physical_event_schedule(problem=problem, serialized_result=serialized)
        save(name + "_physical.json", physical)
    result = {"controls": controls, "native": native, "has_feasible_incumbent": outcome.has_feasible_incumbent,
              "independent_errors": errors, "physical_accepted": physical["accepted"] if physical else None,
              "physical_validation_status": "EXECUTED" if physical else "NOT_RUN_NO_INCUMBENT"}
    save(name + "_summary.json", result)
    print(json.dumps({"case": name, "incumbent": outcome.has_feasible_incumbent,
                      "physical_accepted": result["physical_accepted"]}), flush=True)
    return result


def queue_completion():
    receipt = OUT / "dispatch.json"
    if receipt.exists():
        return
    save("dispatch.json", {"status": "ATTEMPTING", "at_utc": datetime.now(timezone.utc).isoformat()})
    message = ("11月の探索設定診断が終了しました。月別比較の完了ではなくメールは送らないでください。"
               "C:/master-course/output/monthly_fair_weeks_20260914/november_search_diagnosis_20260915/summary.json"
               "またはfailure.jsonと各native logを確認してください。前の同一配車・同一MPSの120/600秒は双方no-incumbentで、"
               "物理検証は未実施でした。今回はLP連続緩和とMIPFocus=1、MIPFocus=1+Method=1を各120秒で診断しています。"
               "MIP候補はモデルSHAと独立物理検証を確認します。結果を根拠に次の修正を進め、全月共通の新条件にする場合は"
               "新しいclean固定版から全12週を新規実行してください。旧10週と新条件を混ぜず、通常処理はスクリプトへ任せてください。")
    result = subprocess.run(["C:/Users/RTDS_admin/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe", "queue",
                             "--thread", "01a0899e-638e-7c91-864e-2d4890de634a", "--message", message],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0 or "Queued message " not in result.stdout:
        raise RuntimeError("Queue acceptance uncertain; inspect dispatch before retry")
    save("dispatch.json", {"status": "QUEUED", "receipt": result.stdout.strip()})


def main():
    OUT.mkdir(exist_ok=False)
    before = source_state()
    try:
        assert before == {"sha": EXPECTED_SHA, "dirty": ""}
        assert digest(INPUT / "full_stage2_120s.mps") == MPS_SHA
        assert digest(INPUT / "stage2_inputs.pkl") == PICKLE_SHA
        # Only our own hash-verified local capture is deserialized.
        with (INPUT / "stage2_inputs.pkl").open("rb") as stream:
            captured = pickle.load(stream)
        save("protocol.json", {"claim_scope": "DIAGNOSTIC_ONLY", "lp_budget": 120,
             "mip_cases": [{"name": "focus1", "MIPFocus": 1}, {"name": "focus1_dual", "MIPFocus": 1, "Method": 1}],
             "mip_budget_each": 120, "source_before": before, "mps_sha256": MPS_SHA, "pickle_sha256": PICKLE_SHA})
        lp = lp_diagnostic()
        cases = {name: mip_diagnostic(name, controls, captured) for name, controls in
                 [("focus1", {"MIPFocus": 1}), ("focus1_dual", {"MIPFocus": 1, "Method": 1})]}
        after = source_state()
        assert before == after
        save("summary.json", {"status": "DIAGNOSTICS_COMPLETED", "claim_scope": "NOT_A_WEEKLY_RESULT",
             "source_before": before, "source_after": after, "lp": lp, "cases": cases})
    except Exception as error:
        save("failure.json", {"error_type": type(error).__name__, "error": str(error), "source_after": source_state()})
        raise
    finally:
        queue_completion()


if __name__ == "__main__":
    main()
