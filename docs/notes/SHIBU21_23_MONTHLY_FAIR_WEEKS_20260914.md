# 渋21〜23：月別に平日5日・土休日2日を揃える7日間比較

新版の途中結果（2026-09-14 17:49 JST）: [固定8acd8bebの1月結果と原本](SHIBU21_23_MONTHLY_NUMERIC_RESULTS_20260914.md)。1/12週が完走・独立監査済みで、2月を計算中。旧版の結果表は初回試行の履歴として保持する。

季節差の範囲: 月別にPV履歴・学習済みPV予測を適用する一方、走行需要の設定は `distance_average_v0`、各需要倍率1.0、`weather_factor_scalar=1.0` である。固定した電費・燃費を距離へ適用し、気温に応じた空調負荷の月別入力は与えない。冷暖房等を含む季節的需要変化の評価とは区別する。固定版の入力生成・需要計算経路と1月canonical Preparedで確認し、パス・hashを `output/monthly_fair_weeks_20260914/monthly_energy_scope_audit.json` へ保存した。全12週の実出力監査は別途継続する。

再実行: 初回の数値的な停止を対処し、`8acd8beb` のclean版で2026-09-14 17:08 JSTに同じ12週を最初から開始した。新worktreeは `C:/master-course-worktrees/shibu21-23-monthly-numeric-20260914`、出力は `output/monthly_numeric_campaign_20260914`、独立監査はmainの `output/monthly_fair_weeks_20260914/monthly_numeric_independent_audit.json`。初回3週を新版の集計へ流用しない。上記の新しいcampaign/auditを結果集計CLIへ指定する。[修正と最終検証](SHIBU21_23_APRIL_NUMERIC_DIAGNOSIS_20260914.md)。

途中結果: [月別結果表と原本hash](SHIBU21_23_MONTHLY_RESULTS_20260914.md)を追加した。1〜3月の3週は完走・物理・会計照合を通過。4月はhour 023のStage 2がinfeasibleを返して停止し、5〜12月は未実行。週間会計が成立しない失敗週を費用表へ補完しない。以下は開始時点の設計・検査記録。

2026-09-14。2025年の各月から1週、計12週・84日を事前選定した。12週すべての入力materializationで曜日構成、同一時刻表原本、1,704便、同一営業便距離、予測672 slot、同一2024年学習モデルを確認した。これは入力検査であり、新clean commitによる完全Prepare・求解・168時間rolling・最終物理検証・会計の完了を意味しない。固定SHA `4c5c5d86f7e41ccb38a4288dd18a2aa72a1c2cb0` のclean worktreeから2026-09-14 14:47 JSTに12週の逐次実行を開始した。開始後の実行状況は冒頭の途中結果を参照。

## 選択日と比較条件

月内に収まる月曜〜日曜のうち、祝日・振替休日を含まない最初の週を選ぶ。PV量や費用を見る前に決める規則であり、晴天週や低費用週を結果から選ばない。

| 月 | 開始（月曜） | 終了（日曜） | 運行日構成 |
|---|---|---|---|
| 1 | 2025-01-06 | 2025-01-12 | 平日5・土曜1・日曜1 |
| 2 | 2025-02-03 | 2025-02-09 | 同上 |
| 3 | 2025-03-03 | 2025-03-09 | 同上 |
| 4 | 2025-04-07 | 2025-04-13 | 同上 |
| 5 | 2025-05-12 | 2025-05-18 | 同上 |
| 6 | 2025-06-02 | 2025-06-08 | 同上 |
| 7 | 2025-07-07 | 2025-07-13 | 同上 |
| 8 | 2025-08-04 | 2025-08-10 | 同上 |
| 9 | 2025-09-01 | 2025-09-07 | 同上 |
| 10 | 2025-10-06 | 2025-10-12 | 同上 |
| 11 | 2025-11-10 | 2025-11-16 | 同上 |
| 12 | 2025-12-01 | 2025-12-07 | 同上 |

