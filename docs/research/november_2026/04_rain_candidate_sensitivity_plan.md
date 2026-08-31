# RAIN候補集合×計算予算2×2計画

## 固定interface

profileは`config/research/november_2026/rain_candidate_profiles_v2.json`から読み、次のfieldだけを変更できる。

`time_limit_seconds`、`stage1_time_limit_seconds`、`stage2_time_limit_seconds`、`stage1_stage2_candidate_limit`、`stage1_composition_search_radius`、`stage1_bev_frontier_enabled`、`stage1_bev_frontier_min_count`、`stage1_bev_frontier_max_count`、`stage1_bev_frontier_target_time_limit_seconds`。

| profile | candidate/radius | frontier min-max | frontier target | Stage 1 | Stage 2 | total request |
|---|---:|---:|---:|---:|---:|---:|
| BASE | 22 / 4 | 15-35 | 120 s | 435 s | 30 s | 2115 s |
| RANGE_ONLY | 44 / 8 | 5-35 | 120 s | 435 s | 30 s | 2775 s |
| BUDGET_ONLY | 22 / 4 | 15-35 | 480 s | 1500 s | 30 s | 3180 s |
| FULL_EXPANDED | 44 / 8 | 5-35 | 480 s | 1500 s | 30 s | 3840 s |

totalは`Stage1 + candidate_limit * Stage2 + 24 * Stage2 + 300 s reserve`で結果を見る前に固定した。Stage 2を30秒から動かさない。

## runnerとFresh Prepare

`tools/november_2026/run_rain_candidate_sensitivity.py`は`--plan-only`、`--validate-inputs-only`、`--execute`を区別する。現在のGoalでは前2つだけが許可される。adapter freeze commitでFresh Prepareを1回行い、4 profileで同じPrepared IDを共有する計画である。public reuseが実行時に成立しなければ、各Fresh Prepareの非profile canonical hash完全一致を要求して停止する。

BASEも同じadapter SHAで再実行し、bb0c005の結果を新しいBASEに流用しない。requested requestとpost-run effective controlsは別artifactに保存する。profile外driftはfail-closed。

## 比較

`analyze_candidate_profile_results.py`は候補数、selectable数、physical assignment数、候補hash集合、BASE保持率、Jaccard、BASE winner有無、profile winner、union winner、selected-to-second margin、費用差、BEV/ICE台数・便数差、gap、termination、runtimeを出す。

閾値がnullなら`AWAITING_ADVISOR_THRESHOLD`で、stable/unstableを判定しない。旧BASE/EXPANDED_1/EXPANDED_2案は候補範囲と時間を同時に変える「複合search-profile感度」であり、今回の実行profileではない。
