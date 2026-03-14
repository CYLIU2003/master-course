import ast
import json
import pathlib

import pytest

from bff.main import app
from src.dataset_integrity import evaluate_dataset_integrity
from src.research_dataset_loader import get_dataset_status


def collect_imports(directory: str) -> list[str]:
    imports: list[str] = []
    root = pathlib.Path(directory)
    if not root.exists():
        return imports
    for file in root.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
    return imports


def test_main_has_app_state_routes():
    paths = {route.path for route in app.routes}
    assert "/api/app-state" in paths
    assert "/api/app/data-status" in paths


def test_main_excludes_catalog_and_public_data_routes():
    paths = {route.path for route in app.routes}
    assert "/api/catalog/operators" not in paths
    assert "/api/scenarios/{scenario_id}/public-data/fetch" not in paths


def test_parquet_schema_files_exist_and_have_required_columns():
    for file_name in ["routes.schema.json", "trips.schema.json", "timetables.schema.json"]:
        path = pathlib.Path("schema/parquet", file_name)
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload.get("required_columns"), dict)
        assert payload["required_columns"]


def test_dataset_integrity_fields_are_exposed():
    report = evaluate_dataset_integrity("tokyu_core")
    assert report["seed_ready"] is True
    status = get_dataset_status("tokyu_core")
    assert "seedReady" in status
    assert "builtReady" in status
    assert "missingArtifacts" in status
    assert "integrityError" in status


# prohibition: no legacy ETL imports in bff/ or src/
FORBIDDEN_IMPORT_TOKENS = {
    "odpt",
    "gtfs_import",
    "catalog_import",
    "public_data",
    "master_data_import",
    "raw_catalog",
}


@pytest.mark.parametrize("directory", ["bff", "src"])
def test_no_legacy_etl_imports(directory: str):
    imports = collect_imports(directory)
    violations = [m for m in imports if any(t in m for t in FORBIDDEN_IMPORT_TOKENS)]
    assert not violations, (
        f"Forbidden ETL imports found in {directory}/: {violations}\n"
        "ETL/ODPT/GTFS code must live only in data-prep/."
    )


def test_bff_routers_do_not_access_raw_odpt_data():
    raw_access_patterns = [
        "odpt",
        "raw/",
        "raw_json",
        "fetch_odpt",
        "requests.get",
        "httpx.get",
        "aiohttp",
    ]
    violations = []
    for file in pathlib.Path("bff/routers").rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        for pattern in raw_access_patterns:
            if pattern in text:
                violations.append(f"{file}: contains '{pattern}'")
    assert not violations, (
        "BFF routers must not access raw feed data or make HTTP requests at runtime.\n"
        + "\n".join(violations)
    )


def test_frontend_does_not_bypass_run_readiness():
    hook_candidates = list(pathlib.Path("frontend/src").rglob("use-scenario-run-readiness*")) + list(
        pathlib.Path("frontend/src").rglob("useScenarioRunReadiness*")
    )
    assert hook_candidates

    run_pages = [
        "frontend/src/pages/dispatch/SimulationRunPage.tsx",
        "frontend/src/pages/dispatch/OptimizationRunPage.tsx",
    ]
    for page_path in run_pages:
        p = pathlib.Path(page_path)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        has_readiness = (
            "useScenarioRunReadiness" in text
            or "useRunReadiness" in text
            or "built_ready" in text
            or "builtReady" in text
            or "isRunnable" in text
        )
        assert has_readiness


def test_backend_legacy_absent_from_active_import_graph():
    active_dirs = ["bff", "src", "frontend/src"]
    violations = []
    for directory in active_dirs:
        path = pathlib.Path(directory)
        if not path.exists():
            continue
        for file in path.rglob("*.py"):
            text = file.read_text(encoding="utf-8")
            if "backend_legacy" in text or "from backend import" in text:
                violations.append(str(file))
        for file in path.rglob("*.ts"):
            text = file.read_text(encoding="utf-8")
            if "backend_legacy" in text:
                violations.append(str(file))
        for file in path.rglob("*.tsx"):
            text = file.read_text(encoding="utf-8")
            if "backend_legacy" in text:
                violations.append(str(file))
    assert not violations


def test_bff_list_routers_do_not_return_unbounded_responses():
    unbounded_patterns = [
        ".to_dict(orient='records')",
        '.to_dict(orient="records")',
        "return list(",
        "return df.to_dict",
    ]
    violations = []
    for file in pathlib.Path("bff/routers").rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        for pattern in unbounded_patterns:
            if pattern in text:
                violations.append(f"{file}: '{pattern}'")
    if violations:
        pytest.xfail("Unbounded list patterns still present (fix in Phase 4)")


