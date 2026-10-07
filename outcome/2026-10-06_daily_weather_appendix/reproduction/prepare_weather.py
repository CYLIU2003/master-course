"""Extract and check 84 frozen Solcast days; no network or optimizer calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('C:/master-course')
EVIDENCE = ROOT / 'outcome/2026-09-28_september_presentation/evidence'
SOURCE = ROOT / 'outcome/2026-10-06_explanation_revision/research_progress_20261006_explained_v2.pptx'
SOURCE_SHA = '7d7e72f2887d9dfa0fc6d1b604f54e2f8eb19e8307aa19840efb31d17fe181e7'
JST = timezone(timedelta(hours=9))
FIELDS = ('ghi', 'dni', 'dhi', 'clearsky_ghi', 'air_temp', 'cloud_opacity', 'precipitation_rate')
LABELS = {'sunny': '晴れ', 'cloudy': 'くもり', 'rainy': '雨', 'unresolved': '未判定＊'}
WEEKDAYS = '月火水木金土日'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def extract_inputs(folder: Path) -> dict:
    manifest = json.loads((EVIDENCE / 'manifest.json').read_text(encoding='utf-8'))
    for relative in ('comparison.json', 'weather/manifest.json', 'weather/weather_labels.csv'):
        key = relative.replace('/', '\\')
        if sha(EVIDENCE / relative) != manifest.get(key, manifest.get(relative)):
            raise ValueError(f'Frozen evidence hash mismatch: {relative}')
    weather = json.loads((EVIDENCE / 'weather/manifest.json').read_text(encoding='utf-8'))
    comparison = json.loads((EVIDENCE / 'comparison.json').read_text(encoding='utf-8'))
    weeks = [c['week'] for c in comparison['cases'] if c['included']]
    if len(weeks) != 12 or len(set(weeks)) != 12:
        raise ValueError('Exactly 12 declared representative weeks required')
    labels = list(csv.DictReader((EVIDENCE / 'weather/weather_labels.csv').open(encoding='utf-8-sig')))
    if len({r['date'] for r in labels}) != len(labels):
        raise ValueError('Duplicate label dates')
    days = {(date.fromisoformat(w) + timedelta(days=i)).isoformat() for w in weeks for i in range(7)}
    if len(days) != 84:
        raise ValueError('Representative weeks overlap')
    selected = []
    sources = []
    for source in weather['sources']:
        path = ROOT / source['path']
        if sha(path) != source['sha256']:
            raise ValueError(f'Raw Solcast hash mismatch: {source["path"]}')
        sources.append({k: source[k] for k in ('path', 'sha256', 'request_sha256')})
        for row in json.loads(path.read_text(encoding='utf-8'))['estimated_actuals']:
            start = datetime.fromisoformat(row['period_end']).astimezone(JST) - timedelta(minutes=15)
            if start.date().isoformat() in days:
                selected.append({'period_end': row['period_end'], 'period': row['period'], **{k: row[k] for k in FIELDS}})
    selected.sort(key=lambda r: datetime.fromisoformat(r['period_end']))
    with (folder / 'solcast_15min_selected.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['period_end', 'period', *FIELDS])
        writer.writeheader(); writer.writerows(selected)
    if sha(SOURCE) != SOURCE_SHA:
        raise ValueError('Current deck changed; re-inspect before snapshotting')
    shutil.copyfile(SOURCE, folder / 'source_base.pptx')
    if sha(SOURCE) != SOURCE_SHA or sha(folder / 'source_base.pptx') != SOURCE_SHA:
        raise ValueError('Deck changed during copy')
    config = {'weeks': weeks, 'labels': [r for r in labels if r['date'] in days],
              'classification_policy': weather['classification_policy'], 'raw_sources': sources,
              'source_deck_sha256': SOURCE_SHA, 'source_sha': comparison['source_sha'],
              'evidence_manifest_sha256': sha(EVIDENCE / 'manifest.json'),
              'selected_intervals_sha256': sha(folder / 'solcast_15min_selected.csv')}
    save_json(folder / 'weather_inputs.json', config)
    return config


def verify_and_write(folder: Path, build: Path, output: Path) -> None:
    config = json.loads((folder / 'weather_inputs.json').read_text(encoding='utf-8'))
    if sha(folder / 'solcast_15min_selected.csv') != config['selected_intervals_sha256']:
        raise ValueError('Selected Solcast data changed')
    if sha(folder / 'source_base.pptx') != config['source_deck_sha256']:
        raise ValueError('Base deck changed')
    by_day = defaultdict(list)
    for row in csv.DictReader((folder / 'solcast_15min_selected.csv').open(encoding='utf-8')):
        start = datetime.fromisoformat(row['period_end']).astimezone(JST) - timedelta(minutes=15)
        if row['period'] != 'PT15M' or not all(math.isfinite(float(row[k])) for k in FIELDS):
            raise ValueError('Invalid Solcast interval')
        by_day[start.date().isoformat()].append((start, row))
    labels = {r['date']: r for r in config['labels']}
    expected_days = {(date.fromisoformat(w) + timedelta(days=i)).isoformat() for w in config['weeks'] for i in range(7)}
    if len(expected_days) != 84 or set(labels) != expected_days or set(by_day) != expected_days:
        raise ValueError('Expected exactly 84 selected dates')
    policy = config['classification_policy']
    maximum_error = 0.0
    for day in sorted(expected_days):
        pairs = sorted(by_day[day], key=lambda pair: pair[0])
        beginning = datetime.combine(date.fromisoformat(day), datetime.min.time(), JST)
        if [p[0] for p in pairs] != [beginning + timedelta(minutes=15*i) for i in range(96)]:
            raise ValueError(f'Incomplete or duplicate intervals: {day}')
        rows = [r for _, r in pairs]
        daylight = [r for r in rows if float(r['clearsky_ghi']) >= policy['daylight_clearsky_ghi_w_m2']]
        values = {
            'daily_irradiation_kwh_m2': math.fsum(float(r['ghi']) * .25 / 1000 for r in rows),
            'precipitation_mm': math.fsum(float(r['precipitation_rate']) * .25 for r in rows),
            'daylight_precipitation_mm': math.fsum(float(r['precipitation_rate']) * .25 for r in daylight),
            'possible_solid_precipitation_mm': math.fsum(float(r['precipitation_rate']) * .25 for r in daylight if float(r['air_temp']) <= policy['suspected_solid_precip_temp_c']),
            'daylight_clearsky_ratio': math.fsum(float(r['ghi']) for r in daylight) / math.fsum(float(r['clearsky_ghi']) for r in daylight)}
        for field, value in values.items():
            error = abs(value - float(labels[day][field]))
            maximum_error = max(maximum_error, error)
            if error > 1e-9:
                raise ValueError(f'Frozen label disagreement: {day}, {field}')
        label = ('rainy' if values['daylight_precipitation_mm'] >= policy['rainy_daylight_precip_mm']
                 else 'sunny' if values['daylight_clearsky_ratio'] >= policy['sunny_clearsky_ratio'] else 'cloudy')
        if values['possible_solid_precipitation_mm'] >= policy['rainy_daylight_precip_mm']:
            label = 'unresolved'
        if label != labels[day]['weather_class']:
            raise ValueError(f'Frozen weather classification disagreement: {day}')
    output.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    table_rows, slides = [], []
    for month_index, week in enumerate(config['weeks'], 1):
        start = date.fromisoformat(week)
        dates = [start + timedelta(days=i) for i in range(7)]
        rows = [labels[d.isoformat()] for d in dates]
        total = math.fsum(float(r['daily_irradiation_kwh_m2']) for r in rows)
        counts = Counter(r['weather_class'] for r in rows)
        values = [['日付（曜日）', '天候', '日射量 GHI\n[kWh/m²/日]', '晴天比 R', '昼間降水\n[mm/日]', '全日降水\n[mm/日]']]
        for day, row in zip(dates, rows):
            values.append([f'{day.month}/{day.day}（{WEEKDAYS[day.weekday()]}）', LABELS[row['weather_class']],
                           f'{float(row["daily_irradiation_kwh_m2"]):.3f}', f'{float(row["daylight_clearsky_ratio"]):.3f}',
                           f'{float(row["daylight_precipitation_mm"]):.3f}', f'{float(row["precipitation_mm"]):.3f}'])
            table_rows.append({'representative_week_start': week, 'date': day.isoformat(), 'weekday_ja': WEEKDAYS[day.weekday()],
                               'weather_ja': LABELS[row['weather_class']], **row})
        summary = f'週の日射量合計：{total:.3f} kWh/m²'
        if counts['unresolved']:
            summary += ' ／ 3/3＊は雨雪未判定。日射データ・週次計算には含む'
        else:
            summary += f' ／ 晴れ {counts["sunny"]}日・くもり {counts["cloudy"]}日・雨 {counts["rainy"]}日'
        slides.append({'number': 44 + month_index, 'title': f'{start.month}月代表週：日別の天候と日射量',
                       'subtitle': f'2025年{start.month}月{start.day}日（月）〜{dates[-1].month}月{dates[-1].day}日（日）／各日0:00〜24:00（日本時間）\nSolcast履歴推定値。水平面の日射量を集計（太陽光発電量とは別）',
                       'values': values, 'takeaway': summary,
                       'footnote': '分類：昼間降水1 mm以上→雨。その他は晴天比 R ≥0.7→晴れ、<0.7→くもり。\nR＝昼間の推定日射／晴天日射。昼間＝晴天時GHI 20 W/m²以上。表示は小数第3位まで。',
                       'notes': f'対象は{week}から連続7日間。出典：2025年Solcast historic radiation_and_weatherの保存済み原本（弦巻営業所）。研究用の天候分類であり気象庁の観測天気ではない。GHIは水平面日射。15分平均GHI[W/m²]×0.25h/1000を各日の96区間で積算。晴天比は昼間のGHI積算/clearsky_ghi積算。雨判定が優先。低温降水の雨雪が未確定の場合は未判定とし、天候統計のみ除外。3月3日も日射量と週次運用には含む。CSVは丸め前の値を保持。週末後の翌朝までの運用集計とは範囲を区別し、本表は7つの暦日を記載。原計算SHA={config["source_sha"]}。再生成データはreproduction/weather_inputs.json、solcast_15min_selected.csv。'})
    if len(table_rows) != 84:
        raise ValueError('Output row coverage failed')
    with (output / 'daily_weather_84days.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table_rows[0]))
        writer.writeheader(); writer.writerows(table_rows)
    save_json(build / 'slides.json', {'slides': slides})
    save_json(build / 'data_verification.json', {'days': 84, 'weeks': 12, 'intervals': sum(map(len, by_day.values())),
              'daily_interval_count': 96, 'maximum_numeric_disagreement': maximum_error,
              'weather_counts': dict(Counter(r['weather_class'] for r in table_rows)),
              'source_deck_sha256': config['source_deck_sha256'], 'fixed_calculation_sha': config['source_sha'],
              'raw_sources': config['raw_sources'], 'numeric_tolerance': 1e-9})
    print('84 days / 8064 intervals verified against frozen labels; table CSV and 12 slide inputs written.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('build', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--extract', action='store_true')
    args = parser.parse_args()
    folder = Path(__file__).parent
    if args.extract:
        extract_inputs(folder)
    verify_and_write(folder, args.build, args.output)
