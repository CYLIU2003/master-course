# AIエージェント向け修正指示書 — 2026-07-26 実行結果の是正

## 0. 目的と完了条件

この指示書は、次の二つの出力を研究・教員説明に耐える状態へ是正するための実装指示である。

| 条件 | 出力ディレクトリ | scenario_id |
|---|---|---|
| 高PV（晴天候補） | output/2026-07-26/run_20260726_1502 | 771d115b-75b0-49f7-a7f0-25f259a2cd21 |
| 低PV（雨天候補） | output/2026-07-26/run_20260726_1518 | b23fd26c-1233-4c73-bb9e-bdb8b1584760 |

完了は「コードを変更した」ことではない。以下をすべて満たす新規の clean-worktree 実行成果物、テスト、再現手順、レビュー記録が揃った時点でのみ完了とする。

1. 物理量、費用、CO2、目的関数の意味がそれぞれ整合し、検証ERRORがゼロである。
2. 実行日・曜日・時刻表・車両台数・天候データの関係が明示され、比較の意味が崩れていない。
3. 日次計画後の時間別 rolling 再最適化が実行され、そのログとSOC・PV・BESSの状態遷移を追跡できる。
4. 生成物が実際に生成に使ったソースのコミット、dirty状態、入力ハッシュ、設定、ソルバログを持つ。
5. 「実コスト最小化」「厳密MILP」「全体最適」「実天候比較」といった主張は、対応する証拠がある場合だけ行う。

この作業は、最小限かつ検証可能な差分で行うこと。旧成果物を上書き・手編集・再ラベル化してはならない。必ず別の新規 run ディレクトリへ再実行すること。

## 1. 現時点で確認済みの事実

### 1.1 成果物の再現性は未達

- 7月26日ZIPの code provenance は dirty な e2e54f1 系であり、現在の clean HEAD とは一致しない。
- 同ZIPの reporting rebuild は solver_rerun=false、simulation_rerun=false、no_reoptimization_performed=true である。従って、後から再構築したグラフを「現在のモデルで再最適化した結果」と表現してはならない。
- run_input_provenance の git_state_available=false と code_provenance の dirty 表示にも不整合がある。

### 1.2 物理燃料台帳とsolver費用台帳が不整合

両runで data_flow_validation_status=ERROR であり、少なくとも次の4件がERRORである。

- solver_fuel_cost_matches_physical_fuel_ledger
- solver_ice_co2_matches_physical_fuel_ledger
- kpi_fuel_cost_matches_fuel_canonical
- cost_breakdown_fuel_cost_matches_fuel_canonical

不一致は燃料費で 59.734513274321216 円、ICE CO2で 1.0297811946886668 kg である。物理燃料は 444.79487876106197 L、solver側の燃料費から逆算される燃料は 444.3966486725665 L である。

実行経路で確認した原因は、BFFの canonical trip assignment が同一の接続デッドヘッドを二重に出力していることである。

- bff/routers/optimization.py の 3820–3852 行は、次legの deadhead_from_prev_min を現legの deadhead_after_km にも書き出す。
- 同ファイルの deadhead_before_km は次leg側で同じ接続移動を既に表す。
- src/optimization/accounting/ledger_builder.py の 265–279 行は before と after の両方を燃料・距離台帳へ加算する。

この経路は、BFFから生成する canonical 出力に到達する実経路として確認済みである。旧来の src/result_exporter.py を先に修正してはならない。CLI等の別エントリポイントにも同じ契約が必要と確認できた場合だけ、その到達経路を別途テストして修正すること。

### 1.3 現在の比較は教員説明用の実験として未達

- 両runとも264/264便を運行し、SOC・契約電力・充電器等の基本的 solution validity は通っているが、research_kpi_eligible=false である。
- 両runとも二段階で、supports_exact_milp=false、objective_is_actual_cost=false である。Stage 2 のoptimal表示を全体統合コストのglobal optimumと呼んではならない。
- 高PV run は PV 614.709375 kWh、PV→BESS 276.088794 kWh、PV→bus 261.526616 kWh、BESS→bus 249.170136 kWh、PV curtailment 77.093966 kWh である。「PVを全量使い切った」とは言えない。
- 低PV run の grid→bus は 411.374162 kWh、高PVとの差額コストは 8,606.380485 円で方向は整合的だが、上記の台帳ERRORと比較設計不備が残るため研究結論には使えない。
- 高PVは2025-08-05（火曜）、低PV候補は2025-08-10（日曜）だが、後者の264便はすべて Weekday 系trip IDである。これは実天候日の運行比較として無効である。
- 車両在庫は35 BEV + 25 ICEであり、要求されている35 BEV + 26 ICEと一致しない。さらにBEV使用は13台にとどまる。必要なら「全35台を使った」とは絶対に言わない。
- rolling status は not_executed である。日次＋時間別再最適化を行ったとは言えない。

