# モデル・月別シナリオの修正（実行保留）

2026-09-19。ユーザーの「修正は進めるが、シミュレーションは開始しない」に従い、コード・設定・求解を伴わない回帰テストまで実施した。新しいPrepare、day-ahead、rolling、監視、メール送信は開始していない。

## 修正した問題

| 問題 | 修正 | 検証 |
|---|---|---|
| BESS終端を明示的に `fixed_target=0 kWh` としても、共通モデルが目標なしに変換していた | 0も有効な等式目標として保持。方針未指定・目標なしの旧入力は従来どおり下限のみ | 修正前に2件失敗を再現。目標解決・残量50 kWhの逸脱検出・rollingの目標凍結を確認 |
| シナリオAPIが明示した初期残量0を既定の容量50%へ置き換え、固定終端0も拒否していた | 未指定と明示0を区別。kWh・ratio・percentを扱い、物理下限未満の目標は拒否 | API正規化→ProblemBuilder→共通目標解決を求解なしで確認 |
| 月別準備処理がdesignに関係なくBESS終端・rollingを `minimum_only` に固定していた | designの対応条件をconfig・overlay asset・日付契約へ伝達。検証側も復元目標を照合 | 旧下限のみ、新しい初期残量復元、契約不一致の拒否を確認 |

既存月別12週はBESS下限1,200 kWh・初期3,000 kWhの `minimum_only` であるため、今回の「明示0」の欠陥が既存12週の受電ピークを生んだという説明はしない。

## 到達する実装経路

- シナリオ保存: `bff/routers/scenarios.py:normalize_depot_energy_asset_config` → 保存済みsimulation/overlay → `ProblemBuilder` → `DepotEnergyAsset`。
- 月別経路: `run_exact_seasonal_campaign.py:run_campaign` → `prepare_week` → `configure_doc` → Prepare → `run_diagnostic` → `solve_week` → `ProblemBuilder` → `OptimizationEngine` → Phase 3 Stage 2。
- 終端: `resolve_bess_terminal_soc_target_kwh` をMILP、rollingの目標凍結、独立 `FeasibilityChecker`、`_build_executed_day_accounting` が参照する。MILPは戻り値が `None` でなければ `E_end = target` を課す。0の保持によりこの等式と逸脱検出が欠落しなくなる。
- 確定費用の唯一の根拠は、受理された実行後の `executed_day_accounting.json` のまま。今回は新規実行・新規会計を生成していない。

## 新しい比較候補

[保留中の全12週設定](../../config/shibu21_23_monthly_cyclic_draft_20260919.json)を別ファイルに作成した。元の固定 `7c7c2334` の設定ファイルと結果は変更していない。新設定には元設定のSHA-256を記録した。

| 条件 | 旧12週 | 新候補（未実行） |
|---|---|---|
| 評価日・曜日構成 | 2025年の各月1週、平日5＋土曜1＋日祝1 | 同じ12週 |
| BESS運転範囲 | 20–80% | 同じ |
| BESS週末 | 下限以上（初期在庫の減少を許す） | その週の元の初期残量に復元 |
| 中間rolling窓のBESS | 下限のみ | 固定したday-ahead予測計画の同じ境界残量 |
| 毎日末のBESS復元 | 課さない | 課さない（evaluation_periodを維持） |
| 起動 | 完了済みの旧結果 | `execution_enabled=false` |

新候補は `E_week_end = E_week_start` を課し、週ごとに初期在庫を取り崩す効果を除く。ただし、rollingの中間目標も変わるため、旧結果との差を「週末の1制約だけの因果効果」と解釈しない。中間目標は将来実績PVを使わず、固定したday-ahead予測から取得する。実行可能性と予測誤差への対応は未検証である。

車両・時刻表・路線・距離・初期状態・PV予測入力・設備容量・単価・求解時間・seed・全接続・物理許容差は、この候補では変更していない。車両数は親シナリオの正確な有効集合から取得する。既存の親シナリオや準備済み入力も今回更新していない。

`return_to_initial` と `rolling_bess_terminal_policy=minimum_only` の組み合わせは週末目標まで消すため、この月別準備経路では拒否する。未対応のBESS方針・運転範囲も既定値へ黙って置換せず拒否する。

## 実行保留の扱い

新設定の `execution_enabled=false` は、campaign・diagnostic・共通 `solve_week` の入口で読み取り、シナリオの準備や求解より前に `EXECUTION_DISABLED` として停止する。JSON文字列の `"false"`、数値0などもbooleanとして受理しない。既存designでこの項目がない場合は従来の呼出し規約を維持する。このフラグは当該benchmark designの停止条件であり、アプリ全体の実行権限を変更するものではない。

実行を依頼された後に、設定確認・独立レビュー・新しいclean固定版からの全12週の新規Prepareと実行を行う。今回はフラグを有効にせず、起動コマンド・起動予約も作成していない。旧版の成功週を新条件の結果へ混ぜない。

## 検証と自己レビュー

関連9ファイルの **128 tests passed**（初回127件に加え、空欄と明示0の区別を追加して影響範囲37件を最終再検証）。対象はBESS目標、月別設定伝達、API保存、canonical builder、rollingの入力境界、campaign制御、週間曜日構成、予測入力契約。新しいrollingテストはエンジンを捕捉用の代替物に置換し、求解呼出しがあれば失敗させる。campaignテストもPrepare・solveを代替し、一時ディレクトリのみを使用する。

実行したテスト:

```text
tests/test_bess_terminal_policy.py
tests/test_monthly_bess_revision.py
tests/test_scenario_update_simulation_settings.py
tests/test_problem_builder_depot_energy_asset_controls.py
tests/test_shibu21_24_seasonal_diagnostic.py
tests/test_rolling_bess_boundary_policy.py
tests/test_run_exact_seasonal_campaign.py
tests/test_monthly_week_contract.py
tests/test_monthly_forecast_contract.py
```

自己レビューでは上記3点を修正し、対象変更の未解決P0/P1は確認していない。独立レビューは未取得。CIや全体テスト（実求解を含む）は実施していない。単体検証の通過を新条件の完走・研究採用と扱わない。

## 根拠が足りず、今回変更していないもの

- ピーク時にBESS残量があっても放電0となった原因。保存結果の観察だけではモデル欠陥や強制買電と断定できず、追加の目的関数・制約・探索状態の診断が必要。
- 200 kWの超過判定値と500円/kWhのペナルティ。実契約の根拠が未確認なので、実料金や物理的受電上限に置換していない。
- 空調負荷・気温依存電費、実道路距離、正式fleet来歴、Stage 1 gap未達。根拠のない係数追加や採用条件の緩和は行っていない。

研究採用は引き続き **BLOCKED**。今回のモデル・シナリオ変更の研究用検証は未実施。
