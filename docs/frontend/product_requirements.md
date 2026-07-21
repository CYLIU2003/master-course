# Product requirements

## 1. Product statement

Build an evidence-first research operations console for configuring, executing and auditing EV-bus dispatch and charging experiments. The first target is browser-hosted React + TypeScript over the existing FastAPI BFF. Desktop packaging with Tauri is a later deployment layer and must not change the research contract.

## 2. Users and primary jobs

| User | Primary job | Required evidence |
|---|---|---|
| Research operator | Configure and execute a reproducible scenario | Input scope, prepared ID, seed, solver settings, status and artifacts |
| Research reviewer | Decide whether a result is valid and comparable | Feasibility, coverage, exactness, fallback/repair flags, units and provenance |
| Developer/operator | Diagnose failed preparation or execution | Stable error code, stage, message, request identity and artifact path |
| Supervisor | Compare scenarios without inspecting raw JSON | Fixed-condition differences, KPI eligibility and explicit limitations |

## 3. Goals and measurable outcomes

| ID | Goal | Measure |
|---|---|---|
| G-01 | Preserve research meaning during UI migration | Backend and React values match exactly before presentation rounding |
| G-02 | Preserve current operation | Tkinter launch and critical smoke flow continue to pass throughout migration |
| G-03 | Make validity visible before KPI interpretation | Invalid/infeasible results cannot present zero-valued KPI cards as valid outcomes |
| G-04 | Reduce execution mistakes | Current scope, stale Prepare state and solver settings remain visible at submission |
| G-05 | Make large outputs inspectable | Summary-first loading; large lists are paginated or virtualized |
| G-06 | Support later desktop packaging | React contains no browser-only assumption that prevents a Tauri shell |

## 4. Scope

### Phase A: React + FastAPI

- Scenario list, overview, create, duplicate, activate and guarded delete.
- Quick Setup and explicit Prepare.
- Prepared-input review with scope counts, warnings, IDs and provenance.
- Optimization, prepared simulation and reoptimization submission.
- Job polling and terminal-state handling.
- Result summary, dispatch schedule, energy balance, cost, audit and artifact views.
- Scenario comparison with eligibility checks.
- Vehicle, template, depot, charger, PV/BESS, cost, CO2, SOC/fuel and solver editors after the read/run workflows stabilize.

### Phase B: React + FastAPI + Tauri

- Start/stop the FastAPI/Python runtime as a sidecar.
- Discover a dynamically selected localhost port and verify readiness.
- Resolve writable data/output directories without relying on the working directory.
- Surface sidecar crash and version mismatch as recoverable application states.
- Preserve the same HTTP contract used by browser-hosted React.

### Explicitly out of scope for the first MVP

- Reimplementing optimization formulas or feasibility rules in TypeScript.
- Changing solver behavior, cost formulas, SOC semantics or timetable contracts.
- Removing or simplifying Tkinter.
- Restoring every historical React screen before results and execution are stable.
- Public-data explorer parity unless separately prioritized.
- Multi-user authentication, remote tenancy and cloud job orchestration.

## 5. Functional requirements

### Application and scenario management

| ID | Requirement | Phase |
|---|---|---|
| FR-APP-01 | Show BFF health, dataset readiness, application version and active scenario | MVP |
| FR-SCN-01 | List scenarios with name, operator, dataset, mode, update time and active state | MVP |
| FR-SCN-02 | Open a scenario without automatically activating or mutating it | MVP |
| FR-SCN-03 | Create and duplicate scenarios while preserving `operator_id` | Edit |
| FR-SCN-04 | Activate a scenario as an explicit mutation with visible confirmation | Edit |
| FR-SCN-05 | Delete only after showing the exact scenario and consequences | Edit |

### Prepare and execution

| ID | Requirement | Phase |
|---|---|---|
| FR-RUN-01 | Save Quick Setup through the BFF and show unsaved/stale state | Run |
| FR-RUN-02 | Prepare and display `preparedInputId`, readiness, scope counts, warnings and effective solver profile | Run |
| FR-RUN-03 | Mark Prepare stale when any preparation dependency changes | Run |
| FR-RUN-04 | Reject run submission locally when no current prepared input exists; still rely on backend validation | Run |
| FR-RUN-05 | Submit optimization, prepared simulation or reoptimization only once per deliberate user action | Run |
| FR-RUN-06 | Poll jobs until `completed` or `failed`, surviving page navigation and reload | Run |
| FR-RUN-07 | On HTTP 409 stale Prepare, show both submitted/current IDs and require or explicitly offer re-Prepare | Run |
| FR-RUN-08 | Never claim cancellation until a backend cancellation contract exists | Run |

