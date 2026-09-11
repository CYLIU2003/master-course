"""Export a verified Solcast period and its twelve descriptive GHI curves.

This command does not acquire data or use an API key. Evaluation holdouts are
explicit dated exclusions; the full-year descriptive reference is not a forecast.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.preprocess.weather.seasonal_irradiance import (
    WeatherClassificationPolicy, build_seasonal_curves,
)
from src.preprocess.weather.solcast_archive import load_verified_archive, resample_records


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError('Cannot export an empty table')
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def plot_curves(payload: dict, output: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    colors = {'sunny': '#A05A00', 'cloudy': '#37668A', 'rainy': '#5C4780'}
    fig, axes = plt.subplots(4, 3, figsize=(12, 10), sharex=True, sharey=True)
    step = payload['period_minutes']/60
    for ax, cell in zip(axes.flat, payload['curves']):
        series = cell['ghi']
        label = f"{cell['season'].title()} / {cell['weather_class'].title()}   n={cell['source_day_count']}"
        ax.set_title(label, loc='left', fontsize=10)
        if series:
            hours = [(i+0.5)*step for i in range(len(series['mean']))]
            color = colors[cell['weather_class']]
            ax.fill_between(hours, series['p10'], series['p90'], color=color, alpha=.18, label='Pointwise P10-P90')
            ax.plot(hours, series['mean'], color=color, linewidth=1.8, label='Mean')
            if cell['status'] == 'SMALL_SAMPLE_DESCRIPTIVE':
                ax.text(.03, .9, 'Small sample: descriptive only', transform=ax.transAxes, fontsize=8, color='#8F2525')
        else:
            ax.text(.5, .5, 'No eligible days', ha='center', transform=ax.transAxes)
        ax.grid(axis='y', color='#DDDDDD', linewidth=.5)
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_xlim(0, 24)
        ax.set_ylim(bottom=0)
        ax.set_xticks([0, 6, 12, 18, 24])
    for ax in axes[:, 0]:
        ax.set_ylabel('GHI [W/m²]')
    for ax in axes[-1]:
        ax.set_xlabel('Interval midpoint [JST hour]')
    fig.suptitle(f"Tsurumaki: seasonal irradiance reference\n{payload['start']} to {payload['end_exclusive']} (end exclusive)", fontsize=16)
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.text(.065, .025, 'Source: Solcast historical estimated actuals. Weather labels are declared precipitation / clear-sky proxies.\n'
             'Band: variability between source days; not a forecast interval. Finite reference period, not a climatic normal.', fontsize=9)
    fig.tight_layout(rect=(0, .065, 1, .94))
    for suffix in ('png', 'svg', 'pdf'):
        fig.savefig(output / f'seasonal_ghi.{suffix}', dpi=180)
    plt.close(fig)


def build_archive(raw_dir: Path, output: Path, start: date, end_exclusive: date,
                  policy: WeatherClassificationPolicy, exclusions: dict[str, str],
                  fit_before: date | None, plot: bool) -> dict:
    records, sources = load_verified_archive(raw_dir, start, end_exclusive)
    if {source['request']['depot_id'] for source in sources} != {'tsurumaki'}:
        raise ValueError('This report is scoped to the Tsurumaki depot')
    result = build_seasonal_curves(records, start=start, end_exclusive=end_exclusive,
                                   policy=policy, excluded_dates=exclusions, fit_before=fit_before)
    output.mkdir(parents=True, exist_ok=True)
    result['sources'] = sources
    result['created_at_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(output / 'seasonal_curves.json', result)
    write_csv(output / f"irradiance_{result['period_minutes']}min.csv", records)
    write_csv(output / 'irradiance_60min.csv', resample_records(records, start, end_exclusive, 60))
    labels = [{**row, 'flags': json.dumps(row['flags'], ensure_ascii=False)} for row in result['daily_labels']]
    write_csv(output / 'weather_labels.csv', labels)
    curve_rows = []
    for cell in result['curves']:
        if not cell['ghi']:
            continue
        for slot, mean in enumerate(cell['ghi']['mean']):
            curve_rows.append({'season': cell['season'], 'weather_class': cell['weather_class'],
                               'source_day_count': cell['source_day_count'], 'status': cell['status'],
                               'interval_start_minute_jst': slot*result['period_minutes'], 'unit': 'W/m2',
                               'mean': mean, **{key: cell['ghi'][key][slot] for key in ('p10','p50','p90','population_std')}})
    if curve_rows:
        write_csv(output / 'seasonal_curves.csv', curve_rows)
    if plot:
        plot_curves(result, output)
    artifacts = {path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
                 for path in sorted(output.iterdir()) if path.is_file() and path.name != 'manifest.json'}
    manifest = {'schema_version': 'seasonal_archive_v1', 'start': start.isoformat(),
                'end_exclusive': end_exclusive.isoformat(), 'record_count': len(records),
                'day_count': (end_exclusive-start).days, 'status': result['status'],
                'classification_policy': result['classification_policy'], 'sources': sources,
                'artifacts': artifacts, 'limitations': result['limitations']}
    code_paths = [Path(__file__), Path('src/preprocess/weather/seasonal_irradiance.py'), Path('src/preprocess/weather/solcast_archive.py')]
    manifest['implementation_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in code_paths}
    write_json(output / 'manifest.json', manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end-exclusive', type=date.fromisoformat, required=True)
    parser.add_argument('--policy', type=Path, default=Path('config/seasonal_weather_classification.json'))
    parser.add_argument('--exclude-dates', type=Path, help='JSON object mapping evaluation dates to exclusion reasons')
    parser.add_argument('--fit-before', type=date.fromisoformat)
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    policy = WeatherClassificationPolicy(**json.loads(args.policy.read_text(encoding='utf-8')))
    exclusions = json.loads(args.exclude_dates.read_text(encoding='utf-8')) if args.exclude_dates else {}
    manifest = build_archive(args.raw_dir, args.output, args.start, args.end_exclusive, policy, exclusions, args.fit_before, args.plot)
    print(json.dumps({key: manifest[key] for key in ('status','day_count','record_count')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
