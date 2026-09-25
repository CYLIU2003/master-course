import json
from pathlib import Path

import pytest

from bff.services.cluster.store import ControllerLock
from tools.cluster.batch import load_state, save
from tools.research import weekly_operator as op
from tools.research.weekly_results import write_json


def fixture(tmp_path):
    operation = {"settings": str(tmp_path / "settings.json"), "campaign": str(tmp_path / "campaign"),
        "git_sha": "a" * 40, "parent": "parent", "weeks": ["2025-05-12"], "workers": ["local"]}
    settings = {"git_sha": "a" * 40, "port": 8890, "config": str(tmp_path / "workers.json"),
        "release": str(tmp_path / "release with spaces"), "python": "python.exe"}
    write_json(Path(operation["settings"]), settings)
    write_json(Path(settings["config"]), {"workers": []})
    write_json(tmp_path / "operation.json", operation)
    campaign = Path(operation["campaign"])
    directory = campaign / operation["weeks"][0]
    spec = {"schema_version": 1, "batch_id": "same-batch", "git_sha": "a" * 40,
        "controller_url": "http://127.0.0.1:8890", "tasks": [{"task_id": "2025-05-12", "submission": {
        "scenario_id": "scenario", "worker_id": "local", "minimum_ram_gb": 18,
        "request": {"prepared_input_id": "prepared"}}}]}
    write_json(directory / "batch.json", spec)
    state_dir = directory / "state"
    state_dir.mkdir()
    state = load_state(spec, state_dir / "batch-state.json")
    state["tasks"]["2025-05-12"] = {"job_id": "same-attempt", "state": "RUNNING"}
    save(state_dir / "batch-state.json", state)
    return operation, settings, campaign, directory


def test_operation_rejects_changed_frozen_case_selection(tmp_path):
    operation, settings, campaign, _ = fixture(tmp_path)
    write_json(campaign / "binding.json", {**operation, "git": {"sha": "a"*40, "dirty": False}, "weeks": ["2025-08-04"]})
    with pytest.raises(ValueError, match="Frozen campaign differs"):
        op.load_operation(tmp_path / "operation.json")


def test_auto_campaign_uses_scheduler_without_pinning_busy_parent(tmp_path):
    from tools.research.weekly_campaign import placement_worker
    from tools.cluster.batch import validate_batch
    operation, settings, campaign, directory = fixture(tmp_path)
    operation["workers"] = ["auto"]
    spec = op.read(directory / "batch.json")
    spec["tasks"][0]["submission"]["worker_id"] = placement_worker(["auto"], 0)
    validate_batch(spec)
    assert spec["tasks"][0]["submission"]["worker_id"] is None
    assert spec["tasks"][0]["submission"]["minimum_ram_gb"] == 18
    assert op.resume_command(operation, settings, campaign)[-2:] == ["--workers", "auto"]
    # Existing pinned operations retain their meaning on restart.
    assert placement_worker(["worker-a", "local"], 3) == "local"


@pytest.mark.parametrize("workers", [[], ["auto", "local"], ["local", "auto"]])
def test_ambiguous_placement_rejected_before_preparing_any_input(workers):
    from tools.research.weekly_campaign import run
    with pytest.raises(ValueError, match="auto alone"):
        run(Path("missing-settings"), Path("unused"), "parent", ["2025-01-06"], workers)


def test_disconnect_preserves_unknown_not_failed_or_zero_progress_completion(tmp_path):
    operation, settings, campaign, _ = fixture(tmp_path)
    class Offline:
        def request(self, path):
            raise TimeoutError()
    report = op.snapshot(operation, settings, campaign, Offline())
    assert report["connection"] == "CONNECTION_UNKNOWN"
    assert report["cases"][0]["state"] == "STATE_UNKNOWN"
    assert report["cases"][0]["last_recorded_state"] == "RUNNING"
    assert report["progress"]["completed_percent"] == 0
    assert op.terminal_notice(operation, campaign, report) == "NOT_TERMINAL"


@pytest.mark.parametrize("state", ["LOST", "RUNNING", "QUEUED", "FAILED"])
def test_recovery_only_reads_same_attempt_never_submits(tmp_path, state):
    _, _, _, directory = fixture(tmp_path)
    calls = []
    class ReadOnly:
        def request(self, path):
            calls.append(path)
            assert path == "/api/cluster/jobs/same-attempt"
            return {"id": "same-attempt", "state": state, "worker_id": "local"}
    assert op.collect_existing(directory, client=ReadOnly())["state"] == state
    assert calls == ["/api/cluster/jobs/same-attempt"]


