# E-Bus Sim — 電気バス運行・充電スケジューリング最適化 シミュレータ

> PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 — 試作アプリケーション

## 概要

本アプリケーションは、電気バス（BEV）の**便割当・充電スケジュール・PV/買電配分**を統合的に最適化するための試作シミュレータです。  
Gurobi (MILP) による厳密解法と ALNS（Adaptive Large Neighbourhood Search）によるメタヒューリスティクス解法の両方に対応しています。

### 主な機能

- **GUI 上でシステム規模・車両性能を自由に変更可能**
- **Gurobi (MILP)**: ステージ別（段階的）求解に対応
- **ALNS**: 大規模問題向けの近似解法、収束曲線表示
- **結果可視化**: SOC推移、電力バランス、買電コスト、便割当ガントチャート
- **JSON インポート/エクスポート**: 既存の `ebus_prototype_config.json` と互換

---

## クイックスタート

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

Gurobi を使う場合は別途 Gurobi ライセンスとパッケージが必要です:

```bash
pip install gurobipy
```

> Gurobi がなくても ALNS（内側 LP は scipy で代替）で動作します。

### 2. アプリの起動

```bash
streamlit run app/main.py
```

ブラウザで `http://localhost:8501` が自動で開きます。

### 3. 基本的な使い方

1. サイドバーから **システム規模**（バス台数、便数、時間刻み等）を設定
2. **車両性能**（バッテリ容量、SOC 範囲、電費）を調整
3. **充電設備**（充電器出力・台数）、**PV・電力料金**を設定
4. 「設定を適用」ボタンを押す
5. ソルバータブで **Gurobi** または **ALNS** を選択して求解
6. 結果を確認、必要ならJSON をダウンロード

---

## ファイル構成

```
master-course/
├── app/
│   ├── __init__.py          # パッケージ初期化
│   ├── main.py              # Streamlit メインアプリ
│   ├── model_core.py        # コアモデル・データ構造
│   ├── solver_gurobi.py     # Gurobi (MILP) ソルバー
│   ├── solver_alns.py       # ALNS ソルバー
│   └── visualizer.py        # Plotly 可視化モジュール
├── constant/                # 研究資料（数理モデル定義、制約一覧等）
├── ebus_prototype_config.json      # プロトタイプ設定 JSON
├── ebus_asset_factors.json         # 属物要因 JSON（車両カタログ等）
├── ebus_config_with_asset_ref.json # 外部ファイル参照スタブ
├── solve_ebus_gurobi.py            # 既存の CLI ソルバー
├── requirements.txt
└── README.md
```

---

## 変数仕様書

### 集合 (Sets)

| 記号 | Python キー | 説明 |
|---|---|---|
| $B$ | `buses` | バス集合 |
| $R$ | `trips` | 便集合 |
| $T$ | `range(num_periods)` | 時間区間集合 ( $0, 1, \ldots, T_{max}-1$ ) |
| $C$ | `depots` | 充電拠点集合 |
| $S$ | `charger_types` | 充電器種別集合 (`"slow"`, `"fast"`) |

### パラメータ (Parameters)

#### バス関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| バッテリ容量 | `cap_kwh` | float | kWh | バス $b$ の公称バッテリ容量 |
| 初期 SOC | `soc_init_kwh` | float | kWh | 計画開始時の SOC |
| SOC 下限 | `soc_min_kwh` | float | kWh | 安全のため下回ってはならない SOC |
| SOC 上限 | `soc_max_kwh` | float | kWh | 過充電防止上限（通常 = `cap_kwh`） |
| 電費 | `efficiency_km_per_kwh` | float | km/kWh | BEV の走行効率 |
| 燃費 | `fuel_efficiency_km_per_l` | float | km/L | ICE 比較用 |
| CO2 原単位 | `co2_g_per_km` | float | g/km | CO2 排出原単位 |

#### 便関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| 開始時刻 | `start_t` | int | — | 便 $r$ の開始時刻インデックス |
| 終了時刻 | `end_t` | int | — | 便 $r$ の終了時刻インデックス |
| 消費電力量 | `energy_kwh` | float | kWh | 便 $r$ 全体の走行消費電力量 |
| 走行距離 | `distance_km` | float | km | ICE コスト算出用 |
| 出発地 | `start_node` | str | — | 便の出発拠点 |
| 到着地 | `end_node` | str | — | 便の到着拠点 |

#### 充電器関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| 充電出力 | `power_kw` | float | kW | 充電器 1 口の定格出力 |
| 台数 | `count` | int | — | 同時利用可能台数 |
| 充電効率 | `efficiency` | float | — | 充電効率（0.0〜1.0、通常 0.95） |

#### エネルギー関連

