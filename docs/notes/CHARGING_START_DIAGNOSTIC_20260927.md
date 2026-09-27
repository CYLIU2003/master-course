# 毎時充電の初期候補再利用：測定と診断用実装

2026-09-27。現在の12代表週の計算固定版は f524eca2 のまま。本機能は既定無効であり、実行中の11月へ配置していない。

## 測定した範囲

既存 `tools/research/rolling_timing_report.py` を使用し、保存済み窓の呼出時間と、対応するnative logの求解終了行を照合した。根LPの途中時間は加算しない。

|対象|保存済み窓|native求解合計 秒|native外の合計 秒|呼出内native比率|optimal / time_limit|
|---|---:|---:|---:|---:|---:|
|11月・途中|75|23,221.58|599.95|97.481%|43 / 32|
|12月・完了|174|17,882.93|1,837.77|90.681%|150 / 24|

これはソルバー呼出内の測定であり、キュー・Prepare・Stage1・転送・実行会計・図表を含む端から端までの所要時間ではない。native外には構築・抽出・検証が混在する。月とPCが異なるのでPC性能比較には使わない。

原本SHA付き証拠は `output/charging_start_review_20260927/{november,december}-timing.json`。11月は同じattempt 490483ef、PID8976の生存を2026-09-27 20:42 JSTに読み取り照合。75窓が保存され、全75窓が可行。現在working set約1.39GiB、観測ピーク13.16GiB、予算16GiB。週全体の検算完了ではない。

## 追加した機能

既存毎時CLIの `--stage2-charging-start-policy` は `none`（既定）と `fixed_assignment_binary` を受け付ける。
`RollingChainRequest → rolling_solver_config → RollingReoptimizer → OptimizationEngine → MILPOptimizer → Stage2 adapter` に実効設定を保持する。

- 固定前日計画の絶対slot indexを使い、充電ON/OFF・物理充電器選択のバイナリ変数だけに `Start` を渡す。
- SOC、充電電力、PV/BESSフロー、価格、目的関数、上下限、制約は変更しない。過去のSOCを再利用しない。
- 実接続と衝突する開始slotは候補から除く。全変数が除かれた場合は `NOT_APPLIED` とし、空の提案を「投入済み」にしない。
- 異なる電源の充電行を合算してから正電力を判定する。非有限値、負電力、表現不能な充電器、同時複数充電器では提案を書き込まない。
- V2Gの放電行は今回の候補生成に非対応。元モデルの通常求解は維持する。
- `SUBMITTED` は候補の提出であり、可行解の発見や採用を意味しない。native採用判定は `NOT_OBSERVED` と記録する。候補の却下と物理検証違反を混同しない。
- 未知のpolicyはライセンスprobeより前に拒否。Gurobiの共有枠・機器別RAM制限は従来どおり。

現行フロントやキャンペーンの要求はこの試験機能を自動選択しない。比較で有効性を確認するまで、通常実行の既定値を変更しない。

## レビューと検証

Claude Sonnetへ差分・helper・テストを読取専用で提示。回答は `output/charging_start_review_20260927/claude-review.json`。
V2G非対応をdocstringへ明記。境界slotは実ウィンドウから渡しており、最初の充電変数から推測しない。充電変数が境界に存在しない場合の回帰も既存テストにあるため、Claudeが提案した変数集合への一律所属制約は追加しなかった。候補の全省略時の誤表示は自己レビューで修正した。

変更後は次の関連71テストが通過。システムPythonにpytestがないため、既存controller-venvを使用した。

```powershell
output/cluster-deployment/controller-venv/Scripts/python.exe -m pytest tests/test_charging_mip_start.py tests/test_multiday_rolling_contract.py tests/test_rolling_timing_report.py tests/test_optimization_engine_postsolve.py tests/test_cluster_solver_policy.py -q
```

CLIのhelpから引数の実在も確認済み。native Gurobiでの比較実験・速度向上・週次通過は未検証。単体テストの通過をそれらの証拠にしない。

## 次の比較と採用条件

