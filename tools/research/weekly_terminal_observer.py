"""Watch a weekly campaign locally; queue one terminal email handoff only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bff.services.cluster.runner import process_identity
from bff.services.cluster.store import ControllerLock
from tools.research.weekly_results import read, sha, write_json


def terminal(directory: Path, launch: dict) -> tuple[str, dict] | None:
    path = directory / "state.json"
    state = read(path) if path.exists() else {}
    if state.get("status") in {"COMPLETED", "PARTIAL_OR_FAILED"}:
        return state["status"], state
    identity = process_identity(int(launch["pid"]))
    if identity != "unknown" and identity != launch["process_identity"]:
        return "PROCESS_STOPPED", state
    return None


def notify_once(directory: Path, launch: dict, outcome: tuple[str, dict], thread: str, codex: Path) -> None:
    output = directory / "terminal_observer"
    if (output / "event.json").exists() or (output / "email_receipt.json").exists():
        return
    status, state = outcome
    subject = f"[master-course] 渋21〜23 四季の週次計算 {status} {launch['git_sha'][:8]}"
    body = (f"渋21〜23の週次計算: {status}\n固定SHA: {launch['git_sha']}\n"
            f"状態と成果物: {directory}\n" + json.dumps(state.get("cases", {}), ensure_ascii=False, indent=2) +
            "\n旧12週の再集計と新しい翌朝SOC条件は別成果です。統合最適性や正式研究採用を意味しません。\n")
    payload = output / "email_payload.json"
    write_json(payload, {"to": "g2681320@tcu.ac.jp", "subject": subject, "body": body})
    event = {"status": "QUEUE_ATTEMPTED", "terminal_status": status, "git_sha": launch["git_sha"],
             "payload_sha256": sha(payload), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(output / "event.json", event)
    message = (f"渋21〜23週次季節計算の{status}イベントです。通常監視ではAIを呼ばず一度だけ通知しています。"
               f"{output / 'event.json'} と {payload}、{directory / 'state.json'} を照合し、"
               "承認済みg2681320@tcu.ac.jpへGmailで1通だけ通知してください。送信済み検索とemail_receipt.jsonで"
               "重複を防ぎ、実message IDを保存してください。未完了を完了とせず、新規投入・再起動は行わないでください。")
    result = subprocess.run([str(codex), "queue", "--thread", thread, "--message", message],
                            capture_output=True, text=True, timeout=60, check=False)
    event.update(status="QUEUED" if result.returncode == 0 else "QUEUE_FAILED", returncode=result.returncode)
    write_json(output / "event.json", event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--codex", type=Path, required=True)
    args = parser.parse_args()
    launch = read(args.launch)
    output = args.campaign / "terminal_observer"
    output.mkdir(parents=True, exist_ok=True)
    lock = ControllerLock(output)
    try:
        while True:
            outcome = terminal(args.campaign, launch)
            if outcome:
                notify_once(args.campaign, launch, outcome, args.thread, args.codex)
                return
            time.sleep(30)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
