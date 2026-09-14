"""Wait locally for the bounded November diagnosis, then wake the existing task once."""
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("C:/master-course")
sys.path.insert(0, str(ROOT))
from scripts.watch_monthly_campaign import observer_lock, read_json, solver_is_alive, write_json, now

BASE = ROOT / "output/monthly_fair_weeks_20260914"
RECEIPT = BASE / "november_diagnosis_dispatch_20260915.json"
CONFIG = BASE / "november_diagnosis_notification_20260915.json"


def main() -> None:
    config = read_json(CONFIG)
    with observer_lock(BASE / "november_diagnosis_notification.lock"):
        if RECEIPT.exists():
            print("Dispatch already attempted; inspect receipt rather than sending twice.")
            return
        while solver_is_alive(config["pid"], config["started_at_utc"]):
            time.sleep(60)
        summary_path = BASE / "november_budget_diagnosis_20260915/summary.json"
        summary = read_json(summary_path) if summary_path.exists() else {}
        success = (summary.get("identical_native_model_sha256") is True
                   and summary.get("replay_feasible") is True and summary.get("physical_accepted") is True)
        message = (
            "11月の充電求解時間診断が終了しました。これは月別12週の完了ではなく、メールは送らないでください。"
            f"診断の物理通過フラグは{success}です。"
            "C:/master-course/output/monthly_fair_weeks_20260914/november_budget_diagnosis_20260915/summary.json、"
            "failed_assignment_comparison.json、同名.log末尾を確認してください。"
            "固定fa0c22bfの1〜10月が監査済み、11月day-aheadは120秒no-incumbent、12月未実行で停止しています。"
            "診断では既存の失敗割当とvehicle/trip順序を照合し、同一MPSで120秒と600秒を比較しました。"
            "結果に応じて公平な全月共通条件の修正を判断し、必要なら新しいclean固定版から全12週を新規実行してください。"
            "旧版の成功10週と新条件の週を混ぜず、実行中の固定コードを変更しないでください。"
            "ユーザーはトークン節約のためスクリプト実行と完了時だけの通知を指定しています。"
        )
        write_json(RECEIPT, {"status": "ATTEMPTING", "attempted_at_utc": now(),
                            "diagnostic_physical_passed": success})
        result = subprocess.run([config["codex"], "queue", "--thread", config["thread_id"], "--message", message],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or "Queued message " not in result.stdout:
            raise RuntimeError(f"Queue acknowledgement uncertain: {result.stderr[-1000:]}")
        write_json(RECEIPT, {"status": "QUEUED", "queued_at_utc": now(), "receipt": result.stdout.strip(),
                            "diagnostic_physical_passed": success})


if __name__ == "__main__":
    main()
