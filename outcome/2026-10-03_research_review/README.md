# 2026-10-03：研究の意味・先生への回答と、既存12週の追加分析

- [研究の問い、結果の読み方、先生への回答、次の少数確認](RESEARCH_MEANING_AND_TEACHER_RESPONSE.md)
- [Claudeとの3回の検討と提案の採否](claude_discussion.md)
- [4月・5月を含む全12週の追加集計](monthly_mechanism_metrics.csv)
- [4月・5月の差額と固定計画の費用分解](april_may_comparison.json)
- [日別のPV・買電・BESS収支](daily_mechanism_metrics.csv)
- [00〜06時の固定買電量に対する算術確認](night_energy_relaxation.csv)
- [5/12〜13の需給・BESS図 PNG](may_time_mismatch.png) / [SVG](may_time_mismatch.svg)
- [原本・集計の検証結果](analysis_verification.json) / [文献・出典](source_manifest.json)
- [文書・数値・表示の確認記録](validation.json) / [この成果一式のhash](bundle_manifest.json)

原本は `../2026-09-28_september_presentation/evidence`。計算固定版は `f524eca2552a4386bd033a15bbe046c14dc09281`。原本を上書きせず、保存済み102ファイルのhash、12週の保存済み物理判定、供給収支、BESS集約収支、費目合計と超過費式を確認した。正式研究採用判定・旧失敗・復旧履歴は変更していない。今回、原solver ZIP全体を新たに検算したものではない。

00〜06時の分析は、観測された買電量をその時間内で固定する簡略な電力量確認。実際の帰庫〜出庫窓、代替計画の可行性、週次最適性を証明するものではない。夜間買電比の分母は、翌朝の末尾区間も含む保存済み全範囲の買電量。

## AIなしで再集計する

PowerShellから、Python標準ライブラリだけで実行できる。API・ライセンス・ソルバーは不要。

```powershell
python -X utf8 C:\master-course\outcome\2026-10-03_research_review\analyze_existing_weeks.py
```

スクリプトは原manifestのSHA256 `52f6b6288ecf9295bad622a4f71de16b2e1cac0094934326e382cecd4de6dd87` を固定し、変化した原本を黙って取り込まない。

## 図を再生成する

使用したMatplotlibは、この作業専用の `C:\master-course\output\research_meaning_20261003\plot_packages` に配置した。最適化のPython環境・依存定義は変更していない。配置済みライブラリがあればネットワーク不要。

```powershell
& 'C:\Users\RTDS_admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -c "import sys,runpy; sys.path.insert(0,r'C:\master-course\output\research_meaning_20261003\plot_packages'); runpy.run_path(r'C:\master-course\outcome\2026-10-03_research_review\build_mechanism_figure.py',run_name='__main__')"
```

他のPCでは、Matplotlibと日本語フォントを用意して `build_mechanism_figure.py` を実行する。使用版はMatplotlib 3.11.2、フォントはWindowsのMeiryo。図の対象は5/12〜13の192連続15分区間で、入力CSVのhashを固定している。横軸は日付を各日の中央へ置き、日境界を薄い破線で表示した。PNGを目視確認済み。

今回の成果は追加分析・研究説明であり、新規最適化、PPTXの変更、controller/workerの更新、外部送信、Git同期は行っていない。
