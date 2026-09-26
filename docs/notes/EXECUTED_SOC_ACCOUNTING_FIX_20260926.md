# 実行済みSOCによる終端会計判定（2026-09-26）

## 原因と変更

ea72251a7ec69341ccad4e2dc698e500a8bcc7e8 の2月試行
`febdd18e-f380-5236-b419-d54a8a130f54` は174/174窓、695/695区間を実行したが、
最終会計の `bev_terminal_energy_not_balanced` でFAILEDになった。最大使用メモリは
13.165 GiBで、16 GiBのタスク予算内。今回の停止はメモリ不足ではない。

各窓の**予測期間末尾の在庫一致フラグ**を全窓ANDしていた。45窓のfalseは
fixed_target下限を上回る予測在庫で、最大短不足は丸め誤差3.748e-10 kWhだった。
fixed_targetは下限、return_to_initialのみ等式という既存モデルと会計判定が不一致だった。

`scripts/run_hourly_charging_reoptimization.py` の最終会計は新しい
`src/optimization/common/executed_soc.py` で、採用済み区間を結合したSOCから、
元の評価期間末尾の目標・運用上下限・各営業日の翌朝出庫前の運用最大を検査する。
return_to_initialの余剰も拒否し、欠損・非有限値も拒否する。対象は経路・充電・SOC記録の
ある車両（固定配車Stage2のassigned BEV契約と同じ）。未稼働車まで終端充電する新条件は加えない。
元の予測フラグは `lookahead_bev_inventory_balance_all_windows` に保存する。
`bev_terminal_energy_balanced` は互換性のため残る名前で、実行済み終端方針の充足を表す。
初終端の在庫一致や全体最適性を意味しない。

呼出経路は週次campaign→cluster worker→既存最適化入口→rolling chain→
hourly runner→executed accounting。ソルバーの制約・許容差・便・SOC/BESS方策・料金は変更しない。
料金や物理量を補正して合格させない。旧FAILED原本は保持する。

別途、rollingの暦監査表示が日付別7日入力を単一の旧service_id（SAT）と比較していた。
canonical `service_calendar_validation_v2` のstatus・errors・日付一覧・hashを利用するよう修正。
不正なv2はERRORとし、単一曜日へのfallbackはしない。日付連続性と原本hash照合は既存builderの責務。
時刻表の再取得・改変・再生成はしていない。

## 原本再検算で得られた1週の結果

原本ZIP SHA256: `e8891f3e9147f4219a88b081294afedbff2ab49e5296641d5cb8b7e75602904c`。
全1,205ファイルのhash、再構築problemのtrip/vehicle input hashが一致。
`output/daily_soc_20260926/terminal_diagnosis/replay.py` はEnv/Modelをfail-fast化し求解0回で
174窓を再集計。独立したイベント物理検査は違反0、FeasibilityCheckerも可行。
BESS695区間の収支最大残差0 kWh。これは旧SHAの原本の後処理再検算であり、新SHAの求解ではない。

対象は2025-02-03～09＋費用込みの最終翌朝（02-10 05:45まで）。

| 指標 | 値 |
|---|---:|
| 便数／営業km | 1,704便／13,925.428829 km |
| 週次費用 | 4,776,386.715807 円 |
| 車両使用費／206車両日 | 4,120,000 円 |
| 買電費 | 110,646.491060 円 |
| 燃料費（在庫消費評価） | 37,385.221659 円 |
| CO2費 | 2,488.603236 円 |
| 契約基準超過費 | 505,866.399851 円 |
| 円/営業km／円/便 | 342.99746／2,803.043847 |
| 買電量／最大受電 | 3,688.216369 kWh／702.210947 kW |
| PV供給可能量／抑制 | 21,340.7375／1,080.796956 kWh |
| BESS初期→終端 | 3,000→2,468.407473 kWh |

使用BEV26台は各282.6 kWhに到達。日々の状態リセットなし。
初期BESS在庫531.592527 kWhの取り崩しをPV効果や恒常的節約と扱わない。
受電設備は仮定値、電費一定、距離は代理距離、未計上設備費あり。
Stage1は時間上限・gap100%（下界0）。統合週次gapは未算出。最適性・12週完了・研究採用は未証明。

成果物: `output/daily_soc_20260926/terminal_diagnosis/reevaluation/` の
weekly_summary.csv、daily_summary.csv、energy_15min.csv、vehicle_soc.csv、
vehicle_schedule.csv、charging_schedule.csv、weekly_energy_soc.png、manifest.json。
図は実表示で日本語・単位・期間・在庫推移を確認済み。

## 検証と運用

関連104テスト通過、共有ライセンス入場を要するnative1件skip、native2件deselect。
return_to_initialの初期65%と設定80%を分けたテストを追加。
日次期限helperの境界テストと実174窓の物理検算を併用した。
Claude Code（claude-opus-5-5）の読み取り専用独立レビューは指定変更範囲P0/P1なし。
レビューは原本再計算そのものを実施していない。研究採用の承認ではない。
初回の関連確認中にはnative2件も通過したが、共有broker経由の実機試験とは数えない。

新しいclean固定版から新規Prepareし、まず2月をend-to-endで確認する。
旧試行のPID不在・既存queueのactiveゼロを確認してから切り替える。
成功後だけ既存スクリプトが残り11代表週を新規Prepare・投入する。
32 GiB以上のGurobi機器、タスク16 GiB・native hard14/soft12.6 GiB、空きRAM/commit余裕、
同時ライセンス管理を維持する。通常監視は読み取りスクリプト、終端だけ通知する。
配置・起動結果は運用出力のreceiptで確認し、本文の予定を実施済みとは扱わない。
