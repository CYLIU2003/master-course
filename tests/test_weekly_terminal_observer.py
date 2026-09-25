from tools.research import weekly_terminal_observer as observer


def sample(stamp, free=3, commit=8, stale=False):
    return {"last_probe_at": stamp, "metrics_stale": stale,
            "capability": {"ram_free_gb": free, "commit_available_gb": commit}}


def test_pressure_requires_three_distinct_fresh_samples_and_recovers():
    state = observer.memory_pressure({}, sample("a"), 4)
    assert state["status"] == "LOW"
    assert observer.memory_pressure(state, sample("a"), 4)["consecutive_low"] == 1
    state = observer.memory_pressure(state, sample("b"), 4)
    assert observer.memory_pressure(state, sample("c"), 4)["status"] == "PRESSURE"
    assert observer.memory_pressure(state, sample("c", 4, 4), 4)["status"] == "OK"


def test_unknown_or_stale_telemetry_does_not_count_as_failure():
    for worker in (sample("a", stale=True), sample("b", free=None), sample("c", commit=float("nan"))):
        state = observer.memory_pressure({"last_probe_at": worker["last_probe_at"], "consecutive_low": 2}, worker, 4)
        assert state["status"] == "UNKNOWN" and state["consecutive_low"] == 0


def test_pressure_notification_only_once(tmp_path, monkeypatch):
    import io, json
    from types import SimpleNamespace
    monkeypatch.setattr(observer, "urlopen", lambda *a, **k: io.StringIO(json.dumps(sample("c"))))
    output = tmp_path / "terminal_observer"
    observer.write_json(output / "memory_guard.json", {"last_probe_at": "b", "consecutive_low": 2})
    calls = []
    monkeypatch.setattr(observer.subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0))
    for _ in range(2):
        observer.check_memory(tmp_path, "http://127.0.0.1:8891", "worker", "thread", tmp_path / "codex")
    assert len(calls) == 1
    assert observer.read(output / "memory_pressure_event.json")["status"] == "QUEUED"


def test_failure_handoff_authorizes_repair_only_when_requested(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(observer.subprocess, "run", lambda args, **k: calls.append(args[-1]) or SimpleNamespace(returncode=0))
    observer.notify_once(tmp_path, {"git_sha": "a" * 40}, ("PARTIAL_OR_FAILED", {}), "thread", tmp_path / "codex", repair_on_failure=True)
    observer.notify_once(tmp_path, {"git_sha": "a" * 40}, ("PARTIAL_OR_FAILED", {}), "thread", tmp_path / "codex", repair_on_failure=True)
    assert len(calls) == 1
    assert "失敗原因を原本から特定" in calls[0]
