# 3月のSOC数値誤差と毎時再計画の設定修正

<!-- monthly-auxiliary-rolling-status -->
最新の月別再実行: 固定 `3289f07b`、独立監査 3/12週、状態 `STOPPED_AFTER_FAILED_CASE`。全月共通MIPFocus=1・前日Method=1・rolling Method=0、物理許容差1e-9。BESSはPVバス優先・余剰蓄電・20～80%内で補助使用。追加予備・終端復元なし。Stage1 1800秒・4threads・目標1%、前日Presolve2・毎時Presolve0。旧結果は混ぜない。研究採用BLOCKED。結果: `docs/notes/SHIBU21_23_MONTHLY_AUXILIARY_ROLLING_RESULTS_20260921.md`。
<!-- /monthly-auxiliary-rolling-status -->


<!-- monthly-auxiliary-rolling-launch -->
固定 `3289f07b` の前日Presolve2/毎時Presolve0による全12週を開始。起動確認UTC 2026-09-21T13:33:23.889786+00:00、計算PID3316、監視PID50460、PREPARING_WEEK・完了0/12。17時間連続と1月/3月の最初の窓の事前検証を通過。旧2週を混ぜず、通常処理はスクリプトのみ。研究採用BLOCKED。記録: `output/monthly_auxiliary_rolling_20260921/startup_verification.json`。
<!-- /monthly-auxiliary-rolling-launch -->


## 今回の停止

固定818e78d0は1月・2月の各168時間、週間物理/会計と独立BESS監査を通過。
3月は152/168時間を受理後、hour152（153時間目）でStage2 infeasible。
4～12月は未実行。成功は2/12で、3月を完了週へ数えず、週間費用も作らない。
前回の内部seedログ不具合は解消。今回の監視は元失敗理由を正しく保存した。
旧queue `01a0c41a-1e22-7851-a6fd-2b2268e88cca` と原本を保全、完了メールは送らない。

## 数値誤差の因果経路

対象車35f95479-c68e-40bc-b31a-1f0a5490227cについて、hour151のPresolve2は
最大制約違反2.850016187494475e-7 kWhを残し、次境界SOC273.4122418539981kWhを渡した。
hour152のIISは243制約・0変数境界で、この車の充電可能時間・SOC遷移・終端下限に集中。
IISの別コピーで初期在庫増分だけを最小化すると約1.900020265566127e-7kWhの不足だった。
このslack診断の増分を運行状態へ加算したり、検証許容誤差を緩和したりしていない。

保存されたPrepared入力・配車・実測状態から再構築したhour152のMPS SHAは
`68dad31cc223384b18aa23617548fe77ae2bdc7452fed0b273a0a932054c0400`。
Presolve2/0とも同じMPSでinfeasible。次の時間だけの再試行では持越し誤差を除去できない。

直前hour151の同一MPS SHAは
`4392075d987814b0bb62bd7280c26735fefa190864968936bf37cae9c6a1c46c`。
Presolve0では最大制約違反5.095384949407411e-11、次境界SOC273.4122420439999kWh、gap0。
旧実行状態を上書きせず、この別診断の新しい実行結果を次時間へ引き継いで再現を確認した。
BESS範囲・予備・復元・PVバス優先を緩和する必要を示す失敗ではない。

根拠は旧制御先 `output/monthly_auxiliary_logfix_20260921/` の
`march_iis_inspection.json`、`march_hour152_diagnosis/`、`march_predecessor_diagnosis/`。
最後の診断はhour151～167の17時間を対象とし、正式な新規週間結果へ流用しない。

17時間すべてで求解と実PVの先頭4区間の実行・独立BESS収支検査が通過。
各求解のgapは0、native最大制約違反の最大は9.567884262651205e-10だった。
新固定版3289f07bでも1月・3月の最初の窓を検証し、両方の求解・実行が通過。
最大制約違反はそれぞれ9.86268844371807e-11、2.8563817977556027e-11、gapは双方0。
これは保存済み配車を使う局所回帰診断であり、週全体の新規計算の成功を示さない。

## 全月共通の修正

- 前日計画はPresolve2を保持。1月の大規模な固定配車充電モデルに必要だった探索設定を維持。
- 毎時再計画は全月のhour0からPresolve0を宣言する。失敗時間だけを再試行する規則ではない。
- Methodは前日1/毎時0、Aggregate0、FeasibilityTol/IntFeasTol1e-9、4threads、
  1800/120秒・毎時15秒・seed42・gap1%は保持。SOC・充電器・配車・会計制約を変更しない。
- 入口でphase別設定を構築し、169件の原本監査も前日2/毎時0を照合。
  旧監査JSONの固定値 `required_presolve=0` は実効値の正しい説明ではなかったため、
  新規監査では `required_presolve_by_kind` を保存。旧監査原本は書き換えない。
- 実失敗直前モデルを圧縮fixtureとして保存し、次時間の厳密SOC下界を満たすことと
  native最大制約違反1e-9以下を回帰検証する。旧3月の累積SOCモデルも継続検証する。

関連78 tests通過（数値/phase別原本監査18、既存月別設計/監視/報告60）。
自己レビューで入口・宣言・native保存・独立監査の一致、変更前モデルの再現を確認した。
対象変更の未解決P0/P1は0。独立レビュー/研究承認の完了とは区別する。

## 実行の条件と通知

新固定版の制御先 `output/monthly_auxiliary_rolling_20260921/`、作業場所
`C:/master-course-worktrees/monthly-auxiliary-rolling-20260921`。
設計 `config/shibu21_23_monthly_auxiliary_rolling_20260921.json`。
既存の17時間連続診断と、最初の24時間窓を使う1月/3月の単発確認が通った場合のみ、
ローカルスクリプトが新しいclean固定版で全12週を新規Prepareから開始する。
検証が失敗したら全月計算を始めず、元理由を保存して既存タスクへ一度だけ通知する。
旧2週を新版へ混ぜない。通常処理はスクリプトのみ。新12週監査と図表確認後だけ承認済み宛先へ1通送る。

局所診断通過は週間完了・統合最適性を意味しない。Stage1 gap/メモリ・独立研究承認は
未解決で、研究採用BLOCKEDを維持する。自己レビューと独立レビューは別で、後者は未実施。
