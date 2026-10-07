# 先生コメントを踏まえた研究進捗資料（2026-10-05）

発表の順序を、**研究の問い → 計算条件 → 連続7日間の成立 → 月別の電力・費用 → 具体的な時系列 → 結論と次の確認**に組み直しました。新しい最適化計算は行わず、固定f524eca2の保存12週と2025年Solcast履歴の値を使っています。

## 使うファイル

- **research_progress_20261005_teacher_ready.pptx**：編集可能な本文18枚＋非表示の補足26枚。図表50個はPowerPointのネイティブチャート。先生のコメント11件と元の46個のExcelデータを保持。
- **research_progress_20261005_teacher_ready.pdf**：本文18枚。通常の発表・確認用。補足はPPTXで見ます。
- [speaker_notes.md](speaker_notes.md)：本文の話し方、質問への短い答え、補足ページの案内。
- [teacher_response.md](teacher_response.md)：埋め込み11コメントの原文、何をどう直したか、参照ページ、残る検証。
- [RESEARCH_EXPLANATION.md](RESEARCH_EXPLANATION.md)：研究の意味と、言えること・まだ言えないこと。
- [claude_review.md](claude_review.md)：実際のClaude Opus 5.5/highとの2回のレビューと採否。原文はreview/へ保存。
- data/：週次費用、4月・5月比較、5/12〜13時系列、天候カーブ・分類のCSV。
- [verification.json](verification.json)、[source_manifest.json](source_manifest.json)、[bundle_manifest.json](bundle_manifest.json)：確認範囲と原本・成果物のSHA256。
- [REBUILD.ps1](REBUILD.ps1)、reproduction/：AI・API・ソルバーを使わない再生成入口。

## 今回の大きな変更

1. 本文を18枚に絞り、内部管理用の名前・hash・詳細月別図をノートと補足へ移しました。シナリオ名「仮・正式用」はユーザー指定として維持。
2. 4月と5月のPV総量差約1%に対し、費用差57.6万円を費目へ分解。仮定単価500円/kWhのもとで約91%が超過モデル費の差です。
3. 5/12〜13のPV・充電・買電・BESSを同じ時刻で表示。翌未明の買電と同日の日中の抑制を分けて説明し、代替計画で回避できないとまでは主張しません。
4. BESSの初期在庫と終端残量を、費用・季節比較より先に示しました。取り崩しを当該週のPV効果や永続的な節約としません。
5. 雨分類・GHI比・P10/P90・除外日の意味を説明。夏の雨20日中、明るい昼と15時以降の降水の両条件を満たすのは2日で、「夕立が多い」とは説明しません。

横軸の日付は各日の中央、日境界は薄い破線です。数値が表せるページでは見出しに伝える内容を置き、定義ページは主題を示します。

## 発表時に維持する条件

12週は2025年の各月1週という**独立した代表週**で、年間連続運用や月平均ではありません。2026年ダイヤ×2025年気象の仮想運用評価で、予測は2024年1年のclimatologyです。天候標準カーブは2025年履歴の記述統計で、今回の予測学習には使っていません。

「成立」は入力した車両・設備条件に対する保存結果の確認です。正式研究採用のBLOCKED/DIAGNOSTIC、図表復旧元のFAILEDは保持。週間統合最適性、実設備の運用保証、PV単独の因果効果、設備投資や補助金額の算定は未確認です。燃料費は距離由来の消費評価で、給油の支払額ではありません。

**残る技術確認は2点**：同じ配車・SOC等の条件で充電時間を変えた比較、設置角・方位を確認した設置面日射の別入力版評価。これらは資料編集だけで解決した扱いにしません。

表紙は[最新の題目候補](../2026-10-05_literature_novelty/TITLE_PROPOSALS.md)に合わせた案です。10/8三者MTGでの承認は未取得。[近接13編と貢献の検討](../2026-10-05_literature_novelty/README.md)も併読してください。

## AIなしで再生成する

この資料フォルダだけを移しても原本は揃いません。C:/master-course内の元PPTX、evidence、tools/thesis_authoring/export_presentation.ps1と、配置済みのPython/Node/Artifact Tool・Presentations検査ツール、Microsoft PowerPointが必要です。既存の環境で動作確認済みです。

PowerShellから：

```powershell
cd C:\master-course
powershell.exe -NoProfile -ExecutionPolicy Bypass -File outcome/2026-10-05_teacher_ready/REBUILD.ps1
```

新しいoutput/presentation_rebuild_日時/へPPTX・PDF・検証結果・全44枚の画像を生成します。原本SHA、固定CSV102ファイル、表と費用の一致を確認し、違えば停止。既存PPTX/PDF/作業先は上書きしません。再生成したスライド画像は、人が全ページを見てから使います。見た目の検査は自動の構造検査と別です。

原本：../2026-10-02_teacher_comments/september_progress_20261002_v5_teacher_revised.pptx。データ：../2026-09-28_september_presentation/evidence/。先生編集原本と旧資料は保持。今回の途中版はoutput/presentation_finish_20261005/intermediate/へ移して、ここには提出候補1版を置いています。

この配布資料のhash・文書参照・11コメント回答・PDF本文の検査だけなら、`reproduction/verify_delivery.py`を配置済みPythonで実行します。AI・ソルバーは使いません。図表を変更した後は数値検査に加え、全ページを再表示して確認します。
