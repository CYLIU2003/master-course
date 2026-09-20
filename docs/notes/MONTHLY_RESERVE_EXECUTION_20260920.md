# BESS予備残量を保持する月別12週の実行

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