| パラメータ | Python キー | 型 | 単位 | 説明 |
|---|---|---|---|---|
| PV 発電量 | `pv_gen_kwh[t]` | float | kWh | 時刻 $t$ の PV 発電可能量 |
| 電力単価 | `grid_price_yen_per_kwh[t]` | float | 円/kWh | 時刻 $t$ の系統電力単価（TOU） |
| 時間刻み | `delta_h` | float | h | 1 スロットの長さ（0.25, 0.5, 1.0） |
| 充電効率 | `charge_efficiency` | float | — | グローバル充電効率 |
| 軽油単価 | `diesel_yen_per_l` | float | 円/L | ICE 比較用の燃料単価 |

#### フラグ・オプション

| パラメータ | Python キー | 型 | 説明 |
|---|---|---|---|
| PV 有効 | `enable_pv` | bool | PV 発電を考慮するか |
| 終端 SOC | `enable_terminal_soc` | bool | 計画末尾の SOC 下限を課すか |
| 終端 SOC 値 | `terminal_soc_kwh` | float? | 終端 SOC 下限値 [kWh] |
| デマンドチャージ | `enable_demand_charge` | bool | 契約電力制約を導入するか |
| 契約電力 | `contract_power_kw` | float? | 契約電力上限 [kW] |

### 決定変数 (Decision Variables)

| 変数 | Python 名 | 型 | 説明 |
|---|---|---|---|
| $x_{b,r}$ | `x[b,r]` | Binary | バス $b$ が便 $r$ を担当するなら 1 |
| $\text{soc}_{b,t}$ | `soc[b,t]` | Continuous | 時刻 $t$ のバス $b$ の SOC [kWh] |
| $y_{b,c,s,t}$ | `y[b,c,s,t]` | Binary | バス $b$ が時刻 $t$ に拠点 $c$・種別 $s$ で充電するなら 1 |
| $e_{b,c,s,t}$ | `e[b,c,s,t]` | Continuous $\geq 0$ | 充電電力量 [kWh] |
| $\text{pv\_use}_t$ | `pv_use[t]` | Continuous $\geq 0$ | PV 利用量 [kWh] |
| $\text{grid\_buy}_t$ | `grid_buy[t]` | Continuous $\geq 0$ | 系統買電量 [kWh] |

### 目的関数

$$\min \sum_{t \in T} \text{grid\_price}[t] \times \text{grid\_buy}[t]$$

系統電力購入コストを最小化する。

### 制約一覧

| No. | 制約名 | 数式 | 実装ステージ |
|---|---|---|---|
| 1 | 便の一意割当 | $\sum_{b} x_{b,r} = 1 \quad \forall r$ | `assignment_only` |
| 2 | 重複便禁止 | $x_{b,r_1} + x_{b,r_2} \leq 1 \quad \forall b, (r_1,r_2) \in \text{overlap}$ | `assignment_only` |
| 3 | 初期 SOC | $\text{soc}_{b,0} = \text{soc\_init}[b]$ | `assignment_plus_soc` |
| 4 | SOC 下限 | $\text{soc}_{b,t} \geq \text{soc\_min}[b]$ | `assignment_plus_soc` |
| 5 | SOC 上限 | $\text{soc}_{b,t} \leq \text{soc\_max}[b]$ | `assignment_plus_soc` |
| 6 | SOC 推移 | $\text{soc}_{b,t+1} = \text{soc}_{b,t} - \text{drive}_{b,t} + \eta \sum_{c,s} e_{b,c,s,t}$ | `assignment_plus_soc` |
| 7 | 充電量連動 | $e_{b,c,s,t} \leq P_{c,s} \cdot \Delta h \cdot y_{b,c,s,t}$ | `assignment_soc_charging` |
| 8 | 充電器台数上限 | $\sum_{b} y_{b,c,s,t} \leq \text{count}[c][s]$ | `assignment_soc_charging` |
| 9 | 同時多拠点禁止 | $\sum_{c,s} y_{b,c,s,t} \leq 1$ | `assignment_soc_charging` |
| 10 | 運行中充電禁止 | $\text{running}_{b,t} + \sum_{c,s} y_{b,c,s,t} \leq 1$ | `assignment_soc_charging` |
| 11 | 位置整合 | $y_{b,c,s,t} \leq \text{allowed}[b][c][t]$ | `assignment_soc_charging` |
| 12 | PV 利用上限 | $\text{pv\_use}_t \leq \text{pv\_gen}[t]$ | `full_with_pv` |
| 13 | 電力収支 | $\sum_{b,c,s} e_{b,c,s,t} = \text{pv\_use}_t + \text{grid\_buy}_t$ | `full_with_pv` |
| 14 | 終端 SOC | $\text{soc}_{b,T} \geq \text{soc\_terminal}$ | オプション |
| 15 | デマンドチャージ | $\text{grid\_buy}_t / \Delta h \leq P_{\text{contract}}$ | オプション |

---

## Gurobi (MILP) ソルバー

### ステージ別実行

段階的にモデルを構築・デバッグできます:

