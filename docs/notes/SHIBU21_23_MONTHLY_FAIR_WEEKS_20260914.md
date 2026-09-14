# 渋21〜23：月別に平日5日・土休日2日を揃える7日間比較

<!-- monthly-search-status -->
最新の月別再実行: 固定 `10a40c9f`、独立監査 1/12週、状態 `IN_PROGRESS`。全月共通MIPFocus=1・Method=1、物理許容差1e-9。旧fa0c22bfの10週は旧版の記録として保存し、新版には混ぜない。研究採用BLOCKED。結果: `docs/notes/SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915.md`。
<!-- /monthly-search-status -->


旧固定版 `fa0c22bf` は1〜10月の10週間が完走・独立監査済み（10/12週、2026-09-15 01:34 JST）。10月の総費用4,269,784.456240円、購入量4,354.188 kWh、最大受電200.795 kW。各週168時間・672 slot、物理検証、会計と日別台帳の差1e-6円以内、各169充電求解の数値設定、同一予測、全接続、前後cleanを照合した。11月で計算停止。失敗理由と未実行の週は結果表に記載し、原因を診断中。研究採用はBLOCKED。 [新版の結果表・原本hash](SHIBU21_23_MONTHLY_BUDGET_RESULTS_20260914.md)。停止版や単独診断は混ぜない。

前回の実行記録: 2026-09-14 19:15 JST開始の固定 `829e3983` は1月の前日計画で停止した（19:37 JST確認）。Stage 2の30秒制限でincumbentなし、`DAY_AHEAD_FAILED`、完走0/12週、rolling未開始。worktree `C:/master-course-worktrees/shibu21-23-monthly-presolve-20260914`、campaign `output/monthly_presolve_campaign_v3_20260914`、main監査 `output/monthly_fair_weeks_20260914/monthly_presolve_independent_audit.json`。同一nativeモデルの120秒枠で最初の解が約36.5秒後に得られ、SOC・物理検証を通過した。全月の前日Stage 2を最大120秒へ揃えて新規実行する。[変更根拠と診断](SHIBU21_23_JANUARY_STAGE2_BUDGET_20260914.md)。停止週の週間費用を補完せず、以下の過去版の完走週も流用しない。[数値修正・検証](SHIBU21_23_MARCH_SOC_REPLAY_DIAGNOSIS_20260914.md)。

過去版の途中結果（2026-09-14 18:52 JST）: [固定8acd8bebの1・2月結果と原本](SHIBU21_23_MONTHLY_NUMERIC_RESULTS_20260914.md)。2/12週が完走・独立監査済み。3月はhour 152のSOC再検証で停止し、152/168時間まで受理、4〜12月は未実行。旧版の結果表は初回試行の履歴として保持する。

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

設計は [config](../../config/shibu21_23_monthly_2025_20260914.json)。渋21/22/23の同じ原本、親シナリオのexact active fleet（観測60台、BEV35・ICE25）、初期SOC、充電器、BESS、料金、seed42、12 threads、Stage 1最大120秒・Stage 2最大120秒・day-ahead共有900秒・rolling最大15秒を全月で保持する。Stage 2の上限は1月の同一モデル診断に基づいて旧30秒から変更した。successor pruningは0、fallback・解後修復は禁止。BEVは週末に各車の初期SOCへ戻し、BESSは既定の20〜80%・週末最低20%条件を維持する。数式・単価・feasible setを変更する作業ではない。

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

2024年の366日から除外されたのは2月5日と3月8日である。両日ともreferenceの `daily_labels` は `quality_flag=excluded`、`weather_class=unresolved`、理由は `solid_precipitation_unresolved_from_temperature_proxy`（気温を用いた代理判定では固体降水を分類し切れない）である。両日は学習対象から除外される。`training_model.json` の `training_source_dates` はこの2日を含まず、全日付が2024年、`training_end_exclusive=2025-01-01`。2025年の評価履歴は訓練に含めない。この除外による予測誤差への影響は未評価であり、雪などの条件への予測性能を主張しない。

モデル内容のハッシュ `content_hash(model)` は `0b876e8e55a8c4950cdbfe928dc114a09027043e8aeee206d9ebf3db6e7599eb`、`training_model.json` のファイル全体のSHA256は `d7b6b15172e4267e07d5f8846943b08199f102915dd14d77ecff540b4f22b8cd`。JSONの内容とファイルのバイト列という異なる対象を照合しており、両値を取り違えない。最終結果のJSONにある `forecast_model_sha256` は後者のファイルSHAを記録する。

