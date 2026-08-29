# 修論用SUNNY／RAIN結果パッケージ

実験SHA `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` のGit管理済み証拠だけから生成した。数値の手入力は行わず、期待値は生成前のfail-closed assertionにのみ使用する。設備定格値は、各fresh runの`scenario_input_snapshot.json`と`run_input_manifest.json`をexact byte copyしたparameter-source supplementから読む。

## 再生成

```powershell
python scripts/build_thesis_weather_result_package.py `
  --evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005 `
  --output-dir docs/thesis/weather_results_bb0c005
```

## 成果物

- `experiment_parameters.csv/.md`: 実験条件と正本位置
- `scenario_results.csv/.md`: 配車、費用、エネルギー、gap、計算時間
- `cost_breakdown.csv/.md`: 費用項目とRAIN－SUNNY差
- `energy_balance.csv/.md`: PV・BESS・系統収支
- `claim_boundary.md`: 使用可能な主張と限定事項
- `results_section_ja.md`: 修論結果章へ転用できる日本語本文
- `01`～`05`のPNG（300 dpi）・SVG図
- `package_manifest.json`: 入出力SHA-256と図表map

## 図表設計

白背景、フォント`Noto Sans JP`、明示単位、ゼロ始点を使用した。SUNNYは青、RAINとの構成差は橙、PVは金、BESSは青、その他は中立色で表現し、色だけに依存しない直接値・積み上げ位置・凡例を併用した。

06_daily_energy_flow_timeseriesは作成していない。正本bundleには96スロットの実行済みPV・BESS・系統フロー列がなく、rolling_chain_summary.jsonには24個の残余ホライズン集計とGit管理外stateファイルへの参照だけがあるため、差分推定を行わなかった。

## 設備パラメータの補助証拠

`docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources/`にはSUNNY/RAINのfresh runから取得した完全な`scenario_input_snapshot.json`と、それをSHA-256で封印する`run_input_manifest.json`を保存した。Prepared ID・Prepared source SHA・実験SHAを公開済みsummaryと照合し、両ケースで受電上限、PV定格容量、BESS定格容量・出力・SOC範囲・効率が一致することをfail-closedで検証する。

## 主張範囲

結果は、評価した有限候補集合から選択されたPhase 3二段階実行可能解である。費用は本モデルの費用定義に基づく24時間Rolling実行日評価額、gapはStage 1の近似目的関数に対するcertified MIP gapとして扱う。2ケースの差を一般化しない。

Source bundle tree SHA-256: `c706da7e10bc4e99a06a441f91e1722baa971b41ab936d29db36e650accede5f`
Parameter-source supplement tree SHA-256: `841440f329539fbf204f284678911393ef14c05887b3ce69aee0997835f566ed`

両tree SHA-256は、各directoryについてファイルを相対path順に並べ、
`relative_path + NUL + file_sha256 + LF`を連結したUTF-8 bytesのSHA-256である。
