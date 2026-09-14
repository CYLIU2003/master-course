# 月別比較の3月 hour 152: SOC再計算の不一致

更新（2026-09-14 19:37 JST）: この修正を凍結した `829e3983` の全月再計算は、1月の前日Stage 2が30秒制限でincumbentを得られず停止した。完走0/12週、rolling未開始、前後SHA/cleanは一致。以下の3月・4月の固定割当診断通過は、1月を含む全月の前日求解時間を保証しない。Stage 2のモデル・数値許容誤差を保持した予算診断を別途行い、全月共通設定を見直す。停止原本は `output/monthly_presolve_campaign_v3_20260914/cases/2025-01-06/diagnostic/2025-01-06/` に保持する。

第2回月別campaign（固定 `8acd8beb`）は1・2月だけが完走し、3月は152/168時間を受理した後に停止した。4〜12月は未実行。以下は原因を確かめる単独診断であり、週間結果や季節の研究結論には使用しない。

## 保存原本から再現した事実

対象車 `befc4670-e889-45d9-bd65-23118c02e196` のhour 152は、初期SOCが123.03739057599992 kWh、終端目標が223.35762 kWhだった。native結果の終端SOCも223.35762 kWhだったが、保存された充電出力と同じ `fixed_path_slot_loads` の走行負荷を64区間にわたって再計算すると223.35761781498206 kWhとなった。差は−2.1850179336979636e-6 kWhで、既存の1e-6 kWhの検証基準を満たさなかった。

元のPrepared入力・固定割当・hour 152初期状態から再構築した問題を、凍結版の同じ設定で求解すると、失敗値と費用目的値157.08362845308528が一致した。Gurobi自身の最大制約違反 `ConstrVio` は5.70004289102144e-7だった。表示の丸めや目標値の取り違えと結論づける根拠はなく、SOC遷移を含む求解値の制約誤差が確認された。

## 同一モデルの比較と修正

ネイティブMPSの係数・右辺・変数上下限・整数条件・目的関数を変えずに比較した。全ケースでFeasibilityTol/IntFeasTolは1e-9、Aggregateは0、seedは42、threadsは12、MIPGapは0.1とした。

| 設定 | 最大制約違反 | 求解秒 | MIP gap |
|---|---:|---:|---:|
| 既存設定 | 5.7000e-7 | 0.819 | 0 |
| NumericFocus=3 | 5.7001e-7 | 1.527 | 0 |
| Presolve=0 | 6.6763e-11 | 1.377 | 0.0109742 |

