"""Reflect a verified monthly report in main documentation and the launch record."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
REPORT_STEM = 'SHIBU21_23_MONTHLY_BUDGET_RESULTS_20260914'
SOURCE_SHA = 'fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8'


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def replace_current_result_paragraph(text: str, replacement: str, source: str) -> str:
    """Preserve other contributors' introductory paragraphs and line endings."""
    newline = '\r\n' if '\r\n' in text else '\n'
    paragraphs = text.split(newline * 2)
    matches = [index for index, paragraph in enumerate(paragraphs)
               if paragraph.startswith('最新の固定版 `fa0c22bf`')]
    require(len(matches) == 1, f'{source}: expected one current-result paragraph')
    paragraphs[matches[0]] = replacement
    return (newline * 2).join(paragraphs)


def replacements() -> tuple[dict[Path, bytes], dict]:
    report = read_json(ROOT / f'docs/notes/{REPORT_STEM}.json')
    audit_path = OUTPUT / 'monthly_budget_independent_audit.json'
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes.decode('utf-8-sig'))
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    require(report['independent_audit']['sha256'] == audit_sha,
            'report audit snapshot is stale; rebuild the report first')
    launch_path = OUTPUT / 'budget_rerun_launch.json'
    launch = read_json(launch_path)
    campaign = Path(launch['frozen_root']) / launch['campaign_relative_path']
    progress = read_json(campaign / 'progress.json')
    require(report['source_git_sha'] == audit['expected_sha'] == launch['source_git_sha']
            == progress['base_git_sha'] == SOURCE_SHA, 'source SHA mismatch')
    rows = sorted(report['weeks'], key=lambda row: row['month'])
    count = len(rows)
    require(0 < count <= 12 and count == report['completed_count'], 'invalid report count')
    require([row['month'] for row in rows] == list(range(1, count + 1)), 'nonsequential months')
    require(report['declared_week_count'] == audit['expected_week_count'] == 12, 'declared count drift')
    passed_weeks = {week for week, record in audit['weeks'].items()
                    if record.get('fully_audited') is True
                    and record.get('status') == 'DIAGNOSTIC_EXECUTION_PASSED'}
    require(passed_weeks == {row['week'] for row in rows}, 'passed audit/report weeks differ')
    require(all(record.get('failure') is True for week, record in audit['weeks'].items()
                if week not in passed_weeks), 'unclassified audit record')
    require(set(audit['weeks']) <= set(progress['completed_weeks']), 'execution is not complete for audited week')
    for row in rows:
        record = audit['weeks'][row['week']]
        require(record['fully_audited'] is True and record['audit_status'] == 'INDEPENDENTLY_AUDITED'
                and record['status'] == row['status'] == 'DIAGNOSTIC_EXECUTION_PASSED', 'week audit failed')
        require(row['hourly_steps_accepted'] == 168 and row['physical_violations'] == 0, 'physical gate')
        require(record['accounting']['within_1e-6_jpy'] is True, 'accounting reconciliation failed')
    complete = count == 12
    require(not complete or report['status'] == progress['status'] == 'COMPLETED', 'completion not proven')
    last = rows[-1]
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M JST')
    months = '1月' if count == 1 else f'1〜{count}月'
    stopped = progress['status'] == 'STOPPED_AFTER_FAILED_CASE'
    next_text = ('全12週の月別・季節別整理を結果表に掲載した。' if complete
                 else f'{count + 1}月で計算停止。失敗理由と未実行の週は結果表に記載し、原因を診断中。' if stopped
                 else f'{count + 1}月以降の計算と最終季節別整理を継続中。')
    lead = (
        f'最新の固定版 `fa0c22bf` は{months}の{count}週間が完走・独立監査済み（{count}/12週、{stamp}）。'
        f'{last["month"]}月の総費用{last["total_cost"]:,.6f}円、購入量{last["grid_import_kwh"]:,.3f} kWh、最大受電{last["peak_grid_kw"]:,.3f} kW。'
        '各週168時間・672 slot、物理検証、会計と日別台帳の差1e-6円以内、各169充電求解の数値設定、同一予測、全接続、前後cleanを照合した。'
        + next_text + '研究採用はBLOCKED。'
    )
    snapshot_path = OUTPUT / 'audit_snapshots' / f'{audit_sha}.json'
    if snapshot_path.exists():
        require(snapshot_path.read_bytes() == audit_bytes, 'existing audit snapshot differs')
    updates = {snapshot_path: audit_bytes}
    for relative in ['README.md', 'docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md',
                     'docs/notes/SHIBU21_23_MONTHLY_FAIR_WEEKS_20260914.md']:
        path = ROOT / relative
        text = path.read_bytes().decode('utf-8')
        target = ('docs/notes/' if relative == 'README.md' else '') + REPORT_STEM + '.md'
        replacement = lead + f' [新版の結果表・原本hash]({target})。停止版や単独診断は混ぜない。'
        updates[path] = replace_current_result_paragraph(text, replacement, relative).encode('utf-8')
    path = ROOT / 'docs/notes/DEVELOPMENT_NOTES.md'
    text = path.read_bytes().decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    marker = f'## 2026-09-14 月別固定版fa0c22bf: {last["week"]}の週間監査を反映'
    if marker not in text:
        record = audit['weeks'][last['week']]
        maximum = record['native_stage2_metadata']['quality_maximums']['maximum_constraint_violation']
        note = (marker + '\n\n' + lead
                + f' 車両日数{last["used_vehicle_day_count"]}、車両使用費以外{last["non_vehicle_usage_cost_jpy"]:,.6f}円、'
                + f'PV発電{last["pv_generated_kwh"]:,.6f} kWh、PV抑制率{last["pv_curtailment_pct"]:.4f}%、'
                + f'BESS在庫減少{last["bess_inventory_drawdown_kwh"]:,.6f} kWh。'
                + f'native最大制約残差は{maximum:.17g}。数値設定の一致と実残差・独立物理検証を区別する。'
                + '確定会計・台帳・PV収支・各原本hashを集計CLIでも照合し、同名Markdown/JSONへ反映した。'
                + '計算中の固定ソース、入力、制約、予測、時間枠は変更していない。\n')
        updates[path] = (text.rstrip() + newline * 3 + note.replace('\n', newline)).encode('utf-8')
    launch.update(passed_weeks=count, execution_passed_weeks=count,
                  execution_finished_cases=len(progress['completed_weeks']),
                  independently_audited_weeks=count,
                  status='COMPLETED' if complete else 'STOPPED_AFTER_FAILED_CASE' if stopped else 'RUNNING')
    launch['latest_checkpoint'] = {
        'checked_at_utc': now.isoformat(), 'execution_passed_week': last['week'],
        'active_week': progress.get('active_week'), 'hourly_steps_accepted': 168,
        'physical_accepted': True, 'accounting_eligible': True,
        'ledger_difference_jpy': audit['weeks'][last['week']]['accounting']['cost_difference_jpy'],
        'independent_audit': 'INDEPENDENTLY_AUDITED', 'report': f'docs/notes/{REPORT_STEM}.md',
    }
    if launch.get('active_week_checkpoint', {}).get('week') != progress.get('active_week') or complete:
        launch.pop('active_week_checkpoint', None)
    updates[launch_path] = (json.dumps(launch, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    return updates, {'completed_weeks': count, 'latest_week': last['week'], 'observed_at': stamp}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    updates, summary = replacements()
    if not args.dry_run:
        for path, payload in updates.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_bytes() != payload:
                path.write_bytes(payload)
    print(json.dumps({**summary, 'dry_run': args.dry_run, 'file_count': len(updates)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
