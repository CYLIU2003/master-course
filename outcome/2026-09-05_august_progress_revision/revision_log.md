# 旧8月版からの変更一覧

2026-09-05 / `c0b82ae3` / documentation and editable presentation only.

元資料：`outcome/修士研究_2026年8月_進捗報告_先行研究図表パラメータ追加版.pptx`。18枚すべてを読み、全ページを描画した上で改訂しました。元の数値結果を別SHAの実験結果へ置換していません。

| 旧ページ | 改訂ページ | 問題・不足と対応 |
| --- | --- | --- |
| 1 表紙 | 1 | 原題・著者・8月日付を保持し、9月5日の改訂であることを区別 |
| 2 背景 | 2 | 図を保持。「一緒に考える」と「統合大域最適」を同一視しないノートを追加 |
| 3 文献の図表一覧 | 3、8、22 | 図の形式の模倣だけでは貢献を示せない。RQと文献の前提・採用方針に変更 |
| 4 実験対象 | 4 | 元の図を保持。有効60台はこのPrepare由来、実日付の晴雨二日比較ではないと明示 |
| 5 手法 | 5、19 | Stage 2後の候補選択を明示。Stage 1エネルギー緩和、固定配車Rolling、費用基準を区別 |
| 6 パラメータ① | 6 | SOC終端・効率を補完。設定に存在することと実測妥当性を分離。設備実在の未確認を開示 |
| 7 パラメータ② | 7、20 | frontier 15–35台の設定と生成候補14–35台の結果を分離。時間上限と実測を区別 |
| 8 前回との差 | 8、9 | 異なるSHAの改善履歴から手法効果を断定しない。文献比較と現在の証拠に組み替え |
| 9 月内の作業 | 9 | 作業量ではなく、実行可能性・精度・優位性の到達点を表示。履歴自体は原版に保存 |
| 10 配車 | 10 | 便数・台数のnative graph化。営業距離比とtrip ID照合による108便の変更を追加 |
| 11 候補費用 | 11 | native scatter化。同じ台数でなく配車hashで対応。前日recourse診断と24h正式検算を区別 |
| 12 費用 | 12 | 車両使用費を分けたnative graph。費用差の比較相手と正本を明示 |
| 13 電源フロー | 13 | 元の図を保持。「時間が合わず」という未識別原因を断定しない。営業所単位の電源フローと明示 |
| 14 主結果表 | 14、20 | 日合計を補足に整理し、本編に実行96区間のPV・充電・抑制曲線を追加 |
| 15 Rolling概念図 | 9、14、15、21 | 成立回数だけでなく実際の時間別値・BESS・抑制時の状態を確認 |
| 16 限界 | 16 | 次点差566.62円は前日評価と明記。限界と、それを解く比較実験を対応づけ |
| 17 次の作業 | 17 | E0、既存安定性P0、E1 baseline、E2ストレスを分離。未署名・未実験・実行前検証を明記 |
| 18 文献 | 18、22 | 本編の結論を新設。文献は確認範囲付き補足へ。元の文献情報を実証済み出典と見なさない |
| 追加 | 19–22 | 数式抜粋、solver指標、BESS時系列、主要文献の書誌を補足として追加 |

## 判断の根拠として修正した主張

- 高PV/低PVの費用差は「PV入力の違う2条件の選択計画の差」。単純充電や先行研究への手法改善額ではない。
- RAINの前日選択評価は698,296.465284円、実行日会計は698,598.628643円。次点差566.622470円は前者に対する比較。
- Stage 1 raw gapは双方9.521%、certified gapは高PV9.521%・低PV1.656%。最終実行日総費用のgapではない。
- 22候補は同じ物理配車hashで両PVを評価した診断集合。全候補が24/24 Rolling・研究承認まで通ったという意味ではない。
- PV抑制と無充電の同時発生75.06%は「原因の寄与率」ではない。設備不足・帰庫・終端条件・別解の切り分けは未完了。
- パラメータ表で参照文献の体裁を借りても、1.316 kWh/kmや6,000 kWhがその論文の実証値になるわけではない。

## 今回追加確認した近接文献

追加検索は2026-09-05、検索語は `Cui 2023 103335 mixed fleet electric conventional bus scheduling charging`、`Zhou An Schmöcker 2025 2506689 electric bus`、`Hu 2025 125714 electric bus charging photovoltaic` 等。これは系統的レビューの完了ではありません。

- **Cui, S., Gao, K., Yu, B., Ma, Z., Najafi, A. (2023)**. *Joint optimal vehicle and recharging scheduling for mixed bus fleets under limited chargers*. Transportation Research Part E, 180, 103335. 固定ダイヤの混成配車と充電器制約を扱うことを[所属機関の要旨](https://research.chalmers.se/en/publication/538305)で確認。出版社直接取得は403。著者公開[全文リンク](https://research.chalmers.se/publication/538305/file/538305_Fulltext.pdf)を発見したが、本改訂では全文精読済みとしない。
- **Soltanpour, A., Ghamami, M., Nicknam, M., Ganji, M., Tian, W. (2023)**. *Charging Infrastructure and Schedule Planning for a Public Transit Network with a Mixed Fleet of Electric and Diesel Buses*. Transportation Research Record, 2677(2). 混成車両・分散電源・気象と設備/運用計画を扱うことを[出版社要旨](https://journals.sagepub.com/doi/10.1177/03611981221112405)で確認。オンライン初出は2022年、巻号年は2023年。詳細性能の評価は未実施。
- Zhouの正式会場名・巻号は *Transportmetrica B: Transport Dynamics*, 13(1), 2506689。[著者所属大学](https://repository.kulib.kyoto-u.ac.jp/handle/2433/300766)と出版社検索結果で照合。
- Manzolliの巻は *Applied Energy*, **381**, 125137。[著者の研究者記録](https://www.cienciavitae.pt/portal/en/7015-8903-18F6)で照合。原稿作成途中の巻誤記を最終版では修正。

Hu・Zhou・Manzolli・国内資料の本文に基づく評価は [先行研究再レビュー](../2026-09-05_literature_review/01_critical_review.md) のページ別根拠を再利用したものです。各論文の実装を再現したわけではありません。

## 検証と残件

原版と凍結正本のハッシュ一致、既存strict loader、native chartの全数値とCSVの照合、96区間のkWh→kW換算、97点のBESS境界を検証。最終テスト14件PASS。編集途中の表配置警告は余白を広げて解消し、最終警告0。PowerPoint埋込数値の精度上限に合わせ、図表の表示用データのみ6桁へ丸めた。値の捏造・正本の変更なし。

未実施：native Officeでの操作確認、人間の独立レビュー、正式実験の新規実行、baseline実装、最適化モデルの改良。GitHubへの書込み・Actions・Copilot実行・課金機能の有効化なし。