Presolve=0を初回から全Stage 2へ一律適用する。既存のAggregate=0も保持する。失敗した時間だけの再試行、SOC補正、充電量の改変、制約・検証許容誤差の緩和は行わない。Gurobiの公式資料も、Aggregate=0で数値問題が残る場合のPresolve=0による検証を説明している。[Gurobi: Solver Parameters to Manage Numerical Issues](https://docs.gurobi.com/projects/optimizer/en/current/concepts/numericguide/numeric_parameters.html)

また、数値診断が存在しない `MaxConstrVio` / `MaxBoundVio` / `MaxIntVio` 属性を参照してnullになっていたため、実在する `ConstrVio` / `BoundVio` / `IntVio` に修正した。Presolve設定は成功・失敗結果のmetadataから公開solver_metadataまで転送する。

これは数値計算手順の変更で、数理モデルの実行可能集合・単位・費用式は変更しない。ただし、時間制限内に得る解やgap、実行時間は変わり得る。上表のPresolve=0は1.097% gapを残す実行可能解で、厳密最適解の証明ではない。元のStage 1のgap未達、二段階分離の制約も残る。

## 検証と再実行条件

- 修正後の実際の `RollingReoptimizer` → `OptimizationEngine` 経路で、保存された3月のhour 152を再実行し、feasible、検証違反なし、公開Presolve=0、最大制約違反6.6763e-11を確認した。
- 回帰テストは元の64区間ネイティブモデルをgzipで保存し、解凍後SHAまで照合する。充電電源フローと走行負荷から終端SOCを再計算するため、solver statusだけでは通過しない。
- 以前の4月の実行可能境界と、初期SOCを1 kWh増やした真の実行不能条件も保持した。上記3テストは通過した。
- 7日全体・672区間の元の固定割当でもfeasible、検証違反なし、最大制約違反6.4920e-10を確認した。これは固定割当Stage 2の診断で、168時間のrolling実行結果ではない。
- 4月の元のhour 023を初期状態から再実行し、feasible、検証違反なし、最大制約違反7.6255e-11を確認した。
- 数値修正の独立レビューはP0/P1/P2ゼロ。追加の契約電力設定修正と最終全体検証は下記へ追記する。

## 全体回帰で見つかった設定不一致

最初の全体回帰は2,281 passed / 5 failed（117.61秒）。既存PowerPoint証拠2件に加え、候補比較の3件が失敗した。旧求解側が `enable_contract_overage_penalty` の未指定をTrueと解釈する一方、独立検証は明示的なboolean Trueだけを許可していた。前処理を無効にすると、未指定ケースに作られた不要な超過変数が正値を取り、検証側の超過量0と一致しない場合があった。

Stage 2、統合モデル、Stage 1の緩和モデル、費用評価に加え、PV不足への事前予備制約と実際のPV実行処理も、既存の検証と解釈を揃えた。未指定・None・文字列・整数1では、受電量を契約上限×区間時間以下にする。明示Trueの場合だけ超過変数を認める。これにより**未宣言入力のモデルはsoft limitからhard limitへ変わる**。明示True/Falseの契約やBuilderが記録するboolean値は変更しない。月別の実際のcanonical problemはTrue、超過単価500円/kWhを明示していることを確認した。

候補比較の既存20テストは全通過し、契約超過・数値修正を含む55テストも通過した。未指定/None/文字列/1を許可と扱わない費用評価の回帰を追加した。受電量や超過量を後処理で書き換えて検証を通す修正ではない。独立レビューでPV予備制約・実行処理に残る不一致（P1）も見つかり修正した。False/None/文字列/1/未指定の5条件では、予備制約が超過を実行不能とし、実行処理もhard import例外で停止することを確認した。明示Trueの対照は保持。関連71件が通過した。最終全体回帰と追加レビューを確認後、新しいclean固定版から12週すべてを再計算する。

元の1・2月を新しい版の結果へ流用せず、hour 152だけを元のchainへ継ぎ足さない。新しい12週の実行と独立監査が完了するまで、月別・季節別の最終結論は未完成である。

## 原本

mainの `output/monthly_fair_weeks_20260914/` 配下:

- `march_hour_152_trace/trace.json`: 保存された充電・走行とnative SOCの区間比較。
- `march_hour_152_native_replay/`: 元モデル再構築、MPS、パラメータ、解、quality、数値設定比較。pickleはこの診断で生成したローカルデータのみを使用。
- `march_hour_152_presolve_0_engine/`: 修正後の全経路の単独診断結果。
- `tests/fixtures/stage2_march_terminal_replay.mps.gz` と同名JSON（repository内）: 元モデルと原本hash、再生に使う初期状態・走行負荷。

停止したcampaignの原本は `C:/master-course-worktrees/shibu21-23-monthly-numeric-20260914/output/monthly_numeric_campaign_20260914` に保存する。これらはDIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSである。

## 最終コード検証

全体回帰は **2,297 passed / 既存PowerPoint証拠2 failed、103.93秒**（`output/monthly_fair_weeks_20260914/pytest-presolve-final-contract-release.xml` と同名log）。既存の失敗は `test_original_and_all_bound_sources_unchanged` と `test_unrelated_presentation_parts_remain_byte_identical` で、研究資料のhash/byte照合に関する未解決項目として維持する。新規失敗は0件。Lunaの `march_numeric_policy_review.json` で残P0/P1/P2ゼロ、レビュー対象hashを最終コードへ照合した。これを研究採用やモデル完成とは扱わず、新しい固定版の月別diagnostic実行へ進める。

## 新しい固定版の実行

clean SHA `829e39835327b75c227737f9a5f4d3a76670adf1` の `C:/master-course-worktrees/shibu21-23-monthly-presolve-20260914` で、凍結後20テストと元hour152の全経路検証を通過。後者は前後同SHA/clean、native Presolve=0、最大制約違反6.6763e-11。2026-09-14 19:15 JSTに `output/monthly_presolve_campaign_v3_20260914` を開始した。開始時点0/12週、1月Prepare中。初回2つの起動は求解前に親シナリオ管理JSONの不足、続いて最初の事前生成出力との衝突で停止して保存。管理JSONの11参照先だけを移設し、その他の全フィールド同一、60台親シナリオの読込みを確認した。47入力ファイルはbyte/hash一致。事前生成データは `source_candidate_preflight_missing_parent` に保存し、v3では新規作成する。これらの事前準備失敗に求解済みの週はない。
