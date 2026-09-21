# BESSを運転範囲内で使い切れる方針

## 5月day-aheadの結果（2026-09-21 10:55 JST）

固定 `534aba0b0a8f8d906c8ad24014b122471afd965e` の診断は完了した。
completion→summary→5原本のSHA、native log、clean状態を照合した。
車両・充電の独立物理検証はVALID、違反0。Prepared inputの設備値を用いてBESSの
672 slotのエネルギー保存・20–80%境界・900 kW出力・同時充放電を追加確認し、違反0、
最大エネルギー収支残差0 kWhだった。初期・終端traceとslot間連続性も一致した。
確認原本は `output/bess_operating_range_20260921_launchfix/review.json`。

| 指標 | 結果 |
|---|---:|
| Stage1初回incumbent / 最終目的値 | 4,157,098.222019495円 / 同じ |
| Stage1探索による改善 | 0円 |
| native下界 / gap | 0円 / 100% |
| 解析下界を含む認証下界 / gap | 4,000,000円 / 3.77904% |
| Stage1求解時間 / 終了 | 600.568秒 / time_limit |
| 根LP | 524,253反復で時間切れ、OPTIMAL MIPNODEなし |
| Gurobi使用量：開始前→終了後 / 最大 | 2.185→7.735 GB / 12.599 GB |
| Stage2充電目的値 / gap | 0円 / 0% |
| 前日計画の総費用 | 4,157,027.3387472522円 |
| BESS初期→最終 | 3,000→1,238.847113218068 kWh |
| BESS正味取り崩し | 1,761.152886781932 kWh |
| BESS traceの最小 / 最大 | 約1,200 / 4,041.316776157117 kWh |
| 予測PV発電 / バス直接利用 | 31,515.09125 / 3,434.769517962077 kWh |
| PV→BESS / BESS→バス | 16,396.131979407033 / 16,470.604353857543 kWh |
| BESS充放電損失 | 1,686.680512331275 kWh |
| PV抑制 / 買電 | 11,684.189752630895 / 0 kWh |

これは7日分の予測を用いた前日計画であり、168時間のrolling実行結果ではない。
充電目的値0円は固定配車・予測PV・現行の費用設定での充電部分だけの値。
総費用の主成分は206車両日×20,000円=4,120,000円、燃料36,469.513141592884円、
CO2項557.8256056673491円。電力費の約-7.7e-9円は数値誤差で、負の電気料金という意味ではない。
PV/BESSの限界費用と設備費が0という仮定も保持している。
Stage1目的値とStage2後の総費用は別の記録であり、その差をStage1探索の改善と扱わない。

旧保護条件より費用水準と認証gapは下がったが、同一モデルの解改善ではない。
追加予備・終端復元を外した影響と初期在庫の取り崩しを含む。探索中の改善は0円、
配車1%目標は未達であり、最適性や月別の実績費用削減は未確認。
新しいBESS方針自体の前日計画成立は確認できたが、全期間の実行は別途必要。

## 次の限定診断

[NoRel診断設定](../../config/shibu21_23_bess_norel_diagnosis_20260921.json)を追加した。
初期解を改善できず根LPが600秒で未完了のため、既存の `bounded_presolve_norel` を試す。
NoRelHeurWork=120を有効にするほかは、端点表現、Method1、4threads、18GB、
Stage1 600秒/Stage2 120秒、seed42、1%目標、BESS物理範囲のみの方針を維持する。
以前のdense+NoRelはメモリ停止だった。端点表現で最大メモリが減ったことが再診断の根拠であり、
NoRelの成功や費用改善を保証するものではない。小規模の関連23 tests通過。

新しいclean固定版から5月のみ新規Prepareし、通常処理はscript、終了時だけ既存タスクへ通知。
旧結果は旧SHAの記録として残し、新版の結果へ転記しない。全12週・メールは開始しない。
自己レビューP0/P1残件なし、独立研究レビューPENDING、研究採用BLOCKED。

2026-09-21のユーザー指示「なくなったらそのままほっとけばいいし、いっぱいになったら抑制」に対応。
初期残量を予備として維持する条件と、評価期間末・rolling窓末に残量を戻す条件を外す。
既存の `minimum_only` / `physical_floor_only` 経路を利用する設定変更であり、ソルバーの物理制約や会計式は変更しない。

## 新しい条件

[新設計](../../config/shibu21_23_bess_operating_range_20260921.json)は次の方針を明示する。

| 項目 | 従来の保護条件 | 新しい方針 |
|---|---|---|
| 初期BESS残量 | 3,000 kWh（50%） | 同じ |
| 設備容量・運転範囲 | 6,000 kWh、1,200–4,800 kWh（20–80%） | 同じ |
| 運転中の追加予備残量 | 3,000 kWhを保護 | なし |
| 週末・rolling窓末 | 元の残量または参照残量に復元 | 1,200–4,800 kWh内ならよい |
| 利用可能量が空 | 予備残量を消費できない | 1,200 kWhまで使い、その後の放電は0 |
| 利用可能量が満杯 | SOC上限とPV抑制 | 同じ。余剰PVを抑制 |
| BESSへの系統充電 | 禁止 | 同じ |
| バスへの給電 | PV/BESS/系統、料金・超過料金を計上 | 同じ |

