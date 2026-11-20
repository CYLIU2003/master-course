# 第2回厳格査読レポート：研究計画改訂案の実験統制・数理・実装監査（neon）

- **対象**：[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md)（および [監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md)）
- **重点**：実験の統制と正しさ（固定配車の選定・初期状態・日射並べ替え・F1/P10定義・実行層統一の数理衝突）
- **基準**：既存ファイル非改変、計算・Git・通信なし。コード・実出力で直接確認した事実のみを根拠とし、未確認事項は「未確認」と明記する。

---

## 1. 前回の重大な指摘への回答状況

前回3名の重大指摘（[review_neon.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_neon.md)、[review_hydro.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_hydro.md)、[review_argon.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_argon.md)）に対する改訂案の対応を判定する。

| # | 前回の重大指摘 | 判定 | 根拠と理由 |
|---|---|---|---|
| 1 | **実行層の非対称性**（規則15分閉ループ vs 最適化1時間開ループ） | **不十分** | 実験1〜3を規則方式に限定して当面回避し、実験4で修正後に実験5を再開する順序は妥当（[改訂案:38-42](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L38-L42)）。しかし「足りない分は蓄電池から出す」では上層MILPと衝突し退化する（後述2-1）。 |
| 2 | **BESS終端評価 $v$ の破綻**（17.43円→0円）と期末在庫未清算 | **対応済み**（※残課題あり） | `rc44` 停止、$v \in \{0, 5, 10, 15, 16.5\}$ の掃引、週初・週末残量差の0円／約17円併記を決定（[改訂案:9-10,39](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L9-L10)）。ただし $v=0$ の縮退対策と監査ハッシュの `v` 欠落修正が抜けている（後述2-6）。 |
| 3 | **別版比較・Stage 1ギャップ（45〜51%）・車両使用費98%の交絡** | **不十分** | 便割当固定・同一版・車両使用費除外の導入は前進（[改訂案:24-28](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24-L28)）。しかし①どの `rc42` 解を固定するか未定（後述2-3）、②12/20原稿土台の `rc42` の `200 kW夏` 24 GiB例外・ローリング時間切れ100回（[deck_data_rc42_et.json:1558-1630,2154-2155](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L1558-L1630)）が未処理。 |
| 4 | **基本料金の外生定数加算と無制限超過（690/768 kW）** | **不十分** | 「基本料金は定数、500円/kWhは罰則係数」と明記し、実量制は2027年1月〜に回した（[改訂案:54,58](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L54)）。説明の誠実さは増したが、12/20原稿の柱Aで「690 kW超過を200 kW基本料のまま総費用比較する」歪みと、受電枠成立／不成立ケースの分離が未明記。 |
| 5 | **目的関数・正式会計・報告費用の三重乖離**（燃料費2.8〜2.9倍水増し・CO₂出し入れ） | **未対応** | 燃料費会計修正は「別途」、CO₂係数も仮値のまま（[改訂案:59-60](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L59-L60)）。最適化内に `co2_price=1円/kg` を入れたまま報告で抜く不整合や、`executed_day_accounting.json` 単一ソース原則との衝突を放置。 |
| 6 | **LNSシード固着**（BEV 95.6% vs ICE 22.0%）とピーク吸収主張の矛盾 | **不十分** | 修論向けに実験6（D）を置いたが（[改訂案:40](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L40)）、12/20原稿の柱A（冬90 kW）の解釈訂正が未記載。実験6自体も全Stage 1＋`vehicle_day` では45%ギャップが解消しない（後述2-8）。 |
| 7 | **BEV初期SOCばらつき（最低38.1%）による初夜スパイク** | **未対応** | 「全実験で同じ値を使い明記（直すかは別途）」と先送り（[改訂案:29](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L29)）。しかし第0日未明のBESS全量枯渇が実験1を直接壊す（後述2-2）。 |
| 8 | **中心の問い不在・柱B②（1,920件・毎朝90%リセット）の破綻** | **対応済み** | 1,920件の連結日計画を明確に撤回し、1文の中心の問いと6本の段階的実験へ再編した（[改訂案:16-20,44](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L16-L20)）。 |
| 9 | **`DIAGNOSTIC` の `rc42` を12/20原稿の土台に使う計画** | **未対応** | 「柱A（rc42）を土台にし対照実験を1図加える」を維持（[改訂案:3,11,53](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L11)）。正式受入未了・24 GiB例外・BESS未清算の土台と新規対照図が同一原稿で混在する（後述2-8）。 |

