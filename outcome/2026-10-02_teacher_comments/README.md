# 先生コメントを反映した9月発表資料（2026-10-02）

編集元は先生の11件のコメント入り `september_progress_20260928_v4_ur.pptx`。元ファイルを上書きせず、本文10枚を訂正し、根拠を示す補足3枚を追加しました。元36枚の順序・番号と、先生のコメントを保持しています。

- [修正版PowerPoint（39枚）](september_progress_20261002_v5_teacher_revised.pptx)
- [PDF（39枚）](september_progress_20261002_v5_teacher_revised.pdf)
- [11コメントへの回答・残件](teacher_response.md)
- [発表者ノート](speaker_notes.md)：原ノートを保持し、回答と出典を追記。
- [Claudeの内容レビュー・採否](claude_review.md)：最終稿はテキストレビュー。図の実表示確認はCodexが担当。
- [検証記録](verification.json)、[追加集計とCSV](evidence/analysis.json)
- [資料制作手引き](../PPT-maker.md)

## 主な内容訂正

分類の出典はSolcastの履歴推定で、降水強度[mm/h]を15分×0.25hで積算して降水量[mm]にします。雨を先に判定し、そのほかの日の昼間積算GHI/晴天時GHI比で晴れ・くもりに分けます。3月3日の低温降水は雪の観測ではなく降水形態未判定です。分類のみ除外し、週次計算には含めています。

夏の雨20日の事後集計では10〜14時の日射比≥0.7が6日、そのうち15時以降の昼間降水≥1mmが2日。「夕立が多い」とは断定しません。補足37に7月10日の例を示します。これは公式の夕立分類ではなく、探索集計です。

3月6日・11月14日の受電ピークではPV供給0、BESS下限1,200kWh、8/10台が翌朝目標90%へ同時充電。SOCと次の営業便発車を原CSVに照合しました（補足39）。系統が供給した理由と、04:15へ集中することが不可避・最適かという問題を分けています。

本文のFAILED/BLOCKED/SHAなどの管理情報はノート・回答文書に保持し、本文は結果と解釈の前提へ変更。診断・条件付き評価と正式研究採用未承認は明示しています。

## 未実施の事項

設置角・方位を反映した傾斜面日射へのPV換算と、新入力版での週次再評価は未実施です（補足38）。夜間充電を他の時刻へ移した対照計算も未実施。今回は内容訂正と既存データからの追加集計です。最適化、ODPT/Solcast取得、worker更新、メール/Slack送信は行っていません。元計算の固定SHAは `f524eca2552a4386bd033a15bbe046c14dc09281` のままです。

既存12週のCSV・会計・物理レポートは [前版evidence](../2026-09-28_september_presentation/evidence/manifest.json) を参照します。今回の保管済み検証レポート確認は、native求解ZIP全体の再検算を実施したという意味ではありません。追加集計CSVは本フォルダのevidenceに収録。図の描画誤差だけを埋め込みExcelへ揃え、Excelや原会計は変更していません（最大差2×10⁻¹³）。

## AIなしで同じ資料を再生成する

Windows、PowerPoint、現端末のバンドルNode/Python、元PPTXと固定evidenceが必要です。新しい出力先を指定します。元PPTXのSHAが異なる場合は停止するため、教員の追加編集を古い版で消しません。Claudeを呼ばず、最適化・API取得・追加監視は実行しません。

```powershell
powershell -NoProfile -File C:\master-course\outcome\2026-10-02_teacher_comments\REBUILD.ps1 -Destination C:\master-course\outcome\teacher_comments_rebuilt
```

実行手順は分析→元デッキの限定訂正→ネイティブ補足生成→PowerPointで結合→既存Excelとキャッシュ照合→最終検証→PDF/全ページPNGです。別の新規出力先で実行し、39枚の再生成・ネイティブ描画を確認しました。自動構造検査だけでは表示を保証しないので、再生成後も図・軸・文字を確認してください。

再生成用コードと固定コメント一覧は [reproduction](reproduction/) に同梱。途中ファイル・失敗ビルドは `C:/master-course/output/teacher_revision_20261002/` に隔離しており、完成物には含めていません。
