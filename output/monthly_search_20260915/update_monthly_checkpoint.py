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
    report = read_json(ROOT / "docs/notes/SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915.json")
    require(report["source_git_sha"] == audit["expected_sha"] == launch["source_git_sha"], "Source mismatch")
    require(report["independent_audit"]["sha256"] == sha256(audit_path), "Audit hash mismatch")
    passed = {week for week, row in audit["weeks"].items() if row.get("fully_audited") is True}
    require(passed == {row["week"] for row in report["weeks"]}, "Audited/report weeks differ")
    require(len(passed) == report["completed_count"], "Count mismatch")
    paragraph = (f'最新の月別再実行: 固定 `{launch["source_git_sha"][:8]}`、独立監査 {len(passed)}/12週、'
                 f'状態 `{report["status"]}`。全月共通MIPFocus=1・Method=1、物理許容差1e-9。'
                 '旧fa0c22bfの10週は旧版の記録として保存し、新版には混ぜない。研究採用BLOCKED。'
                 '結果: `docs/notes/SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915.md`。')
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
