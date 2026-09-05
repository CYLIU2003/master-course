# 複数連続日シミュレーション実装カルシェン

## 現在の実装状況

### ✅ 既に完成している部分

1. **Trip 日替り拡張** (`src/optimization/common/builder.py` L399-432)
   - `planning_days > 1` 時に base trip を複製し、日別に 1440 分（24時間）オフセット追加
   - trip_id は `d{day_idx}_original_id` に自動改名

2. **电力价格 time slot 拡張** (L465-482)
   - base day の TOU 价格を 24h パターン として複製
   - `slot_index` 正規化（day_idx * slots_per_day + base_index）

3. **PV 発電列 拡張** (L1781-1798)
   - base day PV 列を複製し multi-day horizon へ展開
   - 2日目以降も同じ日中パターンを呼び込む（静的近似）

4. **MILP 制約・SOC遷移** (`src/optimization/milp/`)
   - 多日 horizon での trip 繋ぎ制約は既実装
   - deadhead + overnight idle での SOC リセット パターン未確認

5. **BFF route 上の伝播** (`bff/routers/optimization.py` L1329, 1874)
   - scenario.planning_days を ProblemBuilder へ pass

### ❌ 課題と未検証領域

#### A. trip 連鎖の整合性・フェージング
- **問題**: 複数日の trip は昼間に固まり、夜間 gap がある。
  - 1日目の最終便（20:00）→ 2日目の初便（05:00） = 9時間 gap
  - このような gap での overnight idle, remaining SOC の処理
  
- **未検証**:（1）gap が deadhead + idle 制約でロックされ SOC 放電を許容するか（2）連日運用での vehicle efficiency が 1 日分より劇的に変わるか

#### B. PV パターン多様性
- **現行**: `_build_pv_slots()` では同じ 24h パターンを複製（base day のみ）
- **未実装**: `depot_energy_assets[].pv_generation_kwh_by_date[]` の複数日にわたる実プロファイル抽出・反映

#### C. 充電・給油ウィンドウの日跨り対応
- **現行**: `home_depot_charge_pre_window_min` / `post_window_min` は time-relative
- **未検証**: 2日目の首便への pre-window が 1日目の evening に遡らないか

#### D. 契約電力・デマンド料金の集計
- **現行**: `evaluator.py` L770 では全 horizon を通じて max 需要を求めている
- **未検証**: 実装の「日別最大需要」vs「horizon全体最大需要」の解釈

#### E. 運行実績の可視化（output）
- **未実装**: multi-day 出力で「日別」の role ban diagram を生成
- **未実装**: `vehicle_timeline.csv` に「日付（YYYY-MM-DD）」列を追加

#### F. scoped scenario 他フローとの互換性
- **未検証**: `Prepare + Built scenario` として multi-day が正常に SQLite 保存・復元されるか
- **未検証**: BFF API の `/scenarios/{id}/optimization` で multi-day scoped run が正常に動くか

#### G. 研究用 experiment report
- **未実装**: multi-day 用 KPI（日別コスト、日別エネルギー、cross-day activity ratio など）

---

## 実装アクション例

### Phase 1: 基本動作確認（week_1）

1. **シナリオ作成**
   - `planning_days = 2`（金土）の Tokyo-bus scenario 作成
   - 同一 depot、同一 vehicle fleet

2. **Quick Setup で launch**
   - Tk UI → quick_setup で planning_days=2 指定
   - Prepare 実行 → trips 倍加確認（daily ~600 trip × 2 = 1200+）

3. **1モード（mode_milp_only）でテスト実行**
   - time_limit = 600s（10 min）に制限
   - unserved/penalty/total_cost の変化を観察

4. **出力検証**
   ```
   - vehicle_timeline.csv 行数は 2 倍か？
   - cost_breakdown で electricity_cost は？（2倍より高い？）
   - refuel_events に日替りペイターンか？
   ```

### Phase 2: 出力・可視化統一

1. **dated run output に日別 breakdown を追加**
   ```
   cost_breakdown_daily.csv:
     date, metric, value, unit
   vehicle_timeline_daily.json:
     [{ date, vehicle_id, trip_count, soc_min, energy_consumed, ... }]
   depot_energy_flows_daily.csv:
     date, grid_to_bus_kwh, grid_to_bess_kwh, pv_to_*_kwh, ...
   ```

2. **route_band_diagrams/ に日付ディレクトリ**
   ```
   graph/route_band_diagrams/
     2025-08-04/  (day1)
       渋21.svg, 渋22.svg, ...
     2025-08-05/  (day2)
       渋21.svg, 渋22.svg, ...
   ```

### Phase 3: 検証・調整

1. **overnight charger usage が reasonable か**
2. **grid import patterns の日比較**
3. **vehicle SOC trajectories が visually consistent か**

---

## スケジュール

- **本日（4/1）**: Phase 1 基本動作確認を実行（target: 2h）
- **翌日（4/2）**: Phase 2 出力統一・可視化（target: 1.5h）
- **その次（4/3）**: Phase 3 検証・ doc 記録（target: 1.5h）

---

## 参考文献・参照先

- `AGENTS.md`: Future Expansion Targets / Multi-depot support reference
- `docs/constant/formulation.md`: C3 fragment 設定・多日への記載確認
- `README.md`: planning_days パラメータの説明（新規追加予定）