「空」は利用可能領域の下限であり、設備の0 kWhではない。物理SOC、出力900 kW、効率、
充放電同時実行禁止、エネルギー保存、バスのSOCと運行条件を維持する。
設定は `bess_terminal_soc_policy=minimum_only`、`rolling_bess_terminal_policy=minimum_only`、
`bess_forecast_reserve_policy=physical_floor_only`。初期値、時刻表、fleet、料金、完全後続網は変えない。

数式上は `E_min <= E[t] <= E_max` とエネルギー保存を維持し、追加の `E[t] >= E_initial`
保護および `E[end] = E_initial` 復元を要求しない。
放電・充電指令は求解時に物理範囲内で決める。実行時に不可能な指令を事後補正して成功扱いする変更ではない。
現在の発行済みブロックでは、未観測のPVを当てにした放電で物理下限を割らない制約が残る。
この下限は1,200 kWhであり、初期3,000 kWhの追加予備ではない。

## 経路と確認

設計 → `seasonal_bess_controls` → Prepareの `apply_seasonal_bess_policy` →
scenario config/overlay/date-series contract → Stage1/2 → rollingのterminal policy →
`execute_energy_slot` の既存経路を利用する。`minimum_only` は終端目標なし、
`physical_floor_only` は追加reserve targetなしとして扱われる。

実親scenarioから設定プレビューを生成し、親の前後SHA一致、1,200/4,800 kWh、初期3,000 kWh、
終端目標なし、系統からBESSへの充電禁止を確認した。
原本は `output/bess_operating_range_policy_20260921/scenario_policy_preview.json`、
確認記録は同ディレクトリの `policy_validation.json`。これは新規Prepareの完了証拠ではない。

関連136件を確認（既存131件通過、新規5件通過）。新規回帰は、設定から設備への反映、
rolling中間/期間末でBESS復元を求めずBEV目標を維持、利用可能量を使い切って待機、満杯でPV抑制、
Stage1の小規模nativeモデルで後続PVなしに初期在庫を利用できることを検証した。
実行不可能な過放電指令は引き続きエラーになる。全体テストはこの設定変更では繰り返していない。

## 比較と引継ぎ

初期在庫を消費できるので、費用が下がっても旧条件のソルバー改善額とは扱わない。
同じ初期条件で、開始・終了BESS kWh、差分、買電、PV利用・抑制、損失、実績会計を併記する。
終端差分を架空の発電・充電や金額補正で埋めない。週内の減少分は
`E_initial - E_end`（kWh、正は正味取り崩し）として別表示する。
初期状態が共通でも終端状態は異なるため、循環運用や年間平均費用へそのまま一般化しない。

新しい条件は未実行。09:45 JST開始の固定 `00aed18e` のdense/endpoint比較は、
旧BESS条件を共通にした表現比較として継続し、実行コード・入力・出力は変更しない。
その結果が届いたら、検証済みの表現を選び、この新しいBESS方針を新clean固定版へ反映して
新規Prepareから5月day-ahead診断を行う。設定の `execution_enabled=false` は現在の比較との
同時実行を避ける保留であり、ユーザーへ同じ方針の再承認を求めるものではない。
`output/stage1_support_20260921/next_action.json` にも引継ぎを保存した。

旧3,000 kWh保護専用の監査を新条件の合否判定へ流用しない。新条件では物理範囲・状態引継ぎ・
エネルギー保存・会計を検証する。全12週・メールは今回開始していない。
費用改善、実運用の全期間成立、最適性は未確認。自己レビューのP0/P1残件なし、
独立研究レビューPENDING、研究採用BLOCKEDを維持する。

## 10:27 JSTの表現比較終了後

固定00aed18eの比較は完了し、メモリ負荷の小さい端点表現を選択した。
新設計のstage1_sparse_charge_window_support=true、execution_enabled=trueへ更新。
BESSは上記minimum_only/physical_floor_onlyのまま、Stage1 600秒/Stage2 120秒、
4threads、18GB、gap1%の新規5月day-aheadだけを実行する。関連67 tests通過。
旧previewとpolicy_validationは保留時点の記録として保持し、新実行は別固定SHAと
新しい入力import/launch記録へ紐付ける。上記の「保留・実行中」は変更当時の経緯。

## 固定診断の開始記録

2026-09-21 10:34 JST、branch `codex/bess-operating-range-20260921`、
clean固定 `534aba0b0a8f8d906c8ad24014b122471afd965e` から5月day-ahead診断を開始した。
固定版で67 tests通過（5.61秒）、元入力47 SHAとscenario11参照の移設、caseのsource3参照、
minimum_only/physical_floor_only、端点表現trueとsolver設定を確認。実runner PID48300、
venv launcher50600。制御先 `output/bess_operating_range_20260921_launchfix`、
開始確認は `startup_verification.json`。出力は新worktreeの
`output/bess_operating_range_diagnosis_20260921`。通常処理はscript、終了時だけ既存タスクへqueue。

10:33の初回起動はローカルwrapperの設定名に余分な `_diagnosis` があり、ファイル読込みで
停止した。Prepare・求解は未実行、出力ディレクトリも未生成だった。正しい設定参照と
事前存在確認を加え、実行コードを変更せず再起動した。旧制御先
`output/bess_operating_range_20260921/failure_resolution.json` は
`RESOLVED_NEW_LAUNCH_STARTUP_VERIFIED`。旧completionの遅延通知では再診断・メールを行わない。
