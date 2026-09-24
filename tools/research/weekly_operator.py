"""Human-operated weekly campaigns: inspect, resume, collect; no AI calls.

The operator is separate from the immutable computation release. Recovery keeps
the existing batch/attempt identities. Collection has no job-submission API.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from email.message import EmailMessage
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import ClusterConfig, canonical, digest, segment
from bff.services.cluster.resource_policy import resource_fit
from bff.services.cluster.store import ControllerLock
from tools.cluster.batch import Client, load_state, save, validate_batch
from tools.cluster.audit_batch import audit_batch
from tools.cluster.atomic_file import replace_bytes
from tools.research.weekly_collection import collect_week
from tools.research.weekly_results import read, sha, write_json

TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}


def load_operation(path: Path) -> tuple[dict, dict, Path]:
    operation = read(path)
    settings = read(Path(operation["settings"]))
    campaign = Path(operation["campaign"]).resolve()
    if settings["git_sha"] != operation["git_sha"]:
        raise ValueError("Operator and controller SHA differ")
    weeks = operation["weeks"]
    if not weeks or len(set(weeks)) != len(weeks):
        raise ValueError("Declare unique, nonempty weeks")
    if any(date.fromisoformat(w).isoformat() != w for w in weeks):
        raise ValueError("Weeks must use YYYY-MM-DD")
    if not operation["workers"] or not operation["parent"]:
        raise ValueError("Explicit parent scenario and workers are required")
    binding_path = campaign / "binding.json"
    if binding_path.exists():
        binding = read(binding_path)
        for key in ("parent", "weeks", "workers"):
            if binding[key] != operation[key]:
                raise ValueError("Frozen campaign differs: " + key)
        if binding["git"] != {"sha": operation["git_sha"], "dirty": False}:
            raise ValueError("Frozen campaign Git binding differs")
    return operation, settings, campaign


def busy(directory: Path) -> bool:
    """Use the OS lock, never infer process liveness from a saved PID."""
    try:
        lock = ControllerLock(directory)
    except RuntimeError:
        return True
    lock.close()
    return False


def snapshot(operation: dict, settings: dict, campaign: Path, client=None) -> dict:
    client = client or Client(f"http://127.0.0.1:{settings['port']}")
    connection = "CONNECTED"
    try:
        jobs = client.request("/api/cluster/jobs")
        fleet = client.request("/api/cluster/workers")
    except (OSError, ValueError):
        # A broken connection is not a failed or absent computation.
        jobs, fleet, connection = [], {}, "CONNECTION_UNKNOWN"
    jobs_by_id = {j["id"]: j for j in jobs}
    config = ClusterConfig.model_validate(read(Path(settings["config"])))
    worker_views = {w["id"]: w for w in fleet.get("workers", [])}
    cases = []
    recorded = read(campaign / "state.json") if (campaign / "state.json").exists() else {}
    recovery_path = campaign / "operations/collection.json"
    recovered = read(recovery_path).get("cases", {}) if recovery_path.exists() else {}
    for week in operation["weeks"]:
        directory = campaign / week
        path = directory / "state/batch-state.json"
        saved = read(path).get("tasks", {}).get(week, {}) if path.exists() else {}
        row = jobs_by_id.get(saved.get("job_id"))
        state = row["state"] if row else "STATE_UNKNOWN" if saved.get("job_id") else recorded.get("cases", {}).get(week, {}).get("state", "NOT_PREPARED")
        item = {"week": week, "state": state, "last_recorded_state": saved.get("state"),
                "job_id": saved.get("job_id"), "worker": (row or saved).get("worker_id"),
                "prepared": (directory / "prepared.json").exists(),
                "error": (row or saved).get("error") or recorded.get("cases", {}).get(week, {}).get("error"),
                "directory": str(directory), "placement": []}
        if row and state == "QUEUED":
            manifest = row["manifest"]
            for worker in config.workers:
                if manifest.get("worker_id") not in (None, worker.id):
                    continue
                view = worker_views.get(worker.id, {})
                fit = resource_fit(worker, view.get("capability") or {}, manifest, jobs)
                item["placement"].append({"worker": worker.id, "readiness": view.get("status", "UNKNOWN"),
                    "readiness_reasons": view.get("readiness_reasons", []), **fit})
        summary = directory / "results/weekly_summary.json"
        # An output file alone is not proof that its producing audit finished.
        recovered_case = recovered.get(week, {})
        recovery_verified = recovered_case.get("state") == "VERIFIED" and recovered_case.get("job_id") == item["job_id"]
        item["verified"] = (recorded.get("cases", {}).get(week, {}).get("state") == "VERIFIED" or recovery_verified) and summary.exists()
        cases.append(item)
    total = len(cases)
    return {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "connection": connection,
        "solver_git_sha": operation["git_sha"], "cases": cases,
        "progress": {"prepared_percent": 100 * sum(c["prepared"] for c in cases) / total,
                     "completed_percent": 100 * sum(c["state"] == "COMPLETED" for c in cases) / total,
                     "verified_percent": 100 * sum(c["verified"] for c in cases) / total},
        "licenses": {k: fleet.get(k) for k in ("global_gurobi_slots", "external_gurobi_slots", "reserved_gurobi_slots", "cooling_gurobi_slots")},
        "scope": "Operational status, not optimality or research approval"}


def collect_existing(directory: Path, *, client=None) -> dict:
    """Only GET a known attempt and its archive; never call enqueue/retry."""
    spec = read(directory / "batch.json")
    validate_batch(spec)
    state_dir = directory / "state"
    path = state_dir / "batch-state.json"
    if not path.exists():
        return {"state": "NOT_SUBMITTED"}
    # The campaign owns collection while alive; callers hold its lock first.
    try:
        lock = ControllerLock(state_dir)
    except RuntimeError:
        return {"state": "CLIENT_ACTIVE"}
    try:
        state = load_state(spec, path)
        client = client or Client(spec["controller_url"])
        for task in spec["tasks"]:
            item = state["tasks"][task["task_id"]]
            if not item.get("job_id"):
                return {"state": "SUBMISSION_UNKNOWN", "action": "Resume the identical batch; do not create a new ID"}
            row = client.request("/api/cluster/jobs/" + segment(item["job_id"]))
            if row.get("id") != item["job_id"]:
                raise ValueError("Controller returned a different attempt")
            item.update(state=row["state"], worker_id=row.get("worker_id"), error=row.get("error"))
            save(path, state)
            if row["state"] not in TERMINAL:
                return {"state": row["state"], "job_id": item["job_id"]}
            receipt = row.get("result") or {}
            expected = receipt.get("archive_sha256")
            if expected:
                archive = state_dir / (item["job_id"] + ".zip")
                if not archive.exists() or sha(archive) != expected:
                    client.download(item["job_id"], archive, expected)
                item.update(artifacts=archive.name, collected_sha256=expected)
                save(path, state)
            if row["state"] != "COMPLETED":
                return {"state": row["state"], "job_id": item["job_id"], "error": row.get("error")}
        audit = audit_batch(spec, state, state_dir)
        write_json(directory / "operations/recovery-audit.json", audit)
        if audit["unverified"] or not all(t.get("physical_feasibility_claim_eligible") for t in audit["tasks"]):
            return {"state": "FAILED_OR_UNVERIFIED", "audit": str(directory / "operations/recovery-audit.json")}
        prepared = read(directory / "prepared.json")
        if sha(Path(prepared["prepared_path"])) != prepared["prepared_sha256"]:
            raise ValueError("Prepared source changed before recovery collection")
        item = state["tasks"][prepared["week"]]
        receipt_path = directory / "operations/recovery-receipt.json"
        binding = {"archive_sha256": item["collected_sha256"], "prepared_sha256": prepared["prepared_sha256"],
                   "collector_sha256": sha(Path(__file__).with_name("weekly_collection.py"))}
        if receipt_path.exists():
            receipt = read(receipt_path)
            if receipt.get("binding") == binding and all(
                    (directory / p).is_file() and sha(directory / p) == h for p, h in receipt.get("outputs", {}).items()
            ) and receipt.get("outputs"):
                return receipt["result"]
        result = collect_week(prepared, state["tasks"][prepared["week"]], directory, audit)
        outcome = {"state": "VERIFIED", "total_cost_jpy": result["total_cost"], "job_id": result["job_id"]}
        write_json(receipt_path, {"binding": binding, "result": outcome,
            "outputs": {p.relative_to(directory).as_posix(): sha(p) for p in (directory / "results").glob("*") if p.is_file()}})
        return outcome
    finally:
        lock.close()


def collect_campaign(operation: dict, campaign: Path) -> dict:
    lock = None
    try:
        lock = ControllerLock(campaign)
    except RuntimeError:
        # The immutable old campaign has removed these stopped clients from its
        # work list. Other cases remain exclusively owned by that live process.
        pass
    try:
        results = {}
        source = read(campaign / "state.json") if (campaign / "state.json").exists() else {}
        for week in operation["weeks"]:
            directory = campaign / week
            case = source.get("cases", {}).get(week, {})
            if lock is None and case.get("state") not in {"FAILED_OR_UNVERIFIED", "STATE_UNKNOWN"}:
                results[week] = {"state": "CLIENT_ACTIVE"}
                continue
            try:
                results[week] = collect_existing(directory) if (directory / "batch.json").exists() else {"state": "NOT_PREPARED"}
            except (OSError, ValueError, KeyError) as exc:
                results[week] = {"state": "STATE_UNKNOWN", "error_type": type(exc).__name__}
        states = [v["state"] for v in results.values()]
        status = "COMPLETED" if all(s == "VERIFIED" for s in states) else (
            "PARTIAL_OR_FAILED" if all(s in TERMINAL | {"VERIFIED", "FAILED_OR_UNVERIFIED"} for s in states) else "INCOMPLETE")
        result = {"status": status, "cases": results, "solver_git_sha": operation["git_sha"]}
        write_json(campaign / "operations/collection.json", result)
        return result
    finally:
        if lock is not None:
            lock.close()


def terminal_notice(operation: dict, campaign: Path, report: dict) -> str:
    """Create a stable, unsent email file; no OAuth token, Codex or AI dependency."""
    states = [c["state"] for c in report["cases"]]
    if report["connection"] != "CONNECTED" or any(s not in TERMINAL | {"PREPARE_OR_SUBMIT_FAILED"} for s in states):
        return "NOT_TERMINAL"
    source = read(campaign / "state.json") if (campaign / "state.json").exists() else {}
    recovery = campaign / "operations/collection.json"
    if source.get("status") not in {"COMPLETED", "PARTIAL_OR_FAILED"} and recovery.exists():
        source = read(recovery)
    if source.get("status") not in {"COMPLETED", "PARTIAL_OR_FAILED"}:
        return "AWAITING_COLLECTION"
    output = campaign / "operations"
    identity = digest(canonical({"git": operation["git_sha"], "jobs": [c["job_id"] for c in report["cases"]]}))
    record = output / "notification.json"
    if record.exists():
        if read(record)["identity"] != identity:
            raise ValueError("Terminal notification belongs to different attempts")
        return read(record)["status"]
    message = EmailMessage()
    message["To"] = "g2681320@tcu.ac.jp"
    message["Subject"] = f"[master-course] 週次計算 {source['status']} {operation['git_sha'][:8]}"
    message["Message-ID"] = f"<weekly-{identity}@master-course.local>"
    message.set_content(json.dumps(report, ensure_ascii=False, indent=2) + "\n正式研究採用・統合最適性とは別判定です。\n")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "terminal-notice.eml"
    target.write_bytes(bytes(message))
    write_json(record, {"identity": identity, "status": "PENDING_MANUAL_SEND", "mail_file": str(target),
        "sha256": sha(target), "reason": "Standalone mail authentication is not configured; no email has been sent"})
    return "PENDING_MANUAL_SEND"


def render_status(report: dict) -> str:
    labels = {"RUNNING": "実行中", "QUEUED": "投入待ち", "COMPLETED": "計算終了",
              "FAILED": "失敗", "BLOCKED": "事前検査停止", "LOST": "通信不明・同じ試行を照合中",
              "STATE_UNKNOWN": "現在状態を確認できない", "CANCELLED": "取消済み"}
    lines = ["# 週次計算の運転状況", "", f"取得時刻（UTC）: {report['observed_at_utc']}",
             f"通信: {report['connection']} / 計算固定版: {report['solver_git_sha']}", "",
             "完了率はケース数に対する割合です。求解時間の進み具合や最適性ではありません。", "",
             "| 入力準備 | 計算終了 | 検算・集計 |", "|---|---|---|",
             "| " + " | ".join(f"{report['progress'][k]:.1f}%" for k in ("prepared_percent", "completed_percent", "verified_percent")) + " |", "",
             "| 週の開始日 | 計算状態 | 検算・集計 | 担当・指定PC |", "|---|---|---|---|"]
    for case in report["cases"]:
        worker = case["worker"] or ", ".join(p["worker"] for p in case["placement"]) or "未確認"
        lines.append(f"| {case['week']} | {labels.get(case['state'], case['state'])} | {'通過' if case['verified'] else '未完了'} | {worker} |")
    lines.extend(["", "## 待機理由と確認先", ""])
    for case in report["cases"]:
        lines.append(f"- {case['week']}: attempt `{case['job_id'] or '未登録'}` / `{case['directory']}`")
        for placement in case["placement"]:
            lines.append(f"  - {placement['worker']}: {', '.join(placement['reasons'] + placement['readiness_reasons']) or '資源要件内。ライセンス枠・割当待ちを確認'} / 使用可能RAM {placement['available_ram_gb']} GB、要求 {placement['required_ram_gb']} GB")
        if case["error"]:
            lines.append("  - 記録理由: " + str(case["error"]).replace("\n", " "))
    lines.extend(["", "通信不明は計算失敗を意味しません。別PCへ新しい試行を投入せず、同じIDの照合を待ちます。",
                  "メール認証は未設定です。terminal-notice.eml は未送信の通知ファイルです。", ""])
    return "\n".join(lines)


# Fixed Python program; paths/data are argv, never interpolated shell code.
CAMPAIGN_PROGRAM = """import runpy,sys
sys.path.insert(0, sys.argv[1])
from tools.cluster.serve_controller import configure
from pathlib import Path
configure(Path(sys.argv[2]))
script = str(Path(sys.argv[1]) / 'tools/research/weekly_campaign.py')
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name='__main__')
"""


def resume_command(operation: dict, settings: dict, campaign: Path) -> list[str]:
    return [settings["python"], "-c", CAMPAIGN_PROGRAM, settings["release"], operation["settings"],
        "run", "--settings", operation["settings"], "--output", str(campaign),
        "--parent", operation["parent"], "--weeks", *operation["weeks"], "--workers", *operation["workers"]]


def execute(operation: dict, settings: dict, campaign: Path) -> dict:
    # Old releases spawn durable batch clients; do not race their state writers.
    if busy(campaign) or any(busy(campaign / w / "state") for w in operation["weeks"]):
        return {"status": "ALREADY_ACTIVE", "action": "Use status; collection continues under the existing owner"}
    # A powered-off controller must not leave a newly started campaign silently
    # preparing everything and then waiting forever for its API.
    Client(f"http://127.0.0.1:{settings['port']}").request("/api/cluster/workers")
    command = resume_command(operation, settings, campaign)
    result = subprocess.run(command, cwd=settings["release"], check=False)
    return {"status": "CAMPAIGN_EXITED", "returncode": result.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "controller", "status", "run", "collect", "watch"))
    parser.add_argument("--operation", type=Path, required=True)
    args = parser.parse_args()
    operation, settings, campaign = load_operation(args.operation)
    if args.command in {"check", "controller"}:
        if args.command == "controller":
            try:
                Client(f"http://127.0.0.1:{settings['port']}").request("/api/cluster/workers")
            except OSError:
                pass
            else:
                print(json.dumps({"status": "CONTROLLER_ALREADY_RESPONDING", "action": "Use status; no second controller started"}))
                return 0
        command = [settings["python"], str(Path(settings["release"]) / "tools/cluster/serve_controller.py"),
                   "--settings", operation["settings"]]
        return subprocess.run(command + (["--check"] if args.command == "check" else []),
                              cwd=settings["release"], check=False).returncode
    if args.command == "run":
        result = execute(operation, settings, campaign)
        print(json.dumps(result, ensure_ascii=False))
        return int(result.get("returncode", 0))
    if args.command == "collect":
        print(json.dumps(collect_campaign(operation, campaign), ensure_ascii=False, indent=2))
        return 0
    try:
        lock = ControllerLock(campaign / "operations")
    except RuntimeError:
        if args.command == "status":
            print(render_status(snapshot(operation, settings, campaign)))
            return 0
        raise
    try:
        while True:
            if args.command == "watch":
                collect_campaign(operation, campaign)
            report = snapshot(operation, settings, campaign)
            write_json(campaign / "operations/status.json", report)
            replace_bytes(campaign / "operations/STATUS.md", render_status(report).encode("utf-8"))
            notice = terminal_notice(operation, campaign, report)
            print(render_status(report) if args.command == "status" else json.dumps({
                "at": report["observed_at_utc"], "progress": report["progress"], "notification": notice}), flush=True)
            if args.command == "status" or notice == "PENDING_MANUAL_SEND":
                return 0
            time.sleep(30)
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
