"""Observer release gates: no premature completion, duplicate queue, or solver call."""
from copy import deepcopy
import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import watch_monthly_campaign as watcher


@pytest.fixture
def setup(tmp_path):
    weeks = [f"2025-{month:02}-01" for month in range(1, 13)]
    config = {"root": str(tmp_path), "output": str(tmp_path / "observer"),
              "campaign": str(tmp_path / "campaign"), "audit": str(tmp_path / "audit.json"),
              "report_stem": str(tmp_path / "report"), "source_git_sha": "frozen-sha",
              "selected_weeks": weeks, "helper_hashes": {}, "codex": "codex.exe",
              "thread_id": "existing-thread", "solver_pid": 123, "solver_started_at_utc": "timestamp",
              "audit_script": "audit.py", "report_script": "report.py", "checkpoint_script": "checkpoint.py"}
    config["output"] = str(tmp_path / "observer")
    Path(config["output"]).mkdir()
    progress = {"status": "RUNNING_WEEK", "base_git_sha": "frozen-sha", "selected_weeks": weeks,
                "completed_weeks": weeks[:3], "active_week": weeks[3]}
    watcher.write_json(Path(config["campaign"]) / "progress.json", progress)
    audit = {"expected_sha": "frozen-sha", "status": "RUNNING_CAMPAIGN", "weeks": {
        week: {"fully_audited": True, "status": "DIAGNOSTIC_EXECUTION_PASSED",
               "audit_status": "INDEPENDENTLY_AUDITED"} for week in weeks[:3]}}
    watcher.write_json(Path(config["audit"]), audit)
    watcher.write_json(tmp_path / "report.json", {"status": "IN_PROGRESS", "independent_audit": {
        "sha256": watcher.sha256(Path(config["audit"]))}})
    observer = watcher.Observer(config)
    observer.checkpoint("RUNNING", published_audit_sha256=watcher.sha256(observer.audit))
    return observer, progress


@pytest.mark.parametrize("mutation", ["wrong_sha", "duplicates", "wrong_selection", "early_complete", "failure"])
def test_rejects_invalid_or_failed_execution(setup, mutation):
    observer, progress = setup
    changed = deepcopy(progress)
    if mutation == "wrong_sha":
        changed["base_git_sha"] = "old-sha"
    elif mutation == "duplicates":
        changed["completed_weeks"] = [progress["selected_weeks"][0]] * 3
    elif mutation == "wrong_selection":
        changed["selected_weeks"] = list(reversed(changed["selected_weeks"]))
    elif mutation == "early_complete":
        changed["status"] = "COMPLETED"
    else:
        changed["status"] = "STOPPED_AFTER_FAILED_CASE"
    with pytest.raises(ValueError):
        watcher.validate_progress(changed, observer.config)


def test_no_model_or_report_calls_for_unchanged_running_case(setup, monkeypatch):
    observer, _ = setup
    monkeypatch.setattr(watcher, "solver_is_alive", lambda *_: True)
    monkeypatch.setattr(watcher.subprocess, "run", lambda *_args, **_kw: pytest.fail("Unexpected command"))
    assert observer.step() is False
    assert watcher.read_json(observer.output / "state.json")["status"] == "RUNNING"


@pytest.mark.parametrize('status', ['BUILDING_SOURCE_CANDIDATE', 'PREPARING_WEEK', 'RUNNING_WEEK'])
def test_first_week_runs_without_inventing_a_completed_report(setup, monkeypatch, status):
    observer, progress = setup
    progress['status'] = status
    progress["completed_weeks"] = []
    watcher.write_json(observer.campaign / "progress.json", progress)
    watcher.write_json(observer.audit, {"expected_sha": "frozen-sha", "weeks": {}})
    observer.report.with_suffix(".json").unlink()
    monkeypatch.setattr(watcher, "solver_is_alive", lambda *_: True)
    monkeypatch.setattr(watcher.subprocess, "run", lambda *_args, **_kw: pytest.fail("Unexpected command"))
    assert observer.step() is False
    assert not observer.report.with_suffix(".json").exists()
    assert watcher.read_json(observer.output / "state.json")["independently_audited_weeks"] == 0


def test_source_construction_rejects_completed_weeks(setup):
    observer, progress = setup
    progress['status'] = 'BUILDING_SOURCE_CANDIDATE'
    with pytest.raises(ValueError, match='Source construction'):
        watcher.validate_progress(progress, observer.config)


def test_release_deployments_have_separate_binding_and_artifacts():
    old = watcher.deployment_paths({})
    new = watcher.deployment_paths({"deployment": "search"})
    assert all(left != right for left, right in zip(old, new))