LEGACY_RUNTIME_TOKENS = [
    "odpt",
    "gtfs",
    "catalog_import",
    "raw_catalog",
    "fetch_odpt",
    "import_gtfs",
    "public_data",
]


def test_bff_routers_contain_no_legacy_runtime_tokens():
    violations = []
    routers_dir = pathlib.Path("bff/routers")
    if not routers_dir.exists():
        pytest.skip("bff/routers not found")
    for file in routers_dir.rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        for token in LEGACY_RUNTIME_TOKENS:
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if token in stripped:
                    violations.append(f"{file}:{i}: '{token}'")
    assert not violations, (
        "bff/routers must not reference legacy runtime tokens.\n"
        + "\n".join(violations)
    )


HTTP_CLIENT_TOKENS = [
    "requests.get",
    "requests.post",
    "httpx.get",
    "httpx.post",
    "aiohttp.",
]


def test_bff_routers_make_no_outbound_http_calls():
    violations = []
    for file in pathlib.Path("bff/routers").rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        for token in HTTP_CLIENT_TOKENS:
            if token in text:
                violations.append(f"{file}: '{token}'")
    assert not violations


def test_backend_legacy_excluded_from_pytest_config():
    for config_file in ["pytest.ini", "pyproject.toml", "setup.cfg"]:
        path = pathlib.Path(config_file)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "backend_legacy" not in text or "exclude" in text


def test_bff_uses_unified_error_codes():
    errors_path = pathlib.Path("bff/errors.py")
    assert errors_path.exists()
    source = errors_path.read_text(encoding="utf-8")
    required_codes = [
        "SEED_DATASET_REQUIRED",
        "BUILT_DATASET_REQUIRED",
        "DATASET_INTEGRITY_ERROR",
        "MISSING_ARTIFACT",
        "SCHEMA_VALIDATION_ERROR",
    ]
    for code in required_codes:
        assert code in source


def test_frontend_error_types_defined():
    path = pathlib.Path("frontend/src/types/errors.ts")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "AppErrorCode" in text
    assert "BUILT_DATASET_REQUIRED" in text


def test_use_app_state_hook_exists():
    candidates = list(pathlib.Path("frontend/src").rglob("use-app-state*")) + list(
        pathlib.Path("frontend/src").rglob("useAppState*")
    )
    assert candidates


def test_data_readiness_banner_exists():
    candidates = list(pathlib.Path("frontend/src").rglob("DataReadinessBanner*")) + list(
        pathlib.Path("frontend/src").rglob("data-readiness-banner*")
    )
    assert candidates
    banner_text = candidates[0].read_text(encoding="utf-8")
    assert "onClose" not in banner_text and "onDismiss" not in banner_text


def test_no_architecture_tests_are_skipped():
    tree = ast.parse(pathlib.Path("tests/test_architecture.py").read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for candidate in ast.walk(tree):
        for child in ast.iter_child_nodes(candidate):
            parents[child] = candidate

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "pytest" and func.attr == "skip"):
            continue
        current = parents.get(node)
        conditional = False
        while current is not None:
            if isinstance(current, (ast.If, ast.Try, ast.Match)):
                conditional = True
                break
            current = parents.get(current)
        if not conditional:
            violations.append(f"line {getattr(node, 'lineno', 0)}")
    assert not violations, (
        "Unconditional pytest.skip() found in test_architecture.py.\n"
        "Architecture tests must always run.\n"
        + "\n".join(f"  {item}" for item in violations)
    )


REQUIRED_READINESS_STATES = {
    "no-seed",
    "seed-only",
    "built-ready",
    "integrity-error",
    "incomplete",
}


def test_app_state_machine_has_required_states():
    candidates = list(pathlib.Path("frontend/src").rglob("use-app-state*")) + list(
        pathlib.Path("frontend/src").rglob("useAppState*")
    )
    if not candidates:
        pytest.skip("useAppState hook not found")
    text = candidates[0].read_text(encoding="utf-8")
    for state in REQUIRED_READINESS_STATES:
        assert state in text


DATA_PREP_NAMESPACES = [
    "data_prep",
    "odpt_client",
    "gtfs_import",
    "catalog_import",
    "tokyubus_gtfs",
    "build_pipeline",
    "fetch_odpt",
    "canonical_builder",
]


@pytest.mark.parametrize("active_dir", ["bff", "src"])
def test_runtime_does_not_import_from_data_prep_namespaces(active_dir: str):
    if not pathlib.Path(active_dir).exists():
        pytest.skip(f"{active_dir} not present")

    violations = []
    for file in pathlib.Path(active_dir).rglob("*.py"):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for mod in modules:
                if any(ns in mod for ns in DATA_PREP_NAMESPACES):
                    violations.append(
                        f"{file}:{getattr(node, 'lineno', 0)}: imports '{mod}'"
                    )

    assert not violations, (
        f"Runtime code in {active_dir}/ must not import from data-prep namespaces.\n"
        "Move build logic to data-prep/lib or replace with artifact-reader.\n"
        + "\n".join(f"  {item}" for item in violations)
    )


