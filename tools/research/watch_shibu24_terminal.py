"""Wake the existing Codex task once when a frozen staged campaign ends.

The watcher only reads campaign evidence and queues one terminal event. Gmail
delivery is performed by the connected task after checking Sent and a receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.runner import process_identity
from bff.services.cluster.store import ControllerLock, display_text


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def terminal(config: dict) -> tuple[str, str] | None:
    campaign = Path(config["campaign"])
    binding_path = campaign / "binding.json"
    state_path = campaign / "stage-state.json"
    if not binding_path.is_file() or not state_path.is_file():
        return None
    if read(binding_path).get("git_sha") != config["git_sha"]:
        return "FAILURE", "campaign binding does not match the frozen source SHA"
    state = read(state_path)
    stages = state.get("stages") or {}
    if stages.get("months") == "PASSED":
        audit_path = campaign / "twelve-month-audit.json"
        if not audit_path.is_file():
            return "FAILURE", "twelve-month audit is missing after a PASSED marker"
        audit = read(audit_path)
        rows = audit.get("months") or []
        if (audit.get("source_git_sha") != config["git_sha"] or len(rows) != 12
                or len({row.get("task_id") for row in rows}) != 12
                or any(not row.get("collection_verified") or
                       not row.get("physical_feasibility_claim_eligible") for row in rows)):
            return "FAILURE", "twelve-month audit does not certify all 12 collected physical results"
        return "COMPLETED", "12 of 12 weeks collected and independently physically audited"
    if state.get("failure"):
        failure = state["failure"]
        return "FAILURE", display_text(failure.get("message") or failure.get("type"), 300)
    if any(value in {"FAILED", "STATE_UNKNOWN"} for value in stages.values()):
        return "FAILURE", "campaign is failed or the same attempt needs reconciliation"
    return None


def payload(config: dict, status: str, reason: str) -> dict:
    subject = f"[master-course] 渋24段階試験 {status} {config['git_sha'][:8]}"
    campaign = Path(config["campaign"])
    body = (f"渋24の1日→7日→月別12週の段階試験: {status}\n"
            f"固定ソースSHA: {config['git_sha']}\n"
            f"状態: {reason}\n"
            f"確認先: {campaign / 'stage-state.json'}\n"
            "これは技術的な実行通知です。研究採用や統合総費用の最適性の承認ではありません。\n")
    return {"to": config["recipient"], "subject": subject, "body": body}


def dispatch(config: dict, status: str, reason: str) -> dict:
    output = Path(config["output"])
    event_path = output / "event.json"
    if event_path.exists():
        return read(event_path)  # PENDING or QUEUED: never retry an uncertain dispatch.
    email = payload(config, status, reason)
    write(output / "email_payload.json", email)
    event = {"status": "PENDING", "terminal_status": status,
             "reason": reason, "git_sha": config["git_sha"],
             "payload_sha256": hashlib.sha256(
                 json.dumps(email, ensure_ascii=False, sort_keys=True).encode("utf-8")
             ).hexdigest(),
             "recorded_at": datetime.now(timezone.utc).isoformat()}
    write(event_path, event)
    message = (f"渋24段階試験の{status}イベントです。これは通常監視ではなく一度だけの通知です。"
               f"{event_path}と{output / 'email_payload.json'}を確認し、固定SHAと12週監査または"
               "失敗状態を照合してください。承認済みの宛先へGmailで1通だけ通知し、"
               "送信済み検索とemail_receipt.jsonで重複を防ぎ、実message IDを保存してください。"
               "既存計算の再起動や新規ジョブ投入は行わないでください。")
    try:
        command = [config["codex_exe"], "queue", "--thread", config["thread_id"],
                   "--message", message]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                   check=False)
        if completed.returncode:
            event["status"] = "DISPATCH_FAILED"
            event["dispatch_exit_code"] = completed.returncode
        else:
            event["status"] = "QUEUED"
            event["queue_response"] = display_text(completed.stdout, 300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        event["status"] = "DISPATCH_UNCERTAIN"
        event["dispatch_error_type"] = type(exc).__name__
    write(event_path, event)
    return event


def watch(config: dict, *, once: bool = False) -> dict:
    output = Path(config["output"])
    lock = ControllerLock(output)
    try:
        while True:
            if (output / "event.json").is_file():
                return read(output / "event.json")
            try:
                event = terminal(config)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                event = ("FAILURE", f"campaign status cannot be verified: {type(exc).__name__}")
            if event is None:
                identity = process_identity(int(config["campaign_pid"]))
                if identity is None or (identity != "unknown" and identity != config["campaign_identity"]):
                    event = ("FAILURE", "campaign process exited without a terminal state")
            if event is not None:
                return dispatch(config, *event)
            if once:
                return {"status": "RUNNING", "mail_requested": False}
            time.sleep(int(config.get("poll_seconds", 30)))
    finally:
        lock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Read status once without queueing")
    args = parser.parse_args()
    config = read(args.config.resolve())
    if args.check:
        result = {"terminal": terminal(config),
                  "campaign_identity": process_identity(int(config["campaign_pid"])),
                  "expected_identity": config["campaign_identity"],
                  "event_exists": (Path(config["output"]) / "event.json").exists()}
    else:
        result = watch(config)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
