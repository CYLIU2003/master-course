# experiment_logger 組み込みガイド

## 1. `src/run_simulation.py` への追記

`run_simulation.py` の末尾（結果 dict を返す直前）に以下を追加します。

```python
# ─── 実験ログ出力 ───────────────────────────────────────────────────
from src.experiment_logger import log_experiment

# scenario_dict は run_simulation に渡されたシナリオ（dict）
# result_dict  は最適化後に組み立てた結果（dict）
# ↓ このキー名は実際の変数名に合わせてください
report = log_experiment(
    scenario=scenario_dict,
    result=result_dict,
    method=scenario_dict.get("method", "MILP"),   # シナリオに method キーがなければ "MILP"
    print_summary=True,
)
# report.json_path, report.md_path で保存先を参照できます
```

### result_dict が期待するキー（できるだけ揃えると完全なレポートが出力されます）

```python
result_dict = {
    "status":               "OPTIMAL",        # 必須
    "objective_value":      18592.2765,       # 目的値
    "total_cost_jpy":       18592.23,         # 総コスト
    "electricity_cost_jpy": 1234.56,          # 電気代内訳
    "diesel_cost_jpy":      17000.0,          # 軽油代内訳
    "demand_charge_jpy":    300.0,            # デマンド料金
    "vehicle_fixed_cost_jpy": 0.0,
    "co2_kg":               319.7433,
    "bev_trips":            127,
    "ice_trips":            99,
    "total_trips":          226,
    "total_charging_kwh":   5.2,
    "peak_charging_kw":     20.0,
    "solve_time_sec":       42.3,
    "mip_gap_pct":          0.0,              # OPTIMAL なら 0
    # 以下は任意
    "charging_schedule":    {...},            # 時系列充電プロファイル
    "cost_breakdown":       {...},            # より細かいコスト内訳
}
```

> `cost_breakdown` などネストされた形式でも自動的に読み取ります。

---

## 2. `scripts/sim_cli.py` への追記

`run_simulation()` 関数内、`subprocess.run()` の後に追加：

```python
# 最新の result JSON を探してレポート化
result_files = sorted(
    (REPO_ROOT / "results").glob("*.json"),
    key=lambda p: p.stat().st_mtime, reverse=True
)
# ただし experiment_logger が既に run_simulation.py 側で呼ばれている場合は不要
```

または、`sim_cli.py` のプリセット実行後に以下を追加して既存ファイルを後処理：

```python
# ─── sim_cli.py の run_simulation() 関数内 ───────────────────
# subprocess.run() 後に最新の result を表示する例
import glob, os
results_glob = sorted(
    glob.glob(str(REPO_ROOT / "results" / "exp_*.json")),
    key=os.path.getmtime, reverse=True
)
if results_glob:
    with open(results_glob[0]) as f:
        latest = json.load(f)
    print(f"\n{cyan('最新レポート:')} {results_glob[0]}")
```

---

## 3. `scripts/sim_ui.py` への追記

シミュレーション完了後の表示部分（`st.success("✅ ...")` の後）に追加：

```python
# Streamlit UI: レポートを構造化表示
exp_reports = sorted(
    (REPO_ROOT / "results").glob("exp_*.md"),
    key=lambda p: p.stat().st_mtime, reverse=True
)[:5]

if exp_reports:
    st.divider()
    st.subheader("📋 実験レポート")
    for rp in exp_reports:
        with st.expander(rp.stem, expanded=(rp == exp_reports[0])):
            st.markdown(rp.read_text(encoding="utf-8"))
```

---

## 4. 手法名 (`method`) の設定方法

シナリオ JSON に `method` キーを追加するだけで自動反映されます：

```json
{
  "depot": "meguro",
  "objective": "total_cost",
  "method": "MILP+ALNS",   ← ここを追加
  ...
}
```

対応する手法名の例：

| 値 | 意味 |
|---|---|
| `"MILP"` | 純粋な MILP（Gurobi/HiGHS） |
| `"ALNS"` | Adaptive Large Neighborhood Search |
| `"MILP+ALNS"` | MILP で初期解 → ALNS で改善 |
| `"GA"` | 遺伝的アルゴリズム |
| `"SA"` | 焼きなまし法 |

---

## 5. CLI で既存ファイルから後処理レポート生成

過去に実行した結果を後からレポート化したい場合：

```bash
python src/experiment_logger.py \
  --scenario scenarios/scenario_meguro_3r_20260314.json \
  --result   results/result_20260314.json \
  --method   MILP \
  --out      results/
```

---

## 6. 出力ファイルの例

```
results/
  exp_20260314_143022_meguro_total_cost_a3f9b1c2.json   ← 機械可読（全情報）
  exp_20260314_143022_meguro_total_cost_a3f9b1c2.md     ← 論文用メモ（Markdown）
```

### JSON 構造の概略

```json
{
  "experiment_id": "20260314_143022_meguro_total_cost_a3f9b1c2",
  "conditions": {
    "depot": "meguro",
    "routes": ["さんまバス", "東98", "渋72"],
    "objective": "total_cost",
    "method": "MILP",
    "fleet_bev_model": "日野 ブルーリボン Z EV",
    "fleet_bev_count": 12,
    "fleet_ice_model": "いすゞ エルガ ディーゼル",
    "fleet_ice_count": 12
  },
  "cost_conditions": {
    "tou_offpeak_jpy_per_kwh": 18.0,
    "tou_midpeak_jpy_per_kwh": 32.0,
    "tou_onpeak_jpy_per_kwh": 20.0,
    "diesel_jpy_per_l": 150.0,
    "demand_jpy_per_kw_month": 1200.0,
    "grid_max_kw": 200.0,
    "vehicle_fixed_cost_jpy_per_day": 0.0,
    "pv_capacity_kw": 0.0
  },
  "solver_settings": {
    "solver_name": "gurobi",
    "time_limit_sec": 600,
    "mip_gap_pct": null,
    "seed": null
  },
  "results": {
    "status": "OPTIMAL",
    "objective_value": 18592.2765,
    "total_cost_jpy": 18592.23,
    "co2_kg": 319.7433,
    "bev_trips": 127,
    "ice_trips": 99,
    "total_trips": 226,
    "solve_time_sec": 42.3,
    "mip_gap_pct": 0.0
  },
  "reproducibility": {
    "timestamp_utc": "2026-03-14T05:30:22+00:00",
    "timestamp_local": "2026-03-14T14:30:22.134512",
    "git_commit": "a3f9b1c",
    "python_version": "3.11.8",
    "scenario_hash": "a3f9b1c2d4e5"
  }
}
```