### 1.4 晴天だけが速いという仮説は未確認

両7月26日runの総実行時間は約775.9秒で、差は約0.32秒（0.041%）である。Stage 1 はいずれも約750秒の上限まで動き、最初のincumbentは約0.35秒、Stage 2は約0.1秒である。したがって、今回の対比から「晴天だから最適化が一瞬で終わる」とは結論できない。

以前の高速runは、天候よりも、早期停止、Stage構成、時間上限、目的関数、入力規模、キャッシュ、fallback、ソルバ利用可否、あるいは実行経路の相違で説明される可能性が高い。これは推論であり、旧runのprovenance比較で実証するまで断定しないこと。

## 2. 絶対に守る制約

以下を破る変更は受け入れない。

- dispatchの feasibility 条件 arrival + turnaround + deadhead <= next departure を緩めない。
- timetable_rows を黙って書き換えない。operator_id を落とす、補完する、無視することをしない。
- 物理燃料、タンク残量、補給、物理CO2を費用差に合わせて比例補正・再配分しない。
- 目的関数値を費用へ、または費用を目的関数値へ、根拠なく合わせない。
- toleranceを緩めて検証ERRORを隠さない。単位・丸め・数値安定性を先に是正する。
- 旧runのCSV/JSON/XLSXを書き換えて再利用しない。新しいclean runのみを結論の根拠にする。
- 実際に通るBFF経路を確認せずに、名前が似たlegacyコードだけを修正しない。
- 新しい制約、proxy、早期停止、fallbackを「正式な研究モデル」や「最適解」として黙って昇格させない。

## 3. 実装順序

### Step A — provenance契約を先に固定する

1. 最適化開始時に、少なくとも次を run provenance として保存する。
   - Git SHA、dirty状態、差分の有無またはパッチハッシュ
   - Python環境、Gurobiバージョン、solver利用可否、seed、threads
   - 実行モード、Stage別time limit/gap/early-stop設定、fallback可否
   - scenario/prepared input/timetable/vehicle/PV profile のSHA-256
   - service date、weather observation date、weather data source、比較種別
2. reporting再構築は、入力artifactsのprovenanceが一致しない場合、研究用KPIを生成してはならない。明示的に stale または provenance_mismatch として失敗させるか、非研究用表示に落とすこと。
3. updated_files は静的な定数配列ではなく、実在して生成・更新したファイルから作る。results.xlsx が無いのに「更新済み」と記録してはならない。
4. 新規テストで、dirty run、SHA不一致、欠落ファイル、rebuild-onlyを検出し、誤って research-ready と表示しないことを確認する。

### Step B — デッドヘッドを一意の移動イベントとして扱う

1. BFF canonical出力を、trip行の before/after 二重表現ではなく、重複しない movement event を一次情報にする。
2. event type は少なくとも startup、connection、terminal_return を区別し、各eventに vehicle_id、event_id、開始/終了時刻、距離、対応する前後trip、エネルギー・燃料の計算根拠を保存する。
3. connectionは「次のtripの前」に一度だけ所有させる。現tripの after に次tripの deadhead_from_prev を複写してはならない。
4. terminal_return は、solverがその移動をモデル化している場合だけ、最終trip後の一意なeventとして出す。次tripの接続移動から推測してはならない。
5. accounting ledger、vehicle_schedule、可視化CSV、燃料・CO2集計はこの一意event集合を参照する。表示上before/after列を残す必要がある場合も、二重加算しない責務を明文化する。
6. solver/evaluatorと同一の距離・燃費・CO2係数・符号規約を使う。丸めは最後の表示段階だけで行う。
7. 物理量と費用の不一致を、物理台帳の再配分で隠してはならない。原因がsolver本体と台帳のモデル差なら、その差をERRORとして残し、両者を同じ定義へ修正すること。

