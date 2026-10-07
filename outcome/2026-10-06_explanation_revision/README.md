# 13・14・16ページの説明改訂（2026-10-06）

開く資料は [PowerPoint](research_progress_20261006_explained_v2.pptx) または [PDF](research_progress_20261006_explained_v2.pdf) です。10/5の最新資料を基に、指定された3ページと発表ノートを改稿しました。44枚の構成（本文18枚・非表示補足26枚）を維持しています。

- [なぜそうなるか・根拠・仮説・次の確認](explanation_and_hypotheses.md)
- [発表ノートと想定質問](speaker_notes.md)
- [Claudeとの共同検討で採用・修正した内容](claude_collaboration.md)

13ページは、最高受電kWと200 kW超過の積算kWhを分け、週間費用差を説明します。14ページは、この記録時刻で系統が供給源になった理由と、充電集中を生む可能性のある費用式を分けます。16ページは、昼間・雨優先・晴天時との比の各ルールに理由を添えます。原計算、閾値、入力、研究採用判定は変更していません。

原本は [10/5版](../2026-10-05_teacher_ready/README.md) を保持しています。図50点・埋め込みExcel50点・コメント7部品は原本と一致し、先生の11コメントを削除・解決済み化していません。原計算は固定f524eca2の診断・条件付き週次評価で、統合最適性や教員の研究承認を得た結果には変更していません。

## AIなしの再生成

このPCのWindows・同梱Node/Python・PowerPoint環境を使用します。10/5版PPTXが同じリポジトリ内に必要です。既存の出力を上書きしない新しいBuildRoot・OutputRootを指定してください。

```powershell
powershell -NoProfile -File C:/master-course/outcome/2026-10-06_explanation_revision/REBUILD.ps1 -BuildRoot C:/master-course/output/explanation_rebuild_check -OutputRoot C:/master-course/output/explanation_rebuild_check_delivery
```

同梱の確定した文言・ノートから再生成するため、Claude・Solcast・ODPT・最適化を起動しません。原計算の巨大な全成果物一式はこの小さな改稿パッケージへ複製していません。原数値は [保存原本](../2026-09-28_september_presentation/evidence/) を参照してください。構造検査・数値照合・表示比較の詳細は `output/explanation_revision_20261006/` に保存しています。