RUNTIME_BUILD_PATTERNS = [
    "fetch_odpt",
    "reconstruct_canonical",
    "rebuild_artifact",
    "import_gtfs",
    "parse_odpt",
]


def test_bff_does_not_reconstruct_artifacts_at_runtime():
    violations = []
    for file in pathlib.Path("bff").rglob("*.py"):
        text = file.read_text(encoding="utf-8")
        for pattern in RUNTIME_BUILD_PATTERNS:
            if pattern in text:
                for line_no, line in enumerate(text.splitlines(), 1):
                    if pattern in line and not line.strip().startswith("#"):
                        violations.append(f"{file}:{line_no}: '{pattern}'")
    assert not violations, (
        "BFF must not reconstruct artifacts at runtime.\n"
        "Move build logic to data-prep/pipeline/.\n"
        + "\n".join(f"  {item}" for item in violations)
    )


def test_artifact_contract_module_importable():
    from src.artifact_contract import (
        ArtifactContractError,
        ContractErrorCode,
        RUNTIME_VERSION,
        check_artifact_contract,
    )

    assert callable(check_artifact_contract)
    assert issubclass(ArtifactContractError, Exception)
    assert isinstance(RUNTIME_VERSION, str)
    assert str(ContractErrorCode.MANIFEST_MISSING) == "ARTIFACT_MANIFEST_MISSING"


def test_app_cache_references_artifact_contract():
    source = pathlib.Path("bff/services/app_cache.py").read_text(encoding="utf-8")
    assert "check_artifact_contract" in source or "artifact_contract" in source


def test_bff_errors_includes_contract_codes():
    source = pathlib.Path("bff/errors.py").read_text(encoding="utf-8")
    required = [
        "ARTIFACT_MANIFEST_MISSING",
        "ARTIFACT_MANIFEST_INVALID",
        "ARTIFACT_MISSING",
        "ARTIFACT_HASH_MISMATCH",
        "RUNTIME_VERSION_TOO_OLD",
    ]
    for code in required:
        assert code in source, f"bff/errors.py must define '{code}'"


def test_runtime_refuses_manifest_less_built():
    import tempfile

    import pandas as pd

    from src.artifact_contract import (
        ArtifactContractError,
        ContractErrorCode,
        check_artifact_contract,
    )

    with tempfile.TemporaryDirectory() as tmp:
        built_dir = pathlib.Path(tmp)
        pd.DataFrame(
            [{"id": "x", "routeCode": "x", "routeLabel": "x", "name": "x"}]
        ).to_parquet(built_dir / "routes.parquet")
        pd.DataFrame(
            [
                {
                    "trip_id": "x",
                    "route_id": "x",
                    "service_id": "weekday",
                    "departure": "00:00:00",
                    "arrival": "00:00:00",
                }
            ]
        ).to_parquet(built_dir / "trips.parquet")
        pd.DataFrame(
            [
                {
                    "trip_id": "x",
                    "route_id": "x",
                    "service_id": "weekday",
                    "origin": "x",
                    "destination": "y",
                    "departure": "00:00:00",
                    "arrival": "00:00:00",
                }
            ]
        ).to_parquet(built_dir / "timetables.parquet")

        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.MANIFEST_MISSING