必須の回帰テスト:

- startup、connection、terminal return をすべて持つICE dutyで、各移動が台帳にちょうど一回だけ現れる。
- 接続移動の距離合計、燃料L、ICE CO2、燃料費が、独立に計算した期待値と一致する。
- BFFの実際の run-optimization → canonical artifact → build_accounting_artifacts 経路で同じ検査を行う。ledger_builderだけを直接呼ぶ単体テストで代用しない。
- fuel/CO2の4件の既存ERRORが新runでOKになる。目的関数が実コストではない場合でも、燃料・CO2の物理整合はOKでなければならない。

### Step C — service date、曜日、天候の比較契約を実装する

1. src/optimization/common/builder.py でraw timetable_rowsをProblemDataへ採用する前に、service dateと曜日/サービスカレンダー/trip IDの整合を検証する。
2. Sundayのservice dateにWeekday時刻表を載せるような組合せは、明示的なcounterfactual mode以外ではhard failureにする。
3. counterfactual modeでは、運行service dateを保持し、別に weather_observation_date と weather_profile_source を持たせる。成果物には comparison_type=counterfactual_weather_profile を明記し、「当日の実雨天運行」とは表示しない。
4. 実天候比較を行う場合は、各日の実際の時刻表・曜日・祝日・運行カレンダーを使う。単にPV量だけを差し替えた比較とは区別する。
5. 研究仕様が35 BEV + 26 ICEなら、prepared input作成時に台数をhard assertする。35 + 25のまま実験を通してはならない。全BEV使用を研究仮説に含めない限り、未使用BEVを無理に割当てない。使用台数は結果として報告する。

### Step D — SOC終端制約と独立検証を一致させる

1. solver設定、postsolve validator、solution_validity、reportingの終端SOC判定に同じ単位と明示された許容誤差を使う。
2. あるrunで terminal_soc_balance_satisfied=false なら、そのrunを validated_feasible と研究用に同時表示してはならない。差分、目標、許容値、判定経路を一か所に記録する。
3. BEVとBESSの開始SOC、終了SOC、充電、放電、走行消費、損失の収支を独立に再計算する。固定target、return_to_initial、minimum_onlyを混同しない。
4. 既存のStage別FeasibilityTolの意図を保つ。高精度化または低精度化で実行時間を議論する場合は、同一入力・同一上限で比較し、制約違反・gap・runtimeを同時に報告する。

### Step E — 教員説明用の実験を再実行する

新しい比較は、以下を固定したpaired experimentにする。

- 同一の264便、同一service calendar、同一vehicle inventory（35 BEV + 26 ICE）、同一depot、同一料金、同一BESS、同一seed、同一solver設定
- 変える要因は事前登録したPV/weather profileだけ
- 各runで日次最適化後に、時間別rolling再最適化を実行する
- すべてのrolling stepで、引き継いだBEV SOC、BESS SOC、実績/予測PV、未完了trip、再最適化入力と出力を保存する

教員向けには最低限、次を図表またはmachine-readable artifactで示す。

- PV→bus、PV→BESS、BESS→bus、grid→bus、curtailment、BESS損失
- BESS開始/終了SOCとエネルギー収支
- BEV別の充電時刻、充電kW、充電時間、SOC前後、走行消費
- BEV/ICEの使用台数、trip数、走行距離、燃料、CO2、未運行便
- total accounting cost、各費目、objectiveの名称・単位・actual-costかどうか
- Stage別status、best bound、incumbent、適切なgap、time limit、rolling status

比較の主張は、以下のように限定する。

- objective_is_actual_cost=false なら「実コスト最小化」と書かない。
- supports_exact_milp=false または二段階なら「統合問題のglobal optimum」と書かない。
- counterfactualなら「PV供給感度」と書き、「実天候日における運行実績」と書かない。
- 事前に10%以下のgapを要件にした場合、両条件が満たすまで合格にしない。7月26日の低PV候補は約10.54%であり、この基準を満たしていない。

### Step F — 速度問題は測定してから対処する

性能改善はStep A〜Eの正確性が通った後に着手する。

