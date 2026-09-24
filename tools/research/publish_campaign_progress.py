"""Publish a read-only monthly campaign snapshot for the local frontend.

The publisher never starts Prepare, a solver, SSH, or an AI service. It reads
the durable campaign records and atomically replaces one static JSON file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4


SCHEMA = "monthly_campaign_progress_v1"
SOLVED = {"COMPLETED"}
FAILURES = {"FAILED", "BLOCKED", "BLOCKED_PREPARE", "CANCELLED", "AUDIT_FAILED"}
LABELS = {
    "NOT_STARTED": "未着手", "DUPLICATED": "入力を準備中", "PAUSED": "準備を中断・待機中",
    "PREPARED": "入力準備済み", "QUEUED": "配布待ち", "STAGING": "配布中",
    "RUNNING": "計算中", "LOST": "状態不明・照合待ち", "COLLECTING": "成果物を回収中",
    "COMPLETED": "計算完了・監査待ち", "VERIFIED": "成果物監査済み",
    "FAILED": "エラー", "BLOCKED": "停止", "BLOCKED_PREPARE": "入力準備エラー",
    "CANCELLED": "取消済み", "AUDIT_FAILED": "成果物監査エラー",
}


def _read_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def _safe_message(value: object) -> str | None:
    if value is None:
        return None
    message = " ".join(str(value).split())
    message = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)\b(password|token|secret|credential|api[-_ ]?key|wls[-_ ]?key)\b\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]", message,
    )
    return message[:360] or None


def _tail(path: Path, count: int = 8) -> list[str]:
    if not path.is_file():
        return []
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 16_384))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    return [line for line in (_safe_message(value) for value in lines[-count:]) if line]


def _prepare_running(campaign: Path) -> bool | None:
    launch = _read_object(campaign / "prepare_launch.json")
    pid = launch.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    # Win32_Process is a read-only query. Never use os.kill(pid, 0) on Windows.
    command = (
        "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = " + str(pid) + "'; "
        "if ($p) { $p.CommandLine }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    line = result.stdout.lower()
    return ("shibu24_monthly.py" in line and "prepare" in line and
            campaign.name.lower() in line)


def _percent(done: int, total: int) -> int:
    return round(done * 100 / total) if total else 0


def snapshot(campaign: Path, *, prepare_running: bool | None = None) -> dict:
    """Derive percentages only from completed declared work units."""
    binding = _read_object(campaign / "binding.json")
    weeks = binding.get("weeks")
    if (not isinstance(weeks, list) or not weeks or
            any(not isinstance(week, str) or
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week) for week in weeks) or
            len(weeks) != len(set(weeks))):
        raise ValueError("Campaign binding has no valid distinct service weeks")
    if prepare_running is None:
        prepare_running = _prepare_running(campaign)
    summary = _read_object(campaign / "summary.json")
    campaign_state = _read_object(campaign / "campaign-state.json")
    batch = _read_object(campaign / "batch-state" / "batch-state.json")
    audit = _read_object(campaign / "artifact-audit.json")
    tasks = batch.get("tasks") or {}
    if not isinstance(tasks, dict):
        raise ValueError("Batch task state must be an object")
    audit_rows = {row.get("task_id"): row for row in audit.get("tasks", [])
                  if isinstance(row, dict)}
    rows = []
    for week in weeks:
        prepared = _read_object(campaign / week / "state.json")
        task = tasks.get("month-" + week[:7]) or {}
        evidence = audit_rows.get("month-" + week[:7]) or {}
        if not isinstance(task, dict):
            raise ValueError("A batch task has invalid state")
        # A previous audit of the same task label is not evidence for a new attempt.
        if not task.get("job_id") or evidence.get("job_id") != task.get("job_id"):
            evidence = {}
        prep_state = prepared.get("status") or "NOT_STARTED"
        state = task.get("state") or prep_state
        if evidence.get("collection_verified") is True:
            state = "VERIFIED"
        elif state == "COMPLETED" and evidence and evidence.get("collection_verified") is False:
            state = "AUDIT_FAILED"
        elif prep_state == "DUPLICATED" and prepare_running is False:
            state = "PAUSED"
        audit_error = evidence.get("error") if state == "AUDIT_FAILED" else None
        error = _safe_message(audit_error or task.get("error") or prepared.get("error"))
        rows.append({
            "week": week, "status": state, "status_label": LABELS.get(state, "要確認"),
            "prepared": prep_state == "PREPARED", "strict_scope_audit_passed":
            prepared.get("strict_scope_audit_passed") is True,
            "prepared_input_id": prepared.get("prepared_input_id"),
            "prepared_input_sha256": prepared.get("prepared_input_sha256"),
            "scenario_id": prepared.get("scenario_id"),
            "job_id": task.get("job_id"), "worker_id": task.get("worker_id"),
            "collected_sha256": task.get("collected_sha256"),
            "audit_verified": evidence.get("collection_verified") is True,
            "error_code": prepared.get("error_code"), "error": error,
            "warning_codes": list(prepared.get("strict_scope_warning_codes") or []),
            "overnight": prepared.get("overnight"),
        })
    total = len(rows)
    prepared_count = sum(row["prepared"] for row in rows)
    solved_count = sum(row["status"] in SOLVED | {"AUDIT_FAILED"} or row["audit_verified"]
                       for row in rows)
    audited_count = sum(row["audit_verified"] for row in rows)
    failed_count = sum(row["status"] in FAILURES for row in rows)
    overall_done = prepared_count + solved_count + audited_count
    overall_total = total * 3
    if campaign_state.get("status") == "FAILED" or failed_count:
        status = "ERROR"
    elif audited_count == total and total and campaign_state.get("status") == "COLLECTED_DIAGNOSTIC":
        status = "COMPLETED_DIAGNOSTIC"
    elif prepare_running or any(row["status"] in {"QUEUED", "STAGING", "RUNNING", "COLLECTING"} for row in rows):
        status = "RUNNING"
    elif prepared_count or tasks:
        status = "WAITING"
    else:
        status = "NOT_STARTED"
    return {
        "schema_version": SCHEMA, "campaign": campaign.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": binding.get("git_sha"), "status": status,
        "prepare_process": "RUNNING" if prepare_running else
        "STOPPED" if prepare_running is False else "UNKNOWN",
        "preparation_complete": bool(summary.get("all_prepared")) and prepared_count == total,
        "stages": {
            "overall": {"completed": overall_done, "total": overall_total,
                        "percent": _percent(overall_done, overall_total)},
            "prepare": {"completed": prepared_count, "total": total,
                        "percent": _percent(prepared_count, total)},
            "solve": {"completed": solved_count, "total": total,
                      "percent": _percent(solved_count, total)},
            "audit": {"completed": audited_count, "total": total,
                      "percent": _percent(audited_count, total)},
        },
        "campaign_stage": campaign_state.get("stage") or campaign_state.get("status"),
        "campaign_error": _safe_message(campaign_state.get("error") or
                                        (batch.get("connection") or {}).get("detail")),
        "connection_status": (batch.get("connection") or {}).get("status"),
        "failed_count": failed_count, "weeks": rows,
        "recent_log": _tail(campaign / "prepare.log", 5),
        "recent_errors": _tail(campaign / "prepare.err.log", 5),
        "research_status": "DIAGNOSTIC_NOT_RESEARCH_APPROVED",
    }


def publish(campaign: Path, output: Path) -> dict:
    payload = snapshot(campaign)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=5)
    args = parser.parse_args()
    if not 2 <= args.interval_seconds <= 60:
        parser.error("--interval-seconds must be within [2, 60]")
    while True:
        try:
            progress = publish(args.campaign.resolve(), args.output.resolve())
            print(json.dumps({"status": progress["status"],
                              "prepared": progress["stages"]["prepare"]["completed"],
                              "total": progress["stages"]["prepare"]["total"]}), flush=True)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Progress publication failed: {type(exc).__name__}: {_safe_message(exc)}", flush=True)
            if not args.watch:
                raise
        if not args.watch:
            return
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
