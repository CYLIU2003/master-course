# BESS予備残量を保持する月別12週の実行

<!-- monthly-reserve-status -->
最新の月別再実行: 固定 `68f2f4e5`、独立監査 12/12週、状態 `COMPLETED`。全月共通MIPFocus=1・前日Method=1・rolling Method=0、物理許容差1e-9。BESSはPVのみで充電、初期残量を毎時の予備残量として保持し週末に復元。旧2ff239e1の3週・旧7c7c2334の12週は別条件の記録として保持し、新版には混ぜない。研究採用BLOCKED。結果: `docs/notes/SHIBU21_23_MONTHLY_RESERVE_RESULTS_20260920.md`。
<!-- /monthly-reserve-status -->


2026-09-20にユーザーは4月停止の完全な修正を指示した。PV専用BESSを維持し、予測誤差への予備残量とrolling窓末を整合させた新条件を全12週へ適用する。過去の再実行・完了時メールの承認を引き継ぎ、再承認は不要。

- 設計: `config/shibu21_23_monthly_reserve_20260920.json`。
- 修正・数学的な範囲: [BESS予測誤差への修正](BESS_FORECAST_RESERVE_FIX_20260920.md)。
- 制御先: `output/monthly_reserve_20260920/`。source SHA・PID・開始時刻・作業場所は `budget_rerun_launch.json` が原本。
- 計算: 新しいclean固定版の `output/monthly_reserve_campaign_20260920/`。旧12週・旧3週の結果は流用しない。
- 状態: `script_observer/state.json`。通常は60秒ごとにローカルスクリプトだけで進捗・監査・途中報告を処理する。AIの定期起動は追加しない。
- 報告: `docs/notes/SHIBU21_23_MONTHLY_RESERVE_RESULTS_20260920.md/.json`。
- 最終図: `docs/notes/figures/shibu21_23_monthly_reserve_20260920.png/.svg`。
- 全12週の168時間受理・物理検証・確定会計・追加の予備残量監査が揃うまで完了にしない。
- 停止時は原本を保存し、途中報告も停止状態へ更新して一度だけ既存タスクへ通知する。求解の自動再試行、条件緩和、未完了メールは行わない。
- 完了時のみ既存タスクへ一度queueし、bundle/hashと実図を確認後、承認済み `g2681320@tcu.ac.jp` へGmailで1通送る。件名は `MC2025-<今回SHA先頭8文字>`。この制御先のreceiptとGmail送信済み検索で重複を防ぎ、実message IDを保存する。

ソルバー、許容差、料金、seed、threads、車両・時刻表・PV予測原本は設計に明記し、開始後に固定コードを編集しない。今回も2024年のみの学習モデルを使う。並行するSolcast履歴追加を入力へ混ぜない。ユーザー編集中のPowerPointは保全する。

研究採用BLOCKED。独立した研究承認は別途必要であり、この実行の開始を研究承認・全12週完了・メール送信済みと同一視しない。

全体回帰: 2,400 passed / 既存資料2 failed（109.18秒）。今回の実装に関するP0/P1は自己レビューで解消。独立した研究承認はPENDING。

## 2026-09-20 17:26 JST 起動確認

- 固定コミット: `68f2f4e5aa7b242de467ceece487a4c43da00c70`、release branch `codex/monthly-reserve-20260920`。
- 固定作業場所: `C:/Users/RTDS_admin/.codex/worktrees/monthly-reserve-20260920/master-course`。
- 同一入力47ファイルのSHA・親metadata参照11件の移設・cleanを照合。旧結果をコピーせず、固定版で関連57テストも通過した。
- campaign実PID `38308`、開始 `2026-09-20T08:26:09.1757270Z`。observer実PID `34900`。いずれも非表示のローカルスクリプト。
- 起動確認時点: `PREPARING_WEEK`、対象 `2025-01-06`、完了・独立監査 `0/12`。新規Prepareを開始し、observer `RUNNING` と設定・helper SHA照合を確認した。これは週間計算・監査の完了を示さない。
- 配信識別子は `MC2025-68f2f4e5`。メール未送信。全12週の監査と最終図表が揃った時だけ既存タスクを一度復帰させ、承認済み宛先へ1通送信する。

上記PID・開始時刻は起動時の記録。最新状態は `script_observer/state.json` とcampaign `progress.json`を参照する。

## 2026-09-20 全12週完了と配信前確認

固定 `68f2f4e5` の全12週が完走し、保存原本による独立監査を通過した。2026-09-20 23:55 JSTの配信前照合では、2,016受理時間・8,064区間、物理違反0件、確定会計と日別台帳の一致を確認した。BESS予備残量監査の4,032原本ハッシュと添付4ファイルも一致した。最小BESS残量は数値許容差内で3,000 kWh、週末初期残量との差の最大値は `4.23e-11 kWh`。旧4月の停止はこの全12週の実行では再発しなかった。

`script_observer/final_verification.json` にbundle・payload・監査・campaign原本のSHAを保存した。PNGを表示し、6パネルすべての12か月・凡例・単位・注記と欠け／重なりを確認、`final_visual_review.json` にPASSを記録した。計算原本や図表の修正は不要だった。

完成結果は [月別・季節別報告](SHIBU21_23_MONTHLY_RESERVE_RESULTS_20260920.md)。購入電力量が最多なのは5月、最少は2月。受電ピークは最大900 kWで、200 kWの契約基準を有料超過する条件の費用が大きい。完走は費用改善や最適性の証明ではない。研究採用BLOCKEDを維持し、配信の実成否は `script_observer/email_receipt.json` を原本とする。

## 配信完了

2026-09-20 23:57:12 JST、承認済み `g2681320@tcu.ac.jp` へ報告・数値JSON・PNG・SVGを1通送信した。Gmail実message ID / thread IDは `1a0bf523c1c61c5c`。件名 `BESS予備残量・月別12週の整理完了 [MC2025-68f2f4e5]`。送信前はreceiptなし・送信済み検索0件、送信後は同IDのSENT・宛先・件名・添付4件と検索結果1件を確認した。実ID、Gmail時刻、bundle/payload SHA、重複防止の確認を `email_receipt.json` に保存した。Gmailによる送信成功であり、受信者の受信トレイ到達確認ではない。

同じ完了イベントが再来しても、このreceiptとGmailを照合して再送しない。`completion_bundle.json` は未送信時点の不変の配信準備記録として保持し、現在の配信成否はreceiptを優先する。新しい計算や監視の再起動は不要。