現在の11月を同じ試行のまま完了させることを優先する。その後、保存された同一窓・同一入力・同一実状態を使い、noneとfixed_assignment_binaryを別attemptで比較する。遅い候補は11月step15/26/14、12月step46/12/104。これに典型的な短い窓を加え、改善例だけを選ばない。

同一PC・threads・予算・seed・料金・PV・BESS方策を保持し、Start以外の変数・制約・目的のモデル一致、候補採用のnative記録、可行性、目的値/gap、呼出/求解時間、メモリを比較する。候補構築や採否確認時間も含める。枠を確保できなければ待ち、既存予約を解除して始めない。
初期候補が遅い・却下される場合は無効のまま維持する。実測前に高速化率は約束しない。12週の既存成果をこの新設定の成果として再ラベルしない。

## 保存窓の復元を求解前に確認する

`tools/research/prepare_charging_replay.py` は元の回収ZIPと回収時SHAを読み、日付付きの入力・前日配車・直前の実行状態を復元する。時刻表取得・Prepareの再生成・ジョブ投入は行わない。出力は原本とは別の新規JSONだけ。

```powershell
output/cluster-deployment/controller-venv/Scripts/python.exe -X utf8 tools/research/prepare_charging_replay.py --archive output/executed_soc_20260926/remaining_campaign/2025-03-03/state/b5023143-6887-5d46-8a3d-8015649c5bff.zip --archive-sha256 13cd365f16278330a861ffb9dba6c41e8199a92f738caa7c129ee00d1766262f --step 61 --output output/charging_replay_next/preflight.json
```

SHAはその場で新しく作って承認扱いにせず、既存月別comparisonの当該caseの`archive_sha256`を使用する。アーカイブの読取前後に照合し、内部の参照した各原本hashも出力する。`canonical_solver_result.json`もZIP全体のhashで保護される。

3月step12および最も遅かったstep61（元の呼出610.85秒）を実原本で復元し、1698行の前日充電候補と実状態を確認した。Gurobi禁止scope内の再構築でEnv起動・Model生成・求解・禁止呼出はいずれも0。これは求解性能・物理検算の再実施ではない。

初期候補なし／ありで本番の状態変換をそれぞれ通し、復元問題と実効設定の差がpolicyだけであることを確認する。nativeモデルの変数・制約・目的の同一性は、後続の実求解比較で別に確認する。更新PV予測、BESS下限override、初回窓の暗黙状態は未対応として停止し、別条件へ黙って変換しない。

Claudeレビューへの対応：2経路の状態変換比較を追加。solver結果の個別hash未照合との指摘にはZIP全体hashで原本が固定されることを説明した。`RollingChainRequest`は設定抽出のみに使い、空の入出力パスを読む`run_rolling_chain`は呼び出さない。元の固定SHAは出力へ残すが、この汎用ツールをf524eca2だけへハードコードしない。レビューは実機性能承認とは区別する。


## 実求解の比較コマンド

clean checkoutから次を実行する。親機がdraining/disabledなら停止し、CLIが自動解除しない。既存controllerの設定を指定し、ライセンスauthorityと同じqueueを使う。現在値からメモリ余裕を検査する。

```powershell
C:/master-course/output/cluster-deployment/controller-venv/Scripts/python.exe -X utf8 tools/research/run_charging_replay_pair.py --settings C:/master-course/output/executed_soc_20260926/controller-settings.json --archive C:/master-course/output/executed_soc_20260926/remaining_campaign/2025-03-03/state/b5023143-6887-5d46-8a3d-8015649c5bff.zip --archive-sha256 13cd365f16278330a861ffb9dba6c41e8199a92f738caa7c129ee00d1766262f --step 61 --memory-gib 8 --output C:/master-course/output/charging_replay_pair_next
```

この8GiBは両条件共通の診断予算で、過去の16GiB週と同条件の再現という意味ではない。state.jsonに段階・資源判定・比較結果、各policy配下に元の結果構造・native log・MPSとhashを残す。単一窓のエンジン可行判定であり、独立した週間実行監査ではない。MPS一致だけでも実行パラメータや初期候補の採用を保証しないため、native log/設定/結果も確認する。


終了後の集計（求解・再投入なし）:

