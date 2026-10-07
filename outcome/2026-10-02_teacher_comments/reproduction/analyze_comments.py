"""Read-only evidence analysis for the 2026-10-02 teacher revision."""
import csv
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path('C:/master-course')
OUT = Path(__file__).parent
EVIDENCE = ROOT / 'outcome/2026-09-28_september_presentation/evidence'
WEATHER = ROOT / 'data/derived/seasonal_irradiance/tsurumaki/cy2025'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

weather = read_csv(WEATHER / 'irradiance_15min.csv')
labels = read_csv(WEATHER / 'weather_labels.csv')
groups = {}
for row in weather:
    start = datetime.fromisoformat(row['period_end'].replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=9))) - timedelta(minutes=15)
    row['start_jst'] = start.isoformat()
    row['hour'] = start.hour + start.minute / 60
    groups.setdefault(start.date().isoformat(), []).append(row)
assert len(weather) == 35040 and len(groups) == 365
rain_days = []
for label in labels:
    if label['season'] != 'summer' or label['weather_class'] != 'rainy':
        continue
    rows = groups[label['date']]
    noon = [r for r in rows if 10 <= r['hour'] < 14]
    ratio = sum(float(r['ghi']) for r in noon) / sum(float(r['clearsky_ghi']) for r in noon)
    before = sum(float(r['precipitation_rate']) * .25 for r in rows if r['hour'] < 15 and float(r['clearsky_ghi']) >= 20)
    after = sum(float(r['precipitation_rate']) * .25 for r in rows if r['hour'] >= 15 and float(r['clearsky_ghi']) >= 20)
    rain_days.append({'date': label['date'], 'midday_10_14_ratio': ratio, 'daylight_rain_before_15_mm': before, 'daylight_rain_from_15_mm': after, 'daylight_ratio': float(label['daylight_clearsky_ratio'])})
assert len(rain_days) == 20
write_csv(OUT / 'summer_rain_days.csv', rain_days)
example = [{'interval_start_jst': r['start_jst'], 'hour_jst': r['hour'], 'ghi_w_m2': float(r['ghi']), 'clearsky_ghi_w_m2': float(r['clearsky_ghi']), 'precipitation_rate_mm_h': float(r['precipitation_rate'])} for r in groups['2025-07-10']]
write_csv(OUT / 'summer_rain_example_20250710.csv', example)
excluded = next(l for l in labels if l['date'] == '2025-03-03')
peaks = []
all_vehicles = []
inputs = [WEATHER / 'irradiance_15min.csv', WEATHER / 'weather_labels.csv']
for week in ['2025-03-03', '2025-11-10']:
    folder = EVIDENCE / week
    energy = read_csv(folder / 'energy_15min.csv')
    charge = read_csv(folder / 'charging_schedule.csv')
    soc = read_csv(folder / 'vehicle_soc.csv')
    trips = read_csv(folder / 'vehicle_schedule.csv')
    row = max(energy, key=lambda r: float(r['grid_import_kwh']))
    slot = int(row['slot'])
    date = row['interval_start_jst'][:10]
    active = [r for r in charge if int(r['slot_index']) == slot and float(r['charge_kw']) > .001]
    vehicles = []
    for c in active:
        state = next(r for r in soc if r['vehicle_id'] == c['vehicle_id'] and int(r['state_index']) == slot)
        today = [t for t in trips if t['vehicle_id'] == c['vehicle_id'] and t['service_date'] == date]
        minutes = min(int(t['departure'].split(':')[0]) * 60 + int(t['departure'].split(':')[1]) for t in today)
        clock = f'{minutes // 60 % 24:02d}:{minutes % 60:02d}'
        vehicles.append({'week': week, 'peak_start_jst': row['interval_start_jst'], 'vehicle_id': c['vehicle_id'], 'charger_id': c['charger_id'], 'charge_kw': float(c['charge_kw']), 'soc_start_percent': float(state['soc_percent']), 'first_service_departure_jst': clock})
    total_grid = sum(float(r['grid_import_kwh']) for r in energy)
    night_grid = sum(float(r['grid_import_kwh']) for r in energy if 0 <= datetime.fromisoformat(r['interval_start_jst']).hour < 6)
    maximum_residual = max(abs(float(r['grid_import_kwh']) + float(r['pv_to_bus_kwh']) + float(r['bess_to_bus_kwh']) - float(r['bus_charge_kwh'])) for r in energy)
    assert maximum_residual < 1e-6
    peak = {'week': week, 'peak_start_jst': row['interval_start_jst'], 'slot': slot, 'grid_kw': float(row['grid_import_kwh']) * 4, 'bus_charge_kw': float(row['bus_charge_kwh']) * 4, 'pv_to_bus_kw': float(row['pv_to_bus_kwh']) * 4, 'bess_to_bus_kw': float(row['bess_to_bus_kwh']) * 4, 'bess_start_kwh': float(energy[slot-1]['bess_soc_end_kwh']), 'bess_end_kwh': float(row['bess_soc_end_kwh']), 'active_chargers': len(active), 'total_grid_kwh': total_grid, 'night_00_06_grid_kwh': night_grid, 'night_00_06_share_percent': 100 * night_grid / total_grid, 'soc_min_percent': min(v['soc_start_percent'] for v in vehicles), 'soc_max_percent': max(v['soc_start_percent'] for v in vehicles), 'first_departure_min': min(v['first_service_departure_jst'] for v in vehicles), 'first_departure_max': max(v['first_service_departure_jst'] for v in vehicles), 'supply_max_residual_kwh': maximum_residual}
    assert abs(sum(v['charge_kw'] for v in vehicles) - peak['bus_charge_kw']) < .001
    peaks.append(peak)
    all_vehicles.extend(vehicles)
    inputs.extend(folder / name for name in ['energy_15min.csv','charging_schedule.csv','vehicle_soc.csv','vehicle_schedule.csv'])
write_csv(OUT / 'peak_vehicle_evidence.csv', all_vehicles)
result = {'analysis_date': '2026-10-02', 'new_solver_run': False, 'rain_proxy_exploratory_definition': '10:00<=JST<14:00 integrated GHI/clear-sky GHI >=0.7 and daylight (clear-sky GHI>=20 W/m2) precipitation from15:00 >=1mm; not a meteorological shower classification', 'summer_rain_count': len(rain_days), 'bright_midday_count': sum(r['midday_10_14_ratio'] >= .7 for r in rain_days), 'bright_midday_and_afternoon_rain_count': sum(r['midday_10_14_ratio'] >= .7 and r['daylight_rain_from_15_mm'] >= 1 for r in rain_days), 'excluded_day': excluded, 'peaks': peaks, 'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
assert result['bright_midday_count'] == 6 and result['bright_midday_and_afternoon_rain_count'] == 2
(OUT / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k != 'input_sha256'}, ensure_ascii=False, indent=2))

