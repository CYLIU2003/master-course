# 改訂研究計画（2026-11-21）第2回監査報告（査読者：Argon）

監査対象：[監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md)、[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md)（および関連コード・出力成果物）。前回報告（[review_argon.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_argon.md)、362行・65.9 KB）の半分以内（約150行）で回答する。

---

## 1. 前回の重大な指摘への対応状況

| # | 前回の重大指摘（[監査のまとめ](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md#L10-L22) / [review_argon.md](file:///C:/master-course/outcome/2026-11-21_research_audit/review_argon.md#L58-L179)） | 判定 | 根拠と理由 |
|---|---|---|---|
| 1 | **BESS実行層の非対称性**（規則方式＝15分閉ループ、計画方式＝1時間開ループ） | **対応済み** | [研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L9-L10)および[L35-L41](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L35-L41)で柱B①を停止し、実験1〜3を規則方式（`pv_self_consumption`）に統一、実験4で [pv_execution.py](file:///C:/master-course/src/optimization/rolling/pv_execution.py#L105-L127) の実行層を閉ループに揃える順序に改めた点は妥当。 |
| 2 | **BESS終端残量単価 $v$ の極端な設定**（rc43の17.43円→rc44の0円）と往復効率（0.9025）不整合 | **対応済み** | [研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L9)でrc44を投入前停止し、実験5（[L39](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L39)）で $v \in \{0, 5, 10, 15, 16.5\}\text{ 円/kWh}$ を掃引、週初・週末在庫差を0円と約17円の両方で精算する設計（[L42](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L42)）へ修正済み。 |
| 3 | **Stage 1の車両使用費（目的関数の98%・1台日2万円）とMIPギャップ（45〜50%）による比較ノイズ** | **不十分** | 便割当を固定してStage 2＋毎時立て直しのみを解く方針（[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24-L28)）は正しいが、①**どのケースの便割当を基準にするか未確定**（[L24](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24)で先送り）、②**クラスタ実行経路で `fixed_assignment` がBFFから渡らないコード上の未接続**（下記2.1・2.2節）が未解決。 |
| 4 | **柱B②（1,920件）の計算規模破綻**および**週計画W vs 日計画Dの毎朝90%リセットによる差の消失** | **対応済み** | [研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L35-L44)で日次連結実行（1,920件）を撤回し、7日間週計画（全38＋12＝50件）の中で予報（A）・慎重計画と朝80%許容（C）・途中の朝の目標緩和（実験6）を検証する構成へ転換済み。 |
| 5 | **料金Aの現実乖離**（基本料金の事後定数加算・契約超過罰金500円/kWh） | **不十分** | 指導教員方針として料金Aを維持し「500円/kWhは上限遵守の罰則係数で実在の料金ではない」と原稿に明記する決定（[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L54)、[L58](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L58)）は理解できる。しかし柱A（rc42）で冬200 kWが最大690.47 kW受電している事実（[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L2086-L2096)）は契約種別の問題ではなく**200 kW受電制約の物理的破綻**であり、実験1〜3で200 kWを「上限をほぼ守れる境界」と扱う点に矛盾が残る（2.5節）。 |
| 6 | **BEV初期SOCの不均一・低値**（36台中12台が50%未満、最低38.1%＝119.67 kWh） | **未対応** | 「全ての実験で同じ初期値を使うため、今回は直さず、論文に初期値分布を明記する」（[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L29)、[L60](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L60)）と棚上げされたが、これは**実験1（B：日射の並び順）の比較を直接歪める交絡因子**となる（2.3節）。 |
| 7 | **ローリング窓端の車載SOC目標が前日計画値（`day_ahead_boundary_state`）に固定される問題** | **未対応** | [監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md#L18)で「コードでの最終確認は未完了」とされたまま、改訂案に対策がない。実コード（[reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L530-L607)、[soc_helpers.py](file:///C:/master-course/src/optimization/common/soc_helpers.py#L279-L296)）を確認した結果、実験1・2・4・5・6の解釈を左右する拘束が残っている（2.4節）。 |
| 8 | **燃料費会計の約2.9倍計上・CO₂係数の逆転（BEV＞ICE）** | **対応済み（表記回避）** | 原稿では「燃料消費量（L）×150円/L」を報告し、CO₂は排出量（kg）または複数係数で併記する方針（[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L59)）で12/20原稿上の誤認は防げる。 |

---

## 2. 改訂案に新しく生じた問題（重点：実行可能性・クラスタ経路・計算量・日程を含む、重い順に8件）

### 問題1（最重大・実行可能性）：クラスタ実行で「便割当を固定してStage 2＋毎時立て直しのみを解く」経路が現在つながっていない
- **現状の根拠**：
  1. クラスタ受付（[bff/routers/cluster.py](file:///C:/master-course/bff/routers/cluster.py#L195-L196)、[bff/services/cluster/scheduler.py](file:///C:/master-course/bff/services/cluster/scheduler.py#L368-L369)）は `use_existing_duties=True` と `rebuild_dispatch=True` を `ValueError` で明示的に拒否する。
  2. `use_existing_duties=False` かつ `rebuild_dispatch=False` のとき、[bff/routers/optimization.py](file:///C:/master-course/bff/routers/optimization.py#L11663-L11671) は `scenario["duties"] = []` に空初期化するため、[ProblemBuilder._build_baseline_plan_from_scenario](file:///C:/master-course/src/optimization/common/builder.py#L4270-L4278) は `None` を返し、`problem.baseline_plan` は貪欲法（`_build_baseline_plan`、[builder.py](file:///C:/master-course/src/optimization/common/builder.py#L1396)）で作られる（rc42の便割当にはならない）。
  3. 既存ソルバには `mode="phase1_charging_only"`（[bff/services/optimization_run/execute.py](file:///C:/master-course/bff/services/optimization_run/execute.py#L26)、[L117-L134](file:///C:/master-course/bff/services/optimization_run/execute.py#L117-L134)）があり、[GurobiMILPAdapter._solve_charging_only](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L13464-L13527) はStage 1を飛ばして `config.fixed_assignment` でStage 2（`_solve_thesis_stage2_charging_dispatch`）だけを解く。**しかし [bff/routers/optimization.py](file:///C:/master-course/bff/routers/optimization.py#L12131-L12137) はリクエストの `stage1_seed_plan` を `opt_config.stage1_seed_plan` にしか入れず、`opt_config.fixed_assignment` は `None` のまま放置する**。そのため現状で `mode="phase1_charging_only"` を呼ぶと、[solver_adapter.py](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L13476-L13486) が貪欲法の `problem.baseline_plan` にフォールバックし、rc42固定にならない。
  4. さらに [tools/research/weekly_campaign.py](file:///C:/master-course/tools/research/weekly_campaign.py#L85-L98) は `mode="mode_milp_only"` をハードコードし、`stage1_seed_plan` を埋め込む機能を持たない（rc42/rc43の [batch.json](file:///C:/master-course/output/midterm_20261128/rc43/eob400/2025-01-06/batch.json#L10-L26) は別経路で `stage1_seed_plan` を直接JSONに埋め込んで生成されている）。
- **具体的な直し方**：
  - [bff/routers/optimization.py](file:///C:/master-course/bff/routers/optimization.py#L12131-L12137) で `stage1_seed_payload` を復元した `restored_seed_plan` を、`phase_token == "phase1_charging_only"` のときは `opt_config = replace(opt_config, stage1_seed_plan=restored_seed_plan, fixed_assignment=restored_seed_plan)` として両方渡す（約5行の修正）。
  - これにより、`cluster.py` の `use_existing_duties=False` 契約・ポータブルパス検査（[scheduler.py](file:///C:/master-course/bff/services/cluster/scheduler.py#L33-L52)）・バッチ監査（[tools/cluster/audit_batch.py](file:///C:/master-course/tools/cluster/audit_batch.py#L52-L54)：`stage1_seed_plan` は `_run_optimization` のトップレベル引数 `kwargs` に含まれないため不一致エラーにならない）をすべて無改造で通過し、`batch.json` の `"mode": "phase1_charging_only"` ＋ `"stage1_seed_plan": <rc42の便割当>` でStage 1（上限3時間）を完全スキップできる。

### 問題2（重大・実行可能性）：`prepare_week` の入力契約が実験1（並び替え）・実験2（F1）・実験3（P10）を拒否または上書きする
- **現状の根拠**：
  1. クラスタ前処理 [prepare_week](file:///C:/master-course/bff/routers/cluster.py#L123-L173)（[output/midterm_20261128/prepare_ahead.py](file:///C:/master-course/output/midterm_20261128/prepare_ahead.py#L55) から呼ばれる）は内部で [prepare_date_series_scenario](file:///C:/master-course/bff/services/date_series_inputs.py#L190-L294) を実行し、`pv_capacity_factor_by_date` をSolcastアーカイブと `training_only_forecast_proxy` から**毎回再生成して上書き**する（[date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L258-L275)）。
  2. `pv_information_mode` は `'historical_perfect_information'` と `'training_only_forecast_proxy'` の2値しか許さず、他は `ValueError('Unknown PV information mode')` で落ちる（[date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L260-L268)）。
  3. `prepare_week` 実行後に `prepared.json` の中身を書き換えると、`scenario_hash` と `prepared_input_id` の整合検査（[bff/routers/cluster.py](file:///C:/master-course/bff/routers/cluster.py#L183-L192)、[scheduler.py](file:///C:/master-course/bff/services/cluster/scheduler.py#L347-L363)）で弾かれる。また [dated_capacity_factors](file:///C:/master-course/src/optimization/common/date_series.py#L156-L160) が `[row.get('date') for row in rows] != list(service_dates)` を厳密検査するため、実験1で日射日を並び替える際は各要素の `'date'` キーを対象営業日に書き換えつつ元の観測日を別フィールドに記録する必要がある。
- **具体的な直し方**：
  - `prepared.json` を事後編集してはならない。[bff/services/date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L258-L288) の `prepare_date_series_scenario` 内に、①日射日付置換リスト（実験1用）、②予報モード拡張（実験2の `known_weather_class_climatology`、実験3の `training_only_p10_proxy`）を正規分岐として実装してから `prepare_ahead.py` で `prepared.json` を生成すること。

### 問題3（重大・比較の歪み）：「どのrc42解の便割当を固定するか」が未確定であり、上限別固定と単一固定で意味が逆転する
- **現状の根拠**：[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L24)は「どのケースの解を使うかは事前に決めて記録する」とだけ書くが、rc42では季節ごとに200 kWと400 kWでStage 1が選んだ便割当（BEV担当便と使用台日数）が異なる（例：春2025-04-07週は200 kWが202台日・BEV便率93.43%に対し、400 kWは204台日・93.72%：いずれも [deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L160-L205)、[L280-L325](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L280-L325)）。
- **具体的な直し方**：
  - 季節ごとに**単一の基準便割当（原則として受電制約で歪んでいない「rc42・400 kW」の便割当）**に統一し、同じ季節の200 kWと400 kWの両方に同一の便割当を与えること。上限ごとに別々の便割当を固定すると、200 kW vs 400 kWの差に再びStage 1の台日差（1台日＝2万円）が混入する。

### 問題4（重大・実験1の交絡）：初期SOC 38.1%の放置が実験1（B：晴→雨 vs 雨→晴）の結論を直接歪める
- **現状の根拠**：鶴巻営業所のBEV 36台のうち12台は週初（Day 0朝）の初期SOCが50%未満（最低38.1%＝119.67 kWh、[prepared.json](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/prepared.json)）で始まり、Day 0終了時までに翌朝目標90%（282.6 kWh）へ引き上げることが強制される。つまり**Day 0だけは全車で約2.2 MWhの「初期SOC回復用の追加充電」が重なる特殊な日**である。
- **なぜ問題か**：実験1で「前半晴（Day 0〜2が晴） vs 前半雨（Day 0〜2が雨）」を比較すると、初期SOC回復の巨大負荷が当たるDay 0が晴か雨かによって系統買電とピークが大きく変わる。これは「7日間の日射の並び順（先読み・蓄電）の効果」ではなく、「週初だけ初期SOCが38〜80%と低い境界条件のアーティファクト」である。
- **具体的な直し方**：
  - 実験1（B）を実施するなら、①Day 0の初期SOCを翌朝目標と同じ90%（または90%×0.98）に揃えるか、②初期SOCを変えない場合は**Day 0のコスト・買電量を集計から除外し、毎朝90%に揃ったDay 1〜Day 6（6日間）で並び順を定義・比較**すること。

### 問題5（重大・実験設計の穴）：ローリング窓端の車載SOC目標が「前日計画の予測軌跡」に下限拘束されている
- **現状の根拠**：[監査のまとめ_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/監査のまとめ_20261121.md#L18)で「未確認」とされていた [src/optimization/rolling/reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L530-L607) を確認した。`rolling_window_terminal_policy == "day_ahead_boundary_state"`（現在の全ケースの設定）では、毎時の24時間先読み窓の終端時刻 `boundary` における各BEVのSOC目標 `targets[vid]` を**週初Stage 2計画のSOC軌跡 `plan.vehicle_soc_kwh_by_vehicle_slot[vid][boundary]` に固定**し（[L562-L565](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L562-L565)）、[soc_helpers.py](file:///C:/master-course/src/optimization/common/soc_helpers.py#L279-L296) と [solver_adapter.py](file:///C:/master-course/src/optimization/milp/solver_adapter.py#L16288-L16290) で `terminal_soc >= target_soc`（下限拘束）として課している。
- **なぜ問題か**：
  1. **実験2（A：F2完全予見 vs F0平年値）**：F2は「週初Stage 2が実測PVを知っている」だけでなく、「毎時のローリング窓端目標 `targets[vid]` も実測PVに最適化された軌跡になる」二重の優位を持つ。
  2. **実験3（C：80%への緩和）**：週初Stage 2を90%で解き、ローリング時だけ `final_soc_target_percent=80` に変えても、[reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L565) が週初Stage 2の90%軌跡から窓端目標を作るため、**窓端では80%に緩和されない**。
- **具体的な直し方**：
  - 実験3で「前日計画は90%目標、当日立て直しは80%許容」を実装する際は、[reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L565) の `targets[vid]`（窓端目標）と [L628](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L628) の `_freeze_bev_terminal_soc_targets`（週終端目標）に緩和幅（例：$\max(\text{floor}, \text{trace}[boundary] - 0.10 \times \text{cap})$）を反映するか、`rolling_window_terminal_policy="return_to_evaluation_initial"` と比較すること。

### 問題6（中・実験1〜3の対象設定）：冬200 kWは契約超過ゼロではなく最大690 kW（+490 kW超過）の破綻領域である
- **現状の根拠**：[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L18)は「上限をほぼ守れる200 kWと余裕のある400 kWの2水準に絞る」とするが、rc42の200 kW冬（2025-01-06週）はピーク受電**690.47 kW**、契約超過エネルギー**2,126.97 kWh**、超過罰金**1,063,485円**（総費用の63.8%）が発生している（[deck_data_rc42_et.json](file:///C:/master-course/outcome/2026-11-12_three_party/deck_data_rc42_et.json#L2086-L2096)）。春・夏・秋の200 kWもピーク211〜221 kWでわずかに超過している。
- **具体的な直し方**：
  - 200 kWを十把一絡げに「ほぼ守れる上限」と記述してはならない。春・夏・秋200 kWは「境界領域（超過11〜21 kW）」、冬200 kWは「200 kW枠では物理的に不足し500円/kWh罰則が作動する不足領域」と明確に区分して解釈すること（実験2・3を春・冬の2季節に絞るなら特に重要）。

### 問題7（中・計算量と日程の見積もり）：「1件約2時間」は `phase1_charging_only` 実装が前提であり、未実装なら1件3.7〜5時間かかる
- **現状の根拠**：実測ログ（[rc43/eob400/2025-01-06/results/weekly_summary.json](file:///C:/master-course/output/midterm_20261128/rc43/eob400/2025-01-06/results/weekly_summary.json#L12-L41)、[state/batch-state.json](file:///C:/master-course/output/midterm_20261128/rc43/eob400/2025-01-06/state/batch-state.json#L1-L25)、および [rc42/etb400/2025-01-06/results/weekly_summary.json](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/results/weekly_summary.json#L12-L41)）を確認すると、1週間の実行時間内訳は以下の通り：
  - **Stage 1**：`10,803秒`（3.0時間上限張り付き）
  - **Stage 2**：rc42（規則方式）で `912秒`（15分）、rc43（BESS計画方式）で `3,600秒`（1.0時間上限張り付き）
  - **毎時ローリング175回**：rc42で平均9.0秒×175＝`1,568秒`（26分）、rc43で平均19.2秒×175＝`3,356秒`（56分）
  - **合計壁時計時間**：Stage 1込みだとrc42で**3.7時間/件**、rc43で**5.0時間/件**。一方、問題1の修正でStage 1を本当にスキップ（`stage1_runtime_sec=0`）できれば、規則方式（実験1〜3）は **Stage 2（15〜60分）＋ローリング（26〜40分）＝約0.7〜1.7時間/件**、BESS計画方式（実験4〜6）は **Stage 2（60分）＋ローリング（56分）＝約2.0時間/件** で完了する。
- **日程への影響**：
  - [研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L40)、[L50-L52](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L50-L52)の「1件約2時間、38件を6並列で約13時間」という見積もりは、**問題1の `phase1_charging_only` 接続を完了した場合に限り現実的**（むしろ実験1〜3は6並列で7〜11時間で終わる）。逆にStage 1を止めずに `stage1_seed_plan` だけ渡すと38件×3.7〜5時間÷6並列＝24〜32時間かかり、失敗再投入を含めると日程を圧迫する。
  - ただし、`11/22〜11/26` の5日間に「問題1（固定配車接続）＋問題2（B・A・Cの入力生成分岐3種）」を同時実装するのは手戻りのリスクが高い。**12/20原稿用の1本（第4節で選ぶ実験）だけを11/26までに実装・投入し、残りの実験は12/20以降に回す日程**に絞るべきである。

### 問題8（小〜中・実験5と実験6の干渉）：実験5でBESS終端単価 $v>0$ を選んだ場合、実験6（途中の朝の蓄電池目標緩和）は空振りする
- **現状の根拠**：現在、7日間評価におけるBESSは `bess_balance_period="evaluation_period"`（[prepared.json](file:///C:/master-course/output/midterm_20261128/rc43/eob400/2025-01-06/prepared.json)）かつ `rolling_bess_terminal_policy="minimum_only"` で動いており、そもそも**途中の朝（Day 1〜6）に蓄電池を初期残量へ戻す日次目標は課されていない**（週終端Day 7のみ）。したがって、実験6（[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L39)）で「途中の朝の目標を緩める」対象になり得るのは**車載電池（毎朝90%目標）のみ**であり、蓄電池ではない。
- **具体的な直し方**：実験6の記述から「蓄電池の途中の朝の目標緩和」を削り、「車載電池の途中日の朝目標（Day 1〜6は80%、最終日Day 7は90%）の緩和」と正確に定義すること。

---

## 3. 中心の問いと実験1〜6の組み合わせで、新規性・有用性・創造性は十分か

中心の問い（「不確実で偏りのある太陽光発電と契約電力上限のもとで、固定ダイヤの電気バス群と営業所蓄電池をどう計画・立て直せば、運行と翌朝充電を破綻させずに電力費用を抑えられるか」、[研究計画_改訂案_20261121.md](file:///C:/master-course/outcome/2026-11-21_research_audit/研究計画_改訂案_20261121.md#L16)）に対し、**Stage 1の整数ギャップノイズを除去して充電・蓄電・立て直し制御の純粋比較に集中したことで、修士論文としての説得力と有用性は大きく向上した**。ただし、新規性・創造性を確かなものにするため以下の3点を調整すべきである。

1. **【足すもの】実験2（A：予報精度）と実験3（C：慎重計画＋朝目標緩和）を別々に終わらせず、「予報誤差に対するロバスト運用の組み合わせ（2×2交差、計4件）」を1季節（春200 kW）だけでも入れる**
   - 現在の実験1〜3は「日射の並び（B）」「予報の種類（A）」「控えめな計画と朝目標緩和（C）」が互いに独立した単発実験になっている。査読者が最も知りたい創造的な知見は、**「平年値予報（F0）しか使えない現実条件でも、慎重見積もり（P10）＋当日朝SOC 80%許容（C）を組み合わせれば、天気区分予報（F1）や完全予見（F2）との差をどれだけ埋められるか」**である。春200 kWで F0/F1 × 標準/緩和 の4通りを比較すれば、論文の核となる強い主張が作れる。
2. **【削るもの】実験1（B：日射の並び替え20件）は12/20原稿から外し、修士論文の補足分析（1季節・初期SOC均一化後の6件程度）に縮小する**
   - 日射時系列を人工的に並べ替える実験は「環境の性質（どれほど困るか）」を示す感度分析であって、「どう計画・立て直せばよいか」という提案手法（制御則・計画法）の貢献ではない。しかも問題4の通りDay 0の初期SOC 38%問題と強く干渉するため、20件回す優先度は最も低い。
3. **【足すもの】料金指標と物理指標の二層報告の徹底**
   - 料金A（500円/kWh罰則）のもとでの「総費用（円）」だけでは、改善が「買電時間帯のシフト・PV自家消費の増加」によるものか「500円/kWhの超過罰金回避」によるものか区別できない。すべての比較表で**①系統買電量（kWh）、②最大受電電力（kW）と上限超過電力量（kWh）、③PV自家消費率（%）、④罰金除き電力量料金（円）**の4つの物理・会計指標を必ず並記すること。

---

## 4. 12/20 の原稿に入れる対照実験として、実験1〜3のどれが最もよいか（1つ選択）

- **選択：実験2（A：太陽光予報の詳しさと価値：F0平年値 vs F1天気区分別平均 vs F2実測完全予見、計12件）**
- **選ぶ理由**：
  1. **既存の柱A（rc42）との接続が最も自然で、原稿のストーリーが一本に通る**：rc42はすでに `training_only_forecast_proxy`（F0：平年値予報で計画し、実測PVで毎時立て直す）で計算されている（[prepared.json](file:///C:/master-course/output/midterm_20261128/rc42/etb400/2025-01-06/prepared.json)）。したがってrc42の200 kW・400 kWはそのまま実験2のベースライン（F0）に対応し、「柱Aの知見（受電上限の影響）＋予報情報の価値（F0→F1→F2）」として12/20原稿に違和感なく統合できる。
  2. **実装リスクと既存制約との衝突が最小**：
     - 実験1（B）は問題4（Day 0初期SOC 38%による前半晴/雨の非対称バイアス）と問題2（日付置換契約）を抱える。
     - 実験3（C）は問題5（[reoptimizer.py](file:///C:/master-course/src/optimization/rolling/reoptimizer.py#L565) の窓端目標 `day_ahead_boundary_state` が週初計画の90%軌跡を拘束し続ける問題）を改修しないと「当日だけ80%に緩める」挙動が正しく動かない。
     - 一方、実験2（A）は車載SOC目標（90%）やローリング規則を一切変えず、[bff/services/date_series_inputs.py](file:///C:/master-course/bff/services/date_series_inputs.py#L260-L268) の予報プロファイル生成（F0・F1・F2）を切り替えるだけで、同一の実測PV・同一の固定便割当・同一の終端SOC条件のもとで純粋な比較が成立する。
  3. **計算時間が最短（12件＝6並列で約2〜4時間）**：11/26までに問題1（`phase1_charging_only` の `fixed_assignment` 接続）とF1予報生成だけを実装・検証すれば、11/27〜11/28の1日で全12件の計算と集計が完了し、12/20の提出期限に対して最も安全性が高い。
