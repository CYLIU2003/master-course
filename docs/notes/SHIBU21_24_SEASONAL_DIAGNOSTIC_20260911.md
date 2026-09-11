# 渋21・渋22・渋23・渋24 四季1週間診断

弦巻営業所の4系統を合算し、2025-02-03、2025-05-12、2025-08-04、2025-11-03から各7日を診断する。春はゴールデンウィークを避ける。時刻表は取得済みの2026年9月版を固定し、2025年の季節別気象を適用する。2025年の実運行再現ではない。

## 入力と出典

既存の渋21〜23選択済みデータは変更しない。公式ODPT APIで取得した渋24の6パターン・582便（平日224、土曜188、休日170）を別の診断用入力へ接続した。TokyuBusのoperator ID、公式の停留所列、座標の存在と正値の区間距離を監査した。距離は停留所座標から算出したproxyであり、道路に沿った実測運行距離ではない。ブラウザ時刻表との全便照合も未完了なので、研究採用の出典とは扱わない。

`scripts/audits/audit_shibu24_source.py` の監査と `scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py` の接続処理を分離する。新入力は22パターン、冬・春・夏は各3,182便、秋は3,045便。候補段階ではUNKNOWN operatorと非正値距離は各0件である。

## 固定条件

4系統の暦別便数は平日488、土曜391、日曜・祝日351。秋週は11月3日が祝日のため他週より137便少ない。暦を維持した季節診断であり、季節間の総費用差をPVだけの因果効果とは解釈しない。

- 4系統をまとめた1ケース、各季節7日、15分刻み。
- 毎営業日終了時は弦巻へ帰庫。
- 元の親シナリオ `771d115b-75b0-49f7-a7f0-25f259a2cd21` から同じ有効車両集合を引き継ぐ。確認値はBEV35台、ICE25台、計60台で、設定値による車両の補充・除外は行わない。
- seed 42、solver threads 12、day-ahead共通予算900秒、Stage 1最大120秒、Stage 2最大30秒、毎時最大15秒。構築時間を含む既存の予算制御を使用する。
- successor pruning 0、解後修復なし。BESSは初期3,000 kWhへ日次復元し、系統からBESSへ充電しない。BEVは評価終了時に各車両の初期SOCへ戻す。
- PV予測は2024年だけで学習した暫定的な季節気候proxy。2025年の日射推定値は実行評価用の別入力で、予測学習には使わない。2022/2023年不足分の追加API呼出しは行わない。

## Prepareと実行

通常の入力生成は候補を専用の `candidate_prepared_inputs` に保存し、`RunPreparation.is_valid=False` とする。厳密な遷移監査を省略した候補を、正式な `output/prepared_inputs` に置いたり、Prepare成功として扱ったりしない。

コードをコミットしたclean worktreeで、親シナリオと必要な取得済みデータを複製する。シナリオの絶対参照は複製先だけへ付け替え、元の親ファイルとDBのハッシュを保存する。過去のprepared inputやsolver結果は引き継がない。

```powershell
C:\master-course\.venv\Scripts\python.exe -X utf8 scripts/benchmarks/prepare_shibu21_24_seasonal_inputs.py --validate --output output/shibu21_24_seasonal_inputs_validated_20260911
C:\master-course\.venv\Scripts\python.exe -X utf8 scripts/benchmarks/run_shibu21_24_seasonal_diagnostic.py --run --output output/shibu21_24_seasonal_diagnostics_20260911
```

`--validate` は既存の `get_or_build_run_preparation` を4週間それぞれに対して最後まで実行する。開始・完了・例外・経過時間を週ごとの `prepare_progress.json` に保存する。長時間であることだけを失敗とみなさない。

Prepareの返却値が成功でも、遷移ネットワーク、折返し余裕、車種互換性、strict coverageの各監査を個別に確認する。監査が未実施・不成立の週はsolverを開始せず、失敗理由を残す。他の入力検証済みの週は続行する。系統不足や親フリートの変化は共有の阻害要因として4ケースを停止する。系統を減らした代替ケースは実行しない。

各週のsolver例外でも後続週を継続し、`failure.json` と `summary.json` に記録する。Git SHAとdirty状態を開始前・週ごと・終了後に検査し、変化を検出した後のsolver実行を止める。集約した `seasonal_evaluation.json` は全4ケースの状態・毎時prefix数・物理検証・会計適格性・最終費用・阻害理由を保存する。未取得の値はnullとする。

## 検証範囲と未完了事項

最初の凍結SHA `737e07be` の完全Prepare中に、地点照合の反復を観測した。[計算単位のキャッシュ](LOCATION_LOOKUP_SCALABILITY_20260911.md)で同等性・性能・回帰を検証したため、修正後の診断は新しいclean worktreeと出力から再実行する。旧SHAの未完了入力や結果は再利用しない。

候補4ケースの生成、candidate namespaceの拒否、例外後の後続週実行、週単位のPrepare阻害、監査未実施の拒否を回帰テストで確認する。完全Prepareとsolver実行の結果は、凍結後の別成果物に記録する。

診断の成功は、研究採用・予報技能・実運行再現・統合大域最適性を意味しない。独立レビュー、既存PowerPoint証拠の2件の不整合、正式研究実行は別の未解決ゲートである。全成果物を **DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS** として扱う。
