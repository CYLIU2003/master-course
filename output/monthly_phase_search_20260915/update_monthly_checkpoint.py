"""Publish only this release's verified count; keep all older evidence separate."""
import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.watch_monthly_campaign import read_json, require, sha256, write_json

START = "<!-- monthly-search-status -->"
END = "<!-- /monthly-search-status -->"


def replace_status(text: str, paragraph: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join((START, paragraph, END))
    if START in text:
        require(text.count(START) == text.count(END) == 1, "Ambiguous status block")
        start, end = text.index(START), text.index(END) + len(END)
        return text[:start] + block + text[end:]
    require(END not in text, "Incomplete status block")
    first, separator, rest = text.partition(newline)
    return first + separator + newline + block + newline + newline + rest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    launch = read_json(BASE / "budget_rerun_launch.json")
    audit_path = BASE / "monthly_budget_independent_audit.json"
    audit = read_json(audit_path)
    report = read_json(ROOT / "docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.json")
    require(report["source_git_sha"] == audit["expected_sha"] == launch["source_git_sha"], "Source mismatch")
    require(report["independent_audit"]["sha256"] == sha256(audit_path), "Audit hash mismatch")
    frozen = Path(launch["frozen_root"]).resolve()
    require(Path(audit["frozen_root"]).resolve() == frozen, "Frozen root mismatch")
    require(audit["campaign_output"] == launch["campaign_relative_path"], "Campaign mismatch")
    campaign = frozen / launch["campaign_relative_path"]
    progress = read_json(campaign / "progress.json")
    require(progress["base_git_sha"] == launch["source_git_sha"], "Progress source mismatch")
    passed = set()
    for week, row in audit["weeks"].items():
        expected_case = campaign / "cases" / week / "diagnostic" / week
        if row.get("failure") is True and row.get("fully_audited") is False:
            require(row.get("audit_status") == "FAILED_CASE_DIAGNOSTIC_ONLY"
                    and row.get("status") != "DIAGNOSTIC_EXECUTION_PASSED", "Invalid failure record")
            require(Path(row["case_root"]).resolve() == expected_case.resolve(), "Foreign failure case")
            summary_path = expected_case / "summary.json"
            require(sha256(summary_path) == row["hashes"]["case_summary"], "Failure summary changed")
            require(read_json(summary_path)["status"] == row["status"], "Failure status mismatch")
            require(week in progress["completed_weeks"], "Failure case not ended")
            continue
        require(row.get("fully_audited") is True and row.get("status") == "DIAGNOSTIC_EXECUTION_PASSED"
                and row.get("audit_status") == "INDEPENDENTLY_AUDITED" and not row.get("failure"),
                "Incomplete or failed audit record")
        require(Path(row["case_root"]).resolve() == expected_case.resolve(),
                "Audit case belongs to another campaign")
        passed.add(week)
    require(passed <= set(progress["completed_weeks"]), "Audited uncompleted week")
    if report["status"] == "COMPLETED":
        require(progress["status"] == audit["status"] == "COMPLETED" and len(passed) == 12,
                "Premature completion")
    require(passed == {row["week"] for row in report["weeks"]}, "Audited/report weeks differ")
    require(len(passed) == report["completed_count"], "Count mismatch")
    paragraph = (f'最新の月別再実行: 固定 `{launch["source_git_sha"][:8]}`、独立監査 {len(passed)}/12週、'
                 f'状態 `{report["status"]}`。全月共通MIPFocus=1・前日Method=1・rolling Method=0、物理許容差1e-9。'
                 '旧10a40c9fの7週・fa0c22bfの10週は旧版の記録として保存し、新版には混ぜない。研究採用BLOCKED。'
                 '結果: `docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.md`。')
    paths = [ROOT / "README.md", ROOT / "DEVELOPMENT_NOTES.md",
             ROOT / "docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md",
             ROOT / "docs/notes/SHIBU21_23_MONTHLY_FAIR_WEEKS_20260914.md"]
    changes = [(path, replace_status(path.read_bytes().decode("utf-8"), paragraph)) for path in paths]
    if not args.dry_run:
        for path, text in changes:
            path.write_bytes(text.encode("utf-8"))
        snapshots = BASE / "audit_snapshots"
        snapshots.mkdir(exist_ok=True)
        snapshot = snapshots / f"{sha256(audit_path)}.json"
        if not snapshot.exists():
            snapshot.write_bytes(audit_path.read_bytes())
        launch.update(status=report["status"], independently_audited_weeks=len(passed))
        write_json(BASE / "budget_rerun_launch.json", launch)
    print(json.dumps({"audited_weeks": len(passed), "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()