### Results and comparison

| ID | Requirement | Phase |
|---|---|---|
| FR-RES-01 | Separate execution status, solution validity and research-KPI eligibility | MVP |
| FR-RES-02 | Display assigned/unserved trips, used vehicles and coverage from the backend | MVP |
| FR-RES-03 | Display total cost and component costs in JPY with provenance and invalid-result gating | MVP |
| FR-RES-04 | Display grid/PV/BESS flows using kW for power and kWh for energy | MVP |
| FR-RES-05 | Display SOC with its basis (`ratio`, `%`, or `kWh`) and never mix bases in one unlabeled series | MVP |
| FR-RES-06 | Display solver mode requested/effective, status, runtime, gap, exactness support and fallback/repair flags | MVP |
| FR-RES-07 | Link artifacts using backend-provided manifest/path metadata; never guess filenames | MVP |
| FR-CMP-01 | Compare only compatible scenarios by default and list every control mismatch | MVP |
| FR-CMP-02 | Show absolute and relative differences while preserving null/missing values | MVP |
| FR-CMP-03 | Prevent invalid/ineligible runs from being presented as a valid cost-performance comparison | MVP |

### Input editing

| ID | Requirement | Phase |
|---|---|---|
| FR-EDT-01 | Group forms into scope, depot/energy assets, fleet/SOC, costs/CO2, objective and solver sections | Edit |
| FR-EDT-02 | Define one Zod schema and one form state owner per section | Edit |
| FR-EDT-03 | Show units in labels and mathematical effects for hard constraints | Edit |
| FR-EDT-04 | Preserve unknown legacy fields on round trip unless the backend explicitly migrates them | Edit |
| FR-EDT-05 | Never replace `timetable_rows` as a side effect of unrelated form saves | Edit |

## 6. Non-functional requirements

| ID | Requirement | Acceptance target |
|---|---|---|
| NFR-COR-01 | Contract correctness | Generated types originate from typed FastAPI response models, not `Dict[str, Any]` guesses |
| NFR-REP-01 | Reproducibility | Result view exposes scenario/prepared IDs, seed, dataset/version, solver settings and artifact provenance |
| NFR-PERF-01 | Initial responsiveness | Shell and scenario summaries become interactive without loading graph/timetable/result detail payloads |
| NFR-PERF-02 | Large data | Tables use server pagination where available and virtualization otherwise |
| NFR-REL-01 | Job resilience | Reload restores known job IDs and resumes polling; restart-orphaned jobs show the backend failure reason |
| NFR-A11Y-01 | Keyboard/accessibility | All actions keyboard reachable, visible focus, semantic labels, no color-only state |
| NFR-I18N-01 | Language | Japanese is the initial UI language; technical identifiers remain copyable |
| NFR-SEC-01 | Local API boundary | Browser build accepts configured BFF origin; Tauri only connects to its verified localhost sidecar by default |
| NFR-OBS-01 | Diagnostics | Error UI includes stable code, stage, scenario/job ID and copyable detail without exposing secrets |
| NFR-COMP-01 | Compatibility | No React merge may require deletion or behavioral weakening of Tkinter paths |

## 7. Research-validity requirements

- Coverage, feasibility and KPI eligibility are independent fields in the UI.
- `0`, `null`, missing and not-applicable have different renderings.
- Cost cards use backend accounting outputs; presentation rounding occurs only after values are received.
- Demand charge labels state the returned basis, such as JPY/kW/month or JPY for the modeled horizon.
- A time-limit incumbent is not labeled optimal.
- A solver mode is not labeled exact unless actual returned metadata supports that claim.
- Weather comparison must show service dates, PV/weather provenance and control mismatches.
- Every result page includes an audit/evidence entry point.

## 8. Assumptions and limitations

- The current implementation is a local, single-user application.
- The current FastAPI OpenAPI contains request models but almost all success responses are generic objects. Typed response DTO work is therefore a prerequisite for reliable client generation.
- Backend cancellation is not currently available.
- Historical documents refer to an earlier `frontend/` tree, but that directory is absent from the current worktree. Those documents are evidence of past intent, not executable current behavior.

