# core_new 最新コード・実行結果の厳格レビュー（2026-07-17）

## Code Review Summary

**Reviewer:** Codex / MIT CSAIL-style strict review
**Date:** 2026-07-17
**Code:** `origin/core_new` at `1910d24`から作成した`codex/core-new-review-20260717`

### 総評

15分grid-onlyのclean baselineで全264便の物理可行性を示せている点、Stage 2 IISと独立validationを成果物化している点は良い。一方、2026-07-17 UI runでは不可行結果を0円・未担当0便として見せるP0が残っており、枝削減後もexactフラグがtrueになるP1もあった。本変更で両方を修正したが、15分PV/BESS晴雨比較と不確実性評価はまだ未完了である。

### 重要度別件数

- `[BLOCKER]` P0: 1件（修正済み）
- `[MUST]` P1: 2件（exactness表示は修正済み、正式15分晴雨rerunは未実施）
- `[SHOULD]` P2: 2件（24時間rolling、PV予測誤差/seed感度）
- `[NIT]` P3: 0件

### 特に優れていた点

- dispatch hard condition `arrival + turnaround + deadhead <= next departure`を緩和せず、IIS、SOC precheck、candidate pathを分離保存している。
- 15分controlled runはclean commit、fallbackなし、postsolve repairなし、全264便、Stage 2 optimal、独立違反0である。
- 晴雨監査はPV、BESS、grid、燃料、費用を再集計し、残差を`1e-6 kWh`以下で検査している。

## 1. Verified call chain

これはcurrent call pathから確認した事実である。

1. `POST /scenarios/{scenario_id}/run-optimization`
2. `bff/routers/optimization.py::_run_optimization`
3. canonical problem build → `OptimizationEngine.solve`
4. canonical graph export → `_persist_rich_run_outputs`
5. `src.reporting.rebuild_reporting_artifacts_in_place`
6. `summary.json`、root/graph `kpi_summary.json`、validation artifacts

Stage 2不可行時のIIS生成自体は、現行`solver_adapter.py`ですでに実装されている。`stage2_infeasible.ilp`、IIS制約CSV、constraint summary、車両別energy shortage、出発SOC precheckが保存される。

## 2. Root cause

### P0: 不可行zero-ledgerを正常KPIとして再構築

2026-07-17の2 runは、canonicalで`infeasible`、担当0便、未担当264便、objective非有限だった。しかしreporting finalizerは空ledgerを整合した0円台帳として集計し、旧summary/KPIへ未担当0便、総費用0円、`objective_is_actual_cost=true`、`solver_objective_matches_accounting_total=true`を書いた。

根因は、ledger内部の加算整合性と「解が研究評価可能か」を別々に判定していなかったことにある。ゼロ同士が一致しても、不可行解のKPIが有効になるわけではない。

### P1: 枝削減後のexactness過大表示

対象UI runは候補arc 678,600本から113,712本へ削減し、564,888本（83.25%）を除去した。それでもsolver outcomeの複数経路が`supports_exact_milp=true`を返していた。Gurobiが最適と判定できるのは構築済みモデルであり、削減前の候補網に対するglobal optimumではない。

### IISで確認した中間不可行の原因

`research_phase3_sunny_energy_proxy_1500s_20260716`のIISは59制約で、車両`e077…`に集中した。

- `charge_availability`: 19
- `charge_power_vehicle`: 19
- `soc_transition`: 19
- `soc_initial`: 1
- `soc_lower`: 1

同車両は06:15以降、home depotで充電できないままSOCを消費し、19:02、19:54、21:36、22:24の出発で8.3、8.3、37.1、46.2 kWh不足した。Stage 1集約proxyが認めたエネルギー余力と、Stage 2の実時刻・所在地充電可能性が一致しなかったことが直接原因であり、単なるtime limitではない。

## 3. Minimal patch

- canonical resultが`validated_feasible=false`なら、reader-facing cost/energy/CO₂/SOC KPIを`null`にする。
- canonicalの担当/未担当便数、`result_status`、`failure_stage`、`research_kpi_eligible=false`を全summaryへ同期する。
- `site_power_balance.csv`等で`null`を0へ再変換しない。
- backfill時の`results.xlsx`へstatus sheetを追加し、評価セルを空欄化する。既存experiment reportの先頭にはINVALID警告を付ける。
- raw solver artifactsとledgerは変更せず、診断可能性を保持する。
- `pruned_arc_count > 0`なら`supports_exact_milp=false`にする。
- 不可行264便ケース、fallback reporting、exactness semanticsの回帰テストを追加する。

