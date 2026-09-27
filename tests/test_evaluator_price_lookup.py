"""Tariff lookup acceleration must preserve legacy prices and tie breaking."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import EnergyPriceSlot


def legacy_price(slots, index, field):
    value = {slot.slot_index: getattr(slot, field) for slot in slots}.get(index)
    if value is None and slots:
        value = getattr(min(slots, key=lambda slot: abs(slot.slot_index - index)), field)
    return value or 0.0


@pytest.mark.parametrize("slots", [
    (),
    (EnergyPriceSlot(2, 0, -3), EnergyPriceSlot(0, 40, 4)),
    (EnergyPriceSlot(1, 10, 3), EnergyPriceSlot(1, 20, 5), EnergyPriceSlot(3, 30, 6)),
])
def test_lookup_preserves_exact_nearest_duplicate_and_zero_prices(slots):
    evaluator = CostEvaluator()
    problem = SimpleNamespace(price_slots=slots)
    for _ in range(2):
        for index in range(-1, 6):
            assert evaluator._slot_buy_price(problem, index) == legacy_price(slots, index, "grid_buy_yen_per_kwh")
            assert evaluator._slot_sell_price(problem, index) == legacy_price(slots, index, "grid_sell_yen_per_kwh")


def test_replacement_tariff_on_same_problem_does_not_reuse_old_price():
    evaluator = CostEvaluator()
    problem = SimpleNamespace(price_slots=(EnergyPriceSlot(0, 10, 2),))
    assert evaluator._slot_buy_price(problem, 0) == 10
    problem.price_slots = (replace(problem.price_slots[0], grid_buy_yen_per_kwh=45),)
    assert evaluator._slot_buy_price(problem, 0) == 45


@pytest.mark.parametrize("as_tuple", [False, True])
def test_mutable_price_records_are_not_cached(as_tuple):
    slot = SimpleNamespace(slot_index=0, grid_buy_yen_per_kwh=10, grid_sell_yen_per_kwh=2)
    problem = SimpleNamespace(price_slots=(slot,) if as_tuple else [slot])
    evaluator = CostEvaluator()
    assert evaluator._slot_buy_price(problem, 0) == 10
    slot.grid_buy_yen_per_kwh = 99
    assert evaluator._slot_buy_price(problem, 0) == 99


def test_list_of_frozen_records_can_be_replaced_in_place():
    problem = SimpleNamespace(price_slots=[EnergyPriceSlot(0, 10, 2)])
    evaluator = CostEvaluator()
    assert evaluator._slot_buy_price(problem, 0) == 10
    problem.price_slots[0] = EnergyPriceSlot(0, 50, 3)
    assert evaluator._slot_buy_price(problem, 0) == 50


def test_shared_evaluator_does_not_mix_tariffs_between_threads():
    evaluator = CostEvaluator()
    def evaluate(value):
        problem = SimpleNamespace(price_slots=(EnergyPriceSlot(0, value, -value),))
        for _ in range(50):
            assert evaluator._slot_buy_price(problem, 0) == value
            assert evaluator._slot_sell_price(problem, 0) == -value
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(evaluate, range(1, 41)))
