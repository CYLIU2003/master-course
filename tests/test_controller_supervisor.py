import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from bff.services.cluster.store import ControllerLock
from tools.research import controller_supervisor as s


def fixture(tmp_path):
    settings = {"queue": str(tmp_path), "release": str(tmp_path), "python": sys.executable,
                "port": 65533, "git_sha": "a" * 40}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    operation = {"settings": str(path)}
    state = {"binding": s.binding(operation, settings), "enabled": True, "starts": 0, "status": "ARMED"}
    return operation, settings, state, tmp_path / "state.json"


@pytest.mark.parametrize("status", ["PROCESS_PRESENT", "HOLD_MULTIPLE_PROCESSES", "HOLD_PROCESS_UNKNOWN",
                                   "HOLD_PORT_OCCUPIED", "HOLD_QUEUE_OWNED"])
def test_alive_or_uncertain_never_restarts(tmp_path, status):
    operation, settings, state, path = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("Must not check, launch or touch queue under uncertainty")
    result = s.tick(state, operation, settings, path, observation={"status": status},
                    run=forbidden, launch=forbidden, pending=forbidden)
    assert result["status"] == status
    assert result["starts"] == 0


def test_launch_reservation_survives_process_creation_failure(tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    def fail(*args, **kwargs):
        assert json.loads(path.read_bytes())["status"] == "STARTING"
        raise OSError("creation outcome uncertain")
    with pytest.raises(OSError):
        s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
               pending=lambda _: True, run=lambda *a, **k: SimpleNamespace(returncode=0), launch=fail,
               reobserve=lambda *a: {"status": "ABSENT"})
    saved = json.loads(path.read_bytes())
    assert saved["starts"] == 1
    s.tick(saved, operation, settings, path, observation={"status": "ABSENT"})
    assert saved["status"] == "BLOCKED_START_OUTCOME_UNKNOWN"
    assert not saved["enabled"]


def test_full_disk_prevents_launch_before_durable_reservation(monkeypatch, tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    path.write_text('{"original":"retained"}')
    def full(*args):
        raise OSError("disk full")
    def forbidden(*args, **kwargs):
        pytest.fail("Cannot launch without durable reservation")
    monkeypatch.setattr(s, "save", full)
    with pytest.raises(OSError):
        s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
               pending=lambda _: True, run=lambda *a, **k: SimpleNamespace(returncode=0), launch=forbidden,
               reobserve=lambda *a: {"status": "ABSENT"})
    assert json.loads(path.read_bytes()) == {"original": "retained"}


@pytest.mark.parametrize("change,expected", [
    ({"starts": 3}, "BLOCKED_RESTART_BUDGET"),
    ({"next_start_at": 100}, "BACKOFF"),
    ({"enabled": False}, "ARMED"),
])
def test_restart_budget_backoff_and_disable(tmp_path, change, expected):
    operation, settings, state, path = fixture(tmp_path)
    state.update(change)
    s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
           pending=lambda _: True, now=lambda: 50)
    assert state["status"] == expected


