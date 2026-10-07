# 4. 原結果の確認から表・図・考察へ

## 最初に読むもの

今回の入口は `C:/master-course/output/executed_soc_20260926/monthly_report/latest.json`。

1. `complete`、`included`、`declared`、`observed_at_utc` を確認する。
2. `directory` が示すrevisionの `comparison.json`、`manifest.json`、`report.md` を読む。
3. 各caseの `included`、元state、回収・復旧記録、計算SHA、Prepared・原ZIP・費用の出典を照合する。
4. 物理、会計、末尾区間、図表、研究採用を別々に判断する。

2026-10-06の確認対象revisionは
`6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd`。
12週が条件付き週次評価として含まれている。古いcampaign親stateのRUNNINGやSUBMITTEDだけで不足週と判断しない。

1・11・12月の原worker FAILEDと報告復旧履歴は残る。古い親campaignのcase stateと原workerの終端stateは別の記録である。対応は次のとおり。復旧先は `output/executed_soc_20260926/report_recovery/` を基準にする。

| 月 | 親campaign内の保存case state | 原worker | 最新比較の出典 | 復旧receipt |
|---|---|---|---|---|
| 1 | FAILED_OR_UNVERIFIED | FAILED | REPORTING_RECOVERED | `january-weekly-v2/recovery.json` |
| 11 | SUBMITTED | FAILED | REPORTING_RECOVERED | `november-weekly-v1/recovery.json` |
| 12 | SUBMITTED | FAILED | REPORTING_RECOVERED | `december-weekly-v1/recovery.json` |

原workerの失敗ラベルをCOMPLETEDに上書きせず、同じZIPで物理・会計・計画が確認でき、別出力で図表を復旧した範囲を区別する。判定の文章だけでなく出典hashと原本を確認する。ほかの9週の出典も比較JSONのcase/evidenceで確認する。

## 必須成果物と対応

| 成果物 | 内容／読取単位 |
|---|---|
| `experiment_index.csv` | 日付、scenario、SHA、worker、状態、再利用・復旧 |
| `weekly_summary.csv` / 各週`weekly_summary.json` | 全期間の費用内訳、便数、営業km、電力量、BESS、求解情報 |
| `daily_summary.csv` | 営業7日と末尾翌朝の区別、日別費用とエネルギー |
| `energy_15min.csv` | 買電、PV→バス/PV→BESS、BESS→バス、抑制、バス充電、BESS残量 |
| `vehicle_schedule.csv` / `charging_schedule.csv` | 全車両の便・回送・充電、時刻と占有 |
| `vehicle_soc.csv` / `fleet.csv` | 全BEVのSOCと入力車両集合・パラメータ |
| 原実行会計・物理レポート | 数字と制約判断の出典。コピーのhashを保持 |
| manifest | 原本、相対/絶対パス、SHA256、元run/attempt、検査範囲 |

名称が似た旧実験のファイルを使わない。今回の保存済み発表証拠は
`outcome/2026-09-28_september_presentation/evidence/<週開始日>/`。
このフォルダはCSV・会計・検証レポート等を含むが、元の巨大solver ZIP全体をすべて複製したものではない。

## 費用の正本

採用済みRollingの正本は原成果物の
`rolling_hourly_chain/executed_day_accounting.json`。
名前にdayとあっても、このdriverでは週と末尾を含む実行範囲を確認する。

- 便充足、重複、実行区間、充電・燃料・日別会計を原計画と照合する。
- 全期間の日別費用の和と最終総費用は1e-6円以内で一致させる。
- 7日672区間に `overnight.extra_slots` を加えた範囲を確認する。今回695/697区間。
- 毎時窓の目的値、Stage 1代理目的、固定配車Stage 2費用を合算して最終費用を作らない。
- CO₂図の照合警告だけなら会計と図の状態を分ける。本体の物理量・会計不整合なら無視しない。原本から再集計する。
- 未計上設備・保守等は未計上と書く。欠損費用を0で埋めない。

原結果を確認して再集計可能なら、グラフの失敗で再求解しない。現在の `weekly_collection.py` は会計・CSVを保持し図表状態を別に扱う経路があるが、稼働固定版との違いは照合する。旧失敗の原因を確認せず新しい描画を実行して成功扱いにしない。

## 既存結果を別出力へ再集計する

[実行手順](03_RUNBOOK.md)の `$repo`、`$experiment`、`$solverPython` を用意する。次は新しい月別報告を生成し、新規求解しない。

```powershell
& $solverPython -X utf8 "$repo/tools/research/monthly_campaign_report.py" `
    --operation "$experiment/operation.local.json" "$experiment/operation.remaining.local.json" `
    --reporting-recovery "$experiment/report_recovery/january-weekly-v2" `
    --reporting-recovery "$experiment/report_recovery/november-weekly-v1" `
    --reporting-recovery "$experiment/report_recovery/december-weekly-v1" `
    --output '<新しい報告出力ディレクトリの絶対パス>'
