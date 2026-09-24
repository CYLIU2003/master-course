import json
from pathlib import Path
from types import SimpleNamespace

from tools.research import watch_shibu24_terminal as watch


def _config(tmp_path: Path) -> dict:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    watch.write(campaign / "binding.json", {"git_sha": "a" * 40})
    watch.write(campaign / "stage-state.json", {"stages": {"day": "PASSED", "week": "RUNNING"}})
    return {"campaign": str(campaign), "output": str(tmp_path / "observer"),
            "git_sha": "a" * 40, "recipient": "student@example.edu",
            "thread_id": "thread-id", "codex_exe": "codex", "campaign_pid": 123,
            "campaign_identity": "birth-1", "poll_seconds": 1}


def test_running_does_not_queue_mail(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(watch, "process_identity", lambda _pid: "birth-1")
    monkeypatch.setattr(watch.subprocess, "run", lambda *_args, **_kwargs: 1 / 0)

    assert watch.watch(config, once=True) == {"status": "RUNNING", "mail_requested": False}
    assert not (Path(config["output"]) / "event.json").exists()


def test_completed_requires_all_twelve_audited_weeks(tmp_path):
    config = _config(tmp_path)
    campaign = Path(config["campaign"])
    watch.write(campaign / "stage-state.json", {"stages": {"day": "PASSED", "week": "PASSED", "months": "PASSED"}})
    assert watch.terminal(config)[0] == "FAILURE"
    watch.write(campaign / "twelve-month-audit.json", {"source_git_sha": config["git_sha"],
                "months": [{"task_id": f"month-{i:02}", "collection_verified": True,
                            "physical_feasibility_claim_eligible": True} for i in range(1, 13)]})
    assert watch.terminal(config)[0] == "COMPLETED"


def test_failure_queues_once_and_does_not_resubmit(tmp_path, monkeypatch):
    config = _config(tmp_path)
    watch.write(Path(config["campaign"]) / "stage-state.json", {"stages": {"week": "FAILED"},
                "failure": {"type": "ValueError", "message": "GurobiError: Out of memory"}})
    called = []
    def fake_run(command, **_kwargs):
        called.append(command)
        return SimpleNamespace(returncode=0, stdout="queued", stderr="")
    monkeypatch.setattr(watch.subprocess, "run", fake_run)

    first = watch.watch(config, once=True)
    second = watch.watch(config, once=True)

    assert first["status"] == second["status"] == "QUEUED"
    assert first["terminal_status"] == "FAILURE"
    assert len(called) == 1
    assert json.loads((Path(config["output"]) / "email_payload.json").read_text(encoding="utf-8"))["to"] == config["recipient"]


def test_exited_campaign_is_failure_not_completion(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(watch, "process_identity", lambda _pid: None)
    monkeypatch.setattr(watch.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="queued", stderr=""))

    result = watch.watch(config, once=True)
    assert result["terminal_status"] == "FAILURE"
    assert "exited" in result["reason"]