def test_daily_timeline_release_has_separate_artifacts_from_failed_session_run():
    old = watcher.deployment_paths({"deployment": "auxiliary_session"})
    new = watcher.deployment_paths({"deployment": "auxiliary_timeline"})
    assert all(left != right for left, right in zip(old, new))
    assert new[0] == Path("output/monthly_auxiliary_timeline_20260922")


def test_numeric_release_keeps_failed_timeline_artifacts_separate():
    old = watcher.deployment_paths({"deployment": "auxiliary_timeline"})
    new = watcher.deployment_paths({"deployment": "auxiliary_numeric"})
    assert all(a != b for a, b in zip(old, new))
    assert new[0] == Path("output/monthly_auxiliary_numeric_20260922")


def test_hourly_budget_release_has_separate_paths_from_failed_numeric_gate():
    old = watcher.deployment_paths({"deployment": "auxiliary_numeric"})
    new = watcher.deployment_paths({"deployment": "auxiliary_budget"})
    assert all(a != b for a, b in zip(old, new))
    assert new[0] == Path("output/monthly_auxiliary_budget_20260922")


def test_quality_release_has_separate_paths_from_failed_budget_gate():
    old = watcher.deployment_paths({"deployment": "auxiliary_budget"})
    new = watcher.deployment_paths({"deployment": "auxiliary_quality"})
    assert all(a != b for a, b in zip(old, new))
    assert new[0] == Path("output/monthly_auxiliary_quality_20260922")


def test_cyclic_deployment_does_not_reuse_any_old_delivery_paths():
    cyclic = watcher.deployment_paths({"deployment": "cyclic"})
    for version in ("budget", "search", "phase_search"):
        previous = watcher.deployment_paths({"deployment": version})
        assert all(left != right for left, right in zip(cyclic, previous))
    with pytest.raises(ValueError, match="Unknown"):
        watcher.deployment_paths({"deployment": "arbitrary-output"})


def test_reserve_deployment_has_separate_paths_and_preserves_failed_status(setup, monkeypatch):
    reserve = watcher.deployment_paths({"deployment": "reserve"})
    for version in ("budget", "search", "phase_search", "cyclic"):
        assert all(a != b for a, b in zip(reserve, watcher.deployment_paths({"deployment": version})))
    observer, progress = setup
    observer.config["deployment"] = "reserve"
    progress["status"] = "STOPPED_AFTER_FAILED_CASE"
    failed_week = progress["selected_weeks"][3]
    progress["completed_weeks"].append(failed_week)
    watcher.write_json(observer.campaign / "progress.json", progress)
    watcher.write_json(observer.campaign / "cases" / failed_week / "diagnostic" / failed_week / "summary.json",
                       {"status": "HOURLY_SOLVE_FAILED", "hourly_steps_accepted": 158})
    calls = []
    monkeypatch.setattr(observer, "publish", lambda *, complete: calls.append(complete))
    monkeypatch.setattr(observer, "prepare_delivery", lambda: pytest.fail("No incomplete email"))
    with pytest.raises(ValueError, match="partial status recorded"):
        observer.step()
    audit = watcher.read_json(observer.audit)
    assert audit["status"] == "STOPPED_AFTER_FAILED_CASE"
    assert audit["weeks"][failed_week]["fully_audited"] is False
    assert calls == [False]
    assert watcher.read_json(observer.output / "stopped_campaign.json")["independently_audited_weeks"] == 3


@pytest.mark.parametrize("deployment", ["cyclic", "reserve"])
def test_new_reports_always_use_their_own_figure_name(setup, monkeypatch, deployment):
    observer, _ = setup
    observer.config["deployment"] = deployment
    _, _, figure = watcher.deployment_paths(observer.config)
    observer.config["figure_stem"] = str(observer.root / figure)
    calls = []
    monkeypatch.setattr(observer, "run_python", lambda *args: calls.append(args))
    observer.publish(complete=True)
    assert calls[0][-2:] == ("--figure-name", figure)


def test_exited_solver_is_not_completion(setup, monkeypatch):
    observer, _ = setup
    monkeypatch.setattr(watcher, "solver_is_alive", lambda *_: False)
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="exited before"):
        observer.step()
    assert not (observer.output / "completion_bundle.json").exists()


def test_incomplete_report_cannot_prepare_email(setup):
    observer, _ = setup
    with pytest.raises(ValueError, match="Final status gate"):
        observer.prepare_delivery()
    assert not (observer.output / "email_payload.json").exists()


def test_helper_drift_stops_before_work(setup, tmp_path):
    observer, _ = setup
    helper = tmp_path / "helper.py"
    helper.write_text("original")
    observer.config["helper_hashes"] = {str(helper): watcher.sha256(helper)}
    helper.write_text("modified")
    with pytest.raises(ValueError, match="helper changed"):
        observer.step()


