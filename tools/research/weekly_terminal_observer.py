"""Watch a weekly campaign locally; queue one terminal email handoff only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen

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


def notify_once(directory: Path, launch: dict, outcome: tuple[str, dict], thread: str, codex: Path,
                *, repair_on_failure: bool = False) -> None:
    output = directory / "terminal_observer"
    if (output / "event.json").exists() or (output / "email_receipt.json").exists():
        return
    status, state = outcome
    subject = f"[master-course] 渋21〜23 月別代表週の計算 {status} {launch['git_sha'][:8]}"
    body = (f"渋21〜23の週次計算: {status}\n固定SHA: {launch['git_sha']}\n"
            f"状態と成果物: {directory}\n" + json.dumps(state.get("cases", {}), ensure_ascii=False, indent=2) +
            "\n旧12週の再集計と新しい翌朝SOC条件は別成果です。統合最適性や正式研究採用を意味しません。\n")
    payload = output / "email_payload.json"
    write_json(payload, {"to": "g2681320@tcu.ac.jp", "subject": subject, "body": body})
    event = {"status": "QUEUE_ATTEMPTED", "terminal_status": status, "git_sha": launch["git_sha"],
             "payload_sha256": sha(payload), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(output / "event.json", event)
    next_action = ("失敗原因を原本から特定し、ユーザー承認済みの修正・検証・新しい固定版での再実行を進めてください。"
                   "旧試行の終了を確認するまで二重投入せず、実行中ソースと物理条件を変更しないでください。"
                   if repair_on_failure and status != "COMPLETED" else "新規投入・再起動は行わないでください。")
    message = (f"渋21〜23週次季節計算の{status}イベントです。通常監視ではAIを呼ばず一度だけ通知しています。"
               f"{output / 'event.json'} と {payload}、{directory / 'state.json'} を照合し、"
               "承認済みg2681320@tcu.ac.jpへGmailで1通だけ通知してください。送信済み検索とemail_receipt.jsonで"
               "重複を防ぎ、実message IDを保存してください。未完了を完了とせず、" + next_action)
    result = subprocess.run([str(codex), "queue", "--thread", thread, "--message", message],
                            capture_output=True, text=True, timeout=60, check=False)
    event.update(status="QUEUED" if result.returncode == 0 else "QUEUE_FAILED", returncode=result.returncode)
    write_json(output / "event.json", event)


def memory_pressure(previous: dict, worker: dict, floor: float) -> dict:
    """Count distinct fresh samples, not repeated reads of cached telemetry."""
    observed = worker.get("last_probe_at")
    capability = worker.get("capability") or {}
    values = [capability.get(key) for key in ("ram_free_gb", "commit_available_gb")]
    known = (observed and worker.get("metrics_stale") is False
             and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values))
    if known and observed == previous.get("last_probe_at"):
        return previous
    low = bool(known and min(values) < floor)
    count = previous.get("consecutive_low", 0) + 1 if low else 0
    return {"last_probe_at": observed, "consecutive_low": count,
            "status": "PRESSURE" if count >= 3 else "LOW" if low else "OK" if known else "UNKNOWN",
            "ram_free_gb": values[0], "commit_available_gb": values[1], "floor_gb": floor}


def check_memory(directory: Path, controller: str, worker_id: str, thread: str, codex: Path) -> None:
    output = directory / "terminal_observer"
    event_path = output / "memory_pressure_event.json"
    if event_path.exists():
        return
    state_path = output / "memory_guard.json"
    previous = read(state_path) if state_path.exists() else {}
    try:
        with urlopen(controller.rstrip("/") + "/api/cluster/workers/" + worker_id, timeout=10) as response:
            worker = json.load(response)
    except (OSError, ValueError):
        write_json(state_path, {"status": "UNKNOWN", "consecutive_low": 0})
        return
    state = memory_pressure(previous, worker, 4.0)
    write_json(state_path, state)
    if state["status"] != "PRESSURE":
        return
    event = {"status": "QUEUE_ATTEMPTED", "worker_id": worker_id, "memory": state}
    write_json(event_path, event)
    message = (f"週次計算のメモリ余裕が3回の新しい計測で4GiB未満です。{event_path} と {directory / 'state.json'} "
               "を確認してください。通常監視はスクリプトです。現在の同じattemptとPCの実メモリ/ログを照合し、"
               "必要な対処を行ってください。未知状態の二重投入・ライセンス誤解放・実行中コードの変更はしないでください。"
               "空き容量だけで計算失敗と扱わず、この警告だけではメール送信しないでください。")
    try:
        result = subprocess.run([str(codex), "queue", "--thread", thread, "--message", message],
                                capture_output=True, timeout=60, check=False)
        event.update(status="QUEUED" if result.returncode == 0 else "QUEUE_FAILED", returncode=result.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        event.update(status="QUEUE_UNCONFIRMED", error_type=type(exc).__name__)
    write_json(event_path, event)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--repair-on-failure", action="store_true", help="Include authorized repair/retry instruction in terminal handoff")
    parser.add_argument("--controller", help="Optional loopback controller for memory warning")
    parser.add_argument("--worker", help="Worker whose fresh memory samples are checked")
    args = parser.parse_args()
    if bool(args.controller) != bool(args.worker):
        parser.error("--controller and --worker must be supplied together")
    if args.controller:
        from bff.services.cluster.contracts import segment
        url = urlparse(args.controller)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.username or url.password:
            parser.error("Controller must be an unauthenticated loopback HTTP URL")
        segment(args.worker)
    launch = read(args.launch)
    output = args.campaign / "terminal_observer"
    output.mkdir(parents=True, exist_ok=True)
    lock = ControllerLock(output)
    try:
        while True:
            outcome = terminal(args.campaign, launch)
            if outcome:
                notify_once(args.campaign, launch, outcome, args.thread, args.codex,
                            repair_on_failure=args.repair_on_failure)
                return
            if args.controller:
                check_memory(args.campaign, args.controller, args.worker, args.thread, args.codex)
            time.sleep(30)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
