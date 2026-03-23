from pathlib import Path
import matplotlib
matplotlib.use('Agg')
from tools.bus_operation_visualizer_tk import _load_bundle, _build_vehicle_order, _plot_style_1, _plot_style_2

run_dir = Path(r"c:/master-course/outputs/tokyu/2026-03-22/optimization/2b0a60cf-61ad-4094-807c-f766641984c6/tsurumaki/WEEKDAY/run_20260322_2229")
bundle = _load_bundle(run_dir)
vids = _build_vehicle_order(bundle, only_assigned=True)[:20]
fig1 = _plot_style_1(bundle, vids, True)
fig2 = _plot_style_2(bundle, vids, True)
out = run_dir / 'figures'
out.mkdir(exist_ok=True)
fig1.savefig(out / 'smoke_figure_a.png', dpi=200, bbox_inches='tight')
fig2.savefig(out / 'smoke_figure_b.png', dpi=200, bbox_inches='tight')
print('vehicles', len(vids))
print('types_sample', [bundle.vehicle_types.get(v, 'UNKNOWN') for v in vids[:5]])
print('saved', (out / 'smoke_figure_a.png').exists(), (out / 'smoke_figure_b.png').exists())
