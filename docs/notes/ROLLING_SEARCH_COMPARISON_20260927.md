# 毎時充電探索の比較と操作設定（2026-09-27）

目的は、完成済みの月を再計算せず、次の週次実行で使える速く安定した設定を調べること。現行11月の固定f524eca2・同一試行は継続する。

## 実測

固定50260755の親機診断。同じ3月原ZIP、各窓の実行直前状態・配車・同一MPSで、MIPFocusのみ1→3。4threads、タスク8GiB、600秒、gap1%、seed42、Presolve0、Method0、NumericFocus0、厳格許容差は共通。共有ライセンス管理の1枠と同一Envを使用し、ペア終了後330秒解放待ち。正式週次の再実行ではない。

|窓|選定の意味|設定1 native秒|設定3 native秒|native目的値の差|両案の判定|
|---|---|---:|---:|---|---|
|3月step61|既知の600秒窓|600.043|42.301|数値誤差内|engine可行・BESS96区間通過|
|3月step12|元119.89秒の中程度の窓|56.743|106.544|数値誤差内|同上|
|3月step75|元3月中央値18.20秒に最も近い18.23秒、実行前選定|6.925|5.828|数値誤差内|同上|

step12を「通常の短い窓」とした途中説明は訂正する。短い窓の代表はstep75。各窓でコード前後clean・SHA同一、nativeモデルhash同一、実効パラメータ差がMIPFocusのみであることを確認した。step61のgapは1.0093%→0.6291%、step12は0.9097%→0.9260%、step75は両案0%。時間・下界・終了理由を費用削減と混同しない。

step75のnative目的値は両案297,229.603883円だが、別途評価されたwindow_objectiveは4,147,475.105035→4,146,714.171960円と異なる。BESS初期は両案1200kWh、終端は1267.007306→1256.344318kWh。縮約された充電目的の一致から全費用・終端状態の一致は導けない。760.933075円を週間実績の削減として採用しない。

診断のcall_wall_secondsにはMPS書出し・hash照合等も含む。native Runtimeと区別し、差分をそのまま通常処理のモデル構築時間とは呼ばない。MaxMemUsedは同一Env内の累積値で、個々の設定のピーク比較には使わない。

## 結論と操作

設定3は長時間窓の改善候補であるが、すべての窓が高速化する証拠はない。既定は設定1のまま。設定3を全週へ自動適用しない。各窓の将来の求解時間を知っている前提の自動切替も導入しない。

新版の「運行・計算設定」→「毎時充電の探索方針」で、`従来：実行可能解重視（設定1）`／`比較用：下界改善重視（設定3）`を保存できる。実行画面にも保存済み方針を表示する。保存後は新しいPrepareが必要で、旧Preparedの再利用判定は入力hashで拒否する。前日配車の探索設定、SOC/BESS方策、料金、ライセンス・RAM制限は変わらない。

経路：`rollingChargingSearch` → scenario `rolling_charging_search` → Prepare → canonical problem metadata → `RollingChainRequest.charging_search` → `OptimizationConfig.stage2_gurobi_mip_focus` → native MIPFocus。保存・Prepareはenumで未知値を拒否し、CLIからの未知値も求解環境を開く前に拒否する。

既存CLI `scripts/run_hourly_charging_reoptimization.py`には`--charging-search feasibility_first`（既定）／`--charging-search bound_first`を追加。CLIの明示指定と画面の保存値は別の入口なので、CLIでは目的の値を指定する。各hourly_summaryにrequestedとnative effectiveを別記録し、求解例外時のeffectiveは未確認としてnull。再診断も保存されたrequestedを引き継ぎ、effective不一致を拒否する。AI・新規ODPT取得は不要。

## 検証の範囲とレビュー

保存・revision/CAS・入力hash変更、Prepare・canonical metadata・BFF→rolling config・native setParamの引継ぎ、未知値拒否、設定以外のcontrol不変を回帰テストする。画面保存とPrepare要求、TypeScript、本番buildも検証。新設定での全週運用・新UIの稼働コントローラーへの配置は別の確認であり、この診断やmockテストだけで完了としない。

Claude Sonnetによる静的レビューを実施。二重の既定値は旧metadataを読む互換処理として保持し、両経路のテストで一致を確認。毎時以外への影響の疑義は呼出し検索と、差分がstage2_gurobi_mip_focusだけで前日既定が不変という回帰で確認した。「P1だがマージ前必須ではない」という分類は採用せず、実害の証拠と分ける。比較用・速度保証なしの表示は維持。レビューの「step75のみ同一MPS」は誤読で、3組とも同一MPSを照合済み。全週の独立承認ではない。

原本：`output/charging_start_review_20260927/march{61,12,75}-bound-focus/`（各state、preflight、comparison、native MPS/log、result、BESS監査）。Claude原文は同ディレクトリの`ui-search-review.json`。原本を公開Gitへ追加せず、上記SHAと保存場所を維持する。
