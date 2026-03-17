# Core Branch Guide (For External Reviewers)

This document explains how to run and review the `core` branch as a standalone research package.

## 1. What This Repository Is

This repository is a timetable-driven EV bus dispatch and optimization research system.

- Frontend (operational): Tkinter apps
- Backend: FastAPI BFF
- Optimization engine: MILP / ALNS / Hybrid
- Data basis: normalized route and timetable artifacts for Tokyu Bus (`tokyu_core`)

The key policy is:

- Timetable first, dispatch second.
- No physically infeasible connection should appear in output.

## 2. What Is Included In `core`

This branch is intended for direct third-party review and reproducible experimentation.

Included:

- `tools/scenario_backup_tk.py`: Tk operational frontend (scenario setup, prepare, run, optimization)
- `tools/route_variant_labeler_tk.py`: route tagging frontend
- `bff/`: backend API for scenario/data/optimization orchestration
- `src/`: dispatch, optimization, pipeline, model and evaluation logic
- `data/seed/tokyu/`: seed data definitions
- `data/built/tokyu_core/`: normalized/built artifacts used for execution
- `config/`: optimization and runtime configs
- `constant/`: read-only constants/spec documents

Not intended as primary in this branch:

- legacy backend
- temporary debug scripts
- old result dumps

## 3. Environment Requirements

- OS: Windows recommended (verified)
- Python: 3.11+ (3.14 also used in this project)
- Optional solver: Gurobi (for MILP exact solves)

Required Python packages:

- install from `requirements.txt`

## 4. Quick Start (Reproducible Path)

### Step 1: Create and activate virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Verify required built artifacts

Required files under `data/built/tokyu_core/`:

- `manifest.json`
- `routes.parquet`
- `timetables.parquet`
- `stops.parquet`

(If your local setup requires additional generated files, follow Section 9.)

### Step 3: Start backend

```powershell
python -m uvicorn bff.main:app --host 127.0.0.1 --port 8000
```

### Step 4: Start Tk scenario app

In a new terminal:

```powershell
.\.venv\Scripts\Activate.ps1
python tools/scenario_backup_tk.py
```

### Step 5: Run a baseline optimization from Tk app

Typical flow in `scenario_backup_tk.py`:

1. Select/create scenario
2. Load and save quick setup (depot/route/day type/solver params)
3. Prepare simulation
4. Run optimization
5. Inspect output and logs

### Step 6: Optional route tagging workflow

In another terminal:

```powershell
.\.venv\Scripts\Activate.ps1
python tools/route_variant_labeler_tk.py
```

Use this app to edit route variant tags and direction metadata, then re-apply labels to scenario as needed.

## 5. Review Focus (For Research Supervision)

### 5.1 Dispatch feasibility logic

Please review whether the generated duties strictly satisfy:

- location continuity
- time continuity
- vehicle type compatibility

Relevant modules:

- `src/dispatch/graph_builder.py`
- `src/dispatch/pipeline.py`
- `src/dispatch/dispatcher.py`
- `src/dispatch/validator.py`

### 5.2 Objective function and cost terms

Please review objective integrity and interpretation consistency across modes:

- `total_cost`
- `co2`
- `balanced`

Relevant modules:

- `src/optimization/engine.py`
- `src/optimization/milp/*`
- `src/evaluator.py`
- `bff/mappers/scenario_to_problemdata.py`

### 5.3 MILP / ALNS / Hybrid design quality

Please review:

- model constraints validity
- infeasibility handling
- warm-start / fallback behavior
- repair and neighborhood quality in ALNS/hybrid flow

### 5.4 Data boundary and reproducibility

Please review:

- operator boundary invariants
- timetable linkage consistency
- seed/built artifact contract checks

Relevant modules:

- `bff/services/app_cache.py`
- `src/research_dataset_loader.py`
- `src/artifact_contract.py`

## 6. Practical Configuration Knobs

In Tk app quick setup, important knobs include:

- objective mode
- time limit
- MIP gap
- ALNS iterations
- allow partial service
- unserved penalty
- electricity/fuel/CO2 coefficients

These significantly affect result comparability in experiments.

## 7. Typical Questions and Where To Look

Q1. Why did CO2 mode produce lower apparent cost in some runs?

- Check whether objective weights set cost terms to 0 in CO2 mode.
- Inspect exporter/evaluator breakdown interpretation.

Q2. Why is optimization blocked before run?

- Check backend app state for built dataset readiness and missing artifacts.
- See Section 8 troubleshooting.

Q3. How are route tags used in optimization?

- Tags are used for grouping/interpretation, but feasibility remains trip-level.

Q4. Can timetable be modified by dispatch stage?

- No. Timetable is treated as read-only input contract.

## 8. Troubleshooting

### Error: Built dataset is not available

- Ensure `data/built/tokyu_core/` exists with required files.
- Start backend again after confirming paths.

### Error: API connection failed in Tk app

- Confirm backend is running on `127.0.0.1:8000`.
- Check local firewall/port conflicts.

### MILP unavailable

- Gurobi may be missing or license may be unavailable.
- Use ALNS/hybrid mode as fallback for method review.

### Unexpected no-trip / no-timetable behavior

- Verify selected depot/routes/day type in quick setup.
- Verify artifacts and scenario scope consistency.

## 9. If You Need To Regenerate Data

If built artifacts are not present or need refresh:

```powershell
python catalog_update_app.py refresh gtfs-pipeline --source-dir ./data/raw-odpt
```

Then verify `data/built/tokyu_core/` artifacts again.

## 10. Branch Operation Policy

Recommended workflow:

- `main`: active development branch
- `core`: external review branch for stable reproducible snapshots

Feedback cycle:

1. Reviewer checks `core`
2. Issues/comments are collected
3. Fixes are implemented in `main`
4. Approved deltas are synchronized into `core`

## 11. Changing Default Branch To `core` (GitHub UI)

This operation is done on GitHub repository settings:

1. Open repository on GitHub
2. Settings
3. Branches
4. Default branch
5. Select `core`
6. Save

## 12. Contact Notes For Reviewer

If you need a focused review package, start from:

- dispatch feasibility correctness
- objective formulation consistency
- MILP/ALNS/hybrid architecture adequacy
- experiment reproducibility and reporting integrity

This document is meant to be sufficient for independent setup and technical review without prior project context.