主作業場所と固定版の学習モデル・12予測ファイルはバイト一致する。manifestには実装ファイルの改行コードに伴うハッシュ差があり、両場所のmanifest全体の一致とは主張しない。固定版のmanifestを含む47ファイルは実行前の取込記録と一致した。[学習範囲と入力来歴の監査](../../output/monthly_fair_weeks_20260914/forecast_training_coverage_audit.json)では、main対固定版のmanifest一致不成立と、固定版の実行前入力からの不変を別項目で保持する。週間監査は固定版の予測原本を読み、PreparedのモデルファイルSHAとも照合する。

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
.venv/Scripts/python.exe -X utf8 scripts/build_monthly_interpretation.py --campaign C:/master-course-worktrees/shibu21-23-monthly-budget-20260914/output/monthly_budget_campaign_20260914 --audit output/monthly_fair_weeks_20260914/monthly_budget_independent_audit.json --output docs/notes/SHIBU21_23_MONTHLY_BUDGET_RESULTS_20260914 --partial
```

通常モード（`--partial`なし）は12週すべての完走・独立監査・campaign完了が必要。途中版は停止/失敗状態と未確定週を明記し、季節別集計や完成図を出力しない。関連28テスト、実原本3週の数値一致、未完了時の最終生成拒否を確認した。12週の完成図はデータが揃ってから描画・目視検査する。

集計後の資料同期は `.venv/Scripts/python.exe -X utf8 output/monthly_fair_weeks_20260914/update_monthly_checkpoint.py --dry-run` で内容を確認し、同じCLIから `--dry-run` を外して適用する。このCLIは実験を起動しない。reportが参照した監査JSONのSHA一致を要求し、README・blocker・本計画・開発記録・起動記録を更新する。3/12週の版から、参照した監査の正確なバイト列を `output/monthly_fair_weeks_20260914/audit_snapshots/<SHA256>.json` に保持する。同じ名前に異なる内容が存在すれば拒否し、同じ内容は再書込みしない。後続月が加わった後も、各結果表JSONの `independent_audit.sha256` に対応するスナップショットで当時の証拠を確認できる。

## Solcast追加認証と履歴取得

2026-09-14に追加認証を使用し、未取得の2022年12月2,976レコードを取得・検証した。学習対象2022〜2024年の24/36か月・70,176レコードが揃い、残りは2023年の12か月。APIキーはWindowsのユーザー単位暗号化資格情報としてリポジトリ外に保管し、CLI実行時だけ環境変数へ渡す。値は資料・ログ・Git・定期タスク文面へ記載しない。

残りAPI利用枠は取得できていないため、今回は1リクエストで停止した。既存の日次定期取得を追加認証へ更新し、残り枠不明時は1回のみ、402/429なら停止し、課金契約の変更はしない。全月取得後の2022〜2024年学習は別成果物として作成し、この12週比較の2024年固定入力や旧成果物を途中で差し替えない。

## 初回版4c5c5d86の凍結前検証（履歴）

全体回帰は **2,258 passed / 既存PowerPoint証拠2 failed、168.24秒**。JUnitは `output/monthly_fair_weeks_20260914/pytest-release.xml`。新規18件で祝日週・月跨ぎ・曜日/便の改変、forecast hash/モデル/値/時刻/未宣言週、12週designのPrepare伝達、canonical Preparedの暦・予測証拠の不一致を検査した。Lunaの独立最終レビューで未解決P0/P1は0件。旧canonical Preparedの列との互換も実ファイルで確認した。

## 実行場所

現在の凍結branchは `codex/shibu21-23-monthly-budget-20260914`、SHAは `fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8`、worktreeは `C:/master-course-worktrees/shibu21-23-monthly-budget-20260914`。進捗はその配下の `output/monthly_budget_campaign_20260914/progress.json`、週間確定結果は `cases/<開始日>/diagnostic/<開始日>/summary.json`、全体結果は完了後の `summary.json`。全体ログは `output/monthly_budget_campaign_20260914.log`。失敗時は後続を未実行と明示して停止する。監視と独立照合は、ユーザーの既存希望どおりGPT-5.6 Lunaが週単位で担当する。

この固定版は25件の関連テストを凍結後に通過した。基になる数値修正の全体回帰は2,297 passed / 既存PowerPoint証拠2 failedで、1月の予算診断と共通120秒設定は[変更根拠](SHIBU21_23_JANUARY_STAGE2_BUDGET_20260914.md)に記録する。main上で報告資料を更新しても、実験結果のSHAを現在のmain HEADに付け替えない。初回 `4c5c5d86`、数値設定 `8acd8beb`、30秒版 `829e3983` の出力は過去の試行として各worktreeに保持する。

このタスクの既存heartbeatへ完了後の結果整理を追加した。月別計算中の状態確認は30分間隔だが、Solcastの確認・取得は日本時間12時以降、同日未確認の場合だけ、一日最大1リクエストの既存制限を維持する。通常の計算中は通知せず、完了・失敗等だけを知らせる。月別報告後は元の日次12時のSolcast取得設定へ戻す。
