# 近傍文献の調査記録

調査日：2026-10-05 JST。対象期間：2022年から同日まで。電気バスの運行・充電、営業所PV/BESS、複数日・季節比較、混成車両、日本の電力利用評価を対象にした重点調査。

一般Web検索を入口に、出版社、著者所属機関のリポジトリ、arXiv、J-STAGEの原典へ移動した。IEEE/Scopus/Web of Science等の購読DB全件を検索した系統的レビューではない。以下は保存できた主要検索語であり、全ヒット数・重複排除数を用いるPRISMAフローは作成していない。

## 検索語

1. `electric bus photovoltaic storage charging scheduling 2022 2023 rolling horizon Liu`
2. `electric bus weekly multi-day charging scheduling 2024 2025 2026 photovoltaic`
3. `電気バス 太陽光 充電 運行計画 季節 電気学会 2023 2024 2025`
4. `electric bus operating costs photovoltaic subsidies total cost ownership 2023 2024 2025`
5. `"Sustainable charging schedule" "28" rolling horizon`
6. `"Integrated charging scheduling" "2509.05940" authors`
7. `"Electric bus charging scheduling problem considering" "103572"`
8. `site.jstage.jst.go.jp 電気バス 太陽光 充電 計画 2023 2024 2025`
9. `"Impacts of photovoltaic and energy storage system adoption on public transport" 2023`
10. `"Dynamic charging optimization for electric buses" 2026`
11. `"Coordinated Optimization of Cross-Line" 1791`
12. `site.jstage.jst.go.jp "電気バス" "太陽光" 2022 2023 2024 2025 2026`
13. `"Dynamic charging optimization for electric buses under photovoltaic-storage-grid energy supply mode"`
14. `"Optimal charging scheduling of an electric bus fleet with photovoltaic-storage-charging stations"`
15. `"Charging electric buses with solar power under varying environmental temperatures and sunlight conditions"`
16. `"Coordinated Optimization of Cross-Line Electric Bus Scheduling" authors`

参考文献・被引用検索から2023年のPV設備影響論文、2026年の温度・日射比較論文を追跡した。2026-09-24公開のGTFS4EVも採用した。近接13編を比較表へ収録し、アクセスできた本文の該当節6編、出版社公開抜粋5編、抄録2編を分けた。本文の該当節を読むことと、全式・全実験を再検証することは異なる。

## 採否と確認深度

- 採用：バス運行/充電とPV・定置電池・受電・期間/季節の少なくとも一つが直接対応する論文。日本の充電・電力・費用評価2編は周辺分野として採用。
- 一般乗用EV、オンボードPVだけの研究、センサネットワーク、概説・ニュースは主比較から除外。
- ResearchGate、Scribd、転載サイト、一般まとめは原典探索の入口に留め、未取得本文の根拠にはしない。
- MDPIの2026年cross-line論文は検索で発見したが本文取得に失敗したため、今回の13編の比較判定には入れない。見つけた文献をすべて検討済みとはしない。
- 出版社の403、著者PDFのWebツールtimeout、arXiv版付きPDF取得失敗があった。公式著者PDFをローカル読取、arXiv HTML/リンク先PDFの方法節を読取することで補完。日本語PDFは取得できたが文字抽出の一部が未対応なので、今回の判定は抄録に限定した。
- 書誌は一次ページで確認し、補完できた4件をCrossref登録情報と照合。Crossref照会6件のうち2件は取得失敗で、出版社/所属機関の情報を使用した。

## 日付・版の訂正

- L06は2025年投稿、2026-02-15更新のv2を採用。v1の題目とv2の題目は異なる。
- L07は2025年投稿、2026-07-27更新のv2を採用。本文でもNath、Balduaの順と等貢献表記を確認した。
- L09はDOI文字列に2025を含むが、掲載巻は2026-03-15のApplied Energy 407。
- L12は巻表示2024、受理2025、J-STAGE公開2025-07-01。公開年だけで書誌年を上書きしない。
- arXiv掲載4編は本調査で査読済み掲載先を確認していない。査読論文と同じ証拠区分にしない。

原典URL、読んだ節、未確認点は[literature_matrix.json](literature_matrix.json)に保存。著者配布PDFの取得hash・書誌照会記録・Claudeの応答JSONは非配布の`output/literature_novelty_20261005/`に保存した。PDF全文をこの報告へ転載しない。