## 4. Risks / side effects

- 古いconsumerが数値0を必須とすると、`null`対応が必要になる。ただし0を有効値として残す方が研究上危険である。
- raw ledgerは診断用に数値を保持するため、consumerは必ず`research_kpi_eligible`と`result_status`を先に確認する必要がある。
- exactnessフラグの変更により、過去に「exact」と表示されたpruned runの主張は撤回対象になる。数理的可行性そのものは変更しない。
- dispatch feasibility、`timetable_rows`、`operator_id`、SOC式、費用式は今回変更していない。

## 5. Validation steps

1. 不可行fixtureでcanonical未担当264便がsummary/KPIにも264便として出る。
2. 費用、PV→bus、grid import、CO₂は0ではなく`null`になる。
3. `solution_validity_gate`がvalidationへERRORを追加する。
4. raw cost/energy ledgerは再計算前と一致する。
5. `pruned_arc_count > 0`でexact=false、0でexact=trueになる。
6. reporting、canonical export、solution validity、MILP関連回帰を実行する。

実施結果: `python -m pytest -q --ignore=test_multiday_phase1.py` は `730 passed`。除外した`test_multiday_phase1.py`はlocalhost BFFを前提とする手動E2Eである。変更対象Pythonファイルの`py_compile`と`git diff --check`も通過した。既存不可行runの複製にreporting gateを適用し、JSON/CSVに加えて`results.xlsx`でも`INFEASIBLE`、未担当264便、費用空欄となることを確認した。

## 6. Remaining uncertainty

- 最新コード`1910d24`からのclean 15分PV/BESS晴雨runはまだない。
- 15分grid-only clean baselineは全264便可行だがStage 1 gap 45.69%で、費用最適性はない。
- 60分晴雨PV/BESS runはStage 2 optimal・全264便だがdirtyで、gap 13.11/12.94%。機序確認には使えるが修論の正式比較には使わない。
- successor上限8/16/32/無制限の目的値・schedule感度は未実施である。
- hourly rollingは05:00→06:00のみ検証済みで、24時間連鎖は未完了である。
- PV予測誤差、複数seed、複数日、終端価値の感度は未実施である。

## Cost model audit

### Verified formulas / logic path

- slot energyはkWh、`p_avg = grid_import_kWh / timestep_h`でkWへ変換する。
- demand chargeはslot kWの最大値にhorizon換算単価を掛け、kWh合計には掛けない。
- 月額単価は`(planning_horizon_hours / 24) / 30`で評価horizonへ換算する。
- 現行晴雨は単一営業所で、報告需要料金は`peak_grid_import_kw × 40 JPY/kW/day`と一致する。

### Unit consistency issues

現行単一営業所・1日runでは確認した範囲に単位不整合はない。複数営業所では、営業所別契約を想定するなら各営業所peak料金の和、共通受電点なら合算時系列peakのどちらかを契約仕様として固定する必要がある。

### Modeling issues

Stage 1のenergy proxyは充電時刻、充電器競合、受電上限、需要料金を含まない。したがってStage 1 objectiveを実現電気料金として報告しない。

## Literature-centered visualization contract

| 評価軸 | 文献根拠 | 現状 | 判定 |
|---|---|---|---|
| 充電窓・競合 | No42 p.9: 固定15分充電、2基、競合を明示 | 15分grid-onlyのみ正式、晴雨は60分 | Partial |
| 需要料金 | No55 p.8: 15–60分平均電力のbilling-cycle peak | 現行単一営業所pathはslot平均kWの最大 | Implemented in current scope |
| 運行・充電・設備統合 | No55、No16 | Phase 3は二段階、Stage 1は集約proxy | Approximate |
| PV/負荷不確実性 | No16 pp.13–14: 5/10/15/20%誤差のMonte Carlo | 未実施 | Missing |
| solver品質 | incumbent/bound/gap/runtime | Stage別に保存 | Implemented |

再現コマンド:

```powershell
.\.venv\Scripts\python.exe scripts\audit_core_new_review_20260717.py
```

出力は`output/core_new_review_20260717`に保存される。4図はKPI矛盾、証拠層別gap、IIS根因、暫定晴雨エネルギー/費用を示す。