1. 過去に「一瞬で終わった」とされるrunと、新runのprovenanceを並べ、solver_rerun、simulation_rerun、stage別time limit、early stop、objective、入力hash、arcs/variables/constraints、solver availability、fallback、cache hitを比較する。
2. 同一ハードウェア・同一設定・同一入力で各条件を少なくとも3回実行し、wall time、model build time、presolve、nodes、cuts、first incumbent time、best bound、gap、Stage別timeを保存する。
3. 改善策は原因が確認できたものだけを採用する。上限時間の短縮、early stop、制約削除、fallbackを性能改善と見せかけない。
4. successor arc pruningなど、問題の数学的な意味を変える最適化を採用する場合は、未pruned基準とのfeasibility・目的値・割当て差・run timeを比較し、適用範囲を明記する。

## 4. 受入テストと新runのゲート

実装者は新しいテストを追加したうえで、少なくとも以下を実行し、コマンド・環境・結果を成果物に残すこと。

1. 新規のBFF end-to-end canonical movement / fuel / CO2 regression
2. 新規のservice-date / calendar / counterfactual契約テスト
3. 新規のprovenance mismatch / missing artifact / rebuild-only rejectionテスト
4. 新規または拡張したterminal SOC一貫性テスト
5. 既存の次の重点テスト:
   - tests/test_milp_soc_validator_roundtrip.py
   - tests/test_canonical_cost_ledger_alignment.py
   - tests/test_reporting_objective_cost_semantics.py
6. Gurobiが利用可能な環境では、実solverを通る統合テストをskipさせずに実行する。
7. 全回帰:
   .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
8. 静的確認:
   .\.venv\Scripts\python.exe -m compileall -q src bff
   git diff --check

新runを研究用に承認する前に、次のすべてが真であること。

- data_flow_validation_status=OK かつERROR=0
- physical fuel/CO2、canonical cost ledger、出力KPIが定義どおりに一致する
- objectiveとaccountingの一致は objective_accounting_equality_required=true の場合だけ必須とし、falseならSKIPPEDと明記する
- solution_validity、BEV/BESS終端SOC、充電器、契約電力、dispatch feasibilityが通る
- provenanceがclean commitおよび全入力hashと一致する
- calendar/service date/weather comparison contractが通る
- rolling statusがexecutedであり、全stepのログが揃う
- 研究仕様上の車両台数とrun inputが一致する
- これらのどれか一つでも失敗した場合、成果物は exploratory / non-research と表示し、教員説明用の結論・KPI・図表へ昇格させない

## 5. 必須の成果物と文書更新

新規runディレクトリには、少なくとも次を含める。

- code_provenance、run_input_provenance、scenario/prepared input、manifestと全SHA-256
- solver_settings、solver log、Stage別metadata、rolling step log
- canonical cost ledger、energy flow ledger、vehicle slot ledger、movement event ledger
- solution validity、data-flow validation、calendar/weather validation
- 比較表と図の元データ。Excelを更新した場合だけresults.xlsxをmanifestとupdated_filesへ載せる
- 実行コマンド、環境、テスト結果、既知の残余不確実性

コード変更時は必ず DEVELOPMENT_NOTES.md を更新し、目的関数・費用・制約・出力契約・研究主張に影響する変更ならREADMEまたは該当設計文書も更新する。変更前後で比較不能になる成果物を明記すること。

コミットは混ぜない。推奨順は以下である。

1. fix(accounting): canonical movement eventと二重計上の是正、回帰テスト
2. fix(validation): provenance、calendar、terminal SOCのhard gate、回帰テスト
3. feat(reporting): manifest・rolling artifact・比較表示の契約化
4. docs(research): 再現手順、実験設計、結果の有効範囲

## 6. 第三者レビューの必須ゲート

実装完了後、Claude Codeと開発担当の役員に、それぞれ独立に以下をレビューしてもらうこと。

- 実際のBFF call chainでデッドヘッドが一度だけ計上されるか
- 物理燃料・CO2を費用合わせで改変していないか
- 結果のprovenanceと新runのgit SHAが一致するか
- weather/service-date/calendarの比較が研究上有効か
- rollingが実行され、教員に説明できる中間状態が残るか
- objective/optimality/gapに対する主張が過大でないか

P0またはP1指摘が残る限り、承認・発表・教員への「解決済み」報告をしてはならない。レビュー指摘、対応、未対応理由をDEVELOPMENT_NOTES.mdまたは専用レビュー記録へ残すこと。
