from dataclasses import replace
import pytest

from tools.research.prepare_charging_replay import saved_window, capture_window, prepare


def inputs():
    audit = {"scenario_id": "s", "prepared_input_id": "p", "service_date": "2025-03-03", "service_id": "SAT"}
    summary = {**audit, "current_absolute_min": 720, "current_time": "12:00", "execution_minutes": 60,
        "time_limit_sec": 600, "mip_gap": .01, "random_seed": 42, "gurobi_threads": 4,
        "lookahead": 24, "bess_terminal_policy": "minimum_only"}
    return summary, {"current_min": 720}, audit


def test_saved_controls_preserved_and_diagnostic_only():
    summary, state, audit = inputs()
    request = saved_window(summary, state, audit)
    assert request.time_limit_sec == 600
    assert request.gurobi_threads == 4
    assert request.service_id == "SAT"
    assert request.bess_terminal_policy == "minimum_only"
    assert request.research_run is False
    assert request.full_chain is False
    assert request.stage2_charging_start_policy == "none"


def test_saved_search_and_native_evidence_must_agree():
    summary, state, audit = inputs()
    summary.update(charging_search_requested="bound_first", stage2_gurobi_mip_focus_effective=3)
    assert saved_window(summary, state, audit).charging_search == "bound_first"
    for wrong in (None, 1, 2):
        with pytest.raises(ValueError, match="effective native focus"):
            saved_window({**summary, "stage2_gurobi_mip_focus_effective": wrong}, state, audit)


@pytest.mark.parametrize("change", [
    {"scenario_id": "other"}, {"prepared_input_id": "other"}, {"service_date": "2025-03-04"},
    {"current_absolute_min": 780}, {"pv_forecast_update": {}}, {"bess_terminal_min_kwh_override": 1200},
])
def test_mismatched_or_unsupported_input_is_not_silently_changed(change):
    summary, state, audit = inputs()
    with pytest.raises(ValueError):
        saved_window({**summary, **change}, state, audit)


def test_state_fields_reach_production_reoptimizer_without_reset(monkeypatch):
    from src.optimization.rolling.reoptimizer import RollingReoptimizer
    summary, state, audit = inputs()
    state.update(actual_vehicle_soc_kwh={"v": 35}, actual_bess_soc_kwh={"d": 12},
        actual_vehicle_fuel_l={"i": 8}, actual_vehicle_positions={"v": {"location_id": "d"}},
        connected_charger_by_vehicle={"v": "c"}, observed_on_peak_kw_by_depot={"d": 27},
        observed_off_peak_kw_by_depot={"d": 23}, active_charge_session_vehicle_ids=["v"])
    calls = []
    def capture(self, problem, plan, config, current, **kwargs):
        calls.append((problem, plan, config, current, kwargs))
        return problem, config
    monkeypatch.setattr(RollingReoptimizer, "reoptimize_charging_hour", capture)
    problem, plan = object(), object()
    request = saved_window(summary, state, audit)
    _, a = capture_window(problem, plan, request, state)
    _, b = capture_window(problem, plan, replace(request, stage2_charging_start_policy="fixed_assignment_binary"), state)
    assert replace(b, stage2_charging_start_policy="none") == a
    assert calls[0][3] == 720
    kwargs = calls[0][4]
    assert kwargs["actual_soc"] == {"v": 35}
    assert kwargs["actual_bess_soc_kwh"] == {"d": 12}
    assert kwargs["actual_vehicle_fuel_l"] == {"i": 8}
    assert kwargs["connected_charger_by_vehicle"] == {"v": "c"}
    assert kwargs["observed_on_peak_kw_by_depot"] == {"d": 27}
    assert kwargs["observed_off_peak_kw_by_depot"] == {"d": 23}
    assert kwargs["active_charge_session_vehicle_ids"] == ("v",)
    assert kwargs == calls[1][4]


@pytest.mark.parametrize("key,value", [
    ("time_limit_sec", 0), ("time_limit_sec", 1.5), ("gurobi_threads", True),
    ("random_seed", None), ("mip_gap", float("nan")), ("mip_gap", True), ("mip_gap", 2),
])
def test_invalid_controls_are_rejected_instead_of_coerced(key, value):
    summary, state, audit = inputs()
    with pytest.raises(ValueError, match="saved control"):
        saved_window({**summary, key: value}, state, audit)


def test_archive_hash_is_checked_before_any_reconstruction(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare(archive, "0" * 64, 12)


@pytest.mark.parametrize("step", [0, -1, True, 1.5])
def test_replay_requires_a_preceding_explicit_state(tmp_path, step):
    with pytest.raises(ValueError, match="preceding state"):
        prepare(tmp_path / "missing.zip", "0" * 64, step)
