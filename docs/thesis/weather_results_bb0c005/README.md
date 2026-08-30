# 修論用SUNNY／RAIN結果パッケージ

実験SHA `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` のGit管理済み証拠だけから生成した。数値の手入力は行わず、期待値は生成前のfail-closed assertionにのみ使用する。設備定格値は、各fresh runの`scenario_input_snapshot.json`と`run_input_manifest.json`をexact byte copyしたparameter-source supplementから読む。

## 検証と再生成

```powershell
python -m pip install -r requirements-reporting-lock.txt
$fontPath = Join-Path $env:TEMP "NotoSansJP-VF-Sans2.004.ttf"
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/Variable/TTF/Subset/NotoSansJP-VF.ttf" `
  -OutFile $fontPath
$expectedFontHash = "f4b373b226668ee33a6e54b02823dcd2d1209f17159f777421ae8c2275160369"
$actualFontHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $fontPath).Hash.ToLowerInvariant()
if ($actualFontHash -ne $expectedFontHash) { throw "Noto Sans JP SHA-256 mismatch: $actualFontHash" }
$env:THESIS_JAPANESE_FONT_PATH = $fontPath
python scripts/verify_thesis_weather_result_package.py `
  --evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005 `
  --parameter-evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources `
  --committed-dir docs/thesis/weather_results_bb0c005
# 意図的に更新する場合のみ、未変更の正本検証に通った後で再生成する。
python scripts/build_thesis_weather_result_package.py `
  --evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005 `
  --parameter-evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources `
  --output-dir docs/thesis/weather_results_bb0c005
python scripts/verify_thesis_weather_result_package.py `
  --evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005 `
  --parameter-evidence-dir docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources `
  --committed-dir docs/thesis/weather_results_bb0c005
```

## 成果物

- `experiment_parameters.csv/.md`: 実験条件と正本位置
- `scenario_results.csv/.md`: 配車、費用、エネルギー、gap、計算時間
- `cost_breakdown.csv/.md`: 費用項目とRAIN－SUNNY差
- `energy_balance.csv/.md`: PV・BESS・系統収支
- `thesis_summary_table.csv/.md`: 修論本文へ転用できる主要指標の簡潔な比較表
- `claim_boundary.md`: 使用可能な主張と限定事項
- `results_section_ja.md`: 修論結果章へ転用できる日本語本文
- `01`～`05`のPNG（300 dpi）・SVG図
- `package_manifest.json`: 入出力SHA-256と図表map

## 図表設計

白背景、フォント`Noto Sans JP`、明示単位、ゼロ始点を使用した。SUNNYは青、RAINとの構成差は橙、PVは金、BESSは青、その他は中立色で表現し、色だけに依存しない直接値・積み上げ位置・凡例を併用した。

06_daily_energy_flow_timeseriesは作成していない。正本bundleには96スロットの実行済みPV・BESS・系統フロー列がなく、rolling_chain_summary.jsonには24個の残余ホライズン集計とGit管理外stateファイルへの参照だけがあるため、差分推定を行わなかった。

## 設備パラメータの補助証拠

`docs/evidence/weather_dispatch_rerun_bb0c005_parameter_sources/`にはSUNNY/RAINのfresh runから取得した完全な`scenario_input_snapshot.json`と、それをSHA-256で封印する`run_input_manifest.json`を保存した。Prepared ID・Prepared source SHA・実験SHAを公開済みsummaryと照合し、両ケースで充電器ID・営業所・基数・定格出力・同時充電ポート数・双方向設定、受電／契約上限、PV定格容量、BESS定格容量・出力・SOC範囲・効率が一致することをfail-closedで検証する。

## 主張範囲

結果は、評価した有限候補集合から選択されたPhase 3二段階実行可能解である。費用は本モデルの費用定義に基づく24時間Rolling実行日評価額、gapはStage 1の近似目的関数に対するcertified MIP gapとして扱う。2ケースの差を一般化しない。

Source bundle tree SHA-256: `c706da7e10bc4e99a06a441f91e1722baa971b41ab936d29db36e650accede5f`
Parameter-source supplement tree SHA-256: `3a0c955cc9b1fc6a3cba6a3a84fff48bbc505f6180969ca7377e68601df8eae8`

両tree SHA-256は、各directoryについて相対POSIX pathをUnicode casefoldしたkey順に並べ、
`relative_path + NUL + file_sha256 + LF`を連結したUTF-8 bytesのSHA-256である。
