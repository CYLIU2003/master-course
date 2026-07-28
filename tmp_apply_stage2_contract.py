from pathlib import Path

path = Path("src/optimization/milp/solver_adapter.py")
src = path.read_text(encoding="utf-8")

stage2_old = (
    "                if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:\n"
    "                    tolerance_kwh = self._safe_nonnegative_float(\n"
    "                        problem.metadata.get(\n"
    "                            \"bev_terminal_soc_equality_tolerance_kwh\"\n"
    "                        ),\n"
    "                        default=1.0e-6,\n"
    "                    )\n"
    "                    stage2.addConstr(\n"
    "                        terminal_soc_expr <= target_kwh + tolerance_kwh,\n"
    "                        name=f\"terminal_soc__{vehicle_id}__return_to_initial_upper\",\n"
    "                    )\n"
)
stage2_new = (
    "                if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:\n"
    "                    terminal_contract = bev_terminal_numeric_acceptance_contract(\n"
    "                        problem.metadata,\n"
    "                        gurobi_feasibility_tol=stage2_feasibility_tol,\n"
    "                    )\n"
    "                    tolerance_kwh = float(\n"
    "                        terminal_contract[\"numeric_comparison_margin_kwh\"]\n"
    "                    )\n"
    "                    stage2.addConstr(\n"
    "                        terminal_soc_expr <= target_kwh + tolerance_kwh,\n"
    "                        name=f\"terminal_soc__{vehicle_id}__return_to_initial_upper\",\n"
    "                    )\n"
)
count = src.count(stage2_old)
print("stage2 occurrences:", count)
if count != 1:
    raise SystemExit(f"stage2 expected 1 occurrence, got {count}")
src = src.replace(stage2_old, stage2_new)
path.write_text(src, encoding="utf-8")
print("done")