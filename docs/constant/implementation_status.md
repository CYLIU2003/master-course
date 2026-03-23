# 実装状況一覧（Implementation Status）

**作成日：** 2026-03-18
**対象：** `master-course core` の MILP ソルバー（`src/optimization/milp/solver_adapter.py`）および評価器（`src/optimization/common/evaluator.py`）

本文書は `docs/constant/formulation.md` の目標定式化に対し、現時点での実装状況を三段階で明記します。

## 0. 本文書の立ち位置（3層分離）

1. 研究として最終的に目指す定式化: `docs/constant/formulation.md`
2. 2026-03-18 時点で core に実装済みの範囲: 本文書
3. 未実装だが修論計画上で今後導入する範囲: 本文書 4章（フェーズ計画）

## 0.1 先生向けの説明順（要約）

1. 何を決めるモデルか: 便割当・充電量・PV/系統の配分
2. 何を守るモデルか: 運行成立・SOC・充電設備上限・契約電力上限
3. 何を最小化するか: 総費用（O1/O2/O3/O4 + 欠便ペナルティ）
4. 何が評価指標に留まるか: CO2・劣化
5. 何が未実装で、いつ入れるか: 4章の Phase 2-4

## 0.2 非専門向けの用語対応

- 目的関数: モデルが最終的に一番小さくしたい合計費用
- 制約: 現実の運行で破ってはいけない条件
- 決定変数: モデルが自分で決める項目

| 記号 | 意味 |
|------|------|
| ✅ 対応 | 定式どおりに実装済み |
| 🔶 部分対応 | 近似・緩和・代替手段で実装。定式と完全一致しない点あり |
| ❌ 未実装 | 現行 core には実装されていない |

---

## 1. 制約一覧（C1〜C21）

| No. | 内容 | 状況 | 実装詳細・差分 |
|-----|------|------|----------------|
| C1 | 各便の一意割当 $\sum_k y_j^k = 1$ | 🔶 部分対応 | `sum(y[k,j]) + unserved[j] == 1`（未充足便を許容する罰則付き緩和） |
| C2 | フロー保存（便ノードで入流 = 出流） | ✅ 対応 | `incoming + start_arc == y`、`outgoing + end_arc == y` |
| C3 | 各車両の出庫・入庫は高々1回 | ✅ 対応 | `sum(start_arc) <= 1`、`sum(end_arc) <= 1` |
| C4 | 接続可能アークのみ利用可 | ✅ 対応 | `arc_pairs` を `feasible_connections` から生成。不可アークは変数すら作らない |
| C5 | 同時刻の重複運行禁止 | ✅ 対応 | 各車両の重複便ペア `(i,j)` に対し `y[k,i] + y[k,j] <= 1` を明示追加（`_trips_overlap` で区間重複を判定）。C4/C3 の間接抑止に加えて完全実装 |
| C6 | SOC 遷移（デポ滞在中：充電） | 🔶 部分対応 | `s[t+1] = s[t] + η·c[t]·Δt - ...` で時系列遷移を実装。走行/回送/充電の扱いに近似を含む |
| C7 | SOC 遷移（便走行消費） | 🔶 部分対応 | `trip.energy_kwh * y` を SOC 遷移に減算。Big-M 形式ではなく連続遷移で近似 |
| C8 | SOC 遷移（deadhead 消費） | 🔶 部分対応（近似） | `deadhead_energy_expr` を SOC 遷移に投入。距離→エネルギー換算に近似あり |
| C9 | SOC 上下限（常時） | ✅ 対応 | `s_var` の `lb = soc_min`、`ub = cap`（バッテリー容量） |
| C10 | 出庫時 SOC（満充電） | 🔶 部分対応 | `s[first_slot] == initial_kwh`。満充電固定ではなく `initial_soc` パラメータ依存 |
| C11 | 帰庫後 SOC 下限（翌日用確保） | ✅ 対応 | `s[last_slot] >= soc_min * used_vehicle` |
| C12 | 走行中充電禁止（運行と充電の排他） | ✅ 対応 | `c[k,t] <= chargeMax * (1 - running_expr)`（走行中フラグで充電上限をゼロに） |
| C13 | 充電電力上限（充電器定格） | ✅ 対応（MILP adapter経路） | `chi[k,t]`（ON/OFF二値）を導入し、`c[k,t] <= chargeMax * chi[k,t]` を実装 |
| C14 | 同時充電台数制約（充電器台数上限） | ✅ 対応（MILP adapter経路） | `sum_k chi[k,t] <= total_ports`（台数）と `sum_k c[k,t] <= total_kw`（容量）を分離実装 |
| C15 | 電力バランス（系統 + PV = 充電需要） | ✅ 対応 | `g_var + pv_ch_var == sum(c) * Δt` |
| C16 | PV 供給上限（PV 発電量以内） | ✅ 対応 | `pv_ch_var <= pv_available * Δt` |
| C17 | 非逆潮流（系統への注入禁止） | ✅ 対応 | `g_var` の `lb = 0` |
| C18 | 系統受電容量上限（契約電力） | ✅ 対応 | `g_var <= contract_limit_kw * Δt` |
| C19 | デマンド計測期間の平均需要電力定義 | ✅ 対応 | `p_avg_var[t] = g_var[t] / Δt` |
| C20 | オンピーク最大需要電力 | 🔶 対応（改善） | `demand_charge_weight` が設定された tariff slot を優先して `w_on >= p_avg_var[t]` を適用。未設定時は中央値フォールバック |
| C21 | オフピーク最大需要電力 | 🔶 対応（改善） | `demand_charge_weight` が設定された tariff slot を優先して `w_off >= p_avg_var[t]` を適用。未設定時は中央値フォールバック |

