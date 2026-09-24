"""Config-driven cluster submission, resumption and verified artifact collection.

Uses the existing loopback BFF. No AI API, remote shell commands or credentials
are accepted in a batch file. Run the same command after an interruption.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import canonical, digest, segment
from bff.services.cluster.store import ControllerLock


class Client:
    def __init__(self, base: str):
        parsed = urlparse(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
            raise ValueError("Controller must be a loopback HTTP URL")
        self.base = base.rstrip("/")

    def request(self, path: str, body: dict | None = None):
        request = Request(self.base + path, data=canonical(body) if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    def download(self, job_id: str, target: Path, expected: str):
        segment(job_id)
        temporary = target.with_name(target.name + ".partial-" + uuid.uuid4().hex)
        try:
            sha = hashlib.sha256()
            with urlopen(self.base + "/api/cluster/jobs/" + quote(job_id) + "/artifacts", timeout=60) as response:
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        sha.update(chunk)
                        output.write(chunk)
            if sha.hexdigest() != expected:
                raise ValueError("Downloaded artifact hash differs from verified worker receipt")
            if target.exists():
                with target.open("rb") as existing:
                    if hashlib.file_digest(existing, "sha256").hexdigest() != expected:
                        raise ValueError("Refusing to overwrite a different attempt artifact")
            temporary.replace(target)
        finally:
            if temporary.exists() and not temporary.is_symlink() and temporary.resolve().parent == target.parent.resolve():
                temporary.unlink()


def save(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def sanitized_rejection(exc: HTTPError) -> dict:
    """Keep an actionable bounded API reason without storing arbitrary response data."""
    result = {"status": "REQUEST_REJECTED", "http_status": exc.code, "retryable": False}
    try:
        payload = json.loads(exc.read(64 * 1024))
    except (ValueError, OSError):
        payload = None
    finally:
        exc.close()
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("error_code") or detail.get("error")
        message = detail.get("message") or detail.get("error")
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", code):
            result["error_code"] = code
        detail = message
    if isinstance(detail, str):
        prefixed_code = re.match(r"^([A-Z][A-Z0-9_]{1,79}):\s*(.*)$", detail, flags=re.DOTALL)
        if prefixed_code:
            result.setdefault("error_code", prefixed_code.group(1))
            detail = prefixed_code.group(2)
        detail = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", detail)
        detail = re.sub(
            r"(?i)\b(password|token|secret|credential|api[-_ ]?key|wls[-_ ]?key)\b\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]", detail,
        )
        detail = " ".join(detail.split())[:240]
        if detail:
            result["detail"] = detail
    result.setdefault("error_code", f"HTTP_{exc.code}_UNCLASSIFIED")
    return result


def validate_batch(spec: dict, *, allow_formal: bool = False):
    if set(spec) - {"schema_version", "batch_id", "controller_url", "git_sha", "tasks"} or spec.get("schema_version") != 1:
        raise ValueError("Unsupported batch schema")
    if not re.fullmatch(r"[0-9a-f]{40}", spec.get("git_sha", "")):
        raise ValueError("Batch requires the full frozen git_sha")
    segment(spec["batch_id"])
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Batch requires tasks")
    identities = set()
    for task in tasks:
        if set(task) - {"task_id", "submission", "prepare_request", "configuration_revision"}:
            raise ValueError("Unsupported task fields")
        task_id = segment(task["task_id"])
        if task_id in identities:
            raise ValueError("Duplicate task identity")
        identities.add(task_id)
        body = task["submission"]
        if set(body) - {"scenario_id", "worker_id", "minimum_ram_gb", "request"}:
            raise ValueError("Unsupported submission fields")
        ram = body.get("minimum_ram_gb")
        if isinstance(ram, bool) or not isinstance(ram, (int, float)) or not 0 < ram < float("inf"):
            raise ValueError("Optimization task requires a finite positive minimum_ram_gb")
        segment(body["scenario_id"])
        request = body["request"]
        if not isinstance(request, dict):
            raise ValueError("Submission request must be an object")
        if body.get("idempotency_key"):
            raise ValueError("Batch owns the idempotency key")
        if request.get("research_run", False) and not allow_formal:
            raise ValueError("Formal execution requires explicit --allow-formal and all BFF research gates")
        if not request.get("prepared_input_id") and (not task.get("prepare_request") or not task.get("configuration_revision")):
            raise ValueError("Unprepared tasks require explicit prepare_request and configuration_revision")


def load_state(spec: dict, path: Path) -> dict:
    fingerprint = digest(canonical(spec))
    if path.exists():
        state = json.loads(path.read_bytes())
        if state["batch_sha256"] != fingerprint:
            raise ValueError("Batch changed; use a new batch ID/output directory")
        return state
    state = {"schema_version": 1, "batch_sha256": fingerprint, "batch_id": spec["batch_id"],
             "tasks": {task["task_id"]: {} for task in spec["tasks"]},
             "research_approval": "NOT_GRANTED_BY_CLUSTER"}
    save(path, state)
    return state


def advance(spec: dict, state: dict, path: Path, client) -> dict:
    terminal = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
    for task in spec["tasks"]:
        item = state["tasks"][task["task_id"]]
        submission = dict(task["submission"])
        submission["expected_git_sha"] = spec["git_sha"]
        submission["request"] = dict(submission["request"])
        if not submission["request"].get("prepared_input_id"):
            if not item.get("prepared_input_id"):
                scenario = quote(submission["scenario_id"])
                config = client.request(f"/api/desktop/scenarios/{scenario}/configuration")
                if config["revision"] != task["configuration_revision"]:
                    raise ValueError("Scenario configuration changed before Prepare")
                prepared = client.request(f"/api/scenarios/{scenario}/simulation/prepare", task["prepare_request"])
                item["prepared_input_id"] = prepared["preparedInputId"]
                save(path, state)
            submission["request"]["prepared_input_id"] = item["prepared_input_id"]
        if not item.get("job_id"):
            # The server persists this identity before preflight. A lost HTTP
            # response repeats this exact key, including after a CLI restart.
            submission["idempotency_key"] = spec["batch_id"] + "." + task["task_id"]
            submission["batch_id"] = spec["batch_id"]
            submission["task_id"] = task["task_id"]
            submission["batch_task_count"] = len(spec["tasks"])
            accepted = client.request("/api/cluster/jobs", submission)
            item["job_id"] = accepted["job_id"]
            save(path, state)
        row = client.request("/api/cluster/jobs/" + quote(item["job_id"]))
        item.update(state=row["state"], error=row.get("error"), worker_id=row.get("worker_id"))
        if row["state"] in terminal and row.get("result"):
            expected = row["result"].get("archive_sha256")
            if expected and item.get("collected_sha256") != expected:
                target = path.parent / (item["job_id"] + ".zip")
                client.download(item["job_id"], target, expected)
                item.update(collected_sha256=expected, artifacts=target.name)
        save(path, state)
    values = list(state["tasks"].values())
    summary = {"total": len(values), "completed": sum(v.get("state") == "COMPLETED" for v in values),
               "failed": sum(v.get("state") in terminal - {"COMPLETED"} for v in values),
               "unresolved": sum(v.get("state") not in terminal for v in values),
               "collected": sum(bool(v.get("collected_sha256")) for v in values)}
    summary["failure_fraction_of_declared_tasks"] = summary["failed"] / summary["total"]
    summary["excluded_tasks"] = 0
    state["summary"] = summary
    save(path, state)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "run", "status"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--allow-formal", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 60:
        parser.error("poll-seconds must be in [1, 60]")
    spec = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    validate_batch(spec, allow_formal=args.allow_formal)
    client = Client(spec["controller_url"])
    args.state_dir.mkdir(parents=True, exist_ok=True)
    path = args.state_dir / "batch-state.json"
    if args.command == "check":
        print(json.dumps({"valid": True, "tasks": len(spec["tasks"]), "batch_sha256": digest(canonical(spec))}))
        return 0
    lock = ControllerLock(args.state_dir)
    try:
        state = load_state(spec, path)
        if args.command == "status":
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        failures = 0
        while True:
            try:
                summary = advance(spec, state, path, client)
                failures = 0
                state.pop("connection", None)
                save(path, state)
            except (URLError, TimeoutError, ConnectionError) as exc:
                if isinstance(exc, HTTPError) and exc.code not in {502, 503, 504}:
                    # Preserve refusal across CLI restarts without persisting
                    # arbitrary response bodies that could contain credentials.
                    state["connection"] = sanitized_rejection(exc)
                    save(path, state)
                    print(json.dumps(state["connection"]), flush=True)
                    return 1
                failures += 1
                delay = min(120, 5 * 2 ** min(failures - 1, 5))
                state["connection"] = {"status": "RECONNECTING", "retry_seconds": delay}
                save(path, state)
                print(json.dumps(state["connection"]), flush=True)
                if args.once:
                    return 2
                time.sleep(delay)
                continue
            print(json.dumps(summary), flush=True)
            if summary["unresolved"] == 0:
                return 0 if summary["failed"] == 0 else 1
            if args.once:
                return 2
            time.sleep(args.poll_seconds)
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
