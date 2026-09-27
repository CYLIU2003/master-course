# 9月進捗資料の途中更新（2026-09-27）

現行固定版 f524eca2552a4386bd033a15bbe046c14dc09281 の検算済み11週を反映しました。
1〜10月・12月を収録し、11月は未収録です。全12週完了の資料ではありません。

- `monthly_progress_11weeks_20260927_v2.pptx`：最新月別資料へ6枚の更新を先頭追加。元の24枚は履歴として非表示で保持。
- 同名PDF：今回の6枚だけ。会議での閲覧はこちらが明確です。
- `comparison.json`：元の実行会計・検証・回収先へ追跡する集計原値。
- `evidence.json`：固定SHA、集計revisionとcomparison hash。

費用表と電力量グラフは編集可能です。表は万円小数2桁、グラフはMWh小数6桁に表示用丸め。原値はcomparison.json。
各週は営業7日間＋最終翌朝まで。月平均や年間合計ではありません。設備投資費は未計上、燃料費は消費在庫評価を含みます。
研究採用・統合最適性の判定を変更していません。1月・12月の図表復旧は原FAILED記録を残しています。

## AIなしでの更新

PowerShellから、既存の原本集計が更新された後に次を実行します。新しいbuildと出力ファイル名を指定してください。
ソルバーは呼びません。時刻表の取得、入力更新、ジョブ投入も行いません。

```powershell
$env:RUNTIME_DEPENDENCIES='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies'
$env:PRESENTATIONS_SKILL_DIR='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.923.10815/skills/presentations'
& "$env:RUNTIME_DEPENDENCIES/node/bin/node.exe" tools/thesis_authoring/build_monthly_live_update.mjs output/executed_soc_20260926/monthly_report output/monthly_slides_next
& tools/thesis_authoring/merge_monthly_update.ps1 -Source outcome/2026-09-19_urabe_terminology/monthly_progress_20260919_terms_v2.pptx -Update output/monthly_slides_next/validated/update-slides.pptx -Output outcome/monthly_progress_next.pptx -PreviewDirectory output/monthly_slides_next/rendered
```

この補足更新ツールは渋21〜23・各週1704便・現行費目向けです。入力hash・検算済みラベル・有限値・費目合計を確認し、別条件の未対応入力は停止します。
PowerPointが必要です。原本を上書きせず、元のユーザー資料・既に開いているPowerPointを終了しません。
更新後は新しい6枚のPNGとPDFを確認してください。12週の最終版では、旧資料を非表示のまま足すだけでなく、天候標準カーブと説明を本文へ統合する作業が残ります。

## 検証

Artifact Toolによるネイティブ表・グラフ・埋め込みExcel検証を通過。PowerPointで6枚をレンダリングして全ページを確認しました。
PDFは6ページ、PPTXは30枚（旧24枚は非表示）。編集元のSHA不変を確認しました。
