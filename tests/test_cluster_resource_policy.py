"""Performance-aware placement preserves fixed solver controls and reservations."""
from bff.services.cluster.contracts import Worker
from bff.services.cluster.resource_policy import resource_fit, rank_workers
from bff.routers.cluster import SubmitBody
from pydantic import ValidationError
import pytest


def fit(worker_id="a", *, capacity=None, requirement=None, jobs=None, **worker_options):
    worker = Worker(id=worker_id, name=worker_id, **worker_options)
    metrics = {"ram_gb": 16, "ram_free_gb": 12, "disk_free_gb": 50, "cpu_count": 8, "cpu_percent": 10, "ac_power": True}
    metrics.update(capacity or {})
    manifest = {"kind": "optimization", "minimum_ram_gb": 4, "resource_requirements": {"cpu_threads": 4}, **(requirement or {})}
    return worker, resource_fit(worker, metrics, manifest, jobs or [])


def test_fixed_threads_exclude_small_cpu_instead_of_lowering_threads():
    _, result = fit(capacity={"cpu_count": 2})
    assert not result["eligible"] and result["required_cpu_threads"] == 4
    assert "INSUFFICIENT_OR_UNKNOWN_CPU_THREADS" in result["reasons"]


def test_ram_pressure_and_battery_policy_exclude_worker():
    assert not fit(capacity={"ram_free_gb": 2})[1]["eligible"]
    assert not fit(capacity={"ac_power": None}, require_ac_power=True)[1]["eligible"]
    assert not fit(capacity={"cpu_percent": 95})[1]["eligible"]


def test_unknown_or_nonfinite_resources_do_not_become_capacity():
    assert not fit(capacity={"ram_free_gb": float("nan")})[1]["eligible"]
    assert not fit(capacity={"cpu_count": None})[1]["eligible"]


def test_current_headroom_beats_registration_order_without_speed_claim():
    ranked = rank_workers([fit("a", capacity={"ram_free_gb": 5}), fit("b")])
    assert ranked[0][0].id == "b"
    assert ranked[0][1]["ranking_basis"] == "current_load_and_memory_headroom"


def test_no_gurobi_jobs_preserve_solver_capacity_with_fallback():
    fast_solver = fit("solver", gurobi=True, capacity={"cpu_percent": 1, "ram_free_gb": 14})
    heuristic = fit("heuristic", gurobi=False, capacity={"cpu_percent": 30})
    ranked = rank_workers([fast_solver, heuristic], prefer_no_gurobi=True)
    assert [worker.id for worker, _ in ranked] == ["heuristic", "solver"]
    assert ranked[0][1]["ranking_basis"] == "no_gurobi_capacity_then_current_load_and_memory_headroom"
    assert [worker.id for worker, _ in rank_workers([fast_solver], prefer_no_gurobi=True)] == ["solver"]
    assert [worker.id for worker, _ in rank_workers([fast_solver, heuristic])] == ["solver", "heuristic"]


def test_matching_measured_history_beats_core_count():
    def history(worker_id, seconds, profile="legacy"):
        return {"worker_id": worker_id, "state": "COMPLETED", "manifest": {
            "kind": "optimization", "profile_id": profile, "resource_requirements": {"cpu_threads": 4}},
            "result": {"started_at": "2026-09-23T00:00:00+00:00", "finished_at": f"2026-09-23T00:00:{seconds:02d}+00:00"}}
    jobs = [history("a", 30), history("b", 10), history("b", 59, "different")]
    ranked = rank_workers([fit("a", jobs=jobs, capacity={"cpu_count": 32}), fit("b", jobs=jobs)])
    assert ranked[0][0].id == "b" and ranked[0][1]["median_worker_seconds"] == 10
    assert ranked[0][1]["matching_history_count"] == 1


def test_lost_job_retains_memory_and_slot():
    job = {"worker_id": "a", "state": "LOST", "manifest": {"minimum_ram_gb": 10}}
    assert not fit(jobs=[job])[1]["eligible"]


@pytest.mark.parametrize("minimum_ram_gb", [0, -1, float("nan"), float("inf")])
def test_cluster_submission_rejects_invalid_ram_floor(minimum_ram_gb):
    with pytest.raises(ValidationError):
        SubmitBody.model_validate({"scenario_id": "s", "minimum_ram_gb": minimum_ram_gb,
                                   "request": {"prepared_input_id": "p"}})


def test_older_frontend_submission_gets_safe_ram_floor():
    body = SubmitBody.model_validate({"scenario_id": "s", "request": {"prepared_input_id": "p"}})
    assert body.minimum_ram_gb == 16


def test_automatic_gurobi_threads_require_entire_cpu_and_unknown_cpu_is_rejected():
    requirement = {"requires_gurobi": True, "resource_requirements": {"cpu_threads": 0}}
    assert fit(requirement=requirement)[1]["required_cpu_threads"] == 8
    assert not fit(requirement=requirement, capacity={"cpu_count": None})[1]["eligible"]
    job = {"worker_id": "a", "state": "RUNNING", "manifest": {"resource_requirements": {"cpu_threads": 1}}}
    assert not fit(requirement=requirement, jobs=[job], slots=2)[1]["eligible"]


@pytest.mark.parametrize("installed,usable,allowed", [(16, 15.8, False), (24, 23.8, False), (32, 31.5, True), (64, 63.6, True), (None, 31.9, False), (float("nan"), 16, False)])
def test_gurobi_requires_installed_32gb_separately_from_free_ram(installed, usable, allowed):
    _, result = fit(capacity={"installed_ram_gb": installed, "ram_gb": usable}, requirement={"requires_gurobi": True})
    assert result["eligible"] is allowed
    assert ("GUROBI_REQUIRES_32GB_INSTALLED_RAM" in result["reasons"]) is not allowed


def test_32gb_does_not_override_free_ram_and_non_gurobi_can_use_16gb():
    assert not fit(capacity={"installed_ram_gb": 32, "ram_gb": 31.5, "ram_free_gb": 1}, requirement={"requires_gurobi": True})[1]["eligible"]
    assert fit(requirement={"requires_gurobi": False})[1]["eligible"]


@pytest.mark.parametrize('commit', [None, 0, 6.8, float('nan'), float('inf')])
def test_windows_free_ram_does_not_override_exhausted_or_unknown_commit(commit):
    _, result = fit(capacity={'platform': 'Windows-11', 'installed_ram_gb': 32,
                             'ram_gb': 31.7, 'ram_free_gb': 18.5, 'commit_available_gb': commit},
                    requirement={'minimum_ram_gb': 18, 'requires_gurobi': True})
    assert not result['eligible']
    assert 'INSUFFICIENT_OR_UNKNOWN_COMMIT_CAPACITY' in result['reasons']


def test_commit_reserves_other_attempts_and_system_headroom():
    job = {'worker_id': 'a', 'state': 'LOST', 'manifest': {'minimum_ram_gb': 4}}
    _, result = fit(capacity={'platform': 'Windows-11', 'commit_available_gb': 8.5},
                    jobs=[job], slots=2, reserved_system_ram_gb=1)
    assert 'INSUFFICIENT_OR_UNKNOWN_COMMIT_CAPACITY' in result['reasons']
    assert fit(capacity={'platform': 'Windows-11', 'commit_available_gb': 9},
               jobs=[job], slots=2, reserved_system_ram_gb=1)[1]['eligible']
