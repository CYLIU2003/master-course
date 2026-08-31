# DISPLAY/VALIDATE ONLY IN THIS GOAL. Run only in a separately approved execution Goal.
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$Prepare = Join-Path $Repo 'config\research\november_2026\rain_prepare_request_v1.json'
$Optimization = Join-Path $Repo 'config\research\november_2026\rain_optimization_request_v1.json'
$Profiles = Join-Path $Repo 'config\research\november_2026\rain_candidate_profiles_v3.json'
$OracleApproval = Join-Path $PSScriptRoot 'small_oracle_approval.json'
$RainApproval = Join-Path $PSScriptRoot 'rain_2x2_approval.json'
$Root = Join-Path $Repo 'output\research\november_2026_signed'

& $Python -m tools.november_2026.run_small_oracle_matrix --plan-only --scenario-code RAIN --prepare-request $Prepare --optimization-template $Optimization --trip-counts 8 12 24 --time-limit-sec 300 --random-seed 42 --gurobi-threads 1 --vehicles-per-type 5 --output-dir (Join-Path $Root 'oracle_plan')
& $Python -m tools.november_2026.run_rain_candidate_sensitivity --plan-only --profiles $Profiles --prepare-request $Prepare --optimization-request $Optimization --output-dir (Join-Path $Root 'rain_plan')

& $Python -m tools.november_2026.run_small_oracle_matrix --validate-inputs-only --scenario-code RAIN --prepare-request $Prepare --optimization-template $Optimization --trip-counts 8 12 24 --time-limit-sec 300 --random-seed 42 --gurobi-threads 1 --vehicles-per-type 5 --approval-manifest $OracleApproval --output-dir (Join-Path $Root 'oracle_validation')
& $Python -m tools.november_2026.run_small_oracle_matrix --execute --scenario-code RAIN --prepare-request $Prepare --optimization-template $Optimization --trip-counts 8 12 24 --time-limit-sec 300 --random-seed 42 --gurobi-threads 1 --vehicles-per-type 5 --approval-manifest $OracleApproval --job-timeout-seconds 43200 --output-dir (Join-Path $Root 'oracle_run')

& $Python -m tools.november_2026.run_rain_candidate_sensitivity --validate-inputs-only --profiles $Profiles --prepare-request $Prepare --optimization-request $Optimization --preregistration-manifest $RainApproval --output-dir (Join-Path $Root 'rain_validation')
& $Python -m tools.november_2026.run_rain_candidate_sensitivity --execute --profiles $Profiles --prepare-request $Prepare --optimization-request $Optimization --preregistration-manifest $RainApproval --timeout-seconds 28800 --poll-interval-seconds 2 --output-dir (Join-Path $Root 'rain_run')

& $Python -m tools.november_2026.analyze_candidate_profile_results --profile-result BASE (Join-Path $Root 'rain_run\BASE\profile_result_v1.json') --profile-result RANGE_ONLY (Join-Path $Root 'rain_run\RANGE_ONLY\profile_result_v1.json') --profile-result BUDGET_ONLY (Join-Path $Root 'rain_run\BUDGET_ONLY\profile_result_v1.json') --profile-result FULL_EXPANDED (Join-Path $Root 'rain_run\FULL_EXPANDED\profile_result_v1.json') --preregistration-manifest $RainApproval --output-dir (Join-Path $Root 'rain_analysis')