def test_build_all_pipeline_exists():
    path = pathlib.Path("data-prep/pipeline/build_all.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "manifest_writer" in text or "write_manifest" in text
    assert "remove_stale_manifest" in text or "manifest.json" in text
    assert "return 1" in text or "sys.exit(1)" in text


def test_producer_version_module_exists():
    path = pathlib.Path("data-prep/lib/producer_version.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "get_producer_version" in text
    assert "get_min_runtime_version" in text


def test_app_cache_is_testable():
    source = pathlib.Path("bff/services/app_cache.py").read_text(encoding="utf-8")
    assert "BUILT_ROOT" in source
    assert "reload_state" in source


def test_timing_middleware_is_registered():
    source = pathlib.Path("bff/main.py").read_text(encoding="utf-8")
    assert "TimingMiddleware" in source
    assert "app.add_middleware(TimingMiddleware)" in source


def test_metrics_service_exists():
    path = pathlib.Path("bff/services/metrics.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "def timed(" in text


def test_contract_judgment_is_only_in_artifact_contract():
    targets = [
        pathlib.Path("src/research_dataset_loader.py"),
        pathlib.Path("bff/services/app_cache.py"),
        pathlib.Path("bff/routers/app_state.py"),
    ]
    forbidden_tokens = ["sha256", "hashlib", "ContractErrorCode"]
    violations = []
    for file in targets:
        text = file.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                violations.append(f"{file}: '{token}'")
    assert not violations, (
        "Duplicate contract judgment found outside src/artifact_contract.py: "
        + ", ".join(violations)
    )


def test_run_preparation_service_exists():
    path = pathlib.Path("bff/services/run_preparation.py")
    assert path.exists(), "bff/services/run_preparation.py must exist"
    source = path.read_text(encoding="utf-8")
    assert "get_or_build_run_preparation" in source
    assert "_prep_cache" in source
    assert "invalidate_scenario" in source


def test_runtime_scope_module_exists():
    path = pathlib.Path("src/runtime_scope.py")
    assert path.exists(), "src/runtime_scope.py must exist"
    source = path.read_text(encoding="utf-8")
    assert "resolve_scope" in source
    assert "load_scoped_trips" in source
    assert "load_scoped_timetables" in source


def test_simulation_and_optimization_both_use_run_preparation_service():
    for router_file in [
        "bff/routers/simulation.py",
        "bff/routers/optimization.py",
    ]:
        source = pathlib.Path(router_file).read_text(encoding="utf-8")
        assert "run_preparation" in source or "get_or_build_run_preparation" in source, (
            f"{router_file} must use get_or_build_run_preparation() from "
            "bff/services/run_preparation.py. Both simulation and optimization must share the same prep path."
        )


MASTER_DATA_FORBIDDEN = [
    "odpt",
    "gtfs",
    "catalog_import",
    "public_data",
    "timetable_rows",
    "stop_times",
    "all_trips",
    "import_routes",
    "fetch_routes",
]


def test_master_data_router_has_no_forbidden_tokens():
    path = pathlib.Path("bff/routers/master_data.py")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = []
    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('"""'):
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        for token in MASTER_DATA_FORBIDDEN:
            if token in line:
                violations.append(f"line {i}: '{token}' in: {stripped[:80]}")
    assert not violations, (
        "bff/routers/master_data.py contains forbidden tokens.\n"
        "This file must remain summary-only reference data.\n"
        + "\n".join(f"  {item}" for item in violations[:10])
    )


APP_CACHE_FORBIDDEN_LOGIC = [
    "sha256",
    "hashlib",
    "odpt",
    "gtfs",
    "requests.get",
    "httpx",
    "ContractErrorCode",
]


def test_app_cache_does_not_reimplement_contract_logic():
    path = pathlib.Path("bff/services/app_cache.py")
    source = path.read_text(encoding="utf-8")
    violations = []
    in_docstring = False
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('"""'):
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        for token in APP_CACHE_FORBIDDEN_LOGIC:
            if token not in stripped:
                continue
            if token in {"sha256", "hashlib"} and "import" not in stripped:
                violations.append(f"line {i}: '{token}'")
            elif token in {"odpt", "gtfs", "requests.get", "httpx"}:
                violations.append(f"line {i}: '{token}'")
            elif token == "ContractErrorCode" and "class" in stripped:
                violations.append(f"line {i}: defines ContractErrorCode")
    assert not violations, (
        "bff/services/app_cache.py re-implements contract logic that belongs in src/artifact_contract.py.\n"
        + "\n".join(f"  {item}" for item in violations)
    )


SUMMARY_FORBIDDEN_FIELDS = [
    "stop_times",
    "all_trips",
    "stopSequence",
]


def test_master_data_route_list_is_summary_oriented():
    source = pathlib.Path("bff/routers/master_data.py").read_text(encoding="utf-8")
    route_list_block = source.split('@router.get("/scenarios/{scenario_id}/routes")', 1)[1].split(
        "def _route_match_keys",
        1,
    )[0]
    for field in SUMMARY_FORBIDDEN_FIELDS:
        assert field not in route_list_block, (
            f"bff/routers/master_data.py must not return '{field}' in summary endpoints"
        )


def test_heavy_list_endpoints_have_pagination():
    for router_file in ["bff/routers/scenarios.py", "bff/routers/graph.py"]:
        source = pathlib.Path(router_file).read_text(encoding="utf-8")
        has_pagination = "limit" in source or "offset" in source or "cursor" in source
        assert has_pagination, f"{router_file} must implement pagination for heavy list endpoints"


def test_scenario_list_endpoint_does_not_embed_full_overlay():
    source = pathlib.Path("bff/routers/scenarios.py").read_text(encoding="utf-8")
    assert "scenarioOverlay" not in source.split("def get_scenario", 1)[0], (
        "Scenario list/default endpoints must not serialize full ScenarioOverlay payloads"
    )
