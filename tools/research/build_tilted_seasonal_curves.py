"""Season x weather standard irradiance curves on a fixed tilted PV plane (pvlib).

Reads the hashed 2025 Solcast archive, keeps the existing GHI-based weather
classification (verified against the frozen cy2025 curves), and adds the
plane-of-array mean/P10/P50/P90 for the same days.  No API call, no solver.

    .venv/Scripts/python.exe tools/research/build_tilted_seasonal_curves.py --output <new dir>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.seasonal_irradiance import WeatherClassificationPolicy, build_seasonal_curves
from src.preprocess.weather.solcast_archive import load_verified_archive
from src.preprocess.weather.tilted_irradiance import SurfacePlane, poa_for_solcast_rows

ARCHIVE = ROOT / 'data/external/solcast_raw/tsurumaki_2025_2026'
FROZEN = ROOT / 'data/derived/seasonal_irradiance/tsurumaki/cy2025'
FIELD = 'poa_global'
SEASON_JA = {'spring': '春', 'summer': '夏', 'autumn': '秋', 'winter': '冬'}
WEATHER_JA = {'sunny': '晴れ', 'cloudy': 'くもり', 'rainy': '雨'}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tilt', type=float, default=30.0)
    parser.add_argument('--azimuth', type=float, default=180.0)
    parser.add_argument('--albedo', type=float, default=0.2)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'refusing to overwrite existing output: {args.output}')
    plane = SurfacePlane(args.tilt, args.azimuth, args.albedo)
    manifest = json.loads((FROZEN / 'manifest.json').read_text(encoding='utf-8'))
    policy = WeatherClassificationPolicy(**manifest['classification_policy'])
    start, end = date(2025, 1, 1), date(2026, 1, 1)
    records, sources = load_verified_archive(ARCHIVE, start, end)
    query = sources[0]['request']['query']
    poa = poa_for_solcast_rows(records, latitude=float(query['latitude']), longitude=float(query['longitude']),
                               plane=plane)
    tilted = [dict(row, **{FIELD: value}) for row, value in zip(records, poa)]
    result = build_seasonal_curves(tilted, start=start, end_exclusive=end, policy=policy,
                                   extra_irradiance_fields=(FIELD,))
    frozen = json.loads((FROZEN / 'seasonal_curves.json').read_text(encoding='utf-8'))
    ghi_only = [{k: v for k, v in cell.items() if k != FIELD} for cell in result['curves']]
    if ghi_only != frozen['curves'] or result['daily_labels'] != frozen['daily_labels']:
        raise SystemExit('GHI classification/statistics differ from the frozen cy2025 curves')
    result['irradiance_plane'] = plane.describe()
    result['limitations'] = [*result['limitations'],
                             'Plane-of-array irradiance is a pvlib transposition of Solcast GHI/DNI/DHI, not a measured tilted sensor.',
                             'Weather classes remain defined on horizontal GHI; only the summarized irradiance changes.']
    args.output.mkdir(parents=True)
    (args.output / 'seasonal_curves_tilted.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    minutes = result['period_minutes']
    with (args.output / 'seasonal_curves_tilted.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['season', 'weather_class', 'days', 'slot_start_jst', 'ghi_mean_w_m2',
                         'poa_mean_w_m2', 'poa_p10_w_m2', 'poa_p50_w_m2', 'poa_p90_w_m2'])
        for cell in result['curves']:
            if not cell['ghi']:
                continue
            for i in range(1440 // minutes):
                writer.writerow([cell['season'], cell['weather_class'], cell['source_day_count'],
                                 f'{i*minutes//60:02d}:{i*minutes%60:02d}', round(cell['ghi']['mean'][i], 3),
                                 *(round(cell[FIELD][k][i], 3) for k in ('mean', 'p10', 'p50', 'p90'))])
    summary = []
    for cell in result['curves']:
        if not cell['ghi']:
            continue
        g, p = cell['ghi']['mean_daily_irradiation_kwh_m2'], cell[FIELD]['mean_daily_irradiation_kwh_m2']
        summary.append({'season': cell['season'], 'weather_class': cell['weather_class'],
                        'days': cell['source_day_count'], 'ghi_kwh_m2_day': round(g, 3),
                        'poa_kwh_m2_day': round(p, 3), 'poa_to_ghi': round(p / g, 3)})
    with (args.output / 'daily_irradiation_summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = ['Noto Sans JP', 'Yu Gothic', 'Meiryo', 'sans-serif']
    fig, axes = plt.subplots(1, 4, figsize=(16, 4), sharey=True)
    hours = [i * minutes / 60 for i in range(1440 // minutes)]
    colors = {'sunny': '#d08c00', 'cloudy': '#4d7ab0', 'rainy': '#5f6b7a'}
    for ax, season in zip(axes, ('spring', 'summer', 'autumn', 'winter')):
        for cell in (c for c in result['curves'] if c['season'] == season and c['ghi']):
            w = cell['weather_class']
            ax.plot(hours, cell[FIELD]['mean'], color=colors[w], label=f'{WEATHER_JA[w]} 傾斜{args.tilt:g}°（{cell["source_day_count"]}日）')
            ax.plot(hours, cell['ghi']['mean'], color=colors[w], linestyle='--', linewidth=1, label=f'{WEATHER_JA[w]} 水平面')
        ax.set_title(f'{SEASON_JA[season]}')
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 6))
        ax.set_xlabel('時刻 [JST h]')
        ax.grid(alpha=.3)
    axes[0].set_ylabel('日射強度 [W/m²]（平均）')
    axes[-1].legend(fontsize=7, loc='upper right')
    fig.suptitle(f'季節×天候別の標準日射カーブ：傾斜{args.tilt:g}°・真南（実線）と水平面GHI（破線）、2025年 弦巻')
    fig.tight_layout()
    fig.savefig(args.output / 'seasonal_curves_tilted.png', dpi=150)
    artifacts = {p.name: sha(p) for p in sorted(args.output.iterdir())}
    (args.output / 'manifest.json').write_text(json.dumps({
        'schema_version': 'seasonal_irradiance_tilted_v1', 'start': start.isoformat(),
        'end_exclusive': end.isoformat(), 'irradiance_plane': plane.describe(),
        'classification_policy': manifest['classification_policy'],
        'verified_against_frozen': {'path': FROZEN.relative_to(ROOT).as_posix(),
                                    'seasonal_curves_sha256': sha(FROZEN / 'seasonal_curves.json')},
        'sources': [{'sha256': s['sha256'], 'request_sha256': s['request_sha256']} for s in sources],
        'artifacts': artifacts,
        'implementation_sha256': {
            'tools/research/build_tilted_seasonal_curves.py': sha(Path(__file__)),
            'src/preprocess/weather/tilted_irradiance.py': sha(ROOT / 'src/preprocess/weather/tilted_irradiance.py'),
            'src/preprocess/weather/seasonal_irradiance.py': sha(ROOT / 'src/preprocess/weather/seasonal_irradiance.py')},
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for row in summary:
        print(row)


if __name__ == '__main__':
    main()