※補足：[監査のまとめ:18](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md#L18) が「未確認」とした毎時ローリングのBEV窓端制約（`day_ahead_boundary_state`）は今回コード確認し、`bev_terminal_soc_policy="fixed_target"` では**下限制約（`>=`）**と判明した（後述2-4）。

---

## 2. 改訂案に新しく生じた問題（重い順に8件）

### 1.【最重】実験4（実行の層をそろえる）の仕様が上層MILPと数理衝突し、最適化方式を退化・実行失敗させる
- **根拠**：[改訂案:38](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L38)、[pv_execution.py:92-141](file:///C:/master-course/src/optimization/rolling/pv_execution.py#L92-L141)、[bess_dispatch_policy.py:38-61](file:///C:/master-course/src/optimization/common/bess_dispatch_policy.py#L38-L61)、[pv_execution_reserve.py:25-27,112-128](file:///C:/master-course/src/optimization/milp/pv_execution_reserve.py#L25-L27)、[prepare_shibu21_24_seasonal_inputs.py:483,507-508](file:///C:/master-course/scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py#L507-L508)、[solver_adapter.py:23479](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23479)。
- **何が問題か**：改訂案は「最適化方式でも15分ごとに、余った太陽光を蓄電池へ入れ、足りない分は蓄電池から出す」とする。しかし規則方式（`auxiliary_bess_flows`）と同様に `demand > pv` の全不足を無条件に放電すると、以下の4つの数理・実装衝突が起きる。
  1. **上層計画の上書きと退化**：上層MILPが「将来の500円/kWh超過回避や終端価値 $v$ のため、今は17.43円で買電してBESSを温存する」と決めても、下層が即座に放電してしまう。**予報誤差ゼロ（F2）ですら `cost_driven` が規則方式へ物理退化**する。
  2. **消化順序の逆転**：現行 [pv_execution.py:124-127](file:///C:/master-course/src/optimization/rolling/pv_execution.py#L124-L127) は `remaining_bus = max(command.bus_demand_kwh - discharge, 0.0)` で計画放電をPV直接給電より先に引くため、予報より晴れた際にPVが捨てられる。
  3. **予備制約との衝突による `ValueError`**：[pv_execution_reserve.py:112-128](file:///C:/master-course/src/optimization/milp/pv_execution_reserve.py#L112-L128) は1時間（4スロット）の**計画放電のみ**が下限1,200 kWhを割らないことを保証する。下層がスロット1で曇天分の追加放電を行うと、スロット2〜4の計画放電が下限1,200 kWhを割り [pv_execution.py:140-141](file:///C:/master-course/src/optimization/rolling/pv_execution.py#L140-L141) で例外停止する。
  4. **F2での不要な予備制約残存**：[prepare_shibu21_24_seasonal_inputs.py:507-508](file:///C:/master-course/scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py#L507-L508) は `planning_pv_source=="actual_hindsight"` でも `pv_information_mode="training_only_forecast_proxy"` を変えないため、実験5のF2（完全予見）でも「同時間PV=0仮定」の放電制限がかかり続ける。
- **直し方**：下層15分制御の優先順位を **(a) PV→バス直接給電、(b) 余剰PVは `pv_command` クリップなしで空き容量・定格出力まで自動充電（同時充放電禁止維持）、(c) 計画放電は残需要・残量（1,200 kWh超）にクリップ、(d) 追加放電は「契約上限超過の緊急保護（`grid_bus > P_limit * Δt`）」または「予報PV下振れ分 `max(forecast_pv - actual_pv, 0)` の補償」に限定**し、上層の戦略的温存と両立させる。またF2では `pv_information_mode` を実績既知へ切り替え、不要な予備制約を外す。

### 2.【最重】実験1（B：日射の並び順）が初期状態・曜日需要・予報PV・Day 8境界・週末残量の五重交絡を抱える
- **根拠**：[改訂案:29,35](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L29)、[rc42/etb200/2025-01-06/energy_15min.csv:2-28,94-116](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/results/energy_15min.csv#L2-L28)、[etb400/2025-01-06/energy_15min.csv:2-26](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/results/energy_15min.csv#L2-L26)、[etb400/2025-04-07/energy_15min.csv:2-28,695-696](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-04-07/results/energy_15min.csv#L695-L696)、[etb400/2025-07-07/energy_15min.csv:693-696](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-07-07/results/energy_15min.csv#L693-L696)、[daily_summary.csv:2-8](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/results/daily_summary.csv#L2-L8)、[weather_labels.csv:7-13](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2025/weather_labels.csv#L7-L13)、[prepared.json:10-12](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/prepared.json#L10-L12)。
- **何が問題か**：「太陽光の合計を同じにして日ごとに並べ替える」だけでは、以下5つの交絡で順序効果を切り出せない。
  1. **初日未明のBESS人為枯渇**：BEV低初期SOC（最低38.1%＝119.67 kWh、[rolling_chain_summary.json:96](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/rolling_hourly_chain/rolling_chain_summary.json#L96)）の補充で、冬・春とも**第0日00:00〜05:30（日の出前）にBESS在庫1,800 kWhが全量枯渇（3,000→1,200 kWh）**する。実際 `rc42/etb200` 冬の690 kW超過は第0日23:30に起きている。初期状態を現状のまま固定すると、`曇り→晴れ` だけBESS空の月曜に曇りが当たり極端に不利になる。
  2. **曜日需要差と冬実順の偏り**：土日需要は平日より12〜26%低い（[daily_summary.csv:2-8](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/results/daily_summary.csv#L2-L8)：冬平日5.2〜5.3万円→土4.6万・日3.9万円）。`晴れ→曇り` は低需要の週末に曇りを逃がす。しかも冬 `2025-01-06` の実順は既に `雨・曇・晴×4・曇` で `曇り→晴れ` とほぼ同じであり、対象季節自体も未指定。
  3. **予報PVの扱い未定義**：計画PVをF0（日別ほぼ一定）のままにすると、「7日平均の繰り返し」だけ**予報誤差がほぼ消滅**し、物理的な日射平滑化効果と予報誤差縮小効果が交絡する。
  4. **Day 8（`paid_final_overnight`）と合計厳密一致の穴**：週実行は672でなく695〜697スロット（[shibu21_monthly.py:116-198](file:///C:/master-course/tools/research/shibu21_monthly.py#L116-L198)）で、春（3.62 kWh）・夏（27.15 kWh）はDay 8早朝にPVがある。また7日間で太陽高度が変わるため、生GHI並べ替え→POA再換算では合計kWhがずれる。
  5. **週末BESS残量 $E_T$ の非対称**：`曇り→晴れ` は高残量で終了し、`晴れ→曇り` は1,200 kWh張り付きで終わる。
- **直し方**：実験1を実施するなら、①BEV初期SOCを90%統一（または慣らし）で初日枯渇を除去、②計画PVをF2に統一して純粋な物理順序効果を分離（F0は別系列）、③対象季節を明記し、**POA換算後（容量係数・kWh）のDay 1–7日単位置換＋Day 8固定**で合計kWhの厳密一致を検証、④平日反復ダイヤの確認か曜日差の明示、⑤$E_T$ の両建て精算、を条件にする。

### 3.【重】便割当固定における「固定解の選び方」のバイアスと、分散実行での `use_existing_duties` 拒否
- **根拠**：[改訂案:24,50](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24)、[deck_data_rc42_et.json:18-496](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L18-L496)、[cluster.py:195-196](file:///C:/master-course/bff/routers/cluster.py#L195-L196)、[scheduler.py:368-369](file:///C:/master-course/bff/services/cluster/scheduler.py#L368-L369)。
- **何が問題か**：
  1. `rc42` は同一季節内でも受電上限ごとに配車が異なり、春 `etb400` は204台日（`etb200/900` は202台日）、夏BEV担当率は `etb200(rc42m24)` 95.01%・`etb400` 96.01%・`etb900` 97.48%、冬は `eti090` 22.01%・`etb200` 95.07%・`etb400` 95.66% である。もし上限ごとに別の `rc42` 解を固定すれば200 vs 400 kW比較の需要・台数が揃わず、逆に `etb400` を共通固定すれば200 kWに不利（春は余分な+2台日、冬夏は高BEV比率）かつ200 kWでの物理実行可能性が未確認である。
  2. 分散実行経路 [cluster.py:195-196](file:///C:/master-course/bff/routers/cluster.py#L195-L196) と [scheduler.py:368-369](file:///C:/master-course/bff/services/cluster/scheduler.py#L368-L369) は `use_existing_duties=True` を**例外送出で明示禁止**しており、単なるフラグ切替ではクラスタ実行できない。
- **直し方**：季節ごとに「200・400 kW双方で物理実行可能な**単一の共通BEV主力配車**（最有力は全3季節で200 kW実行実績があり春も202台日の `etb200`、ただし夏の `rc42m24` 由来を明記；`etb400` 採用なら200 kW事前検証と春204台日の開示が必須）」を1つ事前決定する。実装面は、不変ハッシュ付きの固定配車ペイロードを分散バンドルへ埋め込み、監査契約を保ったままStage 1をスキップする専用経路を作る。

### 4.【重】F1・P10の定義不整合、夏7/10の異常分類、および「毎時ローリング予報＋`day_ahead_boundary_state` 下限制約」の干渉
- **根拠**：[改訂案:36-37](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L36-L37)、[forecast_holdouts/manifest.json:40-42](file:///C:/master-course/output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json#L40-L42)、[cy2022_cy2024 README:3,12](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2022_cy2024_20260927/README.md#L3)、[seasonal_forecast_proxy.py:63-66,85,102-107](file:///C:/master-course/src/preprocess/weather/seasonal_forecast_proxy.py#L63-L107)、[seasonal_irradiance.py:163-165,199](file:///C:/master-course/src/preprocess/weather/seasonal_irradiance.py#L163-L165)、[seasonal_curves.csv:22-26](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2022_cy2024_20260927/training_reference/seasonal_curves.csv#L22-L26)、[weather_labels.csv:192](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2025/weather_labels.csv#L192)、[cy2025_tilt30/manifest.json:2-14](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2025_tilt30/manifest.json#L2-L14)、[rolling_chain.py:202-221](file:///C:/master-course/bff/services/optimization_run/rolling_chain.py#L202-L221)、[solver_adapter.py:23170-23205](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23170-L23205)、[rc42/etb200/summary.json:86](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/summary.json#L86)。
- **何が問題か**：
  1. **学習年数・統計量・太陽高度処理の不一致**：現行F0は「2024年のみ・算術平均減衰率×日付別快晴GHI→Erbs POA」だが、`cy2022_cy2024` のP10/P50は「2022–2024年・3か月一括の生GHI点別分位」であり、季節内の日の出時刻差（例：春晴 05:00–05:45で `p10=0` vs `p90=148.8 W/m²`）で波形が歪む。傾斜30度POA版も2025年実績（`cy2025_tilt30`）にしかなく学習期間版は存在しない。このままF0 vs F1/P10を比べると、情報差ではなくデータ・統計手法の差を測ってしまう。
  2. **F1のオラクル性と夏7/10の誤分類**：F1は2025年実績分類の参照（`'known_class_oracle_reference'`）であり実天気予報ではない。さらに夏 `2025-07-10` は快晴比 `0.861`・`6.439 kWh/m²`（晴天級）なのに日中降水 `1.4 mm >= 1.0 mm` のため `rainy`（夏雨平均POA 3.55 kWh/m²、[daily_irradiation_summary.csv:7](file:///C:/master-course/data/derived/seasonal_irradiance/tsurumaki/cy2025_tilt30/daily_irradiation_summary.csv#L7)）と分類され、F1が約45%過小予測する異常が生じる。
  3. **ローリング予報同時変更とBEV下限制約の干渉**：改訂案は「前日計画の太陽光」と記すが、[rolling_chain.py:202-221](file:///C:/master-course/bff/services/optimization_run/rolling_chain.py#L202-L221) 上は毎時ローリング予報も同一の `effective_pv_profiles.json` に切り替わる。さらに `bev_terminal_soc_policy="fixed_target"` では、[solver_adapter.py:23172-23205](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23172-L23205) の `day_ahead_boundary_state` は**下限制約（`>= trace[boundary]`）**である（上限は `RETURN_TO_INITIAL` 時のみ）。よって実験3でP10前日計画を立てると高い `trace[boundary]` が毎時ローリングに下限強制され、晴天日でも昼PV待ちへの充電先送りが阻害される。
- **直し方**：F0・F1・P10を**同一学習期間（2022–2024年）・同一の快晴比正規化（時刻別減衰率の統計値×日付別快晴GHI→POA換算）**で統一生成する。F1は「天候区分既知参照（オラクル上限）」と明記し、夏7/10の挙動を注記する。記述も「前日および毎時ローリングの計画太陽光」へ正し、実験3では `day_ahead_boundary_state` との結合を意識して評価する。

### 5.【重】実験3（C）の「朝の目標を80%まで許す」が `rc42` の既存設定と重複し水準定義が曖昧
- **根拠**：[改訂案:37](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L37)、[rc42/etb200/simulation_conditions.json:107-108](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/simulation_conditions.json#L107-L108)、[summary.json:80-81](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/summary.json#L80-L81)、[rolling_chain_summary.json:104-119](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/rolling_hourly_chain/rolling_chain_summary.json#L104-L119)。
- **何が問題か**：`rc42` は**既に** `final_soc_target_percent=90.0`、`final_soc_target_tolerance_percent=10.0`（すなわち80%許容、不足罰則50円/kWh）で走っており、実際 `rc42/etb200` 冬の第0・1日は既に80%（`251.2 kWh`、目標不足 `31.4 kWh`）まで下げている。500円/kWh超過に対して50円/kWh罰則は既に譲歩しているため、改訂案の「200 kW×3季節×4＝12」における「朝の目標を80%まで許す」が、①90%厳守（悪化対照）との比較なのか、②50円罰則撤廃（超過夜にはほぼ無効果）なのか、③70%等へのさらなる緩和なのか不明である。
- **直し方**：現行基準（90%目標／80%下限／50円罰則）を明記したうえで、実験3の対策側は「途中の朝の下限を70%（罰則なしまたは現行）へ緩和し、最終朝のみ90%」へ再定義するか、90%厳守／80%（現行）／70%の3水準で意図を明確化する。

### 6.【重】実験5（最適化）の「1上限」選定による一律単価下の退化リスクと、監査ハッシュの `v` 欠落放置
- **根拠**：[改訂案:39](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L39)、[rolling_chain.py:712-782](file:///C:/master-course/bff/services/optimization_run/rolling_chain.py#L712-L782)、[solver_adapter.py:23537-23582](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L23537-L23582)。
- **何が問題か**：一律単価17.43円・系統→BESS禁止・15分閉ループ統一の下では、超過ゼロの **400 kW** では貪欲自家消費（規則）がPV受入空き容量を最大化しほぼ最適となるため、`cost_driven` が規則に勝つ数理的余地が期末在庫差以外にほぼない。「1上限」に400 kWを選ぶと退化実験になる。また前回指摘した `_non_pv_depot_asset_hash` への `bess_terminal_energy_value_yen_per_kwh` 未収録が放置されており、5価格帯の監査識別ができない。さらに $v=16.5\text{円}$ はCO₂費除外時の損益分岐（16.56円）にはギリギリ未満、CO₂費込み（17.03円）では余裕があり、CO₂最適化組込みの有無で境界が変わる。
- **直し方**：実験5の主上限は**超過が拘束する `200 kW`** に固定する（400 kWは退化検証の補助1点に留める）。実行前に `_non_pv_depot_asset_hash` へ `v` を追加し、CO₂費の最適化内扱いを固定したうえで $v$ 水準（例：0・5・12・16.5円、$v=0$ には微小タイブレーカか縮退確認）を定める。

### 7.【中〜重】計算時間・メモリ・5日実装日程の過小見積もり
- **根拠**：[改訂案:35-37,50-51](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L50-L51)、[柱B設計.md:170](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L170)、[deck_data_rc42_et.json:1578-1594,2154-2155](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L1578-L1594)、[rc42/etb200/2025-07-07/batch-state.json:1](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-07-07/state/batch-state.json#L1)、[rc42/etb200/2025-01-06/solver_settings.json:161](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-01-06/original/output/2026-11-16/run_20261116_1645/solver_settings.json#L161)。
- **何が問題か**：改訂案は1〜3の38件を「1件約2時間、6並列で約13時間」と見積もるが、38件中 **25件が `200 kW`** である。`200 kW` ローリング実測は **1.8〜4.8時間**（[柱B設計.md:170](file:///C:/master-course/outcome/2026-10-30_pillarB_design/柱B設計.md#L170)）、`rc42/etb200` 冬は300秒時間切れだけで **29回＝約2.4時間超**（ローリング全体の正確な実測総秒数は未確認）、さらに `200 kW夏` は14 GiBでStage 2が失敗し24 GiBを要した（[batch-state.json:1](file:///C:/master-course/output/midterm_20261128/rc42/etb200/2025-07-07/state/batch-state.json#L1)）。P10や曇り→晴れで制約が厳しくなれば所要時間はさらに伸びる。また11/22〜11/26の5日間で分散固定配車経路・並べ替え入力・F1・P10・回帰テストをすべて凍結するのは過密である。
- **直し方**：11月末の計算は最優先の1実験（後述の実験2＝18件）に集中し、1件3〜5時間想定＋事前に冬・夏200 kW各1件のパイロットで14/24 GiB所要メモリを確認してから本投入する。

### 8.【中〜重】実験6（D）の `vehicle_day` 実装方針の矛盾と、12/20原稿の統制品質分裂
- **根拠**：[改訂案:11,40,53](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L40)、[stage1_lns.py:36-41,95-117](file:///C:/master-course/src/optimization/milp/stage1_lns.py#L95-L117)、[deck_data_rc42_et.json:1706-2034](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L1706-L2034)、[原稿の構成.md:3-5](file:///C:/master-course/outcome/2026-12-20_ieej_manuscript/原稿の構成.md#L3-L5)。
- **何が問題か**：①実験6は「振替上限 $K$」と「`vehicle_day` 近傍有効化」を並べるが、`stage1_lns.py` の `vehicle_day` は480万変数の全Stage 1のまま（ギャップ45%・不在充電楽観）で動き、$K$ 上限制約も未実装である。これでは $K$ に対する滑らかな限界価値曲線にならない。②12/20原稿で `rc42`（DIAGNOSTIC・外生基本料・690 kW超過・BESS未清算・`200 kW夏` 24 GiB例外）を土台にしつつ固定配車対照図を1図足すと、前半と後半で統制水準が分裂する。
- **直し方**：実験6は全Stage 1ではなく、基準BEV配車からの「$K$ 便（または $K$ 台日）ICE振替付き小規模部分再割当＋精確充電MILP」として低ギャップで解く。12/20原稿の柱A部分では、車両使用費除外の運用費内訳・受電枠成立／不成立の明確分離・BESS残量差両建て・24 GiB例外とDIAGNOSTIC注記を徹底し、追加1図と論理を直結させる。

---

## 3. 中心の問いと実験1〜6で、新規性・有用性・創造性は十分か

**判定：骨格は大幅に改善したが、現状の実験設計のままでは新規性・切れ味がまだ不十分。**

中心の問い（[改訂案:16](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L16)）は、受電制約×PV予報外れの下で(1)予報情報・(2)充電時刻とBESS・(3)燃料バス振替の寄与を分解する明快な因果軸になっており、修論の背骨として強い。しかし、1〜3が規則方式止まりかつ実験1・3に設計穴があり、実験5は400 kW選定なら退化し、実験6は45%ギャップのままでは、「実データの丁寧な感度分析」を越える学術的発見（メカニズム・理論境界）が弱い。以下の3点で絞込みと強化を行うべきである。

1. **【削る／再設計】実験1（8件）と実験3（12件）を11月末の必須列から外し、1〜3の38件を18件へ圧縮する。** 実験1は初期SOC・曜日差・予報PV・Day 8を直さずに回すと論文化不能になり、実験3は「朝80%」の重複とP10歪みの整理が先決である。修論へ回すなら、実験3は「当日実績補正（T1）＋途中朝70%緩和」へ差し替えた方がMPC研究として価値が高い。
2. **【足す】実験5を「200 kW必須＋二層閉ループ下での $v$ の理論境界（$0 < v < \eta_{\text{dis}} p_{\text{eff}}$）と情報価値の実証」へ引き上げる。** 一律単価・閉ループ統一の下で「いつ規則が十分で、どの条件（超過拘束＋天候情報＋適切な $v$）から最適化が勝つか」を数理境界と実証で示せば、仮に差が小さくても強い電気工学的知見になる（$v$ は4水準・200 kW中心に絞って件数を抑える）。
3. **【足す／差し替え】実験6（D）を「固定BEV配車起点の $K$ 便（台日）部分再割当（低ギャップ）」へ刷新し、修論では同一基準で(1)情報・(2)BESS最適化・(3)ICE振替の超過削減効果を横並び比較する。** 実量制デマンド料金・冬季電費+20〜30%感度を重ねれば、題目「GXに向けた燃料バス併用」に真正面から答える独自性が完成する。

---

## 4. 12/20 の原稿に入れる対照実験の選定（実験1〜3から1つ）

**結論：実験2「A 情報の価値（規則）」（F0 / F1 / F2）を選ぶべきである。**

- **選ぶ理由**：
  1. **実験統制が最も純粋で破綻しない**：実績PV・曜日ダイヤ・第0日初期状態・Day 8境界を一切動かさず計画側の予報情報だけを変えるため、実験1のような初日BESS枯渇・曜日需要差・Day 8境界の五重交絡が起きない。
  2. **実験3の設計未確定リスクを回避できる**：実験3は「朝80%許容」の既存設定との重複、P10の季節内太陽高度歪み、`day_ahead_boundary_state` との干渉、2介入同時変化の解釈複雑さを抱え、2ページ原稿の1図に収めるには脆い。
  3. **柱A（`rc42`）の現象と中心の問いへ一直線に繋がる**：柱Aの核心である「200 kW冬の超過（534 kWh／690 kW）と400 kWとの差」を、**「物理限界で不可避な分（F2でも残る分）」** と **「平年値予報外れによる損失（F0−F2）」**、さらに **「天候区分だけで削れる分（F0→F1）」** に1図で分解でき、「単なる運用試算」を「原因解明の研究」へ変える最も明快な対照になる。
  4. **12/20締切に現実的に間に合う**：規則方式のため実験4の実行層改修を待たずに走らせられ、全18件（逼迫時は200 kW 3季節＋400 kW冬＝12件を先行）で11月末〜12月初旬に完了できる。
- **採用時の必須4条件**：①F0とF1を**同一学習期間（2022–2024年）・同一手法（快晴比正規化の平均減衰率→POA）**で揃え、F1は「天候区分既知参照（オラクル上限）」と明記（夏7/10の降水誤分類を注記）、②季節ごとの単一固定配車の選定根拠と車両使用費固定を明記、③週初・週末BESS残量差を0円／約17円の両建てで併記、④「前日および毎時ローリング双方の計画PVを変更」と正確に記述すること。