祝日は[内閣府の公式CSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)に基づく。2026-09-14取得分と既存の検証済みcalendar原本のSHA256はともに `cec37a743c96995cdb9cb52b685c9003634682a9b0e1a640a6b9b96881fe964a`。旧秋週2025-11-03は文化の日を含み平日4日だったため、11月10日開始へ変更した。

設計は [config](../../config/shibu21_23_monthly_2025_20260914.json)。渋21/22/23の同じ原本、親シナリオのexact active fleet（観測60台、BEV35・ICE25）、初期SOC、充電器、BESS、料金、seed42、12 threads、Stage 1最大120秒・Stage 2最大30秒・day-ahead共有900秒・rolling最大15秒を保持する。successor pruningは0、fallback・解後修復は禁止。BEVは週末に各車の初期SOCへ戻し、BESSは既定の20〜80%・週末最低20%条件を維持する。数式・単価・feasible setを変更する作業ではない。

同じ曜日構成で同じ時刻表原本をmaterializeした結果、各週1,704便、営業便距離は同値となった。この距離は停留所間の地理的代理距離に基づく営業便合計であり、回送を含む実道路走行距離ではない。使用台数・車両日数・費用は求解結果なので固定値を作らず、完走後に別々に比較する。

## 入力・予測の照合

`run_exact_seasonal_campaign.py` → `prepare_week(..., design=case_design)` → `configure_doc` → 完全Prepare → `audit_prepared_inputs` → 既存day-ahead・168時間rolling経路を使う。

- campaign開始時に、検証済み祝日原本のhash、設定内祝日一覧、12週選択を再計算・照合する。
- materializationとcanonical Preparedの両方で、7日の日付・曜日構成・日別サービスID・便数・時刻表hashを検査する。入力行を補正・削除して合格させない。
- 月別campaignは明示holdout directoryを渡す。学習モデルhash、週別profile hash、対象週、訓練終了日、全valid start、全予測値を照合し、計画へ渡すPVと週別検証資料の不一致を拒否する。従来の非月別callerの既定入力は保持する。
- 計画予測と履歴推定実績PVは分離する。2025年実績を学習へ混ぜない。

