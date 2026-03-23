from pathlib import Path
from tools.bus_operation_visualizer_tk import _load_bundle, _build_summary_rows, _build_details_rows

run_dir = Path(r"c:/master-course/outputs/tokyu/2026-03-22/optimization/2b0a60cf-61ad-4094-807c-f766641984c6/tsurumaki/WEEKDAY/run_20260322_2229")
bundle = _load_bundle(run_dir)
summary_rows = _build_summary_rows(bundle)
detail_rows = _build_details_rows(bundle)
print('summary_count', len(summary_rows))
print('has_total_cost', any(k == 'total_cost' for k, _ in summary_rows))
print('has_total_co2', any(k == 'total_co2_kg' for k, _ in summary_rows))
print('detail_count', len(detail_rows))
print('sample')
for r in summary_rows[:6]:
    print(r)
