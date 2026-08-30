# RAIN候補範囲感度計画

## interface調査結果

public `RunOptimizationBody` には以下が存在する。

| 意味 | request field |
| --- | --- |
| 候補上限 | `stage1_stage2_candidate_limit` |
| 構成半径 | `stage1_composition_search_radius` |
| frontier ON/OFF | `stage1_bev_frontier_enabled` |
| frontier最小/最大 | `stage1_bev_frontier_min_count` / `stage1_bev_frontier_max_count` |
| frontier 1 target上限 | `stage1_bev_frontier_target_time_limit_seconds` |
| seed | `random_seed` |
| Stage 1上限 | `stage1_time_limit_seconds` |

formal `research_run=true` かつ `phase3_two_stage` では、サーバ側policyが候補22、radius 4、frontier ONを最低線として強制する。frontier maxはPrepared active BEV数で上限化される。要求値と実効値を必ず別保存する。

## profile

| field | BASE | EXPANDED_1 | EXPANDED_2 |
| --- | ---: | ---: | ---: |
| candidate limit | 22 | 32 | 44 |
| composition radius | 4 | 6 | 8 |
| frontier enabled | true | true | true |
| frontier min/max | 15/35 | 10/35 | 5/35 |
| frontier target limit | 120 s | 240 s | 480 s |
| Stage 1 limit | 435 s | 900 s | 1500 s |
| Stage 2 per candidate cap | 30 s | 45 s | 60 s |
| total day-ahead request cap | 1200 s | 1800 s | 2700 s |
| seed / threads | 42 / 1 | 42 / 1 | 42 / 1 |
| 保守的solver累積上限（Rolling含む） | 1815 s | 3060 s | 4860 s |
| 予想wall（上限設定用） | 45 min | 70 min | 100 min |
| 最大artifact予約 | 300 MB | 300 MB | 300 MB |

frontier minを下げるのは、現行15～35台より少ないBEV利用構成を含めるためである。上限35はPrepared active BEV数に一致する。profile差以外のrequest fieldとFresh Prepared input hashを固定する。

## exact request JSON差分

各profileは正本RAIN requestへ次のoverlayだけを適用する。完全な共通requestと実行手順は `07_exact_commands.md` に置く。

```json
{
  "BASE": {"time_limit_seconds":1200,"stage1_time_limit_seconds":435,"stage2_time_limit_seconds":30,"stage1_stage2_candidate_limit":22,"stage1_composition_search_radius":4,"stage1_bev_frontier_enabled":true,"stage1_bev_frontier_min_count":15,"stage1_bev_frontier_max_count":35,"stage1_bev_frontier_target_time_limit_seconds":120},
  "EXPANDED_1": {"time_limit_seconds":1800,"stage1_time_limit_seconds":900,"stage2_time_limit_seconds":45,"stage1_stage2_candidate_limit":32,"stage1_composition_search_radius":6,"stage1_bev_frontier_enabled":true,"stage1_bev_frontier_min_count":10,"stage1_bev_frontier_max_count":35,"stage1_bev_frontier_target_time_limit_seconds":240},
  "EXPANDED_2": {"time_limit_seconds":2700,"stage1_time_limit_seconds":1500,"stage2_time_limit_seconds":60,"stage1_stage2_candidate_limit":44,"stage1_composition_search_radius":8,"stage1_bev_frontier_enabled":true,"stage1_bev_frontier_min_count":5,"stage1_bev_frontier_max_count":35,"stage1_bev_frontier_target_time_limit_seconds":480}
}
```

## 判定規則

安定:

- 3 profileのwinner physical assignment hashが同一、または
- winnerが変わっても、BASEからの費用改善率が指導教員の事前閾値以下で、使用BEV/ICEとBEV/ICE便数に関する中心解釈が不変。

不安定:

- 上記以外。負の結果として保存し、追加profileを後付けしない。

## 実行可能性blocker

public APIは設定可能だが、Fresh Prepare、RAIN-only、profile overlay、requested/effective control照合、artifact hashを一つの既存CLIで行うrunnerがない。直接HTTPを手作業実行すると保存漏れの危険がある。`scripts/run_weather_dispatch_diagnosis.py` の既存Fresh Prepare/isolated workerを再利用し、6項目を引数化する小さな非core adapterが必要である。新しい監査器は作らない。
