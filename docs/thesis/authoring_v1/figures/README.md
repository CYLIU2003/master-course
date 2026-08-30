# 図の出典とcaption

- `candidate_cost_vs_used_bev`: 有限22候補における使用BEV台数と評価額。因果的な限界費用を表さない。
- `candidate_cost_rank_comparison`: SUNNY/RAINの候補費用順位。Spearman相関は候補集合内に限る。
- `sunny_rain_candidate_cost_scatter`: 同一物理配車を2条件へ適用した評価額。
- `candidate_composition_distribution`: 候補の使用BEV/ICE構成。
- `selected_and_second_best_comparison`: 各条件の選択候補と次点。RAINの差が小さい点に注意する。
- `sunny_executed_power_flows` / `rain_executed_power_flows`: hash検証済み96スロット実行prefixの電力フロー。
- `sunny_rain_grid_import_comparison`: 15分ごとの系統受電比較。
- `sunny_rain_bess_soc_comparison`: BESS終端SOC時系列。両条件とも日末3,000 kWhへ戻る。
- `sunny_rain_pv_use_curtailment`: PV利用と抑制の比較。低抑制率だけを優位性と解釈しない。

PNGは本文挿入、SVGは編集・高解像度組版用である。元データは `../tables` と `../evidence_supplements` にある。
