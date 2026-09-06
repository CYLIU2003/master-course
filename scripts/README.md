# 正式実験・監査スクリプトの案内

ここには実験CLI、根拠生成処理、入力整備スクリプトを置いています。
入力整備の本体は用途別フォルダへ分離しました。旧パスは互換入口です。
正式実験・根拠生成CLIは保存済みコマンドと凍結manifestを保つため現位置を維持します。
以下は主要な入口の用途別案内です。
名前が `run_`、`verify_` だから安全・承認済みという意味ではありません。

## 先に読むもの

- [正式runbook](../docs/notes/FORMAL_RUNBOOK_CURRENT.md)
- [現行blocker](../docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md)
- [ファイル保管ルール](../docs/REPOSITORY_LAYOUT.md)

## 用途別の主要入口

- [catalog: カタログ構築・変換・車両データ抽出](catalog/README.md)
- [weather: 天候データ整備](weather/README.md)
- [validate_output_consistency.py: 出力整合性検査](validate_output_consistency.py)

新規の入力整備スクリプトは上記フォルダに追加し、ルートの互換入口を実装本体として編集しないでください。

| 用途 | 既存スクリプト |
|---|---|
| 正常経路の晴雨診断 | [run_weather_dispatch_diagnosis.py](run_weather_dispatch_diagnosis.py) |
| Phase 3 frontend晴雨実行 | [run_research_phase3_frontend_weather.py](run_research_phase3_frontend_weather.py) |
| PV制御比較 | [run_frontend_controlled_pv_pair.py](run_frontend_controlled_pv_pair.py) |
| 純ICE集約A/B | [run_pure_ice_aggregation_weather_ab.py](run_pure_ice_aggregation_weather_ab.py) |
| 入力provenance検証 | [verify_run_input_provenance.py](verify_run_input_provenance.py) |
| frontend成果物検証 | [verify_frontend_run_artifacts.py](verify_frontend_run_artifacts.py) |
| 修論の結果package | [build_thesis_weather_result_package.py](build_thesis_weather_result_package.py) |
| 修論package検証 | [verify_thesis_weather_result_package.py](verify_thesis_weather_result_package.py) |
| 実験計画表 | [build_thesis_experiment_matrix.py](build_thesis_experiment_matrix.py) |
| 時間刻みの結果整理 | [build_time_discretization_reporting.py](build_time_discretization_reporting.py) |
| 固定解stress | [run_fixed_solution_stress.py](run_fixed_solution_stress.py) |
| カタログDB構築 | [build_tokyu_full_db.py](catalog/build_tokyu_full_db.py)、[build_tokyu_gtfs_db.py](catalog/build_tokyu_gtfs_db.py) |

同じprefixの他ファイルもあります。この表は全件の安全性監査や実行許可ではありません。
新しい補助計測は [tools/benchmarks](../tools/benchmarks/README.md)、
資料作成は [tools/thesis_authoring](../tools/thesis_authoring/README.md)、
手動スモーク実験は [tools/manual_experiments](../tools/manual_experiments/README.md) へ分離します。
過去の診断を、正式な実験結果として再分類しないでください。