```

operationと復旧記録が原本の同じSHA・親hashへ対応することを確認する。現在の観測で追加のoperations recoveryが参照される場合は、比較JSONの各caseの出典も照合する。渡した復旧だけで全FAILEDの成功化を保証しない。

再集計が12件未満なら、その時点で再求解しない。上表とlatest revisionの出典・receipt・原本アクセスとの差分を特定して報告する。原本の読取不足と求解の不足を混同しない。

`--watch` は監視を続ける追加指定。同じ出力へ監視を多重起動しない。現行コードは、比較が完了したか全対象campaignが終端になった時に監視を終了する。一つが失敗しただけで、別campaignの回収を止める旧挙動へ戻さない。

現在の月別結果をPPT用CSVと証拠へ変換する既存入口：

```powershell
& $solverPython -X utf8 "$repo/tools/thesis_authoring/prepare_september_evidence.py" `
    --report "$experiment/monthly_report" `
    --output '<新しい発表証拠フォルダの絶対パス>'
```

9月・12週の固定資料用で、任意scenarioの正式採用を認証する汎用validatorではない。必要な原ZIP、Prepared、復旧receipt、Solcast保存原本が存在する時に使用する。原本を読めない場合はhashだけで新しい独立監査をしたとしない。

## 既存追加分析を使う

[2026-10-03の追加分析](../../../outcome/2026-10-03_research_review/README.md)には12週の費目分解、日別電力量、4月・5月比較、5/12〜13の需給・BESS図がある。まずそれを読む。

同じ固定証拠を再集計する標準ライブラリの入口：

```powershell
& $solverPython -X utf8 C:/master-course/outcome/2026-10-03_research_review/analyze_existing_weeks.py
```

これは当該フォルダの分析出力を上書き再生成し、出力先を指定する引数はない。再生成の依頼がある時だけ行い、まず既存フォルダを別の保全先へ複製し、ファイルhashを記録してから実行する。複製できない場合は実行しない。実行後は差分を確認する。解釈系は上のsettingsで指定したPythonを使う。任意の原本へ切り替えるため固定manifest照合を削除しない。別の入力は別の分析版にする。AI・API・Gurobiは呼ばない。

図再生成は同フォルダREADMEの実在するランタイム・フォント・出力先の手順を使う。最新版の資料コメント対応は[2026-10-02版](../../../outcome/2026-10-02_teacher_comments/README.md)と、現在ユーザーが編集した版を確認する。日付が新しいフォルダ名だけで編集元を決めない。

## 指標を出す時の定義

| 指標 | 定義・注意 |
|---|---|
| 円/週 | 営業7日＋今回含めた末尾費用。両方の内訳を示す |
| 円/営業km | 同じ期間の総費用÷営業便距離。回送距離は別 |
| 円/便 | 総費用÷担当営業便数。未担当や重複がある計画を有効な基準にしない |
| 最大15分平均受電電力[kW] | 15分買電kWh÷0.25hの最大。電力量と混同しない |
| PV利用 | PV→バスとPV→BESSを区別。後のBESS→バスを同じPVとして二重計上しない |
| BESS初終端 | 初期在庫と当該週のPVを分ける。取り崩しを恒常的節約にしない |
| 電気バス担当 | 便数と営業km、使用車両日数を分ける |
| gap | Stage 1、固定配車Stage 2、毎時窓それぞれの対象を示す。週全体は未算出なら未算出 |

集計に必要な台帳がない指標は推測値で埋めない。車両別の電源比率は、比例配賦なら比例配賦と書き、solver-nativeの供給経路とはしない。

## 図と考察の順序

1. 代表1週の全便充足、運行・充電、SOCと翌朝目標を示す。
2. 7日と末尾の電力需給を、PV・買電・バス充電・BESS・抑制に分けて示す。
3. 12月別週の費目内訳を示す。車両日費が支配的なら総額だけでなく電力・燃料・超過モデル費を別表示する。
4. 費用差を便数・距離・PV・配車・充電時刻・ピーク・在庫と対応させる。
5. 何が結果として確認でき、どこに比較不足があるかを書き、必要な少数対照へつなげる。

横軸は週開始からの時間数だけにせず日付を各日の中央へ配置し、0時の日境界を薄い破線で示す。kWの15分系列は階段表示、単位・対象日・scenario名を明示。日本語の表示確認を行う。主スライドは問い・結果・理由・限界に絞り、管理情報はノートか補足へ残す。[PPT-maker.md](../../../outcome/PPT-maker.md)を参照する。

具体例として、5月−4月の総費用差576,380.85円の91.07%は契約超過モデル費の差。PV総量差は約1.07%。これは固定計画の費目分解で、PVだけの因果効果・実契約料金の差・削減実証ではない。値は[既存比較JSON](../../../outcome/2026-10-03_research_review/april_may_comparison.json)に照合する。

## 他者へ原本を渡す

CSV・図だけでなく、コードSHA・環境、入力snapshot、Prepared、元の計画・会計・物理検証、job/attempt、相対パスとhash、検査入口を一式で対応付ける。ローカル絶対パスとhashだけでは別PCで検算できない。

`export_monthly_evidence_bundle.py` と `verify_monthly_evidence_bundle.py` は存在するが、既定入力は9/22の旧報告で、要求schemaと検算範囲もその版に基づく。今回の `comparison.json` をそのまま渡して現在の12週を検証できるとは案内しない。現在のartifact schemaとの互換性を確認したうえで、対象版を明示する。検証器は全SOC・時間・車両制約や設備承認まで検査するものではない。

元ZIPを共有できない時は、共有済みの範囲と検査できない部分を明記する。機密の時刻表・車両原本、鍵・ライセンスは公開Gitへ入れない。図やPPTだけを修正したことを理由に全月の求解をやり直さない。