12週holdout生成（取得済み原本のみ使用、Solcast APIリクエストなし）：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/weather/build_forecast_holdouts.py --design config/shibu21_23_monthly_2025_20260914.json --output output/monthly_fair_weeks_20260914/forecast_holdouts
```

入力検査証拠は `output/monthly_fair_weeks_20260914/input_materialization_check.json`、holdoutの原本hash・12週一覧は同ディレクトリの `forecast_holdouts/manifest.json` にある。学習モデルは検証済みreferenceが採用した2024年の364日を使用する。

新しいclean research branch/worktreeで、上記holdoutを同じ相対パスへコピーしhashを照合してから実行する。source candidateとcampaign outputは新規作成し、旧4週成果物を再利用しない。

```powershell
C:/master-course/.venv/Scripts/python.exe -X utf8 scripts/benchmarks/run_exact_seasonal_campaign.py --config config/shibu21_23_monthly_2025_20260914.json --output output/monthly_fair_weeks_campaign_20260914
```

## 結果のまとめ方と主張の限界

補足: [選択週の日射量と月全体の比較](SHIBU21_23_MONTHLY_IRRADIANCE_CONTEXT_20260914.md)を作成した。2025年全日のGHIを事後分析した資料で、週選択や学習・計画入力には使わない。

全12週で合計2,016回の毎時rollingと8,064個の15分slotを確認する。週ごとに入力・day-ahead・rolling・物理・会計を別判定し、失敗週や未実行週を結果から隠さない。確定費用は受理済み `rolling_hourly_chain/executed_day_accounting.json` だけから取得し、日別台帳と1e-6円以内で照合する。

比較には総費用、車両日費とそれ以外の費用、購入電力量、受電ピーク、PV発電・直接利用・BESS充電・抑制、BESS初期/終端在庫、使用車両日数を使う。平日/土休日の営業量を揃えることで旧秋週の交絡を一つ除くが、割当・充電時刻・PV・solver incumbentの差は残る。月別の結果を先に提示し、冬12/1/2月・春3/4/5月・夏6/7/8月・秋9/10/11月の3週ずつを記述的に整理する。同年12月と1/2月は連続した一つの冬ではないことも明記する。

各月1週の目的選定であり、月平均・年平均・統計的な季節一般化・PV単独の因果効果を主張しない。時刻表は2026年原本、評価日は2025年、実績PVは履歴推定、予測は2024年のみのclimatology proxy。10% gap、正式fleet contract、統合最適性、既存資料2件の証拠不一致等の研究採用条件は別に残る。結果は **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**、研究採用 **BLOCKED** を維持する。

季節別の集計では、3週の費用・購入量は「選択週当たり平均」と範囲を示す。PV利用率・抑制率は3週の分子合計÷発電量合計で求め、週別百分率の単純平均を使わない。受電ピークは週別値の範囲と3週中の最大値を示す。各7日間は同じ初期状態から別々に始めるため、3週合計を連続21日間の運用結果として扱わない。BESS初期在庫の減少量も各週と合計を併記する。

## 結果表の再生成

結果集計はmain側の次の専用CLIで行う。実験worktreeへの書込み・Prepare・求解は行わず、独立監査のhashと原本を再照合する。

```powershell
.venv/Scripts/python.exe -X utf8 scripts/build_monthly_interpretation.py --campaign C:/master-course-worktrees/shibu21-23-monthly-fair-20260914/output/monthly_fair_weeks_campaign_20260914 --audit output/monthly_fair_weeks_20260914/monthly_independent_audit.json --partial
```

通常モード（`--partial`なし）は12週すべての完走・独立監査・campaign完了が必要。途中版は停止/失敗状態と未確定週を明記し、季節別集計や完成図を出力しない。関連28テスト、実原本3週の数値一致、未完了時の最終生成拒否を確認した。12週の完成図はデータが揃ってから描画・目視検査する。

## Solcast追加認証と履歴取得

2026-09-14に追加認証を使用し、未取得の2022年12月2,976レコードを取得・検証した。学習対象2022〜2024年の24/36か月・70,176レコードが揃い、残りは2023年の12か月。APIキーはWindowsのユーザー単位暗号化資格情報としてリポジトリ外に保管し、CLI実行時だけ環境変数へ渡す。値は資料・ログ・Git・定期タスク文面へ記載しない。

残りAPI利用枠は取得できていないため、今回は1リクエストで停止した。既存の日次定期取得を追加認証へ更新し、残り枠不明時は1回のみ、402/429なら停止し、課金契約の変更はしない。全月取得後の2022〜2024年学習は別成果物として作成し、この12週比較の2024年固定入力や旧成果物を途中で差し替えない。

## 凍結前の検証

全体回帰は **2,258 passed / 既存PowerPoint証拠2 failed、168.24秒**。JUnitは `output/monthly_fair_weeks_20260914/pytest-release.xml`。新規18件で祝日週・月跨ぎ・曜日/便の改変、forecast hash/モデル/値/時刻/未宣言週、12週designのPrepare伝達、canonical Preparedの暦・予測証拠の不一致を検査した。Lunaの独立最終レビューで未解決P0/P1は0件。旧canonical Preparedの列との互換も実ファイルで確認した。

## 実行場所

凍結branchは `codex/shibu21-23-monthly-fair-20260914`、worktreeは `C:/master-course-worktrees/shibu21-23-monthly-fair-20260914`。進捗はその配下の `output/monthly_fair_weeks_campaign_20260914/progress.json`、週別結果は `cases/<開始日>/summary.json`、全体結果は完了後の `summary.json`。全体ログは `output/monthly_fair_weeks_campaign_20260914.log`。失敗時は後続を未実行と明示して停止する。監視と独立照合は、ユーザーの既存希望どおりGPT-5.6 Lunaが担当する。

このタスクの既存heartbeatへ完了後の結果整理を追加した。月別計算中の状態確認は30分間隔だが、Solcastの確認・取得は日本時間12時以降、同日未確認の場合だけ、一日最大1リクエストの既存制限を維持する。通常の計算中は通知せず、完了・失敗等だけを知らせる。月別報告後は元の日次12時のSolcast取得設定へ戻す。
