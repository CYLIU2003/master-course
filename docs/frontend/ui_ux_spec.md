# React UI/UX specification

## 1. Design intent

The application is a research operations console, not a decorative dashboard. It should make scope, model conditions, validity and evidence easier to inspect than raw JSON while retaining a path to the raw artifacts.

Use the repository tokens in `docs/frontend/DESIGN.md`: navy structure, teal primary action/ready state, restrained borders, small radii, Yu Gothic UI, explicit units and no color-only meaning.

## 2. Responsive target

- Primary target: desktop, 1280 px and wider.
- Supported minimum: 1024 x 720 without horizontal page scrolling; dense tables may scroll within their panel.
- Mobile optimization is out of scope.
- Tauri window minimum should match the supported browser viewport.

## 3. Core component patterns

### Validity banner

Always present on result pages.

| Condition | Heading | KPI behavior |
|---|---|---|
| Valid and eligible | `検証済み実行可能解` or backend-supported optimal label | Show values |
| Feasible, exactness unproven | `実行可能解（最適性未証明）` | Show values with gap/evidence |
| Time limit with incumbent | `時間制限で終了・実行可能解あり` | Show values, never “最適” |
| Infeasible | `実行可能解なし` | KPI values unavailable/null; diagnostics remain |
| Validation failed | `結果検証に失敗` | KPI values unavailable/null |
| Unknown schema/status | `未対応の結果状態` | No optimistic interpretation |

### Metric card

- Label includes unit.
- Value renders `—` for null/unavailable, not `0`.
- Secondary line states source/provenance or comparison basis.
- No client-side recomputation beyond formatting and explicitly labeled deltas.

### Research parameter field

- Human label first, storage key as optional secondary text.
- Unit is always visible.
- Hard constraints include a short explanation of mathematical effect.
- Invalid values are reported beside the field and in a page-level summary.
- Defaulted values visually distinguish “saved value” from “backend default”.

### Data table

- Sticky header and first identity column.
- Column chooser with a research-safe default set.
- Server sorting/filtering when the endpoint supports it; otherwise clearly local to loaded rows.
- Virtualization for more than 200 rendered rows.
- Copyable IDs and export through backend artifacts.

## 4. Page specifications

### Scenario list

Default columns: name, operator, dataset, mode, active state, updated time, latest run status. Primary action is “新規シナリオ”. Row click opens read-only overview; activation and delete are overflow actions.

Empty state differentiates “no scenarios” from “BFF/dataset unavailable”.

### Quick Setup

Use an ordered form:

1. Operator/dataset identity (read-only unless scenario creation supports change).
2. Depot and route scope.
3. Day type and service date(s).
4. Trip inclusion and route-swap policies.
5. Fleet and charging summary.
6. Objective, solver and experiment conditions.
7. Advanced weather/PV/BESS and compatibility controls.

The sticky footer shows `変更あり`, last saved time, “破棄”, and “保存してPrepare”. Saving and preparing are distinct backend mutations even when offered as a sequential convenience action.

### Run workspace

Never provide one ambiguous “実行” button. The selected operation is explicit: optimization, prepared simulation or reoptimization. Show prerequisites and the exact prepared ID before enabling submission.

Job progress is factual: raw percentage if present, otherwise an indeterminate bar with backend stage text. Do not synthesize progress from elapsed time.

### Dispatch results

Default table columns: vehicle ID/type, duty, route family/variant, direction, trip ID, origin/destination, departure/arrival, deadhead/turnaround/slack, distance and assignment status. Connection diagnostics use backend reason codes and preserve the feasibility condition.

The diagram view is secondary to the table and must have a textual equivalent.

### Energy results

Charts share one time axis and support depot filtering:

- Grid import, charging demand and contract limit in kW.
- PV generation/use/curtailment and BESS charge/discharge in kW.
- Energy totals in a separate kWh summary.
- EV/BESS SOC on labeled axes with explicit basis.

Stacking is used only for flows that mathematically add. Sign convention is stated beside the legend. Missing series are omitted with a warning, not filled with zeros.

### Cost and CO2 results

Show the backend total, reconciled component sum, basis and eligibility. A reconciliation residual must be visible when provided. Demand charge displays rate basis and horizon conversion metadata. CO2 and money are separate groups.

### Comparison

The selection panel shows scenario/run identity before results. A compatibility panel checks dataset, service scope, fleet availability, timestep, objective flags, solver conditions, weather inputs and result eligibility. Differences are not ranked until required controls match or the user explicitly switches to a diagnostic, non-causal comparison.

## 5. Loading, empty and error states

Every query surface implements:

- skeleton/loading state without shifting the shell;
- empty state with the exact missing prerequisite;
- retryable network error;
- stable contract/error code rendering;
- stale-data marker when cached data remains visible;
- unsupported-schema fallback with raw evidence link.

Avoid full-page spinners after the shell loads. Large result tabs fetch independently.

## 6. Accessibility and keyboard behavior

- WCAG 2.1 AA contrast target.
- Visible focus ring on every interactive control.
- Logical heading structure and landmarks.
- Form errors associated through `aria-describedby`.
- Status changes announced through a polite live region; failures use assertive announcement.
- Charts have textual summaries and downloadable source data.
- Weather, vehicle type and validity use label/icon/pattern in addition to color.
- Keyboard shortcuts are optional and never replace visible actions.

## 7. Japanese terminology baseline

| Internal term | UI label |
|---|---|
| scenario | シナリオ |
| prepare/prepared input | 実行準備 / 準備済み入力 |
| optimization | 最適化計算 |
| feasible | 実行可能 |
| infeasible | 実行可能解なし |
| unserved trips | 未担当便 |
| incumbent | 暫定実行可能解 |
| mip gap | 最適性ギャップ |
| artifact | 成果物 |
| provenance | 入力・生成元 |

Labels may include the English technical term in secondary text where it prevents ambiguity.

## 8. Frontend state ownership

| State | Owner |
|---|---|
| Server resources/results/jobs | TanStack Query |
| URL-selected scenario/tab/filter | Router/search params |
| Unsaved form values | React Hook Form |
| Runtime validation | Zod + backend error mapping |
| Short-lived dialog/toast state | Local component state |
| Persisted current job IDs | Small versioned browser-storage adapter |

Do not duplicate server payloads into a general-purpose global store. This avoids stale synchronization and accidental mutation of common assets.

