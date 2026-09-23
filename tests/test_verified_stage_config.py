"""A partial cluster rollout only enables workers with matching release evidence."""

import json

import pytest

from tools.cluster import verified_stage_config as staged


def test_partial_stage_keeps_failed_worker_disabled_until_verified_retry(tmp_path, monkeypatch):
    sha = "a" * 40
    git = {"sha": sha, "dirty": False}
    monkeypatch.setattr(staged, "git_state", lambda _release: git)
    source = tmp_path / "workers.json"
    source.write_text(json.dumps({"workers": [
        {"id": "local", "name": "Parent", "transport": "local"},
        {"id": "child", "name": "Child", "transport": "ssh", "host": "100.65.118.103",
         "repo": f"C:/mc-worker/releases/{'b' * 40}"},
    ]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"git": git, "source_digest": "digest",
        "uv_lock_sha256": "lock", "dataset_hashes": {"a": "hash"}}), encoding="utf-8")
    report = tmp_path / "first/report.json"
    report.parent.mkdir()
    report.write_text(json.dumps({"git": git, "gurobi_env_started": 0,
        "workers": [{"id": "local", "status": "VERIFIED"},
                    {"id": "child", "status": "FAILED"}]}), encoding="utf-8")

    def evidence(report_path, identity):
        root = report_path.parent / identity
        (root / "dataset").mkdir(parents=True)
        (root / "transport.stdout").write_text(json.dumps({"git": git,
            "source_digest": "digest", "runtime_versions": {"uv_lock_sha256": "lock"}}),
            encoding="utf-8")
        (root / "dataset/transport.stdout").write_text(json.dumps({"a": "hash"}), encoding="utf-8")

    evidence(report, "local")
    config, summary = staged.derive(source, [report], tmp_path / "release", manifest)
    assert summary["verified"] == ["local"]
    assert summary["disabled_until_restage"] == ["child"]
    assert not config.workers[1].enabled and config.workers[1].monitoring_enabled

    retry = tmp_path / "retry/report.json"
    retry.parent.mkdir()
    retry.write_text(json.dumps({"git": git, "gurobi_env_started": 0,
        "workers": [{"id": "child", "status": "VERIFIED"}]}), encoding="utf-8")
    evidence(retry, "child")
    config, summary = staged.derive(source, [report, retry], tmp_path / "release", manifest)
    assert summary["verified"] == ["local", "child"]
    assert config.workers[1].enabled
    (retry.parent / "child/dataset/transport.stdout").write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError, match="Stage evidence differs"):
        staged.derive(source, [report, retry], tmp_path / "release", manifest)