```powershell
C:/master-course/output/cluster-deployment/controller-venv/Scripts/python.exe -X utf8 tools/research/summarize_charging_replay_pair.py C:/master-course/output/charging_start_review_20260927/march61-native-pair --output C:/master-course/output/charging_start_review_20260927/march61-comparison.json
```

未完了、モデルhash不一致、結果とsummary不一致は拒否。目的値差は得られた候補同士の数値差で、週次実績費用削減ではない。終了理由/gap・可行性を別表示し、短いだけで候補を自動採用しない。Gurobi MaxMemUsedは共有Envの累積ピークであり、後から解いた候補の単独ピークとは扱わない（[公式定義](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/model.html#maxmemused)）。


保存提案のBESSだけを再計算する入口は `tools/research/audit_charging_replay_bess.py --help`。`--archive`へ監査済み元ZIP、`--preflight`へ診断のpreflight.json、`--result`へ各policy/result.json、`--output`へ新しい検査JSONを指定する。元ZIP/hashから設備の効率と制限・直前の実残量を読み、対象窓の96区間を検算する。前日初期在庫に戻さない。許容差は1e-6kWh。これは車両SOC・運行・PV量・会計・終端目標の独立監査を代替しない。


## 2026-09-27：初期候補の実測結果と次の探索比較

固定3e6a2678・同一3月step61の比較は両案ともengine可行、600秒time_limit、native費用157,588.716155円、下界155,998.160626円、gap1.009308%。呼出時間633.655秒対634.073秒で、費用・速度の改善はない。全native MPS SHAは一致。binary Startは新incumbentを作らなかったが、候補の数学的不可行を証明したわけではない。標準policyはnoneのまま。

両案の元ZIP/設備/直前状態を用いたBESS96区間の別検算は通過（1,889.439768→2,920.230289kWh、最大収支残差2.14e-13kWh）。これは週間実行・全車両・会計の独立再監査ではない。証拠は `output/charging_start_review_20260927/march61-comparison.json` と同 `march61-native-pair/*bess*audit.json`。

次の診断は既存CLIへ `--comparison bound_focus` を指定する。元のMIPFocus1/no-startとMIPFocus3/no-startだけを比較し、600秒、gap1%、seed42、4threads、許容差、Presolve0、Method0、SOC・BESS方策は保持する。起動時の全Config比較と、native MPS・実効パラメータ記録で差分を検査する。実行後は従来のsummary CLIで集計できる。省略時のcomparisonは従来のcharging_start。通常キャンペーンの既定値は変更しない。

目的は同じ終了基準へ早く到達するかの確認であり、下界改善を費用削減と扱わない。まずstep61、改善の兆しがあれば既に復元済みの通常窓step12も確認する。可行性、費用、gap、時間、メモリを並記する。600秒未達・費用悪化・可行性不明なら高速化の採用根拠にしない。単一窓で週次安定性を主張しない。既存11月のattempt・予約・固定版は変更しない。

Claudeの提案はMIPFocus3。ただし「Startが劣る」「改善する可能性が高い」は証明されておらず採用理由にしない。根拠はログ上38秒以降のincumbent、75秒以降のbound停滞と、Gurobi公式の[パラメータ定義](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html#parameter-MIPFocus)。実測で判断する。


## 11週全体の毎時所要時間（原本照合、再求解なし）

1〜10月・12月の1917窓を照合した。時間切れ67窓（3.50%）がnative求解時間の56.34%を占める。呼出合計88502.91秒のうちnative71347.26秒（80.62%）、それ以外17155.65秒。11月途中のnative約97%だけを全月へ外挿しない。6〜8月は時間切れ0で、構築/抽出/検査も相対的に大きい。

測定元は `output/charging_start_review_20260927/monthly-timings-v2/{summary.json,comparison.csv,README.md}`、再現スクリプトは同親ディレクトリの `collect_monthly_timings.py`。各窓のsummary/result/native logを回収ZIP SHAおよびmember hashと照合した。求解打切りと物理失敗は別。queue、Prepare、前日計画、実行再現、回収・図表はこの時間に含まず、月・PC差があるのでPC速度比較にもしない。