def test_settings_edit_disarms_without_starting(tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    Path(operation["settings"]).write_text("{}")
    s.tick(state, operation, settings, path)
    assert state["status"] == "BLOCKED_BINDING_CHANGED"
    assert not state["enabled"]


def test_preflight_failure_is_terminal_not_restart_loop(tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
           pending=lambda _: True, run=lambda *a, **k: SimpleNamespace(returncode=2))
    assert state["status"] == "BLOCKED_PREFLIGHT"
    assert not state["enabled"]
    assert state["starts"] == 0


def test_controller_started_during_preflight_is_adopted(tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("A controller appeared while checking")
    s.tick(state, operation, settings, path, observation={"status": "ABSENT"}, pending=lambda _: True,
           run=lambda *a, **k: SimpleNamespace(returncode=0), launch=forbidden,
           reobserve=lambda *a: {"status": "PROCESS_PRESENT", "process": {"pid": 123, "identity": "birth"}})
    assert state["status"] == "PROCESS_PRESENT"
    assert state["starts"] == 0


def test_finished_queue_does_not_restart(tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    with sqlite3.connect(tmp_path / "cluster.sqlite3") as db:
        db.execute("CREATE TABLE jobs(state TEXT)")
        db.execute("INSERT INTO jobs VALUES ('COMPLETED')")
    s.tick(state, operation, settings, path, observation={"status": "ABSENT"})
    assert state["status"] == "IDLE_NO_PENDING_WORK"
    assert not state["enabled"]


def test_reused_pid_does_not_claim_old_controller(monkeypatch, tmp_path):
    operation, settings, state, path = fixture(tmp_path)
    state["process"] = {"pid": 123, "identity": "old"}
    monkeypatch.setattr(s, "inspect_processes", lambda _: ([], False))
    monkeypatch.setattr(s, "process_identity", lambda _: "new")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        settings["port"] = listener.getsockname()[1]
    assert s.observe(settings, s.command(operation, settings), state)["status"] == "ABSENT"
    lock = ControllerLock(tmp_path)
    try:
        assert s.observe(settings, s.command(operation, settings), state)["status"] == "HOLD_QUEUE_OWNED"
    finally:
        lock.close()


def test_different_server_on_port_blocks_start(monkeypatch, tmp_path):
    operation, settings, state, _ = fixture(tmp_path)
    monkeypatch.setattr(s, "inspect_processes", lambda _: ([], False))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        settings["port"] = listener.getsockname()[1]
        assert s.observe(settings, s.command(operation, settings), state)["status"] == "HOLD_PORT_OCCUPIED"


@pytest.mark.skipif(os.name != "nt", reason="Windows process creation/CIM evidence")
def test_windows_real_process_crash_recovery(tmp_path):
    """Kill only the disposable child created here; no solver/API/SSH access."""
    operation, settings, state, path = fixture(tmp_path)
    # Terminate the disposable interpreter itself, not only its venv trampoline.
    settings["python"] = sys._base_executable
    script = tmp_path / "tools/cluster/serve_controller.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys,time\nif '--check' not in sys.argv: time.sleep(60)\n")
    children = []
    def start(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child
    try:
        s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
               pending=lambda _: True, launch=start, now=lambda: 100)
        assert state["status"] == "STARTED"
        found, _ = s.inspect_processes(s.command(operation, settings))
        assert len(found) == 1
        s.tick(state, operation, settings, path, observation={"status": "PROCESS_PRESENT", "process": found[0]})
        assert len(children) == 1
        children[0].terminate()
        children[0].wait(timeout=10)
        s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
               pending=lambda _: True, launch=start, now=lambda: 110)
        assert state["status"] == "BACKOFF"
        s.tick(state, operation, settings, path, observation={"status": "ABSENT"},
               pending=lambda _: True, launch=start, now=lambda: 161)
        assert len(children) == 2
        assert children[0].pid != children[1].pid
        assert state["starts"] == 2
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)


def test_command_matching_rejects_another_settings_or_program(tmp_path):
    operation, settings, _, _ = fixture(tmp_path)
    command = s.command(operation, settings)
    assert s.matches(command, command)
    assert s.matches([command[0], *command[3:]], command)
    assert not s.matches([*command[:-1], str(tmp_path / "other.json")], command)
    assert not s.matches([*command, "--check"], command)
    assert not s.matches([command[0], "-c", "pass"], command)


@pytest.mark.skipif(os.name != "nt", reason="Windows command line parser")
def test_venv_parent_child_are_one_but_unrelated_controller_is_not(monkeypatch, tmp_path):
    operation, settings, _, _ = fixture(tmp_path)
    command = s.command(operation, settings)
    rows = [{"ProcessId": pid, "ParentProcessId": parent, "CommandLine": subprocess.list2cmdline(command)}
            for pid, parent in [(10, 1), (11, 10)]]
    monkeypatch.setattr(s.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(rows)))
    monkeypatch.setattr(s, "process_identity", lambda pid: str(pid))
    assert s.inspect_processes(command) == ([{"pid": 11, "identity": "11"}], False)
    rows.append({"ProcessId": 12, "ParentProcessId": 1, "CommandLine": subprocess.list2cmdline(command)})
    assert len(s.inspect_processes(command)[0]) == 2
