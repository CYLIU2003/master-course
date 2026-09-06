"""Verify reorganized imports and CLI delegation without running workloads."""

import importlib
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _import_entrypoint(name):
    return importlib.import_module(name)


MOVED_MODULES = [
    [
        "scripts.build_tokyu_bus_data",
        "scripts.catalog.build_tokyu_bus_data"
    ],
    [
        "scripts.build_tokyu_full_db",
        "scripts.catalog.build_tokyu_full_db"
    ],
    [
        "scripts.build_tokyu_gtfs_db",
        "scripts.catalog.build_tokyu_gtfs_db"
    ],
    [
        "scripts.build_tokyu_subset_db",
        "scripts.catalog.build_tokyu_subset_db"
    ],
    [
        "scripts.export_tokyu_sqlite_to_built",
        "scripts.catalog.export_tokyu_sqlite_to_built"
    ],
    [
        "scripts.rebuild_built_from_normalized",
        "scripts.catalog.rebuild_built_from_normalized"
    ],
    [
        "scripts._odpt_runtime",
        "scripts.catalog._odpt_runtime"
    ],
    [
        "scripts._stop_timetable_fallback",
        "scripts.catalog._stop_timetable_fallback"
    ],
    [
        "scripts.tokyu_subset_config",
        "scripts.catalog.tokyu_subset_config"
    ],
    [
        "scripts.extract_engine_bus",
        "scripts.catalog.extract_engine_bus"
    ],
    [
        "scripts.query_engine_bus",
        "scripts.catalog.query_engine_bus"
    ],
    [
        "tools.fast_catalog_ingest",
        "scripts.catalog.fast_catalog_ingest"
    ],
    [
        "tools.update_tokyu_depots",
        "scripts.catalog.update_tokyu_depots"
    ],
    [
        "tools.scenario_backup_tk",
        "tools.gui.scenario_backup_tk"
    ],
    [
        "tools.route_variant_labeler_tk",
        "tools.gui.route_variant_labeler_tk"
    ],
    [
        "tools.bus_operation_visualizer_tk",
        "tools.gui.bus_operation_visualizer_tk"
    ],
    [
        "tools.multi_run_visualizer_tk",
        "tools.gui.multi_run_visualizer_tk"
    ],
    [
        "tools._visualizer_report_utils",
        "tools.gui._visualizer_report_utils"
    ],
    [
        "tools.profile_catalog_ingest",
        "tools.benchmarks.profile_catalog_ingest"
    ],
    [
        "tools.validate_output_consistency",
        "scripts.validate_output_consistency"
    ]
]


@pytest.mark.parametrize("old_name,new_name", MOVED_MODULES)
def test_compatibility_import_preserves_module_identity(old_name, new_name):
    old = _import_entrypoint(old_name)
    canonical = _import_entrypoint(new_name)
    assert old is canonical
    for name in ("REPO_ROOT", "_REPO_ROOT", "_ROOT"):
        if hasattr(canonical, name):
            assert Path(getattr(canonical, name)) == ROOT


@pytest.mark.parametrize("old_name,new_name", MOVED_MODULES)
@pytest.mark.parametrize("exit_code", [0, 7])
def test_compatibility_cli_preserves_exit_status(old_name, new_name, exit_code, monkeypatch):
    canonical = _import_entrypoint(new_name)
    if not hasattr(canonical, "main"):
        return  # Data/config modules deliberately have no executable entrypoint.
    main = Mock(return_value=exit_code)
    monkeypatch.setattr(canonical, "main", main)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / (old_name.replace(".", "/") + ".py")), run_name="__main__")
    assert result.value.code == exit_code
    main.assert_called_once_with()
