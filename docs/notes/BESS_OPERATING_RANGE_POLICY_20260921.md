# BESSを運転範囲内で使い切れる方針

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
