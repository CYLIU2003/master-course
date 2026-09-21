"""Audit a running frozen campaign without model polling; queue one final delivery.

This observer never starts a solver or changes the frozen experiment. Gmail is
used by the existing Codex task after final review, not from this Python process.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_RELATIVE = Path("output/monthly_fair_weeks_20260914")


def deployment_paths(config: dict) -> tuple[Path, str, str]:
    version = config.get("deployment", "budget")
    require(version in {"budget", "search", "phase_search", "cyclic", "reserve", "auxiliary", "auxiliary_presolve", "auxiliary_logfix", "auxiliary_rolling", "auxiliary_session", "auxiliary_timeline", "auxiliary_numeric"}, "Unknown observer deployment")
    if version == "auxiliary_numeric":
        return (Path("output/monthly_auxiliary_numeric_20260922"),
                "SHIBU21_23_MONTHLY_AUXILIARY_NUMERIC_RESULTS_20260922", "shibu21_23_monthly_auxiliary_numeric_20260922")
    if version == "auxiliary_timeline":
        return (Path("output/monthly_auxiliary_timeline_20260922"),
                "SHIBU21_23_MONTHLY_AUXILIARY_TIMELINE_RESULTS_20260922", "shibu21_23_monthly_auxiliary_timeline_20260922")
    if version == "auxiliary_session":
        return (Path("output/monthly_auxiliary_session_20260922"),
                "SHIBU21_23_MONTHLY_AUXILIARY_SESSION_RESULTS_20260922", "shibu21_23_monthly_auxiliary_session_20260922")
    if version == "auxiliary_rolling":
        return (Path("output/monthly_auxiliary_rolling_20260921"),
                "SHIBU21_23_MONTHLY_AUXILIARY_ROLLING_RESULTS_20260921", "shibu21_23_monthly_auxiliary_rolling_20260921")
    if version == "auxiliary_logfix":
        return (Path("output/monthly_auxiliary_logfix_20260921"),
                "SHIBU21_23_MONTHLY_AUXILIARY_LOGFIX_RESULTS_20260921", "shibu21_23_monthly_auxiliary_logfix_20260921")
    if version == "auxiliary_presolve":
        return (Path("output/monthly_auxiliary_presolve_20260921"),
                "SHIBU21_23_MONTHLY_AUXILIARY_PRESOLVE_RESULTS_20260921", "shibu21_23_monthly_auxiliary_presolve_20260921")
    if version == "auxiliary":
        return (Path("output/monthly_auxiliary_20260921"),
                "SHIBU21_23_MONTHLY_AUXILIARY_RESULTS_20260921", "shibu21_23_monthly_auxiliary_20260921")
    if version == "reserve":
        return (Path("output/monthly_reserve_20260920"),
                "SHIBU21_23_MONTHLY_RESERVE_RESULTS_20260920", "shibu21_23_monthly_reserve_20260920")
    if version == "cyclic":
        return (Path("output/monthly_cyclic_20260919"),
                "SHIBU21_23_MONTHLY_CYCLIC_RESULTS_20260919", "shibu21_23_monthly_cyclic_20260919")
    if version == "phase_search":
        return (Path("output/monthly_phase_search_20260915"),
                "SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915", "shibu21_23_monthly_phase_search_20260915")
    if version == "search":
        return (Path("output/monthly_search_20260915"),
                "SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915", "shibu21_23_monthly_search_20260915")
    return DEPLOYMENT_RELATIVE, "SHIBU21_23_MONTHLY_BUDGET_RESULTS_20260914", "shibu21_23_monthly_20260914"


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_configuration(config: dict) -> None:
    """Keep all mutable paths in main, with a stable lock and authorized addressee."""
    root = ROOT.resolve()
    require(Path(config["root"]).resolve() == root, "Observer root must be the main checkout")
    relative, report_name, figure_name = deployment_paths(config)
    base = root / relative
    expected = {"output": base / "script_observer", "audit": base / "monthly_budget_independent_audit.json",
                "audit_script": base / "audit_budget_week.py", "checkpoint_script": base / "update_monthly_checkpoint.py",
                "report_script": root / "scripts/build_monthly_interpretation.py",
                "report_stem": root / "docs/notes" / report_name,
                "figure_stem": root / "docs/notes/figures" / figure_name,
                "python": root / ".venv/Scripts/python.exe"}
    for key, path in expected.items():
        require(Path(config[key]).resolve() == path.resolve(), f"Unexpected observer {key} path")
    campaign = Path(config["campaign"]).resolve()
    require(not campaign.is_relative_to(root) and not root.is_relative_to(campaign),
            "Frozen campaign and main must be separate")
    launch = read_json(base / "budget_rerun_launch.json")
    frozen = Path(launch["frozen_root"]).resolve()
    require(not root.is_relative_to(frozen) and not frozen.is_relative_to(root), "Frozen/main overlap")
    require(campaign == (frozen / launch["campaign_relative_path"]).resolve(), "Wrong frozen campaign")
    require(config["source_git_sha"] == launch["source_git_sha"], "Wrong configured source SHA")
    require(config["recipient"] == "g2681320@tcu.ac.jp", "Unauthorized recipient")
    require(config["thread_id"] == "01a0899e-638e-7c91-864e-2d4890de634a", "Wrong completion task")
    for helper in ("audit_script", "checkpoint_script", "report_script"):
        require(str(Path(config[helper])) in config["helper_hashes"], f"Unpinned helper: {helper}")


def bind_configuration(config: dict, *, read_only: bool) -> None:
    """Binding lives at a fixed main path so changing output cannot reset deduplication."""
    digest = config_hash(config)
    binding = ROOT / deployment_paths(config)[0] / "observer_binding.json"
    if binding.exists():
        require(read_json(binding).get("config_sha256") == digest, "Observer configuration changed")
    state_path = Path(config["output"]) / "state.json"
    if state_path.exists():
        require(read_json(state_path).get("config_sha256") == digest, "State has missing/different configuration identity")
    if not read_only and not binding.exists():
        write_json(binding, {"config_sha256": digest, "bound_at_utc": now()})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    # Campaign progress is written by another process, occasionally non-atomically.
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            if attempt == 4:
                raise
            time.sleep(0.2)
    raise RuntimeError("Unreachable JSON read state")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False, suffix=".tmp") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def observer_lock(path: Path):
    """The OS releases the lock after a crash; a stale file never blocks restart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def solver_is_alive(pid: int, started_at: str) -> bool:
    """Check Windows process identity, including birth time to reject PID reuse."""
    require(os.name == "nt", "This deployment requires Windows process identity checks")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no process with this PID
            return False
        raise ctypes.WinError(error)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != 259:  # STILL_ACTIVE
            return False
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        birth = ((times[0].dwHighDateTime << 32) + times[0].dwLowDateTime) / 1e7 - 11644473600
        return abs(birth - datetime.fromisoformat(started_at).timestamp()) < 2
    finally:
        kernel.CloseHandle(handle)


