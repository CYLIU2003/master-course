"""Create a local, AI-free operator entry folder without submitting any jobs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research.weekly_operator import load_operation


def install(operations: list[Path], output: Path) -> Path:
    """Validate all references before creating a new (never overwritten) kit."""
    if not operations or len({p.resolve() for p in operations}) != len(operations):
        raise ValueError("Select nonempty, unique operation files")
    entries = []
    for path in operations:
        operation, settings, campaign = load_operation(path)
        if not Path(settings["python"]).is_file():
            raise ValueError("Configured Python is missing; restore the declared runtime")
        entries.append({"path": str(path.resolve()), "campaign": str(campaign),
                        "weeks": operation["weeks"], "git_sha": operation["git_sha"],
                        "url": f"http://127.0.0.1:{int(settings['port'])}/#cluster"})
    output = output.resolve()
    registry = {"schema_version": 1, "operations": entries,
                "wrapper": str(ROOT / "tools/research/weekly_operations.ps1"),
                "guide": str(ROOT / "docs/guides/weekly_operations.md")}
    output.mkdir(parents=True, exist_ok=False)
    (output / "registry.local.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    # PowerShell 5 reads BOM-less non-ASCII script text using the system codepage.
    source = ROOT / "tools/research/operator_console.ps1"
    (output / "start.ps1").write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    for name, action in (("00_MENU", "menu"), ("01_STATUS", "status"), ("02_CHECK", "check"),
                         ("03_CONTROLLER", "controller"), ("04_RUN_OR_RESUME", "run"),
                         ("05_COLLECT_EXISTING", "collect"), ("06_WATCH", "watch")):
        # User data is JSON, never interpolated into shell source.
        command = '@echo off\nsetlocal\npowershell.exe -NoProfile -File "%~dp0start.ps1" -Action ' + action
        command += '\nset "result=%errorlevel%"\necho.\necho Operator exit code: %result%\npause\nexit /b %result%\n'
        (output / f"{name}.cmd").write_text(command, encoding="ascii")
    (output / "README.md").write_text(
        "# AIなしの操作入口\n\n00_MENU.cmd を開き、対象期間を選びます。最初は01_STATUS、起動前は02_CHECK。\n"
        "03はコントローラー、04は保存済みIDで開始・続行、05は既存結果の回収、06は監視です。\n"
        "Ctrl+Cは操作スクリプトの終了であり、遠隔計算の取消ではありません。\n"
        "終了コード0は操作成功、3は未完了/通信不明、2は操作エラー、130は中断です。\n"
        "statusの0は12週の完了ではありません。通知.emlは未送信です。\n\n"
        f"詳細手順: {registry['guide']}\n\n"
        "registry.local.jsonはこのPC専用です。鍵やAPIトークンは格納しません。\n"
        "このフォルダは参照と入口だけです。研究原本・設定・キューは移動していません。\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(install(args.operation, args.output))
    except (OSError, ValueError, KeyError) as exc:
        print(f"Operator kit not installed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