def test_client_with_lost_submit_response_is_not_replaced(tmp_path):
    _, _, _, directory = fixture(tmp_path)
    path = directory / "state/batch-state.json"
    state = op.read(path)
    state["tasks"]["2025-05-12"] = {}
    write_json(path, state)
    class NeverCall:
        def request(self, path):
            pytest.fail("Cannot guess attempt after lost submit response")
    assert op.collect_existing(directory, client=NeverCall())["state"] == "SUBMISSION_UNKNOWN"


def test_recovery_rejects_another_attempt_response(tmp_path):
    _, _, _, directory = fixture(tmp_path)
    class WrongAttempt:
        def request(self, path):
            return {"id": "another-attempt", "state": "RUNNING"}
    with pytest.raises(ValueError, match="different attempt"):
        op.collect_existing(directory, client=WrongAttempt())


def test_active_campaign_only_allows_recovery_of_retired_client(tmp_path, monkeypatch):
    operation, _, campaign, _ = fixture(tmp_path)
    write_json(campaign / "state.json", {"cases": {"2025-05-12": {"state": "FAILED_OR_UNVERIFIED"}}})
    calls = []
    def recover(directory):
        calls.append(directory)
        return {"state": "RUNNING", "job_id": "same-attempt"}
    monkeypatch.setattr(op, "collect_existing", recover)
    lock = ControllerLock(campaign)
    try:
        result = op.collect_campaign(operation, campaign)
        assert len(calls) == 1
        assert result["cases"]["2025-05-12"]["state"] == "RUNNING"
        assert op.read(campaign / "state.json")["cases"]["2025-05-12"]["state"] == "FAILED_OR_UNVERIFIED"
    finally:
        lock.close()


def test_active_campaign_is_not_restarted_or_collected_twice(tmp_path, monkeypatch):
    operation, settings, campaign, _ = fixture(tmp_path)
    lock = ControllerLock(campaign)
    monkeypatch.setattr(op.subprocess, "run", lambda *a, **kw: pytest.fail("must not launch"))
    try:
        assert op.execute(operation, settings, campaign)["status"] == "ALREADY_ACTIVE"
        assert op.collect_campaign(operation, campaign)["cases"]["2025-05-12"]["state"] == "CLIENT_ACTIVE"
    finally:
        lock.close()


def test_live_orphan_batch_client_is_not_restarted(tmp_path, monkeypatch):
    operation, settings, campaign, directory = fixture(tmp_path)
    lock = ControllerLock(directory / "state")
    monkeypatch.setattr(op.subprocess, "run", lambda *a, **kw: pytest.fail("must not launch"))
    try:
        assert op.execute(operation, settings, campaign)["status"] == "ALREADY_ACTIVE"
    finally:
        lock.close()


def test_resume_uses_frozen_interpreter_release_and_original_output(tmp_path):
    operation, settings, campaign, _ = fixture(tmp_path)
    command = op.resume_command(operation, settings, campaign)
    assert command[0] == settings["python"]
    assert command[3] == settings["release"]
    assert command[command.index("--output")+1] == str(campaign)
    assert "configure(Path(sys.argv[2]))" in command[2]
    assert command[-1] == "local"


def test_terminal_notice_is_unsent_stable_and_waits_for_audit(tmp_path):
    operation, _, campaign, _ = fixture(tmp_path)
    report = {"connection": "CONNECTED", "cases": [{"state": "COMPLETED", "job_id": "same-attempt"}]}
    assert op.terminal_notice(operation, campaign, report) == "AWAITING_COLLECTION"
    write_json(campaign / "state.json", {"status": "COMPLETED"})
    assert op.terminal_notice(operation, campaign, report) == "PENDING_MANUAL_SEND"
    first = (campaign / "operations/terminal-notice.eml").read_bytes()
    assert op.terminal_notice(operation, campaign, report) == "PENDING_MANUAL_SEND"
    assert (campaign / "operations/terminal-notice.eml").read_bytes() == first
    assert op.read(campaign / "operations/notification.json")["status"] != "SENT"


def test_local_summary_alone_does_not_prove_verification(tmp_path):
    operation, settings, campaign, directory = fixture(tmp_path)
    write_json(directory / "results/weekly_summary.json", {"total_cost": 1})
    class Online:
        def request(self, path):
            return [{"id": "same-attempt", "state": "COMPLETED"}] if path.endswith("jobs") else {"workers": []}
    report = op.snapshot(operation, settings, campaign, Online())
    assert report["progress"]["completed_percent"] == 100
    assert report["progress"]["verified_percent"] == 0
