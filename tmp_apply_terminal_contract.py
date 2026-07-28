from pathlib import Path

path = Path("src/optimization/milp/solver_adapter.py")
src = path.read_text(encoding="utf-8")

# Stage 1 / day-ahead path (deeper indent, uses model.addConstr + hard_target_kwh)
stage1_old = (
    "                            if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:\n"
    "                                tolerance_kwh = self._safe_nonnegative_float(\n"
    "                                    problem.metadata.get(\n"
    "                                        \"bev_terminal_soc_equality_tolerance_kwh\"\n"
    "                                    ),\n"
    "                                    default=1.0e-6,\n"
    "                                )\n"
    "                                model.addConstr(\n"
    "                                    _slot_end_soc_expr(target_slot_idx, day_idx)\n"
    "                                    <= hard_target_kwh\n"
    "                                    + tolerance_kwh\n"
    "                                    + cap * (1 - day_use_var)\n"
    "                                )\n"
)
stage1_new = (
    "                            if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:\n"
    "                                terminal_contract = bev_terminal_numeric_acceptance_contract(\n"
    "                                    problem.metadata,\n"
    "                                    gurobi_feasibility_tol=getattr(\n"
    "                                        model, \"_mc_stage_feasibility_tol_kwh\", None\n"
    "                                    ),\n"
    "                                )\n"
    "                                tolerance_kwh = float(\n"
    "                                    terminal_contract[\"numeric_comparison_margin_kwh\"]\n"
    "                                )\n"
    "                                model.addConstr(\n"
    "                                    _slot_end_soc_expr(target_slot_idx, day_idx)\n"
    "                                    <= hard_target_kwh\n"
    "                                    + tolerance_kwh\n"
    "                                    + cap * (1 - day_use_var)\n"
    "                                )\n"
)
count1 = src.count(stage1_old)
print("stage1 occurrences:", count1)
if count1 != 1:
    raise SystemExit(f"stage1 expected 1 occurrence, got {count1}")
src = src.replace(stage1_old, stage1_new)

# Stage 2 / fixed charging path (uses stage2.addConstr + terminal_soc_expr)
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
count2 = src.count(stage2_old)
print("stage2 occurrences:", count2)
if count2 != 1:
    raise SystemExit(f"stage2 expected 1 occurrence, got {count2}")
src = src.replace(stage2_old, stage2_new)

path.write_text(src, encoding="utf-8")
print("done")