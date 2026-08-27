from __future__ import annotations

from scripts.run_weather_dispatch_diagnosis import (
    assignment_hash_from_rows,
    candidate_is_selectable,
    classify_weather_winners,
    deduplicate_candidates,
    select_canonical_candidate,
    validate_fixed_dispatch_evidence,
)
from bff.routers.optimization import (
    RunOptimizationBody,
    _apply_research_phase3_candidate_coverage_policy,
)
from src.optimization.milp.solver_adapter import (
    _EXACT_ICE_CLONE_REPRESENTATION_OVERRIDE,
    _phase3_candidate_selection_key,
)


def _assignment(vehicle_id: str, trip_id: str = "trip-1") -> list[dict[str, str]]:
    return [
        {
            "duty_id": f"duty-{vehicle_id}",
            "trip_id": trip_id,
            "vehicle_id": vehicle_id,
            "powertrain": "BEV" if vehicle_id.startswith("bev") else "ICE",
        }
    ]


def _candidate(
    assignment_hash: str,
    cost: float,
    *,
    used_vehicle_count: int = 2,
    proxy: float = 0.0,
    **overrides,
) -> dict:
    candidate = {
        "assignment_hash": assignment_hash,
        "canonical_actual_cost_jpy": cost,
        "used_vehicle_count": used_vehicle_count,
        "stage1_proxy_jpy": proxy,
        "stage2_feasible": True,
        "physical_validation_feasible": True,
        "accounting_reconciliation_passed": True,
        "fallback_used": False,
        "repair_used": False,
    }
    candidate.update(overrides)
    return candidate


def test_selects_minimum_stage2_canonical_cost() -> None:
    selected = select_canonical_candidate(
        [_candidate("expensive", 200.0), _candidate("cheap", 100.0)]
    )
    assert selected["assignment_hash"] == "cheap"


def test_stage1_proxy_order_can_reverse_without_changing_final_selection() -> None:
    selected = select_canonical_candidate(
        [
            _candidate("proxy-best", 200.0, proxy=1.0),
            _candidate("canonical-best", 100.0, proxy=999.0),
        ]
    )
    assert selected["assignment_hash"] == "canonical-best"


def test_classifies_different_weather_winners_as_case_a() -> None:
    verdict = classify_weather_winners(
        [_candidate("sunny-best", 100.0), _candidate("rain-best", 110.0)],
        [_candidate("sunny-best", 120.0), _candidate("rain-best", 90.0)],
        candidate_target=2,
        unique_candidate_count=2,
    )
    assert verdict["case"] == "A"
    assert not verdict["same_selected_assignment"]


def test_classifies_same_weather_winner_as_case_b() -> None:
    verdict = classify_weather_winners(
        [_candidate("same", 100.0), _candidate("other", 110.0)],
        [_candidate("same", 90.0), _candidate("other", 120.0)],
        candidate_target=2,
        unique_candidate_count=2,
    )
    assert verdict["case"] == "B"
    assert verdict["same_selected_assignment"]


def test_fixed_dispatch_evidence_rejects_assignment_change() -> None:
    evidence = validate_fixed_dispatch_evidence(
        requested_assignment_hash="requested",
        solved_assignment_hash="changed",
        sunny_recourse_hash="sun",
        rain_recourse_hash="rain",
    )
    assert evidence["dispatch_reoptimization_performed"] is False
    assert evidence["assignment_unchanged"] is False


def test_fixed_assignment_allows_weather_specific_energy_recourse() -> None:
    evidence = validate_fixed_dispatch_evidence(
        requested_assignment_hash="same",
        solved_assignment_hash="same",
        sunny_recourse_hash="sun",
        rain_recourse_hash="rain",
    )
    assert evidence["energy_recourse_optimization_performed"] is True
    assert evidence["scenario_recourse_can_differ"] is True


def test_assignment_hash_deduplication_uses_physical_assignment() -> None:
    rows = _assignment("bev-1")
    computed = assignment_hash_from_rows(rows)
    unique = deduplicate_candidates(
        [
            {"assignment_hash": "source-a", "candidate_hash": "a", "vehicle_trip_assignments": rows},
            {"assignment_hash": "source-b", "candidate_hash": "b", "vehicle_trip_assignments": list(reversed(rows))},
        ]
    )
    assert len(unique) == 1
    assert unique[0]["assignment_hash"] == computed
    assert len(unique[0]["provenance"]) == 2


def test_fallback_repair_and_accounting_mismatch_are_not_selectable() -> None:
    assert not candidate_is_selectable(_candidate("fallback", 1.0, fallback_used=True))
    assert not candidate_is_selectable(_candidate("repair", 1.0, repair_used=True))
    assert not candidate_is_selectable(
        _candidate("accounting", 1.0, accounting_reconciliation_passed=False)
    )
    assert not candidate_is_selectable(
        _candidate("missing-cost", 1.0, canonical_actual_cost_jpy=None)
    )


def test_tie_break_is_used_fleet_then_assignment_hash() -> None:
    selected = select_canonical_candidate(
        [
            _candidate("z", 100.0, used_vehicle_count=3),
            _candidate("b", 100.0, used_vehicle_count=2),
            _candidate("a", 100.0, used_vehicle_count=2),
        ]
    )
    assert selected["assignment_hash"] == "a"


def test_production_phase3_tie_break_key_is_cost_then_fleet_then_hash() -> None:
    candidate = (123.5, 7, "abc", 99, object(), object())
    assert _phase3_candidate_selection_key(candidate) == (123.5, 7, "abc")


def test_pure_ice_aggregate_diagnostic_override_remains_off_by_default() -> None:
    assert _EXACT_ICE_CLONE_REPRESENTATION_OVERRIDE.get() is None


def test_formal_phase3_enables_neutral_candidate_coverage_policy() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=True,
        stage1_stage2_candidate_limit=1,
        stage1_composition_search_radius=0,
        stage1_bev_frontier_enabled=False,
    )
    effective = _apply_research_phase3_candidate_coverage_policy(requested)
    assert effective.stage1_stage2_candidate_limit == 22
    assert effective.stage1_composition_search_radius == 4
    assert effective.stage1_bev_frontier_enabled is True
    assert requested.stage1_stage2_candidate_limit == 1


def test_nonresearch_phase3_keeps_requested_candidate_controls() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=False,
        stage1_stage2_candidate_limit=1,
        stage1_composition_search_radius=0,
        stage1_bev_frontier_enabled=False,
    )
    assert _apply_research_phase3_candidate_coverage_policy(requested) is requested
