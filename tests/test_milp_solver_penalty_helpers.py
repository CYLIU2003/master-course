from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def test_soft_charge_concurrency_limit_respects_ratio_and_bounds() -> None:
    adapter = GurobiMILPAdapter()
    assert adapter._soft_charge_concurrency_limit(10.0, 0.7) == 7
    assert adapter._soft_charge_concurrency_limit(1.0, 0.0) == 1
    assert adapter._soft_charge_concurrency_limit(4.0, 2.0) == 4


def test_early_charge_weight_decreases_toward_horizon_end() -> None:
    adapter = GurobiMILPAdapter()
    slots = [0, 1, 2, 3]
    assert adapter._early_charge_weight(0, slots) > adapter._early_charge_weight(1, slots)
    assert adapter._early_charge_weight(1, slots) > adapter._early_charge_weight(2, slots)
    assert adapter._early_charge_weight(3, slots) == 0.0