| ステージ | 含まれる制約 | 用途 |
|---|---|---|
| `assignment_only` | 便割当、重複禁止 | 便割当だけが成立するか確認 |
| `assignment_plus_soc` | + SOC 推移、上下限 | 電池残量込みで成立するか確認 |
| `assignment_soc_charging` | + 充電変数、充電器容量、位置整合 | 充電スケジュールの妥当性 |
| `full_with_pv` | + PV、電力収支、コスト最適化 | 完全モデル |

### Gurobi パラメータ

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `time_limit_sec` | 300.0 | 求解制限時間 [秒] |
| `mip_gap` | 0.01 | MIP ギャップ閾値（1% で十分近似的に最適） |
| `verbose` | False | Gurobi のログを出力するか |

---

## ALNS ソルバー

### アーキテクチャ

```
外側: ALNS（便割当 x の探索）
  ├── 破壊オペレータ
  │   ├── random_destroy: ランダムに便を除去
  │   ├── worst_destroy:  消費電力量の大きい便を優先除去
  │   └── related_destroy: 同一バスの便をまとめて除去
  │
  ├── 修復オペレータ
  │   ├── greedy_repair: 負荷均等化で貪欲割当
  │   └── random_repair: ランダム割当
  │
  └── 内側: LP/MILP（充電量・SOC・PV・買電を最適化）
      ├── Gurobi LP（利用可能な場合）
      └── scipy.linprog（フォールバック）
```

### ALNS ハイパーパラメータ

| パラメータ | Python キー | デフォルト | 説明 |
|---|---|---|---|
| 最大反復回数 | `max_iterations` | 500 | ALNS の最大ループ回数 |
| 改善なし上限 | `max_no_improve` | 100 | 改善なしで早期終了する回数 |
| 初期温度 | `init_temp` | 1000.0 | SA の初期温度 |
| 冷却率 | `cooling_rate` | 0.995 | 温度の減衰率 (0.99〜0.999) |
| 最小破壊率 | `destroy_ratio_min` | 0.1 | 最小破壊比率 |
| 最大破壊率 | `destroy_ratio_max` | 0.4 | 最大破壊比率 |
| セグメント長 | `segment_length` | 50 | 重み更新の間隔 |
| 最良スコア | `score_best` | 10.0 | 全体最良解更新時のスコア |
| 改善スコア | `score_better` | 5.0 | 現在解改善時のスコア |
| 受理スコア | `score_accept` | 2.0 | SA で受理時のスコア |
| 棄却スコア | `score_reject` | 0.0 | 棄却時のスコア |
| 重み減衰 | `decay_factor` | 0.8 | 重み更新の減衰係数 |
| 乱数シード | `seed` | 42 | 再現性のための乱数シード |

---

## 評価指標 (KPI)

| 指標 | 説明 | 単位 |
|---|---|---|
| 目的関数値 | 総系統買電コスト | 円 |
| 総買電量 | 全時間帯の系統買電量合計 | kWh |
| PV 利用量 | PV 自家消費量合計 | kWh |
| 最低 SOC | 全バス・全時刻の最低 SOC | kWh |
| 最大同時充電台数 | 充電器の最大同時稼働数 | 台 |
| 計算時間 | ソルバーの実行時間 | 秒 |

---

## 感度分析で変更可能なパラメータ

研究計画（`ebus_asset_factors.json`）に基づく感度分析軸:

| 軸 | GUI での変更方法 | 推奨範囲 |
|---|---|---|
| PV 容量 | PV出力倍率スライダー | 0.0 〜 5.0 |
| BEV 比率 | バス台数 (将来: ICE/BEV 混在を拡張) | 0% 〜 100% |
| 充電器台数 | 普通/急速充電器台数 | 0 〜 10 |
| 契約電力上限 | デマンドチャージオプション | 100 〜 300 kW |
| 時間帯別電力単価 | TOU / 一律 モード切替 | 自由設定 |
| 軽油単価 | 軽油単価入力 | 130 〜 160 円/L |

---

## 既存ファイルとの互換性

- `ebus_prototype_config.json` → 「JSON インポート」で直接読み込み可能
- `solve_ebus_gurobi.py` → 同等の定式化を `solver_gurobi.py` で再実装
- `ebus_asset_factors.json` → 車両カタログ情報を参照可能（将来拡張で自動マージ予定）

---

## 今後の拡張予定

- [ ] BEV/ICE 混成フリートの明示的サポート
- [ ] HEV 車両の追加
- [ ] 車両カタログ (`ebus_asset_factors.json`) からの自動インポート
- [ ] TOU 料金のカスタム時間帯設定
- [ ] バッチ感度分析（パラメータスイープ）
- [ ] 結果の CSV/Excel エクスポート
- [ ] バッテリ劣化コストの簡易モデル
- [ ] V2G 拡張

---

## ライセンス

修士論文研究用の試作アプリケーションです。
