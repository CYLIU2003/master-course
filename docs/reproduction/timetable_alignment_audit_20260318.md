# Timetable Alignment Audit Report (2026-03-18)

## 1. 目的

本資料は、以下3指標を実測値で提示し、第三者が同じ手順で再検証できるようにするための監査レポートです。

- timetable_rows 件数
- unserved_trip_ids 件数（= unserved_trip_count）
- 採用便の departure/arrival 一致率

## 2. 監査対象データ

- Scenario ID: `bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f`
- Prepared Input: `outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-7822b5b6dd60630d.json`
- Optimization Result (WEEKDAY): `outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/WEEKDAY/optimization_result.json`
- Optimization Result (SAT, 比較用): `outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/SAT/optimization_result.json`

## 3. 算出ロジック

監査スクリプト: `scripts/audit_timetable_alignment.py`

### 3.1 定義

- `timetable_rows_count`: prepared input の `timetable_row_count`
- `served_trip_count`: optimization result の `solver_result.assignment` に現れるユニーク trip_id 件数
- `unserved_trip_count`: まず `summary.trip_count_unserved` を使用し、無い場合は `solver_result.unserved_tasks` 長さを使用
- `departure_arrival_match_rate`:

$$
\text{departure\_arrival\_match\_rate}
= \frac{\text{departure\_arrival\_match\_count}}{\text{departure\_arrival\_checked\_count}}
$$

ここで `checked_count` は、served trip が prepared と dispatch_report の両方で解決可能な件数。

### 3.2 妥当性ガード

- `checked_coverage_rate = checked_count / served_trip_count`
- `day_tag_match`（trip_id中の `Weekday` / `Saturday` / `Holiday` / `Sunday` の最頻タグ一致）

`day_tag_match=false` の場合、prepared input と optimization result のサービス日種別が不一致であり、
一致率は品質指標として解釈しない。

## 4. 実測結果

| Case | timetable_rows_count | served_trip_count | unserved_trip_count | match_count | checked_count | match_rate | checked_coverage_rate | day_tag_match |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| WEEKDAY | 1010 | 1010 | 0 | 1010 | 1010 | 100.0% | 100.0% | true |
| SAT (比較用) | 1010 | 355 | 0 | 0 | 0 | 0.0% | 0.0% | false |

## 5. 結論（第三者向け）

- 品質評価に有効なのは `day_tag_match=true` のケースのみ。
- WEEKDAYケースでは、
  - `timetable_rows_count=1010`
  - `unserved_trip_count=0`
  - `departure_arrival_match_rate=100.0%`
  を実測で確認した。
- SATケースは prepared input が Weekday であるため、監査は「不整合検知」として機能し、
  指標の誤用を防止できることを確認した。

## 6. 再現手順

### 6.1 WEEKDAY監査

```powershell
python scripts/audit_timetable_alignment.py `
  --scenario-id bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f `
  --prepared-input-path outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-7822b5b6dd60630d.json `
  --optimization-result-path outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/WEEKDAY/optimization_result.json `
  --out-dir outputs/audit/bbe1e1bd
```

### 6.2 SAT比較（不整合検知の確認）

```powershell
python scripts/audit_timetable_alignment.py `
  --scenario-id bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f `
  --prepared-input-path outputs/prepared_inputs/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/prepared-7822b5b6dd60630d.json `
  --optimization-result-path outputs/tokyu/2026-03-14/optimization/bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f/meguro/SAT/optimization_result.json `
  --out-dir outputs/audit/bbe1e1bd_sat
```

## 7. 成果物

- `outputs/audit/bbe1e1bd/timetable_alignment_audit.json`
- `outputs/audit/bbe1e1bd/timetable_alignment_audit.csv`
- `outputs/audit/bbe1e1bd/timetable_alignment_audit.md`
- `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.json`
- `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.csv`
- `outputs/audit/bbe1e1bd_sat/timetable_alignment_audit.md`