def test_os_lock_blocks_second_observer_and_releases_after_exit(tmp_path):
    lock = tmp_path / "lock"
    with watcher.observer_lock(lock):
        with pytest.raises(OSError):
            with watcher.observer_lock(lock):
                pytest.fail("Second observer obtained lock")
    with watcher.observer_lock(lock):
        pass


def test_queue_acceptance_is_persisted_and_never_repeated(setup, monkeypatch):
    observer, _ = setup
    calls = []
    def queue(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="Queued message event-123 for thread existing-thread.", stderr="")
    monkeypatch.setattr(watcher.subprocess, "run", queue)
    observer.queue_once("completion")
    observer.queue_once("completion")
    assert len(calls) == 1
    assert calls[0][1:4] == ["queue", "--thread", "existing-thread"]
    assert watcher.read_json(observer.output / "completion_dispatch.json")["status"] == "QUEUED"


def test_ambiguous_queue_ack_does_not_retry_blindly(setup, monkeypatch):
    observer, _ = setup
    monkeypatch.setattr(watcher.subprocess, "run", lambda *_args, **_kw:
                        SimpleNamespace(returncode=1, stdout="", stderr="connection lost"))
    with pytest.raises(ValueError, match="Queue failed"):
        observer.queue_once("completion")
    monkeypatch.setattr(watcher.subprocess, "run", lambda *_args, **_kw: pytest.fail("Duplicate queue"))
    with pytest.raises(ValueError, match="uncertain dispatch"):
        observer.queue_once("completion")


