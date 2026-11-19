"""Lab gateway: tokens, bundle validation, HTTP API isolation and the dispatcher, with fake machines (no SSH)."""
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from tools.lab_gateway.bundle import BundleError, validate_args, validate_bundle
from tools.lab_gateway.dispatcher import Dispatcher, memory_budget
from tools.lab_gateway.remote import JOB_ID, Machine, RemoteError
from tools.lab_gateway.server import Gateway
from tools.lab_gateway.store import JobStore, Tokens


def make_zip(path: Path, files: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in (files or {"main.py": b"print(1)"}).items():
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # set after construction: ZipInfo rewrites os.sep on Windows, hiding backslash cases
            archive.writestr(info, data)
    return path


class FakeMachine:
    def __init__(self, machine_id, *, total=16, free=12, cpu=5, disk=100, python_ok=True, script=None):
        self.id = machine_id
        self.info = {"total_gb": total, "free_gb": free, "cpu_load": cpu, "disk_free_gb": disk, "python_ok": python_ok}
        self.script = list(script or [{"state": "RUNNING", "pid": 42},
                                      {"state": "DONE", "outcome": "EXITED", "exit_code": 0, "result_bytes": 5}])
        self.staged, self.killed, self.cleaned, self.fail_status = [], [], [], False

    def probe(self):
        return dict(self.info)

    def stage(self, job_id, bundle, job):
        self.staged.append((job_id, job))

    def status(self, job_id):
        if self.fail_status:
            raise RemoteError("down")
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def fetch_result(self, job_id, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"PK-result")

    def kill(self, pid):
        self.killed.append(pid)

    def cleanup(self, job_id):
        self.cleaned.append(job_id)


@pytest.fixture
def env(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    tokens = Tokens(tmp_path / "tokens.json")
    return store, tokens, tmp_path


def new_job(store, tmp_path, owner="alice", ram=4.0, name="j"):
    bundle = make_zip(tmp_path / f"{owner}-{name}.zip")
    return store.create(owner=owner, name=name, entry="main.py", args=[], ram_gb=ram, threads=1, time_limit_min=5,
                        bundle_path=str(bundle), bundle_bytes=10)


def settle(dispatcher):
    for thread in list(dispatcher.threads.values()):
        thread.join(10)


# ---- tokens
def test_tokens_store_only_digests_and_can_be_revoked(env):
    _, tokens, tmp_path = env
    token = tokens.add("alice")
    assert token.startswith("lab_") and token not in (tmp_path / "tokens.json").read_text()
    assert tokens.authenticate(token) == {"name": "alice", "admin": False}
    assert tokens.authenticate("lab_wrong") is None and tokens.authenticate(None) is None
    with pytest.raises(ValueError):
        tokens.add("alice")
    assert tokens.revoke("alice") == 1 and tokens.authenticate(token) is None
    assert tokens.add("alice") != token  # a revoked name can be issued again with a fresh token


@pytest.mark.parametrize("name", ["", "a b", "../x", "a;b"])
def test_token_names_are_restricted(env, name):
    with pytest.raises(ValueError):
        env[1].add(name)


# ---- bundle validation
@pytest.mark.parametrize("name", ["../evil.py", "/abs.py", "..\\evil.py", "C:/x.py", "ok/../../x.py"])
def test_unsafe_zip_paths_are_rejected(tmp_path, name):
    with pytest.raises(BundleError):
        validate_bundle(make_zip(tmp_path / "b.zip", {name: b"x", "main.py": b"x"}), "main.py")


@pytest.mark.parametrize("entry", ["../main.py", "main.txt", "/main.py", "a b.py", "", "main.py;rm"])
def test_bad_entries_are_rejected(tmp_path, entry):
    with pytest.raises(BundleError):
        validate_bundle(make_zip(tmp_path / "b.zip"), entry)


def test_entry_must_be_in_bundle_and_zip_must_be_valid(tmp_path):
    with pytest.raises(BundleError):
        validate_bundle(make_zip(tmp_path / "b.zip", {"other.py": b"x"}), "main.py")
    (tmp_path / "not.zip").write_bytes(b"nope")
    with pytest.raises(BundleError):
        validate_bundle(tmp_path / "not.zip", "main.py")
    assert validate_bundle(make_zip(tmp_path / "ok.zip", {"pkg/main.py": b"abc"}), "pkg/main.py") == 3


def test_symlink_entries_are_rejected(tmp_path):
    path = tmp_path / "s.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("link.py")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target.py")
        archive.writestr("main.py", "x")
    with pytest.raises(BundleError):
        validate_bundle(path, "main.py")


@pytest.mark.parametrize("bad", [["a b"], ["$(x)"], ["a;b"], [1], "x", ["x"] * 41, ["`x`"]])
def test_bad_args_are_rejected(bad):
    with pytest.raises(BundleError):
        validate_args(bad)


def test_good_args():
    assert validate_args(["--n=3", "data/in.csv", "1,2"]) == ["--n=3", "data/in.csv", "1,2"]


# ---- dispatcher
def test_budget_rule_matches_cluster():
    assert memory_budget(16) == 8 and memory_budget(32) == 24 and memory_budget(7.9) == pytest.approx(3.95)


def make_dispatcher(env, machines, **kw):
    store, _, tmp_path = env
    return Dispatcher(store, machines, tmp_path, sleep=lambda _s: None, poll_seconds=0, **kw)


def test_job_runs_to_completion_and_result_is_stored(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1")
    dispatcher = make_dispatcher(env, {"m1": machine})
    job = new_job(store, tmp_path)
    dispatcher.tick()
    settle(dispatcher)
    done = store.get(job["id"])
    assert done["state"] == "COMPLETED" and done["machine"] == "m1" and Path(done["result_path"]).read_bytes() == b"PK-result"
    assert machine.cleaned == [job["id"]] and machine.staged[0][1]["entry"] == "main.py"


@pytest.mark.parametrize("outcome,code,state", [("EXITED_NONZERO", 3, "FAILED"), ("TIMEOUT", -1, "TIMEOUT")])
def test_failure_and_timeout_states_are_kept_distinct(env, outcome, code, state):
    store, _, tmp_path = env
    machine = FakeMachine("m1", script=[{"state": "DONE", "outcome": outcome, "exit_code": code, "result_bytes": 5}])
    dispatcher = make_dispatcher(env, {"m1": machine})
    job = new_job(store, tmp_path)
    dispatcher.tick()
    settle(dispatcher)
    row = store.get(job["id"])
    assert row["state"] == state and row["exit_code"] == code and row["result_path"]


def test_one_job_per_machine_and_fifo(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1", script=[{"state": "RUNNING", "pid": 1}])
    dispatcher = make_dispatcher(env, {"m1": machine}, per_owner_active=5)
    first, second = new_job(store, tmp_path, name="a"), new_job(store, tmp_path, name="b")
    dispatcher.tick()
    assert store.get(first["id"])["state"] in {"STAGING", "RUNNING"} and store.get(second["id"])["state"] == "QUEUED"
    dispatcher.stop_event.set()
    settle(dispatcher)


def test_per_owner_active_limit_lets_other_members_in(env):
    store, _, tmp_path = env
    machines = {f"m{i}": FakeMachine(f"m{i}", script=[{"state": "RUNNING", "pid": i}]) for i in range(3)}
    dispatcher = make_dispatcher(env, machines, per_owner_active=1)
    a1, a2, b1 = new_job(store, tmp_path, "alice", name="a1"), new_job(store, tmp_path, "alice", name="a2"), new_job(store, tmp_path, "bob")
    dispatcher.tick()
    assert store.get(a2["id"])["state"] == "QUEUED"
    assert store.get(a1["id"])["state"] != "QUEUED" and store.get(b1["id"])["state"] != "QUEUED"
    dispatcher.stop_event.set()
    settle(dispatcher)


@pytest.mark.parametrize("info,reason", [({"python_ok": False}, "PYTHON_ENVIRONMENT_MISSING"), ({"free": 2}, "INSUFFICIENT_FREE_RAM"),
                                         ({"cpu": 99}, "CPU_BUSY"), ({"disk": 1}, "INSUFFICIENT_DISK"), ({"total": 7}, "EXCEEDS_MACHINE_MEMORY_BUDGET")])
def test_admission_reasons(env, info, reason):
    store, _, tmp_path = env
    machine = FakeMachine("m1", **info)
    dispatcher = make_dispatcher(env, {"m1": machine})
    assert dispatcher.admits(new_job(store, tmp_path, ram=4), machine.probe()) == reason


def test_job_larger_than_every_machine_is_rejected_not_queued_forever(env):
    store, _, tmp_path = env
    dispatcher = make_dispatcher(env, {"m1": FakeMachine("m1", total=16), "m2": FakeMachine("m2", total=8)})
    job = new_job(store, tmp_path, ram=20)
    dispatcher.tick()
    assert store.get(job["id"])["state"] == "REJECTED"


def test_unreachable_machine_never_causes_rejection(env):
    store, _, tmp_path = env

    class Down(FakeMachine):
        def probe(self):
            raise RemoteError("offline")
    dispatcher = make_dispatcher(env, {"m1": Down("m1")})
    job = new_job(store, tmp_path, ram=20)
    dispatcher.tick()
    assert store.get(job["id"])["state"] == "QUEUED"


def test_cancel_queued_and_running(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1", script=[{"state": "RUNNING", "pid": 77}])
    dispatcher = make_dispatcher(env, {"m1": machine}, per_owner_active=5)
    running, waiting = new_job(store, tmp_path, name="r"), new_job(store, tmp_path, name="w")
    dispatcher.tick()
    assert dispatcher.cancel(waiting["id"])["state"] == "CANCELLED"
    dispatcher.cancel(running["id"])
    settle(dispatcher)
    assert store.get(running["id"])["state"] == "CANCELLED" and machine.killed == [77]


def test_cancel_before_the_program_started_does_not_hang(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1", script=[None])  # status.json never appears (no pid)
    dispatcher = make_dispatcher(env, {"m1": machine})
    job = new_job(store, tmp_path)
    store.update(job["id"], cancel_requested=True, state="STAGING", machine="m1")
    dispatcher._lifecycle(job["id"], machine, True)
    assert store.get(job["id"])["state"] == "CANCELLED" and machine.killed == []


def test_program_that_never_starts_fails_instead_of_staying_running(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1", script=[None])
    dispatcher = make_dispatcher(env, {"m1": machine}, start_grace_seconds=0)
    job = new_job(store, tmp_path)
    store.update(job["id"], state="RUNNING", machine="m1")
    dispatcher._lifecycle(job["id"], machine, True)
    row = store.get(job["id"])
    assert row["state"] == "FAILED" and "did not start" in row["message"] and machine.cleaned == [job["id"]]


def test_lost_contact_marks_lost_instead_of_rerunning(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1")
    machine.fail_status = True
    dispatcher = make_dispatcher(env, {"m1": machine})
    job = new_job(store, tmp_path)
    dispatcher.tick()
    settle(dispatcher)
    row = store.get(job["id"])
    assert row["state"] == "LOST" and len(machine.staged) == 1


def test_restart_loses_staging_and_resumes_running(env):
    store, _, tmp_path = env
    machine = FakeMachine("m1")
    staging, running = new_job(store, tmp_path, name="s"), new_job(store, tmp_path, name="r")
    store.update(staging["id"], state="STAGING", machine="m1")
    store.update(running["id"], state="RUNNING", machine="m1")
    dispatcher = make_dispatcher(env, {"m1": machine})
    dispatcher.recover()
    settle(dispatcher)
    assert store.get(staging["id"])["state"] == "LOST"
    assert store.get(running["id"])["state"] == "COMPLETED" and machine.staged == []  # resumed: not staged again


def test_remote_job_ids_cannot_inject_paths():
    assert JOB_ID.fullmatch("0123456789ab") and not JOB_ID.fullmatch("../../x") and not JOB_ID.fullmatch("0123456789ab; rm")
    with pytest.raises(ValueError):
        Machine.job_dir("../../Windows")


# ---- HTTP API
@pytest.fixture
def api(env):
    store, tokens, tmp_path = env
    machine = FakeMachine("m1", script=[{"state": "RUNNING", "pid": 1}])
    dispatcher = make_dispatcher(env, {"m1": machine})
    gateway = Gateway(("127.0.0.1", 0), store=store, tokens=tokens, dispatcher=dispatcher, data_dir=tmp_path)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{gateway.server_address[1]}", "tokens": tokens, "store": store, "dispatcher": dispatcher, "tmp": tmp_path}
    gateway.shutdown()
    gateway.server_close()
    dispatcher.stop_event.set()


def http(api, method, path, token=None, body=None, headers=None):
    request = urllib.request.Request(api["url"] + path, data=body, method=method, headers={**({"Authorization": f"Bearer {token}"} if token else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def submit_headers(**extra):
    return {"X-Entry": "main.py", "X-Ram-Gb": "2", "X-Time-Limit-Min": "10", "X-Name": "test", **extra}


def zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("main.py", "print(1)")
    return buffer.getvalue()


def test_api_requires_a_valid_token(api):
    assert http(api, "GET", "/v1/health")[0] == 200
    for path in ("/v1/jobs", "/v1/pool"):
        assert http(api, "GET", path)[0] == 401 and http(api, "GET", path, token="lab_bad")[0] == 401
    assert http(api, "POST", "/v1/jobs", body=zip_bytes(), headers=submit_headers())[0] == 401


def test_members_only_see_their_own_jobs(api):
    alice, bob, admin = (api["tokens"].add("alice"), api["tokens"].add("bob"), api["tokens"].add("root", admin=True))
    status, body = http(api, "POST", "/v1/jobs", alice, zip_bytes(), submit_headers())
    assert status == 201
    job = json.loads(body)
    assert "bundle_path" not in job and job["owner"] == "alice"
    assert http(api, "GET", f"/v1/jobs/{job['id']}", bob)[0] == 404
    assert http(api, "POST", f"/v1/jobs/{job['id']}/cancel", bob)[0] == 404
    assert json.loads(http(api, "GET", "/v1/jobs", bob)[1])["jobs"] == []
    assert len(json.loads(http(api, "GET", "/v1/jobs", alice)[1])["jobs"]) == 1
    assert len(json.loads(http(api, "GET", "/v1/jobs", admin)[1])["jobs"]) == 1
    assert http(api, "GET", f"/v1/jobs/{job['id']}", admin)[0] == 200


def test_submit_validation_errors(api):
    token = api["tokens"].add("alice")
    good = zip_bytes()
    cases = [({"X-Ram-Gb": "100"}, good), ({"X-Time-Limit-Min": "0"}, good), ({"X-Entry": "../x.py"}, good), ({"X-Args": "[\"a b\"]"}, good),
             ({"X-Name": "bad;name"}, good), ({"X-Threads": "99"}, good), ({}, b"not a zip")]
    for extra, data in cases:
        assert http(api, "POST", "/v1/jobs", token, data, submit_headers(**extra))[0] == 400, extra
    assert api["store"].rows() == []


def test_idempotency_key_returns_the_same_job(api):
    token = api["tokens"].add("alice")
    first = json.loads(http(api, "POST", "/v1/jobs", token, zip_bytes(), submit_headers(**{"X-Idempotency-Key": "k1"}))[1])
    status, body = http(api, "POST", "/v1/jobs", token, zip_bytes(), submit_headers(**{"X-Idempotency-Key": "k1"}))
    assert status == 200 and json.loads(body)["id"] == first["id"] and len(api["store"].rows()) == 1


def test_cancel_and_result_download_flow(api):
    token = api["tokens"].add("alice")
    job = json.loads(http(api, "POST", "/v1/jobs", token, zip_bytes(), submit_headers())[1])
    assert http(api, "GET", f"/v1/jobs/{job['id']}/result", token)[0] == 409
    status, body = http(api, "POST", f"/v1/jobs/{job['id']}/cancel", token)
    assert status == 200 and json.loads(body)["state"] == "CANCELLED"
    assert http(api, "POST", f"/v1/jobs/{job['id']}/cancel", token)[0] == 409
    result = api["tmp"] / "results" / "r.zip"
    result.write_bytes(b"PK-data")
    api["store"].update(job["id"], result_path=str(result))
    assert http(api, "GET", f"/v1/jobs/{job['id']}/result", token) == (200, b"PK-data")


def test_oversize_and_missing_length_are_refused(api):
    token = api["tokens"].add("alice")
    assert http(api, "POST", "/v1/jobs", token, b"", submit_headers())[0] in {400, 411, 413}


def test_pool_view_hides_hosts_and_users(api):
    token = api["tokens"].add("alice")
    status, body = http(api, "GET", "/v1/pool", token)
    text = body.decode()
    assert status == 200 and "m1" in text and "host" not in text and "user" not in text and "python" not in text


def test_audit_log_records_requests_without_tokens(api):
    token = api["tokens"].add("alice")
    http(api, "GET", "/v1/jobs", token)
    log = (api["tmp"] / "audit.log").read_text()
    assert "alice GET /v1/jobs 200" in log and token not in log


# ---- run_job.py (the program that runs on each lab PC), exercised locally
def run_local_job(tmp_path, code, *, timeout_min=1, args=None):
    import subprocess
    import sys
    from tools.lab_gateway import run_job
    job_dir = tmp_path / "job"
    (job_dir / "work").mkdir(parents=True)
    (job_dir / "work" / "main.py").write_text(code, encoding="utf-8")
    (job_dir / "job.json").write_text(json.dumps({"job_id": "abc", "python": sys.executable, "entry": "main.py", "args": args or [],
                                                  "timeout_min": timeout_min, "threads": 3}), encoding="ascii")
    subprocess.run([sys.executable, run_job.__file__, str(job_dir)], check=True, timeout=60)
    return job_dir, json.loads((job_dir / "status.json").read_text())


def test_run_job_success_packages_output_and_logs(tmp_path):
    code = "\n".join(["import os, sys",
                      "open(os.path.join(os.environ['MC_LAB_OUTPUT_DIR'], 'r.txt'), 'w').write(os.environ['MC_LAB_THREADS'] + ' ' + sys.argv[1])",
                      "print('hi')"])
    job_dir, status = run_local_job(tmp_path, code, args=["x=1"])
    assert status["state"] == "DONE" and status["outcome"] == "EXITED" and status["exit_code"] == 0 and status["result_bytes"] > 0
    with zipfile.ZipFile(job_dir / "result.zip") as archive:
        assert set(archive.namelist()) == {"r.txt", "stdout.log", "stderr.log"} and archive.read("r.txt") == b"3 x=1"
        assert archive.read("stdout.log").strip() == b"hi"


def test_run_job_reports_nonzero_exit_and_stderr(tmp_path):
    job_dir, status = run_local_job(tmp_path, "\n".join(["import sys", "sys.stderr.write('boom')", "sys.exit(4)"]))
    assert status["outcome"] == "EXITED_NONZERO" and status["exit_code"] == 4
    with zipfile.ZipFile(job_dir / "result.zip") as archive:
        assert archive.read("stderr.log") == b"boom"


def test_run_job_stops_a_program_at_the_time_limit(tmp_path):
    import sys
    import time
    from tools.lab_gateway import run_job
    started = time.monotonic()
    job_dir = tmp_path / "job"
    (job_dir / "work").mkdir(parents=True)
    (job_dir / "work" / "main.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    (job_dir / "job.json").write_text(json.dumps({"job_id": "abc", "python": sys.executable, "entry": "main.py", "args": [],
                                                  "timeout_min": 0.02, "threads": 1}), encoding="ascii")
    run_job.run(job_dir)
    status = json.loads((job_dir / "status.json").read_text())
    assert status["outcome"] == "TIMEOUT" and status["exit_code"] == -1 and time.monotonic() - started < 30
