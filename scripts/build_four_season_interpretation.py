"""Summarize frozen weekly execution evidence without running or editing a solver."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / 'docs/notes/SHIBU21_23_FOUR_SEASON_COMPLETION_20260912.json'
DEFAULT_OUTPUT = ROOT / 'docs/notes/SHIBU21_23_SEASONAL_INTERPRETATION_20260912'
TOLERANCE = 1e-6
COST_KEYS = (
    'total_cost', 'vehicle_usage_cost', 'electricity_cost', 'fuel_cost',
    'co2_cost', 'contract_overage_cost', 'used_vehicle_day_count',
    'grid_import_kwh', 'peak_grid_kw', 'pv_generated_kwh', 'pv_used_total_kwh',
    'pv_curtailed_kwh', 'pv_to_bus_kwh', 'pv_to_bess_kwh', 'bess_to_bus_kwh',
    'grid_to_bess_kwh', 'contract_over_limit_kwh', 'total_co2_kg',
    'ice_fuel_consumed_l', 'pv_asset_cost', 'bess_asset_cost',
    'stationary_battery_degradation_cost', 'bess_discharge_cost',
)
FLOW_FIELDS = {
    'grid_import_kwh': ('grid_to_bus_kwh_by_depot_slot', 'grid_to_bess_kwh_by_depot_slot'),
    'pv_used_total_kwh': ('pv_to_bus_kwh_by_depot_slot', 'pv_to_bess_kwh_by_depot_slot'),
    'pv_curtailed_kwh': ('pv_curtail_kwh_by_depot_slot',),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def file_digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_close(actual: float, expected: float, label: str) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise ValueError(f'{label}: non-finite value')
    if abs(actual - expected) > TOLERANCE:
        raise ValueError(f'{label}: mismatch {actual} versus {expected}')


def aggregate_slots(plan: dict[str, Any], fields: tuple[str, ...]) -> list[float]:
    return [math.fsum(float(slots.get(str(slot), 0))
                     for field in fields for slots in plan[field].values())
            for slot in range(672)]


def verified_week(week: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    for source in week['source_evidence'].values():
        if file_digest(Path(source['path'])) != source['sha256']:
            raise ValueError(f"Source hash mismatch: {source['path']}")
    accounting_path = Path(week['source_evidence']['executed_day_accounting']['path'])
    accounting = read_json(accounting_path)
    plan = read_json(Path(week['source_evidence']['executed_plan_with_daily_ledger']['path']))
    costs = accounting['cost_breakdown']
    if not accounting['eligible'] or week['hourly_steps_accepted'] != 168:
        raise ValueError('The weekly execution/accounting gate did not pass')
    row = {key: costs[key] for key in COST_KEYS}
    row.update({key: week[key] for key in ('season', 'week', 'end_date', 'trip_count')})
    # The runner sums problem.trips, so this denominator excludes deadhead distance.
    row['scheduled_trip_distance_km'] = week['distance_km']
    row['used_vehicle_count'] = week['used_vehicle_count']
    row['used_vehicle_types'] = week['used_vehicle_types']
    row['stage1_gap'] = week['stage1_gap']
    row['source_evidence'] = week['source_evidence']
    component_total = math.fsum(costs[key] for key in
                               ('vehicle_usage_cost', 'electricity_cost', 'fuel_cost',
                                'co2_cost', 'contract_overage_cost'))
    require_close(component_total, costs['total_cost'], 'Cost component reconciliation')
    row['non_vehicle_usage_cost_jpy'] = math.fsum(costs[key] for key in
                                               ('electricity_cost', 'fuel_cost',
                                                'co2_cost', 'contract_overage_cost'))
    require_close(row['non_vehicle_usage_cost_jpy'],
                  costs['total_cost'] - costs['vehicle_usage_cost'], 'Cost subtraction')
    row['cost_per_scheduled_km_jpy'] = costs['total_cost'] / week['distance_km']
    row['non_usage_cost_per_scheduled_km_jpy'] = row['non_vehicle_usage_cost_jpy'] / week['distance_km']
    row['grid_kwh_per_scheduled_km'] = costs['grid_import_kwh'] / week['distance_km']
    row['vehicle_usage_cost_share_pct'] = costs['vehicle_usage_cost'] / costs['total_cost'] * 100
    row['pv_utilization_pct'] = costs['pv_used_total_kwh'] / costs['pv_generated_kwh'] * 100
    row['pv_curtailment_pct'] = costs['pv_curtailed_kwh'] / costs['pv_generated_kwh'] * 100
    require_close(costs['pv_used_total_kwh'] + costs['pv_curtailed_kwh'],
                  costs['pv_generated_kwh'], 'PV balance')
    slots = {key: aggregate_slots(plan, fields) for key, fields in FLOW_FIELDS.items()}
    for key, values in slots.items():
        require_close(math.fsum(values), costs[key], key)
    if len(plan['grid_to_bus_kwh_by_depot_slot']) != 1:
        raise ValueError('Peak comparison requires this report to contain one depot')
    require_close(max(slots['grid_import_kwh']) / 0.25, costs['peak_grid_kw'], 'Peak grid power')
    row['overage_slot_count_above_tolerance'] = sum(v > 50 + TOLERANCE for v in slots['grid_import_kwh'])
    require_close(math.fsum(max(v - 50, 0) for v in slots['grid_import_kwh']),
                  costs['contract_over_limit_kwh'], 'Contract excess quantity')
    require_close(costs['contract_over_limit_kwh'] * 500,
                  costs['contract_overage_cost'], 'Contract excess fee')
    terminal = accounting['bess_terminal_soc_by_depot']['tsurumaki']
    for field in ('grid_to_bess_kwh', 'pv_asset_cost', 'bess_asset_cost',
                  'stationary_battery_degradation_cost', 'bess_discharge_cost'):
        require_close(costs[field], 0, field)
    require_close(terminal['initial_soc_kwh'], 3000, 'BESS initial inventory')
    require_close(terminal['terminal_soc_kwh'], 1200, 'BESS final inventory')
    row['bess_initial_kwh'] = terminal['initial_soc_kwh']
    row['bess_final_kwh'] = terminal['terminal_soc_kwh']
    row['bess_inventory_drawdown_kwh'] = terminal['initial_soc_kwh'] - terminal['terminal_soc_kwh']
    row['bess_observed_max_kwh'] = week['bess_observed_max_kwh']
    daily = []
    for day, ledger in enumerate(plan['daily_cost_ledger']):
        start, end = day * 96, (day + 1) * 96
        record = {'season': week['season'], 'week': week['week'], 'day_index': day,
                  'service_date': (datetime.fromisoformat(week['week']) + timedelta(days=day)).date().isoformat(),
                  'allocated_total_cost_jpy': ledger['total_cost_jpy']}
        record.update({key: math.fsum(values[start:end]) for key, values in slots.items()})
        record['pv_generated_kwh'] = record['pv_used_total_kwh'] + record['pv_curtailed_kwh']
        record['peak_grid_kw'] = max(slots['grid_import_kwh'][start:end]) / 0.25
        daily.append(record)
    require_close(math.fsum(day['allocated_total_cost_jpy'] for day in daily),
                  costs['total_cost'], 'Daily ledger')
    return row, daily


def compare_weeks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    winter, spring, summer, autumn = rows
    fields = ('total_cost', 'vehicle_usage_cost', 'electricity_cost', 'fuel_cost',
              'co2_cost', 'contract_overage_cost', 'non_vehicle_usage_cost_jpy',
              'grid_import_kwh', 'pv_generated_kwh', 'scheduled_trip_distance_km')
    results = {}
    for label, before, after in (('spring_vs_winter', winter, spring),
                                 ('summer_vs_winter', winter, summer),
                                 ('autumn_vs_summer', summer, autumn)):
        results[label] = {key: {'difference': after[key] - before[key],
                               'ratio': after[key] / before[key] if abs(before[key]) > TOLERANCE else None}
                          for key in fields}
    bridge = results['autumn_vs_summer']
    require_close(bridge['total_cost']['difference'],
                  bridge['vehicle_usage_cost']['difference'] + bridge['non_vehicle_usage_cost_jpy']['difference'],
                  'Autumn cost bridge')
    return results


def chart_contracts() -> list[dict[str, str]]:
    return [
        {'question': 'How much PV was used or curtailed in each selected week?',
         'type': 'stacked_bar', 'fields': 'pv_used_total_kwh, pv_curtailed_kwh', 'unit': 'MWh'},
        {'question': 'How did grid energy purchases vary?', 'type': 'bar',
         'fields': 'grid_import_kwh', 'unit': 'MWh'},
        {'question': 'How did the maximum 15-minute grid power vary?', 'type': 'bar',
         'fields': 'peak_grid_kw', 'unit': 'kW; 200 kW soft contractual reference'},
        {'question': 'How did costs excluding vehicle usage vary?', 'type': 'stacked_bar',
         'fields': 'electricity_cost, fuel_cost, co2_cost, contract_overage_cost', 'unit': '10,000 JPY'},
    ]


def render_figure(rows: list[dict[str, Any]], destination: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_path = Path('C:/Windows/Fonts/meiryo.ttc')
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams.update({'font.size': 11, 'axes.unicode_minus': False, 'svg.fonttype': 'none'})
    labels = [f"{r['season']}\n{r['week'][5:]}〜{r['end_date'][5:]}" for r in rows]
    blue, grey, gold, orange, ink = '#477DB3', '#D6D9DD', '#D7B665', '#C77942', '#263545'
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.8))
    fig.subplots_adjust(left=.075, right=.975, top=.855, bottom=.20, hspace=.64, wspace=.26)
    fig.suptitle('渋21〜23の四季比較：各7日間の実行結果', x=.075, ha='left', y=.985,
                 fontsize=19, fontweight='bold', color=ink)
    fig.text(.075, .93, '2025年評価週／2026年時刻表。60台入力・32台運行。冬春夏1,704便／秋1,621便。各季節1週。',
             fontsize=11, color=ink)
    for ax in axes.flat:
        ax.set_xticks(range(4), labels)
        ax.set_axisbelow(True)
        ax.grid(axis='y', color='#E7E9EC', linewidth=.7)
        ax.spines[['top', 'right']].set_visible(False)
        ax.spines[['left', 'bottom']].set_color('#9CA3AA')
        ax.set_ylim(bottom=0)
    used = [r['pv_used_total_kwh'] / 1000 for r in rows]
    curtailed = [r['pv_curtailed_kwh'] / 1000 for r in rows]
    ax = axes[0, 0]
    ax.set_title('① PV発電量と利用・抑制の内訳', loc='left', pad=32, color=ink)
    ax.bar(range(4), used, .56, color=blue, edgecolor=ink, linewidth=.6, label='利用：直接充電＋BESS充電')
    ax.bar(range(4), curtailed, .56, bottom=used, color=grey, edgecolor=ink, linewidth=.6,
           hatch='///', label='抑制（未利用）')
    ax.legend(loc='lower left', bbox_to_anchor=(-.02, 1.005), frameon=False, ncol=2, fontsize=8.5)
    ax.set_ylabel('PV電力量 [MWh]')
    ax.set_ylim(0, 36)
    for index, row in enumerate(rows):
        ax.text(index, row['pv_generated_kwh'] / 1000 + .5, f"{row['pv_generated_kwh']/1000:.2f}", ha='center')
        ax.text(index, used[index] + curtailed[index] / 2,
                f"抑制{row['pv_curtailment_pct']:.1f}%", ha='center', va='center', fontsize=8.5,
                bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .85, 'pad': 1})
    for ax, field, scale, title, unit in (
        (axes[0, 1], 'grid_import_kwh', 1000, '② 系統からの購入電力量', '購入電力量 [MWh]'),
        (axes[1, 0], 'peak_grid_kw', 1, '③ 最大受電電力（15分平均）', '受電電力 [kW]')):
        ax.set_title(title, loc='left', pad=32, color=ink)
        values = [r[field] / scale for r in rows]
        ax.bar(range(4), values, .56, color=blue, edgecolor=ink, linewidth=.6)
        ax.set_ylabel(unit)
        ax.set_ylim(0, max(values) * 1.22)
        for index, value in enumerate(values):
            ax.text(index, value + max(values) * .025, f'{value:.2f}' if scale == 1000 else f'{value:.1f}', ha='center')
    axes[1, 0].axhline(200, color=ink, linestyle='--', linewidth=1)
    axes[1, 0].text(.02, 1.045, '破線：契約値200 kW（有料超過を許可）',
                     transform=axes[1, 0].transAxes, fontsize=9, color=ink)
    ax = axes[1, 1]
    ax.set_title('④ 車両使用費を除いた費用', loc='left', pad=32, color=ink)
    bottom = [0.] * 4
    for field, name, color, hatch in (
        ('electricity_cost', '電力', blue, ''), ('fuel_cost', '燃料在庫評価', grey, '///'),
        ('co2_cost', 'CO₂', gold, '..'), ('contract_overage_cost', '契約超過', orange, '\\\\')):
        values = [r[field] / 10000 for r in rows]
        ax.bar(range(4), values, .56, bottom=bottom, label=name, color=color,
               edgecolor=ink, linewidth=.6, hatch=hatch)
        bottom = [a + b for a, b in zip(bottom, values)]
    ax.set_ylim(0, 35)
    ax.set_ylabel('費用 [万円]')
    ax.legend(loc='lower left', bbox_to_anchor=(-.02, 1.005), frameon=False, ncol=4, fontsize=8.5)
    for index, value in enumerate(bottom):
        ax.text(index, value + .5, f'{value:.2f}', ha='center')
    fig.text(.075, .055,
             'PV利用量はBESSへの充電時点を含み、車両への最終供給量とは異なる。図④には車両使用費・設備投資費を含めない。\n'
             '全季節でBESSは初期3,000→週末1,200 kWh。Stage 1 gap 84〜85%：研究結論・最適性の証明には未採用。\n'
             '出典：e09fb550 の rolling_hourly_chain/executed_day_accounting.json（四季4週）。',
             fontsize=9, color=ink, linespacing=1.8)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination.with_suffix('.png'), dpi=180, facecolor='white')
    svg_path = destination.with_suffix('.svg')
    fig.savefig(svg_path, facecolor='white')
    svg_text = svg_path.read_text(encoding='utf-8')
    svg_path.write_text('\n'.join(line.rstrip() for line in svg_text.splitlines()) + '\n', encoding='utf-8')
    plt.close(fig)


def report_markdown(data: dict[str, Any], output: Path, figure: Path) -> str:
    rows = data['weeks']
    winter, spring, summer, autumn = rows
    change = data['comparisons']
    weekly_table = '\n'.join(
        f"| {r['season']} | {r['week']}〜{r['end_date']} | {r['trip_count']:,} | "
        f"{r['pv_generated_kwh']/1000:.3f} | {r['grid_import_kwh']/1000:.3f} | "
        f"{r['total_cost']:.6f} | {r['non_vehicle_usage_cost_jpy']:.6f} |" for r in rows)
    detail_table = '\n'.join(
        f"| {r['season']} | {r['pv_curtailment_pct']:.2f}% | {r['peak_grid_kw']:.3f} | "
        f"{r['contract_overage_cost']:.6f} | {r['used_vehicle_day_count']} | "
        f"{r['cost_per_scheduled_km_jpy']:.3f} | {r['non_usage_cost_per_scheduled_km_jpy']:.3f} |"
        for r in rows)
    relative_figure = figure.relative_to(output.parent).as_posix()
    spring_pv = (change['spring_vs_winter']['pv_generated_kwh']['ratio'] - 1) * 100
    spring_grid = (change['spring_vs_winter']['grid_import_kwh']['ratio'] - 1) * 100
    summer_grid = (1 - change['summer_vs_winter']['grid_import_kwh']['ratio']) * 100
    autumn_bridge = change['autumn_vs_summer']
    return f'''# 渋21〜23：四季の結果と季節差からの示唆

**今回の4週では、夏の購入電力量・電力費が最少、秋が最多だった。ただし秋の総費用は車両使用日数が少ないため最少になった。春は冬よりPV発電量が多くても、購入電力量が増えた。季節差を読むには、発電総量に加えてPVの未利用量、受電ピーク、運行量を確認する必要がある。**

対象は凍結 `{data['source_git_sha']}` で完走した四季各7日間。60台（BEV35・ICE25）を入力に保持し、各週で32台（BEV26・ICE6）が運行。全4週168/168時間、物理・会計検証通過、接続候補削減・未割当・解後修復は0。この文書は既存の確定成果物の記述的分析であり、新しい求解や条件変更は行っていない。

**DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。研究採用はBLOCKEDのまま。** 各季節1週のみで、季節母集団の平均・有意差・因果効果を示さない。

## 結果

| 季節 | 対象期間 | 便数 | PV発電量 [MWh] | 購入電力量 [MWh] | 週間総費用 [JPY] | 車両使用費を除いた費用 [JPY] |
|---|---|---:|---:|---:|---:|---:|
{weekly_table}

| 季節 | PV抑制率 | 最大受電 [kW] | 契約超過料金 [JPY] | 使用車両日 | 総費用/営業便km [JPY] | 車両使用費を除いた費用/営業便km [JPY] |
|---|---:|---:|---:|---:|---:|---:|
{detail_table}

![四季のPV・購入電力・受電ピーク・費用比較]({relative_figure}.png)

[編集可能なSVG]({relative_figure}.svg) ／ [丸め前の集計・28日分の内訳・原本参照]({output.name}.json)

## 観測できた違いと、その示唆

### 1. 夏は購入電力量が少ないが、PVを使い切れていない

夏のPV発電量は{summer['pv_generated_kwh']/1000:.3f} MWhで4週中最多、購入電力量は{summer['grid_import_kwh']/1000:.3f} MWhで最少だった。冬に比べ購入電力量は{summer_grid:.2f}%少なく、電力費は{winter['electricity_cost']:.6f}円から{summer['electricity_cost']:.6f}円となった。同じ便数・営業便距離・使用車両日数の冬春夏では、夏の総費用と車両使用費を除いた費用が最少だった。

一方、夏のPV抑制量は{summer['pv_curtailed_kwh']/1000:.3f} MWh、発電量の{summer['pv_curtailment_pct']:.2f}%だった。**発電量の多さを、そのまま有効利用量や費用削減量とみなせない。** 充電可能時間、BESSの充放電電力、予測と実行のずれを次の確認対象とする。実行時BESS最大SOCは{summer['bess_observed_max_kwh']:.3f} kWhで上限4,800 kWh未満であり、この結果だけから蓄電容量不足や増設の有効性を断定しない。

### 2. 春は冬より発電量が多くても、購入量・費用が増えた

春のPV発電量は冬比+{spring_pv:.2f}%だが、購入電力量も+{spring_grid:.2f}%だった。PV利用量（直接充電＋BESS充電）は冬{winter['pv_used_total_kwh']/1000:.3f} MWh、春{spring['pv_used_total_kwh']/1000:.3f} MWhで、抑制率は{winter['pv_curtailment_pct']:.2f}%から{spring['pv_curtailment_pct']:.2f}%へ上昇した。

**週間発電量だけでは運行時の電力不足を説明し切れないことが、この4週から読み取れる。** 時間帯・日別の需給のずれ、配車の違い、予測誤差、限られた求解時間の影響は候補原因だが、今回の集計では寄与を分離していない。「春という季節が購入電力を増やす」とは主張しない。

### 3. 秋は総費用が低く見えても、電力側の負担は最大

秋の購入電力量は夏の{autumn_bridge['grid_import_kwh']['ratio']:.2f}倍、車両使用費を除いた費用は{autumn_bridge['non_vehicle_usage_cost_jpy']['ratio']:.2f}倍だった。しかし便数は1,704→1,621、使用車両日は206→194に減り、20,000円/車両日の使用費が240,000円少ない。

夏→秋の総費用差は、次の恒等式で照合した。

`総費用差 {autumn_bridge['total_cost']['difference']:.6f}円 = 車両使用費差 {autumn_bridge['vehicle_usage_cost']['difference']:.6f}円 + その他4費目の差 {autumn_bridge['non_vehicle_usage_cost_jpy']['difference']:.6f}円`

営業便距離で割った総費用は夏{summer['cost_per_scheduled_km_jpy']:.3f}円/kmに対し秋{autumn['cost_per_scheduled_km_jpy']:.3f}円/kmとなる。**総費用の単純順位を、季節による経済性の順位として扱わない。** 距離で割っても、運行時間帯や配車の交絡が取り除かれたわけではない。

### 4. 購入電力量と受電ピークは、別の指標で評価する必要がある

冬の最大受電は約200 kW、春は{spring['peak_grid_kw']:.3f} kW、夏は{summer['peak_grid_kw']:.3f} kW、秋は{autumn['peak_grid_kw']:.3f} kW。購入量が最少の夏にも{summer['contract_overage_cost']:.6f}円、秋には{autumn['contract_overage_cost']:.6f}円の超過料金が生じた。

今回の料金は、各15分slotの `max(購入電力量 - 200 kW × 0.25 h, 0)` を合計し500円/kWhを掛けるモデル値であり、最大kWに課すデマンド料金ではない。超過料金が出ることと物理違反は別で、今回は有料超過を明示的に許可している。**PVが多い週でも、充電集中への対処が必要になる可能性がある。** 最適な契約電力や設備容量は、この4週から決定しない。

## 先生への説明文案

> 四季各7日間で、全接続候補を保持した運行・充電計画の実行可能性と費用整合を確認しました。選んだ週では夏の購入電力が少なく、秋は購入電力と受電ピークが大きくなりました。一方、春は冬より発電量が多くても購入量が増え、夏にも約4割のPV抑制がありました。したがって、季節差を評価する際には、発電総量だけでなく充電機会との時間的な対応、PV利用量、受電ピークを見る必要があると考えています。これは現段階では記述的な示唆です。同じ運行条件でPVだけを変える比較と、求解品質の確認が今後の検証課題です。

## 定義・比較上の制限

- 費用の唯一の確定源は各週の `executed_day_accounting.json.cost_breakdown`。車両使用費を除いた費用は電力＋燃料＋CO₂＋契約超過料金の合計で、この4週では他費目を落としていないことを照合済み。週間費用・超過料金の表記は元JSONと1e-6円以内で一致する。距離当たり単価・比率・電力量は表示精度で丸めており、未丸め値は添付JSONを参照する。
- 分母の営業便距離は `sum(problem.trips.distance_km)`：冬春夏13,925.428829 km、秋13,325.586034 km。回送込みの総走行距離ではない。全費用をこの分母で割った参考指標であり、回送費の除外は行わない。
- PV利用量は `PV→車両 + PV→BESS`。BESSからの再放電をもう一度加えない。蓄電損失を含むため、車両が最終的に受け取ったPV由来電力量や再エネ比率とは異なる。PVは履歴推定値で、現地実測とは称さない。
- BESSは全週で初期3,000→週末1,200 kWh、SOC在庫を約1,800 kWh減らす条件。BEVは各車の初期SOCへ戻す。BESSの在庫減少をそのまま車両への供給量とみなさず、週を繰り返した定常運用の費用ともみなさない。
- この4週の系統→BESS充電、PV/BESS設備費、BESS放電費・定置電池劣化費はいずれも計上0。設備の無償性や投資採算を意味しない。給油は0でも、燃料費には消費した初期燃料在庫の評価を含む。
- 2026年時刻表に2025年の評価日・PVを適用し、予測学習は2024年のみ。暑さ・寒さによる空調負荷の効果や、年平均の季節傾向を今回の差から説明しない。
- Stage 1 gapは約84〜85%で事前宣言10%に未達。正式fleet contract未宣言、既存PowerPoint証拠2件の不一致も残る。日別28行を独立した28回の季節実験として統計検定しない。

## 再現と検証

`python scripts/build_four_season_interpretation.py` で原本ハッシュを検証し、集計JSON・図PNG/SVG・この文書を生成する。各4週の費用5成分、PV収支、raw flow合計、15分平均ピーク、超過量×単価、7日分台帳を照合。入力・solver・凍結原本は変更しない。

[完走記録](SHIBU21_23_FOUR_SEASON_COMPLETION_20260912.md) ／ [研究採用に残る条件](CURRENT_RESEARCH_RELEASE_BLOCKERS.md)
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=DEFAULT_AUDIT)
    parser.add_argument('--output-stem', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    audit = read_json(args.audit)
    campaign_summary = Path(audit['campaign_directory']) / 'summary.json'
    if file_digest(campaign_summary) != audit['campaign_summary_sha256']:
        raise ValueError('Campaign summary hash mismatch')
    if [week['season'] for week in audit['weeks']] != ['冬', '春', '夏', '秋']:
        raise ValueError('Expected exactly four ordered seasonal weeks')
    rows, daily = [], []
    for week in audit['weeks']:
        row, days = verified_week(week)
        rows.append(row)
        daily.extend(days)
    output = args.output_stem.resolve()
    figure = output.parent / 'figures/shibu21_23_seasonal_20260912'
    data = {'schema_version': 'four_season_interpretation_v1',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_git_sha': audit['source_git_sha'],
            'source_audit_path': str(args.audit.resolve()), 'source_audit_sha256': file_digest(args.audit),
            'research_status': audit['research_status'],
            'analysis_kind': 'descriptive_comparison_of_four_selected_weeks_not_causal_or_annual',
            'validation': 'PASS_SOURCE_HASHES_COMPONENTS_RAW_FLOWS_PEAKS_PV_BALANCE_FEES_DAILY_LEDGER',
            'distance_denominator': 'scheduled_trip_distance_excludes_deadhead',
            'pv_utilization_definition': '(pv_to_bus_kwh + pv_to_bess_kwh) / pv_generated_kwh',
            'chart_contract': {'renderer': 'matplotlib PNG and editable SVG for research document',
                               'categories': 4, 'palette': 'blue, grey, gold, orange; hatch and direct labels',
                               'absolute_bar_axes_start_at_zero': True, 'panels': chart_contracts()},
            'weeks': rows, 'daily_execution_flows': daily, 'comparisons': compare_weeks(rows)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    render_figure(rows, figure)
    output.with_suffix('.md').write_text(report_markdown(data, output, figure), encoding='utf-8')
    print(json.dumps({'report': str(output.with_suffix('.md')), 'figure': str(figure.with_suffix('.png')),
                      'weeks': len(rows), 'daily_rows': len(daily), 'validation': data['validation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
