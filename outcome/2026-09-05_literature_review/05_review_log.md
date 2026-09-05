# 調査・検証記録

## 実施範囲

- 日付：2026-09-05（Asia/Tokyo）。HEAD：`c0b82ae30e874f65fabcfec94599982023bc3ca6`。
- 開始時は前の進捗説明作業による変更あり。既存変更・8月PPT・凍結authoring/evidenceを保持し、今回は新しい日付付き文献フォルダと案内・開発記録を追加。
- 対象：現在の`先行文献/`直下の23PDF。全23件をテキスト抽出し表題等を確認。14件を重点再読、9件を一次整理。本文の全数学的導出を検証したわけではない。
- 再読の選定理由：既存主要9文献に、統合計算比較No06、双方向不確実性No62、out-of-sample評価No27、車両/資源と実測のNo47、待ち時間評価No44を加えた。残り9件を棄却せず、精読残件として台帳へ残した。
- 原文PDFの再配布・変更は行わない。抽出全文と4枚の確認用ページ画像はGit管理対象外の`output/literature_review_20260905/`に置いた。成果物には出典と短い要約・評価を記載。

## 検索方法と確認の深さ

一般検索で網羅性を主張せず、手元論文のDOI/正確な題名から出版社情報を照合。ScienceDirect、Taylor & Francis、MDPI、Higher Education Press/Chalmersの原著情報を参照した。

代表的な検索語：

- `10.1007/s42524-024-3102-2`
- `10.1016/j.apenergy.2025.125714`
- `Robust electric bus charging in photovoltaic-energy storage systems with dual uncertainties`
- `Optimization of charging and discharging schedules` + `2506689`
- `A Robust Optimization Approach for E-Bus Charging` + `Kang`
- `Joint optimal vehicle and recharging scheduling for mixed bus fleets under limited chargers`
- `Mixed bus fleet scheduling under range and refueling constraints`
- `Integrated optimization of charging infrastructure, electric bus scheduling and energy systems`

追加のCui2023・Li2019・Najafi2025は出版社の検索結果・要旨等の範囲。Cui/Najafiの直接ページ取得は403となり、取得済みの一次情報から確認できない細部は未評価にした。未取得の本文、検索で出た関連論文、全文未読の参考文献を読んだことにはしていない。

## 原本との照合

- 23PDFのパス・ページ数・SHA-256を [source_inventory.json](source_inventory.json) に保存。
- No06 Table 5（PDF p.14）をレンダリングし、50便と418便の費用・時間・未求解の位置を目視確認。
- 国内マクロ論文のpp.1–2をレンダリングし、式(1)のminと本文の最大化という記述不一致を確認。
- 国内MPC論文p.2をレンダリングし、2日計画/日次更新と終端条件差を確認。図の棒の幅から独自の数値を推定していない。
- 旧9件CSVに対してNo16、No61、Huの著者名等を照合。旧CSVを上書きせず訂正文書と新版草稿を作成。

## 実行していないこと

新規solver、Prepare、Rolling、モデル変更、許容誤差緩和、署名代行、GitHub Actions/AIレビュー/課金機能、commit/pushはゼロ。今回の文献再読から実験結果や独立査読の承認は生じない。

## ローカル検証と再確認方法

23原本のハッシュ一致、台帳14重点/9一次、文書リンクとdiffを確認。READMEの既存ナビゲーションテストも使用する。

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_readme_navigation.py
git diff --check
Get-FileHash -Algorithm SHA256 outcome\2026-09-05_literature_review\01_critical_review.md
```

原本の完全照合：

```powershell
$reviewSources = Get-Content -Raw -Encoding UTF8 outcome\2026-09-05_literature_review\source_inventory.json | ConvertFrom-Json
foreach ($source in $reviewSources) {
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.file).Hash.ToLowerInvariant()
    if ($actualHash -ne $source.sha256) { throw "Source hash mismatch: $($source.file)" }
}
```

成果物の全ファイルSHA-256は [artifact_inventory.json](artifact_inventory.json)。自己参照を避け、この一覧自体は一覧に含めない。

## 次回の研究上の残件

1. Cui2023・Li2019・Najafi2025の正規に利用できる全文を取得し、本研究との決定変数・制約・比較の差を照合する。
2. 既存の小規模統合参照に必要な人間の署名を得る。今回の採用案を承認とみなさない。
3. 単純充電baselineの出典・同時刻処理・目標SOC・BESS方策を固定する。
4. 電費/PV誤差の実測根拠と評価日分割を決める。
5. 本人が「配車固定と配車最適化」「他解との差と認証gap」「実行可能性と未知条件への頑健性」を自分の言葉で説明できるか確認する。
