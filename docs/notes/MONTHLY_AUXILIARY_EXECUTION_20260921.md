# BESS補助運用による月別12週の再実行

2026-09-21、ユーザーが旧12カ月計算の停止と修正版での全月再実行を指示した。
事前のWindowsプロセス照合ではPython/Gurobi・campaign・observerの実行はなく、
直近のmonthly_reserveは12/12完了・配信済みだった。停止すべき実プロセスはなかった。
旧成果・配信記録を保全し、新規のclean固定版・新規Prepare・新規出力で開始する。

## 共通条件

- 設計: `config/shibu21_23_monthly_auxiliary_20260921.json`。
- 2025年の各月から既定の12週。祝日なしの平日5日・土曜1日・日曜1日。
- BESSは20–80%、初期50%、PVはバス充電優先、余剰PVで蓄電。
  下限なら放電待機、上限なら充電停止・PV抑制。追加予備・終端復元なし。
- 修正済みCO2会計と同じ設備・車両・完全後続網・時刻表・2024年予測モデルを使用する。
- Stage1 1,800秒、Stage2 120秒、主wall 2,400秒、rolling 15秒、4threads、1%目標。
  既存のbarrier/Crossover0/soft18GB profile。各週168時間を逐次実行する。
- seed費用の別診断は実施しない。週間比較の費用原本は実行後の
  `rolling_hourly_chain/executed_day_accounting.json`。探索改善額とは区別する。

## スクリプトと保存先

制御先は `output/monthly_auxiliary_20260921/`、固定実行先は
`C:/master-course-worktrees/monthly-auxiliary-20260921`。
実SHA・PID・開始時刻は制御先の `budget_rerun_launch.json`、状態は
`script_observer/state.json`。固定版の `output/monthly_auxiliary_campaign_20260921/`
に全12週を新規作成し、過去の成功週を混ぜない。

`run_exact_seasonal_campaign.py` がPrepare・前日計画・毎時実行を順番に行い、
`watch_monthly_campaign.py` が通常60秒間隔で保存状態のみを読む。
AIによる定期監視は追加しない。失敗なら後続計算を停止して一度だけ既存タスクへ通知する。
自動再試行・条件緩和・未完了メールは行わない。

旧監査原本は変更せず、追跡対象の `audit_monthly_execution.py` に監査コードを保存し、
solver設定を旧版の120秒/12threads等ではなく今回の固定設計と比較する。
`audit_auxiliary_bess.py` はPrepared設備値から169計画と168実行prefixを独立再計算し、
PV優先、上下限、効率、エネルギー収支、バス充電量、確定実行planとの一致を照合する。
監査なし・原本hash不一致なら完成結果へ掲載しない。

全12週の独立監査・月別/季節別報告・最終図表が揃った時だけ既存タスクを一度復帰させ、
[配信手順](MONTHLY_COMPLETION_DELIVERY_20260914.md)に従い、承認済み
`g2681320@tcu.ac.jp` へ1通送信する。新しい件名 `MC2025-<今回SHA先頭8文字>` と
今回のreceipt/Gmail送信済み検索で重複を防ぐ。

## 検証・主張範囲

関連101 tests通過（UTF-8実行）。新設定、古いsolver条件の混入拒否、338原本を持つ
模擬1週の監査、会計planの改変拒否、既存監視/報告、2日間のnative Stage2を含む。
最初のテスト実行は既存2件がWindows既定cp932でUTF-8のfixtureを読めず失敗した。
本番と同じ `-X utf8` に揃えて101件通過。計算結果の不具合ではない。

自己レビュー完了、独立研究承認はPENDING。1%目標未達・メモリ停止等を隠さず記録し、
物理/会計通過と最適性を分離する。Phase3は週間総費用の統合大域最適の証明ではない。
各週の初期BESS在庫取り崩しをPV効果や継続週の節約とは扱わない。
研究採用BLOCKED、DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSを維持する。

## 起動確認

- 2026-09-21 17:59:26 JST開始。固定SHA `a4b9c679ead3c735a5e759eefb8b9399c0dcb996`。
- release branch `codex/monthly-auxiliary-20260921`、固定実行先は上記の新worktree。
- 入力原本47件のSHA一致、親metadata参照11件のみ移設、旧実験出力コピーなし。
- 固定版で20 tests通過。開始前後のGit cleanを確認。
- 実campaign PID44384、実observer PID20964。起動時点は1月週 `2025-01-06` の
  `PREPARING_WEEK`、完了/監査0/12。全12週完了・最適性・メール送信を示すものではない。
- 配信識別子 `MC2025-a4b9c679`。最新状態と将来の実送信IDは、今回のscript_observerだけを参照する。
- この記録以降、固定実行コードを変更せず、通常監視はスクリプトへ引き継ぐ。
