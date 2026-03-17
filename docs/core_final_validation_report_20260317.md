# Core Final Validation Report (2026-03-17)

## 3) Tk運用フロー最終チェック（優先実施）

目的
- Tkinter + BFF の core 導線で、東急最適化まで到達できるかを確認する。

チェックリスト
- [ ] Tk起動: tools/scenario_backup_tk.py が起動する
- [ ] シナリオ作成/選択: Scenario CRUD が機能する
- [ ] Quick Setup 読込/保存: 営業所・路線・日種を保存できる
- [ ] Prepare 実行: ready=true を返す
- [ ] Optimization 実行: ジョブが completed まで到達する
- [ ] 結果確認: optimization_result を取得できる

自動検証で取得済みの事実
- Prepare は成功（ready=true）
- Job は completed まで到達
- mode は mode_milp_only で実行
- solver_status は ERROR（最適化の数理解としては未成立）

証跡ファイル
- outputs/jobs/a5ad85b0-27d9-45d8-bf01-ff1402c7b222.json
- outputs/scenarios/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f.json

注意
- このセッションでは Tk GUI 自体の手動クリック操作ログを自動収集していない。
- 先生レビュー前に、上記チェックリストの手動実行ログ（スクリーンショット or 操作記録）を添付すること。

## 2) solver_status=ERROR の切り分け（次優先）

観測
- Job metadata:
  - status=completed
  - mode=mode_milp_only
  - solver_status=ERROR
- optimization_result.json は未生成

解釈
- BFF のジョブ管理は完了しているが、MILP 求解は失敗または実行可能解なしで終了した状態。
- これは「APIクラッシュ」ではなく「ソルバ結果失敗」の系統。

直近の技術原因候補
- C1 が unserved 付き緩和で、罰則とのトレードオフ次第で解品質が不安定
- C8/C11/C12/C15-C21 など、docs/constant/formulation.md の制約群が実行ソルバに未反映
- 目的関数が TOU 平均単価近似で、電力需給制約群と整合した厳密モデルではない

更新メモ（2026-03-17 追記）
- `src/optimization/milp/solver_adapter.py` に C8/C11/C12/C15-C21 を追加実装
- 目的関数 O1/O2/O3（ICE燃料・TOU買電・デマンド料金）を実装
- ALNS/GA/ABC も `src/optimization/common/evaluator.py` の共通評価で O1/O2/O3 を反映

次アクション（修正候補）
1. solver_adapter.py に電力バランス系（g_t, pv_t, contract, demand）を実装
2. terminal SOC（C11）と走行中充電禁止（C12）を追加
3. deadhead energy（C8）を SOC 遷移へ投入
4. infeasibility diagnostics（IIS/Farkas）を結果に保存

## 1) GitHub同期前の最終確認

- README.md に docs/constant/formulation.md の C1-C21 対応表を記載済み
- docs/core_parameter_preservation_manifest.md は追加済み
- docs/tkinter_feature_parity_backlog.md は追加済み
- 本レポートを添付し、レビュー時の検証証跡として利用可能
