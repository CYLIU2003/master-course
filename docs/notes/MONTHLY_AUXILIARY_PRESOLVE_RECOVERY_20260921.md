# 1月の充電計画停止と前処理設定の修正

旧固定 `a4b9c679` の月別計算は1月day-aheadで停止した。監視障害ではない。
Prepareは通過、Stage1は候補あり・memory_limit（1,475.21秒、gap3.728001%）、
Stage2は120秒time_limit・候補0。rollingは0/168、成功/監査0/12、2～12月は未実行。
`commands.log` は最初の完了週の監査に到達しなかったため未作成。
失敗した結果の費用0は利用可能な運行費用ではない。完了メールは送らない。

## 原因を分離した診断

制御先 `output/monthly_auxiliary_20260921/stage2_search_diagnosis/` に証拠を保存した。
保存された配車CSVから32台・1,704便のvehicle/trip順序を再構築・照合し、Stage1を再求解せず比較。
両MPSのSHA256は `bfb96ee8cb6a1cf557487972e9974aae5894053428a94c22e94e2e51688e710d`。
567,884制約・553,060変数・280,896二値変数・2,016 MIN制約。
Method1/MIPFocus1/Aggregate0/4threads/120秒/許容差1e-9は共通、変えたのはPresolveのみ。

| 条件 | 実行可能解 | 最初の候補 | 終了時間 | 充電部分のgap | 独立物理 |
|---|---:|---:|---:|---:|---|
| Presolve0 | 0 | なし | 120.157秒 | 未定義 | 候補なし・未実施 |
| Presolve2 | 2 | 37.234秒 | 59.639秒 | 0% | VALID、違反0 |

Presolve2の充電目的値は101,400.096733円、最大制約残差6.37e-12。
この金額は固定配車の充電部分であり、週間総費用やStage1の改善額ではない。
BESSの上下限・PV優先・余剰充電・追加予備/終端復元なしは変更していない。
解を得られない原因が少なくともこの配車では探索設定にあることを、同一モデルで確認した。

[Gurobiの一般制約](https://docs.gurobi.com/projects/optimizer/en/current/concepts/modeling/constraints.html)は
前処理で簡略化される場合がある。MIN制約追加後も前処理を止めたままの設定が今回には不利だった。
全月・全rollingで必ず成功するという証明ではなく、各ケースの物理/会計監査を継続する。
診断はnativeで設定変更したため、旧アダプタ由来のplan内Presolve表示0は実効値ではない。
実効値は各native JSON/logの2。製品経路では新しい明示設定からmetadataにも同値を保存する。

独立式でPrepared PV入力から672区間を再計算し、SOC収支・PVバス優先・余剰蓄電を確認した。
BESS初期3,000→終端1,200kWh、最高3,459.354435kWh、在庫取り崩し1,800kWh。
予測買電3,324.593336kWh、PV直接利用2,742.344590kWh、PV蓄電13,393.689910kWh、抑制0。
固定配車の予測総費用4,238,344.070110円（205車両日）。これは週間実績ではなく、
初期在庫取り崩しをPV由来の節約と扱わない。根拠は `stage2_search_diagnosis/evidence_review.json`。

## 修正と新規再実行

- `OptimizationConfig.stage2_gurobi_presolve` を追加。旧既定0、新設計で2を明示し、全月・全rollingに継承。
  Aggregate0、FeasibilityTol/IntFeasTol1e-9、同日路線・時刻・帰庫・バスSOC・BESSルールを保持する。
- Stage2 native logを出力し、解なし/成功の両方にパスを保存する。
  time_limitで存在しないIISを参照する説明を修正した。
- observerは最初の週の停止でも元の失敗理由・原本path/hashを保存する。
  監査は今回の明示Presolve設定との一致を要求し、旧設定の混入を拒否する。
- 関連143 tests通過。旧既定0と新設定2の境界値、真のSOC超過拒否、2日間計画/実行整合、
  native log、最初の週の失敗理由保存、月別設定・監視・報告を確認した。
- 設計 `config/shibu21_23_monthly_auxiliary_presolve_20260921.json`、制御先
  `output/monthly_auxiliary_presolve_20260921/`、新しい固定作業場所
  `C:/master-course-worktrees/monthly-auxiliary-presolve-20260921`。
  同じ12週を新規Prepareから実行し、旧版の結果を混ぜない。

新規起動SHA/PIDは今回の `budget_rerun_launch.json`、状態は `script_observer/state.json`。
通常処理はスクリプトのみ。完了時の338原本/週のBESS監査と実図確認後、承認済み
`g2681320@tcu.ac.jp` へ1通送信。旧失敗イベントの再処理・完了メールは不要。
Stage1のメモリ/gap、週間統合最適性、独立研究承認は未解決。研究採用BLOCKEDを維持する。

## 修正箇所の自己レビュー

2026-09-21、Codexによる自己レビュー。設定の入口→solver→rolling継承→保存原本→監査の
到達経路、真のSOC超過拒否、失敗時の原本保存を確認した。対象変更の未解決P0/P1は0。
宣言条件と実効metadataの照合を維持し、旧出力を流用しない構成を確認。
143件の対象テストと差分検査を実施。追加CI/有料サービスは起動していない。
独立レビューは未実施であり、自己レビューを独立承認や研究採用と扱わない。
