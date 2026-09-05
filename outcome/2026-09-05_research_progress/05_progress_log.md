# 進捗メモ 2026-09-05

## 今日の研究上の問い

高PV／低PVで選ばれた配車は、便数以外の運行量と、充電の時間配分でどう違うか。

## 実施済み

- 正本結果とPrepared・物理検算・Rollingの入力を読み、分析用の便別表528行と15分別表192行を作成。
- 営業距離ベースBEV比率72.78%／29.73%、営業時間比率72.43%／29.23%を算出。
- ICEからBEVへ変わる108便を特定。渋22の78便、渋23の30便。
- PV抑制の75.06%が未充電枠と同時発生すると確認。満杯BESS・全ポート充電という説明の根拠は確認できなかった。
- 充電電源別の按分行を合算し、使用ポートを二重計上しない集計を追加。
- 共通車両費64万円と、残る評価額20,983.78円／58,598.63円を区別。
- 本人向け理解ガイド、発表資料、パラメータ根拠表、次の比較設計を作成。

## 今回進めた研究の範囲

`DESCRIPTIVE_REANALYSIS_COMPLETE`。2026-08-29の凍結実験SHA `bb0c0050883a91dd86a9e8813ae88d4b6d8c361d` の追加説明。資料作成時HEADは `c0b82ae30e874f65fabcfec94599982023bc3ca6`。現HEADで新たな最適化を実行した意味ではない。

最適化・Prepare・Rolling・HTTPの新規実行は0。GitHub Actions、AI自動レビュー、アカウント設定変更、pushは行っていない。

## 次に答える問い

- 優先：小規模統合参照との評価額差。既存承認書は未署名のため、その判断材料を説明する。
- 単純方式比較：既存M0〜M3とは違うため、baselineの固定配車と先着順充電規則を定義する。
- 残件：PV抑制の因果分解、充電待ち時間、最小必要充電器数、実車パラメータの独立した文献・実績裏付け。

## 再集計のコマンド

PowerShell、リポジトリルート `C:\master-course` で実行。既存出力保護のため、新しい空の出力先を指定する。

```powershell
.\.venv\Scripts\python.exe tools/thesis_authoring/build_progress_explanation.py --help
.\.venv\Scripts\python.exe tools/thesis_authoring/build_progress_explanation.py --output-dir outcome/2026-09-05_research_progress/reproduction_01
.\.venv\Scripts\python.exe -m pytest -q tests/test_progress_explanation.py tests/thesis_authoring/test_authoring_evidence.py tests/test_readme_navigation.py
```

ローカルの2実行フォルダと凍結Preparedファイル、Windows Meiryoフォントを必要とする。存在しない場合は失敗し、代替入力を作らない。出力ファイル一覧・SHA-256は `analysis/manifest.json`。

## 検証記録

新規集計テスト6件と既存の関連テストを合わせ12件成功。充電電源按分の二重計上、同じポートへの複数車両、微小電力、距離比の分母、便の重複・欠落を確認した。凍結根拠108ファイルと生成物のSHA-256を記録。追加の物理・最適化実験ではない。

発表PPTXは9枚、編集可能な表4枚・グラフ2枚と発表者ノートを含む。出力パッケージ・文字配置・グラフ数値の埋め込みを検証し、9枚の描画を確認した。PowerPointアプリ内での表示確認は未実施。

PPT作成ソースは `tools/thesis_authoring/build_progress_presentation.mjs`。Node runtimeは現PCのCodex bundled runtimeを指定している。グラフ値は表現用に割合を小数6桁、円を小数2桁へ丸め、元JSON/CSVの値は維持する。既存PPTを上書きしないため、再作成時はソース中の出力ファイル名を新しい名前にする。

## 本人のメモ欄

- 自分の言葉で説明できたこと：
- まだ曖昧な言葉・式：
- 指導教員に確認する判断：
- 次回、最初に一緒に確認する図：

この欄は本人の回答用。GPTが本人の理解度や承認を代筆しない。
