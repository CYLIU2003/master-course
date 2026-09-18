# 9月18日 進捗報告・占部先生のご指摘への回答

研究目的・前提・用語・計算手順から通して説明する[全体改訂版（24枚）](../2026-09-18_monthly_explanation/README.md)を追加しました。この20枚版と詳細集計は引き続き保存しています。

9月16日のSlack DMでいただいた、3月と11月の購入電力の違い、週間費用差の判断材料、資料の説明順序へのご指摘に対応した資料です。9月15日版を基に、同じ固定版12週の実行データを再集計しました。

## ファイル

- [説明資料 PowerPoint](monthly_progress_20260918_urabe_response_v2.pptx)：本文15枚・補足5枚。グラフ・表は編集可能です。
- [説明資料 PDF](monthly_progress_20260918_urabe_response_v2.pdf)：配布・閲覧用。
- [Slack返信案](slack_reply_draft.md)：未送信。先生への返信に使う文章です。
- [発表者ノート](speaker_notes.md)：各ページの説明と注意点。
- [分析の根拠](evidence_explanation.md)：定義、実数、解釈、残る課題。
- [再集計データ](analysis.json)：丸め前の値、3月・11月の672区間時系列、原本のSHA-256。
- [再集計スクリプト](analyze.py)：固定済みの原本を読み、整合性を検算してanalysis.jsonを生成します。

## 説明の中心

11月の系統購入は7日すべてに発生し、1 kW超の時間は合計50.75時間でした。ただし200 kWを超えた部分は11月13日夜〜14日朝に集中しています。購入電力量全体と、契約基準超過の電力量を分けて説明します。

3月と11月の週間費用差は23.99万円で、93.5%がモデル内の超過ペナルティの差です。手法の優位性を判断するには同じ週の基準運用との比較が必要であり、現在の異なる週の差を削減効果とは呼びません。

## 前回資料からの変更

- 前回P9右図の「最大15分平均受電電力」と週間平均電力を明確に区別。
- 15分の実行時系列、日別購入量、超過時間の拡大図、ピーク時の電源内訳を追加。
- 週間費用の差分表、同じ便数当たりの費用、超過単価だけを置き換える算術比較を追加。
- 本文を問い・定義・観測・費用・判断の順に再構成。

元の[9月15日版](../2026-09-15_monthly_progress/monthly_progress_20260915_presentation.pptx)は保存しています。最適化コード、凍結した実験出力、研究採用の判定は変更していません。今回、新たな最適化計算やメール・Slack送信は行っていません。

## 研究上の位置付け

DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。全12週の物理・会計検証は通過していますが、研究採用はBLOCKEDです。最適性、手法の優位性、年間・季節全体への一般化は未検証です。詳細は[分析の根拠](evidence_explanation.md)を参照してください。

## 再集計

リポジトリのPython環境で実行します。外部APIやAI呼び出し、ソルバー実行はありません。原本のworktreeが存在する環境が必要です。表示資料はanalysis.jsonの値を丸めて使用しています。

```powershell
& C:/master-course/.venv/Scripts/python.exe C:/master-course/outcome/2026-09-18_urabe_followup/analyze.py
```

原本は `docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.json` と、その `source_evidence` が指す固定版7c7c2334のファイル群です。各週の `executed_day_accounting.json` が週間費用の出典です。