def test_pending_docs_checkpoint_is_recovered_without_reaudit(setup, monkeypatch):
    observer, _ = setup
    observer.checkpoint("AUDITING_WEEK")
    published = []
    monkeypatch.setattr(observer, "publish", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(watcher, "solver_is_alive", lambda *_: True)
    assert observer.step() is False
    assert published == [{"complete": False}]


def test_atomic_json_replacement_is_valid_utf8(tmp_path):
    path = tmp_path / "state.json"
    watcher.write_json(path, {"state": "初期"})
    watcher.write_json(path, {"state": "完了"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "完了"}


def test_configuration_binding_survives_changed_output(setup, monkeypatch):
    observer, _ = setup
    monkeypatch.setattr(watcher, "ROOT", observer.root)
    watcher.bind_configuration(observer.config, read_only=False)
    changed = deepcopy(observer.config)
    changed["output"] = str(observer.root / "elsewhere")
    with pytest.raises(ValueError, match="configuration changed"):
        watcher.bind_configuration(changed, read_only=False)
    assert not (observer.root / "elsewhere").exists()


def test_rejects_legacy_state_without_configuration_identity(setup, monkeypatch):
    observer, _ = setup
    monkeypatch.setattr(watcher, "ROOT", observer.root)
    watcher.write_json(observer.output / "state.json", {"status": "RUNNING"})
    with pytest.raises(ValueError, match="missing/different"):
        watcher.bind_configuration(observer.config, read_only=True)


@pytest.mark.parametrize("field", ["output", "audit", "audit_script", "report_script", "checkpoint_script", "report_stem"])
def test_write_paths_and_helpers_cannot_point_into_frozen_tree(setup, monkeypatch, field):
    observer, _ = setup
    monkeypatch.setattr(watcher, "ROOT", observer.root)
    root = observer.root
    base = root / watcher.DEPLOYMENT_RELATIVE
    config = dict(observer.config, output=str(base / "script_observer"), audit=str(base / "monthly_budget_independent_audit.json"),
                  audit_script=str(base / "audit_budget_week.py"), checkpoint_script=str(base / "update_monthly_checkpoint.py"),
                  report_script=str(root / "scripts/build_monthly_interpretation.py"),
                  report_stem=str(root / "docs/notes/SHIBU21_23_MONTHLY_BUDGET_RESULTS_20260914"),
                  figure_stem=str(root / "docs/notes/figures/shibu21_23_monthly_20260914"),
                  python=str(root / ".venv/Scripts/python.exe"))
    config[field] = str(root.parent / "frozen" / "forbidden")
    with pytest.raises(ValueError, match="Unexpected observer"):
        watcher.validate_configuration(config)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_current_paragraph_update_preserves_added_introduction(newline):
    helper = Path(__file__).resolve().parents[1] / "output/monthly_fair_weeks_20260914/update_monthly_checkpoint.py"
    spec = importlib.util.spec_from_file_location("checkpoint_helper", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paragraphs = ["# README", "別の担当者が追加した説明", "最新の固定版 `fa0c22bf` は3/12", "既存の詳細"]
    source = (newline * 2).join(paragraphs)
    updated = module.replace_current_result_paragraph(source, "最新の固定版 `fa0c22bf` は4/12", "README")
    assert updated == source.replace("は3/12", "は4/12")
    with pytest.raises(ValueError, match="expected one"):
        module.replace_current_result_paragraph(source + newline * 2 + paragraphs[2], "new", "README")


def test_checkpoint_excludes_failed_finished_case_and_shows_stopped_status(tmp_path, monkeypatch):
    helper = Path(__file__).resolve().parents[1] / "output/monthly_fair_weeks_20260914/update_monthly_checkpoint.py"
    spec = importlib.util.spec_from_file_location("stopped_checkpoint", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = tmp_path / "output"
    monkeypatch.setattr(module, "OUTPUT", output)
    source_sha = module.SOURCE_SHA
    week = "2025-01-06"
    failed_week = "2025-02-03"
    record = {"fully_audited": True, "status": "DIAGNOSTIC_EXECUTION_PASSED", "audit_status": "INDEPENDENTLY_AUDITED",
              "accounting": {"within_1e-6_jpy": True, "cost_difference_jpy": 0},
              "native_stage2_metadata": {"quality_maximums": {"maximum_constraint_violation": 0}}}
    audit = {"expected_sha": source_sha, "expected_week_count": 12, "weeks": {
        week: record, failed_week: {"fully_audited": False, "failure": True, "status": "DAY_AHEAD_FAILED"}}}
    watcher.write_json(output / "monthly_budget_independent_audit.json", audit)
    row = {"week": week, "month": 1, "status": record["status"], "hourly_steps_accepted": 168,
           "physical_violations": 0, "total_cost": 100, "grid_import_kwh": 1, "peak_grid_kw": 1,
           "used_vehicle_day_count": 1, "non_vehicle_usage_cost_jpy": 1, "pv_generated_kwh": 1,
           "pv_curtailment_pct": 0, "bess_inventory_drawdown_kwh": 0}
    report = {"source_git_sha": source_sha, "completed_count": 1, "declared_week_count": 12,
              "status": "STOPPED_AFTER_FAILED_CASE", "weeks": [row],
              "independent_audit": {"sha256": watcher.sha256(output / "monthly_budget_independent_audit.json")}}
    watcher.write_json(tmp_path / f"docs/notes/{module.REPORT_STEM}.json", report)
    watcher.write_json(output / "budget_rerun_launch.json", {"source_git_sha": source_sha,
                       "frozen_root": str(tmp_path), "campaign_relative_path": "campaign"})
    watcher.write_json(tmp_path / "campaign/progress.json", {"base_git_sha": source_sha,
                       "completed_weeks": [week, failed_week], "status": "STOPPED_AFTER_FAILED_CASE", "active_week": None})
    for relative in ["README.md", "docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md",
                     "docs/notes/SHIBU21_23_MONTHLY_FAIR_WEEKS_20260914.md"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Title\n\n別担当の導入文\n\n最新の固定版 `fa0c22bf` 旧結果\n", encoding="utf-8")
    (tmp_path / "docs/notes/DEVELOPMENT_NOTES.md").write_text("# Notes\n", encoding="utf-8")
    updates, _ = module.replacements()
    launch = json.loads(updates[output / "budget_rerun_launch.json"])
    assert launch["status"] == "STOPPED_AFTER_FAILED_CASE"
    assert launch["execution_passed_weeks"] == launch["independently_audited_weeks"] == 1
    assert launch["execution_finished_cases"] == 2
    text = updates[tmp_path / "README.md"].decode("utf-8")
    assert "2月で計算停止" in text and "別担当の導入文" in text
    assert "2月以降の計算と最終季節別整理を継続中" not in text


def test_first_week_failure_keeps_original_reason_without_audit_command(setup, monkeypatch):
    observer, progress = setup
    week = progress['selected_weeks'][0]
    progress.update(status='STOPPED_AFTER_FAILED_CASE', completed_weeks=[week])
    watcher.write_json(observer.campaign/'progress.json', progress)
    watcher.write_json(observer.audit, {'expected_sha':'frozen-sha','weeks':{}})
    summary_path=observer.campaign/'cases'/week/'diagnostic'/week/'summary.json'
    reason='[STAGE2_NO_INCUMBENT] Charging optimization returned time_limit'
    watcher.write_json(summary_path, {'status':'DAY_AHEAD_FAILED','day_ahead_reasons':[reason]})
    monkeypatch.setattr(observer,'run_python',lambda *a: pytest.fail('No completed week to audit'))
    observer.publish_stopped(progress)
    stopped=watcher.read_json(observer.output/'stopped_campaign.json')
    assert stopped['independently_audited_weeks']==0 and stopped['email_sent'] is False
    assert stopped['failed_cases']==[{'week':week,'status':'DAY_AHEAD_FAILED','reasons':[reason],
        'source_path':str(summary_path),'source_sha256':watcher.sha256(summary_path)}]