---

## 2. 目的関数一覧（O1〜O4 + 拡張）

| 記号 | 内容 | 状況 | 実装詳細・差分 |
|------|------|------|----------------|
| O1 | ICE 燃料費（便 + deadhead） | ✅ 実装済み | `diesel_price * fuel_k(j) * y_j^k`（便）+ `diesel_price * fuel_k^{dh}(i,j) * x_{ij}^k`（回送） |
| O2 | TOU 電力料金（系統買電費） | ✅ 実装済み | `sum_t price_t * g_t`（スロット別単価 × 買電量） |
| O3 | デマンド料金（最大需要電力） | ✅ 実装済み | `demand_on * W^on + demand_off * W^off` |
| O4 | 車両固定費 | ✅ 実装済み | `fixed_use_cost_k * z_k`。個別無効化: 車両の `acquisitionCost=0`。一括無効化: UI チェックボックス `disable_vehicle_acquisition_cost=true`（simulation_config 経由でマッパーが全車両の fixed_use_cost を 0 上書き） |
| —   | 欠便ペナルティ | ✅ 実装済み | `unserved_penalty * sum_j u_j`（大きな重みで欠便を強く抑制） |
| —   | CO₂ 費用 | ✅ 実装済み | `co2_price_per_kg > 0` のとき MILP 目的関数・evaluator.py 両方に加算。ICE 燃料由来 + 系統電力由来を個別計算 |
| —   | 電池劣化費 | ✅ 実装済み | `weights.degradation > 0` のとき MILP・evaluator.py 両方で目的関数に加算。充電 kWh / 容量 × 単価/cycle × 重み |
| —   | PV 余剰売電 / 逆潮流 | ❌ 未実装 | `pv_t^{sell}` 変数・売電益の定式化は将来拡張 |

---

## 3. ALNS / GA / ABC における評価器の対応

`src/optimization/common/evaluator.py` の `CostEvaluator` は MILP と同等の O1〜O3 を評価します。

| 費目 | MILP | evaluator.py |
|------|------|--------------|
| O1 ICE 燃料費 | ✅ | ✅ |
| O2 TOU 買電費 | ✅ | ✅（PV 自家消費差引きあり） |
| O3 デマンド料金 | ✅ | ✅ |
| O4 車両固定費 | ✅ | ✅ |
| 欠便ペナルティ | ✅ | ✅ |
| CO₂ 費用 | ✅（`co2_price_per_kg > 0` 時） | ✅（同条件、`co2_cost` フィールドに分離） |
| 電池劣化費 | ✅（`weights.degradation > 0` 時） | ✅（同条件、`degradation_cost` フィールド） |

---

## 4. 修論フェーズ別の実装計画

### Phase 1（2026-03-18 ～ 修論前半）
- ✅ 本文書の新設（仕様書と実装の分離明記）
- ✅ README・formulation.md に注意書き追加
- ✅ CO₂ 計算結果を結果 JSON・出力画面に明示（JSON既存 + Tk結果Summaryへ表示追加）
- ✅ 充電器台数制約を総 kW と分離（`N_c^max` による台数カウント）

### Phase 2（修論前半）
- ✅ 充電 ON/OFF 二値変数 $\xi_{k,t}$ の導入（C13/C14 の厳密化）
- ✅ オンピーク/オフピーク時間帯を tariff テーブル優先で定義（C20/C21 の改善、未設定時フォールバックあり）
- ✅ C5（重複禁止）明示制約を追加（`_trips_overlap` + `y[k,i] + y[k,j] <= 1`）

### Phase 3（修論中盤）
- ✅ CO₂ を重み付き和で目的関数化（`co2_price_per_kg > 0` のとき有効）
- ✅ 劣化費の簡易線形モデルを目的関数に追加（`weights.degradation > 0` のとき有効）
- 🔲 ε 制約法による多目的化（CO₂ を上限制約として扱う形式）
- 🔲 deterministic MILP の妥当性確認完了

### Phase 4（修論後半）
- 🔲 ALNS 外側探索 + MILP 内側評価のハイブリッド化本格導入
- 🔲 Rolling horizon / 不確実性対応（将来拡張）

---

## 5. 参照ファイル

| ファイル | 用途 |
|----------|------|
| `docs/constant/formulation.md` | 目標定式化（本文書の比較元）|
| `src/optimization/milp/solver_adapter.py` | MILP 実装本体 |
| `src/optimization/common/evaluator.py` | ALNS/GA/ABC 評価器 |
| `src/optimization/milp/model_builder.py` | 可行アーク生成 |
| `README.md` の10章 | 制約 C1〜C21 の詳細対応表（変数名付き）|