def validate_progress(progress: dict, config: dict, *, allow_stopped: bool = False) -> list[str]:
    weeks = config["selected_weeks"]
    require(len(weeks) == len(set(weeks)) == 12, "Exactly twelve unique declared weeks required")
    require(progress["base_git_sha"] == config["source_git_sha"], "Campaign source SHA changed")
    require(progress["selected_weeks"] == weeks, "Declared weeks changed")
    completed = progress["completed_weeks"]
    require(completed == weeks[:len(completed)], "Completed weeks are not a unique declared prefix")
    status = progress["status"]
    allowed = {"BUILDING_SOURCE_CANDIDATE", "RUNNING_WEEK", "PREPARING_WEEK", "COMPLETED"}
    if allow_stopped:
        allowed.add("STOPPED_AFTER_FAILED_CASE")
    require(status in allowed, f"Campaign stopped: {status}")
    require(status != "BUILDING_SOURCE_CANDIDATE" or not completed,
            "Source construction cannot contain completed weeks")
    require(status != "COMPLETED" or completed == weeks, "Completion without all twelve weeks")
    return completed


class Observer:
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["root"])
        self.output = Path(config["output"])
        self.campaign = Path(config["campaign"])
        self.audit = Path(config["audit"])
        self.report = Path(config["report_stem"])

    def check_helpers(self) -> None:
        for filename, expected in self.config["helper_hashes"].items():
            require(sha256(Path(filename)) == expected, f"Observer helper changed: {filename}")

    def run_python(self, script: str, *arguments: str) -> None:
        self.check_helpers()
        command = [self.config["python"], "-X", "utf8", script, *map(str, arguments)]
        with (self.output / "commands.log").open("a", encoding="utf-8") as log:
            log.write(f"\n{now()} {script} {arguments}\n")
            log.flush()
            subprocess.run(command, cwd=self.root, stdout=log, stderr=log, check=True,
                           timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def checkpoint(self, status: str, **details) -> None:
        write_json(self.output / "state.json", {"status": status, "checked_at_utc": now(),
                   "observer_pid": os.getpid(), "source_git_sha": self.config["source_git_sha"],
                   "config_sha256": config_hash(self.config), **details})

    def publish(self, *, complete: bool) -> None:
        arguments = ["--campaign", str(self.campaign), "--audit", str(self.audit),
                     "--output", str(self.report)]
        if self.config.get("deployment") in {"search", "phase_search", "cyclic", "reserve", "auxiliary", "auxiliary_presolve", "auxiliary_logfix", "auxiliary_rolling", "auxiliary_session", "auxiliary_timeline", "auxiliary_numeric"}:
            arguments.extend(["--figure-name", Path(self.config["figure_stem"]).name])
        if not complete:
            arguments.append("--partial")
        self.run_python(self.config["report_script"], *arguments)
        self.run_python(self.config["checkpoint_script"], "--dry-run")
        self.run_python(self.config["checkpoint_script"])

    def step(self) -> bool:
        self.check_helpers()
        progress = read_json(self.campaign / "progress.json")
        if self.config.get("deployment") in {"reserve", "auxiliary", "auxiliary_presolve", "auxiliary_logfix", "auxiliary_rolling", "auxiliary_session", "auxiliary_timeline", "auxiliary_numeric"} and progress["status"] == "STOPPED_AFTER_FAILED_CASE":
            self.publish_stopped(progress)
            raise ValueError("Campaign stopped: STOPPED_AFTER_FAILED_CASE (partial status recorded)")
        completed = validate_progress(progress, self.config)
        complete = progress["status"] == "COMPLETED"
        # Wait for the campaign finalizer before publishing month twelve.
        eligible = completed if complete or len(completed) < 12 else completed[:-1]
        audit = read_json(self.audit)
        require(audit["expected_sha"] == self.config["source_git_sha"], "Wrong independent audit SHA")
        require(set(audit["weeks"]) <= set(completed), "Audit contains an uncompleted week")
        if not eligible:
            require(solver_is_alive(self.config["solver_pid"], self.config["solver_started_at_utc"]),
                    "Solver exited before the first completed week")
            self.checkpoint("RUNNING", completed_weeks=[], independently_audited_weeks=0,
                            active_week=progress.get("active_week"), published_audit_sha256=sha256(self.audit))
            return False
        changed = False
        for week in eligible:
            record = audit["weeks"].get(week, {})
            if not (record.get("fully_audited") is True
                    and record.get("status") == "DIAGNOSTIC_EXECUTION_PASSED"
                    and record.get("audit_status") == "INDEPENDENTLY_AUDITED"):
                self.checkpoint("AUDITING_WEEK", week=week, completed_weeks=completed)
                self.run_python(self.config["audit_script"], "--week", week, "--audit-output", str(self.audit))
                changed = True
        audit = read_json(self.audit)
        if complete and audit["status"] != "COMPLETED":
            self.run_python(self.config["audit_script"], "--week", eligible[-1], "--audit-output", str(self.audit))
            changed = True
        report_path = self.report.with_suffix(".json")
        report = read_json(report_path) if report_path.exists() else {}
        stale = report.get("independent_audit", {}).get("sha256") != sha256(self.audit)
        state_path = self.output / "state.json"
        state = read_json(state_path) if state_path.exists() else {}
        unpublished = state.get("published_audit_sha256") != sha256(self.audit)
        if changed or stale or unpublished or (complete and report["status"] != "COMPLETED"):
            self.publish(complete=complete)
        if complete:
            self.prepare_delivery()
            self.checkpoint("AWAITING_FINAL_REVIEW_AND_EMAIL", completed_weeks=completed,
                            published_audit_sha256=sha256(self.audit))
            self.queue_once("completion")
            return True
        if not solver_is_alive(self.config["solver_pid"], self.config["solver_started_at_utc"]):
            # Final progress can race the process exit; observe once more before declaring failure.
            time.sleep(1)
            latest = read_json(self.campaign / "progress.json")
            require(latest["status"] == "COMPLETED", "Solver exited before campaign completion")
            return False
        self.checkpoint("RUNNING", completed_weeks=completed,
                        independently_audited_weeks=len(audit["weeks"]), active_week=progress.get("active_week"),
                        published_audit_sha256=sha256(self.audit))
        return False

    def publish_stopped(self, progress: dict) -> None:
        """Preserve failed cases and publish the stop before the one-shot alert."""
        completed = validate_progress(progress, self.config, allow_stopped=True)
        audit = read_json(self.audit)
        require(audit["expected_sha"] == self.config["source_git_sha"], "Wrong independent audit SHA")
        require(set(audit["weeks"]) <= set(completed), "Audit contains an uncompleted week")
        failed_cases = []
        for week in completed:
            case = self.campaign / "cases" / week / "diagnostic" / week
            summary_path = case / "summary.json"
            if not summary_path.exists():
                # Prepare can fail before any solve artifact exists. The case
                # summary/progress remains the failure source, never a pass.
                outer_path = self.campaign / "cases" / week / "summary.json"
                if outer_path.exists():
                    outer = read_json(outer_path)
                    failed_cases.append({"week": week, "status": outer.get("status"),
                        "reasons": outer.get("reasons") or [outer.get("error", "Prepare failed")],
                        "source_path": str(outer_path), "source_sha256": sha256(outer_path)})
                continue
            summary = read_json(summary_path)
            if summary["status"] == "DIAGNOSTIC_EXECUTION_PASSED":
                if not audit["weeks"].get(week, {}).get("fully_audited"):
                    self.run_python(self.config["audit_script"], "--week", week, "--audit-output", str(self.audit))
                    audit = read_json(self.audit)
                continue
            failed_cases.append({"week": week, "status": summary["status"],
                "reasons": summary.get("day_ahead_reasons") or summary.get("hourly_reasons")
                    or summary.get("reasons") or [],
                "source_path": str(summary_path), "source_sha256": sha256(summary_path)})
            audit["weeks"][week] = {
                "status": summary["status"], "audit_status": "FAILED_CASE_DIAGNOSTIC_ONLY",
                "failure": True, "fully_audited": False,
                "case_root": str(case), "hashes": {"case_summary": sha256(summary_path)},
            }
        audit["status"] = progress["status"]
        audit["observed_at_utc"] = now()
        write_json(self.audit, audit)
        passed = sum(row.get("fully_audited") is True for row in audit["weeks"].values())
        if passed:
            self.publish(complete=False)
        write_json(self.output / "stopped_campaign.json", {
            "status": progress["status"], "independently_audited_weeks": passed,
            "campaign_progress_sha256": sha256(self.campaign / "progress.json"),
            "audit_sha256": sha256(self.audit), "email_sent": False,
            "failed_cases": failed_cases,
        })

    def prepare_delivery(self) -> None:
        report = read_json(self.report.with_suffix(".json"))
        progress = read_json(self.campaign / "progress.json")
        validate_progress(progress, self.config)
        audit = read_json(self.audit)
        require(progress["status"] == report["status"] == audit["status"] == "COMPLETED", "Final status gate")
        require(report["completed_count"] == report["declared_week_count"] == len(report["weeks"]) == 12,
                "Incomplete final report")
        require([row["week"] for row in report["weeks"]] == self.config["selected_weeks"], "Report weeks differ")
        require(set(audit["weeks"]) == set(self.config["selected_weeks"]), "Missing weekly audit")
        require(len(report["seasons"]) == 4 and not report["pending_weeks"], "Missing seasonal report")
        require(report["source_git_sha"] == self.config["source_git_sha"] == audit["expected_sha"], "Final SHA gate")
        require(report["independent_audit"]["sha256"] == sha256(self.audit), "Final audit hash gate")
        require(report["research_status"] == "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS", "Claim scope changed")
        for row in audit["weeks"].values():
            require(row["fully_audited"] is True and row["audit_status"] == "INDEPENDENTLY_AUDITED"
                    and row["status"] == "DIAGNOSTIC_EXECUTION_PASSED", "Unaccepted weekly audit")
        artifacts = [self.report.with_suffix(suffix) for suffix in (".md", ".json")]
        artifacts += [Path(self.config["figure_stem"]).with_suffix(suffix) for suffix in (".png", ".svg")]
        for path in artifacts:
            require(path.is_file() and path.stat().st_size > 100, f"Missing artifact: {path}")
        from PIL import Image
        with Image.open(artifacts[2]) as picture:
            picture.verify()
        # This validates file integrity. Final visible chart QA remains a separate task.
        receipt = {"status": "READY_FOR_FINAL_REVIEW_AND_EMAIL", "prepared_at_utc": now(),
                   "source_git_sha": self.config["source_git_sha"], "completed_weeks": 12,
                   "research_acceptance": "BLOCKED", "to": self.config["recipient"],
                   "subject": self.config["email_subject"], "audit_sha256": sha256(self.audit),
                   "artifacts": [{"path": str(path), "sha256": sha256(path)} for path in artifacts],
                   "email_sent": False}
        write_json(self.output / "completion_bundle.json", receipt)
        sys.path.insert(0, str(self.root))
        from scripts.build_monthly_interpretation import observation_paragraphs
        body = ("月別12週（各週：平日5日・土曜1日・日曜1日）の計算、独立監査、季節別整理が完了しました。\n"
                "固定版: " + self.config["source_git_sha"] + "\n"
                "各週168時間・672 slot、物理検証と確定会計を照合済みです。\n\n"
                + "\n\n".join(observation_paragraphs(report))
                + "\n\n結果表・図・編集可能なSVG・数値JSONを添付します。\n\n"
                "位置付け：DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKED。"
                "Stage 1 gap未達、二段階解法、代理距離、2026年時刻表と2025年評価日、2024年climatology予測等の制約が残ります。"
                "気温・空調需要の季節変化は未入力で、月1週から季節一般・年平均・PV単独の因果を主張しません。"
                "各週のBESS終端条件と初期・終端の在庫増減も結果表に記載しています。\n"
                "別途継続している2023年Solcast履歴の追加収集は、この12週比較の完了条件には含めていません。\n")
        parts = [{"mime_type": "text/plain", "charset": "utf-8", "body": {"content": body}}]
        for path in artifacts:
            mime = {".md": "text/markdown", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}[path.suffix]
            parts.append({"mime_type": mime, "filename": path.name, "content_disposition": "attachment",
                          "body": {"base64_url_content": base64.urlsafe_b64encode(path.read_bytes()).decode("ascii")}})
        write_json(self.output / "email_payload.json", {"to": self.config["recipient"],
                   "subject": self.config["email_subject"], "payload": {"mime_type": "multipart/mixed", "parts": parts}})

    def queue_once(self, event: str) -> None:
        path = self.output / f"{event}_dispatch.json"
        if path.exists():
            # A crash/timeout after acceptance is ambiguous; never queue twice blindly.
            prior = read_json(path)
            require(prior.get("config_sha256") == config_hash(self.config), "Dispatch configuration changed")
            require(prior["status"] == "QUEUED", f"Inspect uncertain dispatch before retry: {path}")
            return
        message = (f"ローカル月別監視スクリプトの{event}イベントです。通常監視でAIを呼ばないというユーザー指示に従い一度だけ通知しています。"
                   f"C:/master-course/docs/notes/MONTHLY_COMPLETION_DELIVERY_20260914.md の手順と {self.output}/state.json を確認してください。"
                   + ("全12週の独立監査と最終図表を生成済みです。completion_bundle.jsonのhashと実図の表示を確認し、"
                      "承認済みのg2681320@tcu.ac.jp宛にemail_payload.jsonをGmailで1通送信し、実message IDをemail_receipt.jsonへ保存してください。"
                      "送信済み記録とGmail送信済み検索で重複を防いでください。"
                      if event == "completion" else
                      "監視または計算の失敗です。failure.jsonとcommands.logの末尾を確認し、完了メールは送らず実際の原因を扱ってください。"))
        write_json(path, {"status": "ATTEMPTING", "attempted_at_utc": now(), "event": event,
                          "config_sha256": config_hash(self.config)})
        result = subprocess.run([self.config["codex"], "queue", "--thread", self.config["thread_id"],
                                 "--message", message], cwd=self.root, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        require(result.returncode == 0 and "Queued message " in result.stdout,
                f"Queue failed; inspect {path}: {result.stderr[-1000:]}")
        write_json(path, {"status": "QUEUED", "queued_at_utc": now(), "event": event,
                          "receipt": result.stdout.strip(), "config_sha256": config_hash(self.config)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Read-only deployment check; no queue or writes")
    parser.add_argument("--once", action="store_true", help="Process one checkpoint and exit")
    args = parser.parse_args()
    config = read_json(args.config)
    validate_configuration(config)
    observer = Observer(config)
    if args.check:
        bind_configuration(config, read_only=True)
        observer.check_helpers()
        progress = read_json(observer.campaign / "progress.json")
        weeks = validate_progress(progress, config)
        alive = solver_is_alive(config["solver_pid"], config["solver_started_at_utc"])
        require(alive or progress["status"] == "COMPLETED", "Solver not alive")
        print(json.dumps({"status": "CHECK_PASSED", "completed_weeks": len(weeks), "solver_alive": alive}))
        return 0
    with observer_lock(observer.output / "observer.lock"):
        bind_configuration(config, read_only=False)
        try:
            while True:
                if observer.step() or args.once:
                    return 0
                time.sleep(config.get("poll_seconds", 60))
        except Exception as error:
            observer.checkpoint("NEEDS_ATTENTION", error=str(error), error_type=type(error).__name__)
            stopped_path = observer.output / "stopped_campaign.json"
            stopped = read_json(stopped_path) if stopped_path.exists() else {}
            write_json(observer.output / "failure.json", {"failed_at_utc": now(),
                       "error_type": type(error).__name__, "error": str(error),
                       "failed_cases": stopped.get("failed_cases", [])})
            try:
                observer.queue_once("failure")
            except Exception as dispatch_error:
                print(f"Failure notification pending: {dispatch_error}", file=sys.stderr)
            raise


if __name__ == "__main__":
    raise SystemExit(main())
