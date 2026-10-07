# 2026年9月 進捗発表資料

対象は「仮・正式用」の渋21・22・23、2025年各月から事前選定した連続7日間×12週です。本文20枚、補足16枚。4季節は気象カーブの分類であり、最適化を4ケースに減らしたものではありません。

- [編集可能なPowerPoint](september_progress_20260928_v4.pptx)
- [閲覧用PDF](september_progress_20260928_v4.pdf)
- [発表者ノート](speaker_notes.md)（PPTX内にも収録）
- [先生の指摘への対応と説明](teacher_response.md)
- [用語と計測境界](terminology.md)
- [月別原値一覧CSV](evidence/weekly_summary.csv)
- [原本照合とレビューの記録](validation.md)

各週の `evidence/YYYY-MM-DD/` に、全60台の台帳、対象便の運行割当、充電、運行BEVのSOC、15分電力、日別費用、物理検証、最終実行会計を保存しています。未使用車はfleet.csvで識別します。CO₂図表係数の照合エラーは注意として保持し、費用は最終実行会計の値を使います。

`evidence/weather/` に12分類のカーブCSV、365日の日別分類CSV、原本のSHAを含むmanifestがあります。原本12か月・35,040区間から分類と全曲線を再計算して一致を確認しました。2025年の記述統計であり、予測学習ではありません。

## 根拠と主張の範囲

- 計算固定版：`f524eca2552a4386bd033a15bbe046c14dc09281`。
- 月別集計revision：`6729fc3bb239e8985c73f9ec537f6bd9d476794bc32391c1a68a996ff4d3a7fd`。
- 9/19原本：`../2026-09-19_urabe_terminology/monthly_progress_20260919_terms_v2.pptx`。SHA256 `51a42771ab406476893267f6c34ee9571f3bbf0b506248e4e5dfe392822b28fc`。
- 9/19版の説明構成・配色・フォントを継承した別名資料です。原本とユーザー保存PPTを変更していません。旧版数値・旧条件は現在の結果に混ぜていません。
- 原FAILEDの1・11・12月は、同じZIPの物理・会計・計画と、別のreporting recovery receiptを照合しました。最適化の再実行はありません。
- 物理可行性と会計の確認済み結果を用いた条件付き週次評価です。正式研究採用BLOCKEDを保存。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。統合週間最適性・対照手法への優越性・実設備運用・年間節約を証明していません。

図表は編集可能なネイティブ表・チャート＋埋込Excelです。15分電力は階段表示、日付は各日の中央、日境界は0時の薄い破線です。終端翌朝の短い区間も表示します。チャートは小数6桁の表示用丸め、CSVは原値を保持しています。

## AIなしでの再生成

リポジトリルート `C:\master-course` から実行します。既存ファイルを上書きしないため、毎回新しい出力先を指定してください。最適化・ODPT/Solcast取得・メール送信は呼びません。

### 保存済み証拠から図表だけ作り直す

Microsoft PowerPointと、今回確認したArtifact Toolランタイムが必要です。環境を移した場合は実在するランタイムのパスを指定します。コードは `tools/thesis_authoring/` にあります。

```powershell
$env:RUNTIME_DEPENDENCIES='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies'
$env:PRESENTATIONS_SKILL_DIR='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.923.10815/skills/presentations'
New-Item -ItemType Directory -Path outcome/september-regenerated
& "$env:RUNTIME_DEPENDENCIES/node/bin/node.exe" tools/thesis_authoring/build_september_final.mjs outcome/2026-09-28_september_presentation/evidence output/september-regenerated-build outcome/september-regenerated/progress.pptx
powershell -NoProfile -File tools/thesis_authoring/export_presentation.ps1 -Pptx outcome/september-regenerated/progress.pptx -Pdf outcome/september-regenerated/progress.pdf -Images output/september-regenerated-images
```

PowerPointは作成した資料だけ閉じ、利用者の他の資料を閉じません。日付配置と線の補間指定は `apply_calendar_axes.ps1`、PowerPointの浮動小数点書出しノイズの除去は `normalize_chart_cache.py` が行います。差が1e-7を超える数値変更は拒否します。再生成後は表示を確認してください。手編集は別名保存し、そのファイルを次の編集元にしてください。

### 原ZIPから再照合・CSV出力も行う

元の月別レポートが参照するZIP・Prepared・復旧receipt、気象原本がこのPCに必要です。巨大な原ZIPそのものは本資料フォルダへ複製していません。別PCへ検算一式を渡すときは、許可された範囲で原ZIPも別途渡してください。hashだけで第三者が再検算できるとは主張しません。

```powershell
& output/cluster-deployment/controller-venv/Scripts/python.exe -X utf8 tools/thesis_authoring/prepare_september_evidence.py --report output/executed_soc_20260926/monthly_report --output outcome/september-regenerated-evidence
& output/cluster-deployment/controller-venv/Scripts/python.exe -m pytest tests/test_september_presentation_evidence.py -q
```

証拠入力のmanifest不一致、未完了週、異なる計算SHA、欠便、物理・会計不一致は拒否します。解法のgap未達だけで既存の正しい会計を消す処理はありません。再生成コードはこの9月・12週の資料用であり、任意のシナリオの正式採用を自動承認する機能ではありません。
