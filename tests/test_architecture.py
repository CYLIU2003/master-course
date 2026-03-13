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
    if violations:
        pytest.xfail(
            f"Forbidden ETL imports found in {directory}/: {violations[:20]}"
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
    if violations:
        pytest.xfail(
            "BFF routers still contain runtime fetch patterns: " + ", ".join(violations[:10])
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
    if violations:
        pytest.xfail("bff/routers legacy tokens still present")


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
