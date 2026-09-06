"""Check relocated entrypoints and navigation without launching BFF jobs."""

from pathlib import Path
import re
import runpy
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_manual_compatibility_entrypoint_is_inert_on_import() -> None:
    namespace = runpy.run_path(str(ROOT / "test_multiday_phase1.py"))
    assert namespace["__test__"] is False
    assert "requests" not in namespace


def test_manual_compatibility_entrypoint_delegates_only_when_executed() -> None:
    source = (ROOT / "test_multiday_phase1.py").read_text(encoding="utf-8")
    with patch("runpy.run_path") as delegate:
        exec(compile(source, "test_multiday_phase1.py", "exec"), {
            "__name__": "__main__", "__file__": str(ROOT / "test_multiday_phase1.py"),
        })
    delegate.assert_called_once_with(
        str(ROOT / "tools/manual_experiments/test_multiday_phase1.py"),
        run_name="__main__",
    )


def test_relocated_manual_script_is_not_a_pytest_test() -> None:
    namespace = runpy.run_path(str(ROOT / "tools/manual_experiments/test_multiday_phase1.py"))
    assert namespace["__test__"] is False
    assert callable(namespace["test_multiday_scenario"])


def test_organization_document_links_resolve() -> None:
    documents = [
        "docs/REPOSITORY_LAYOUT.md", "tools/README.md",
        "tools/manual_experiments/README.md", "tools/thesis_authoring/README.md",
        "docs/archive/implementation_notes/README.md",
        "docs/archive/implementation_notes/analysis_multiday_plan.md",
        "docs/archive/implementation_notes/experiment_logger_integration.md",
        "tools/benchmarks/README.md", "scripts/README.md",
        "docs/FILE_ORGANIZATION.md", "scripts/catalog/README.md",
        "scripts/weather/README.md", "tools/gui/README.md",
        "docs/constant/README.md",
    ]
    for name in documents:
        document = ROOT / name
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            assert (document.parent / target).is_file(), (name, target)


@pytest.mark.parametrize("name", ["benchmark_api", "benchmark_bff", "benchmark_catalog_ingest"])
def test_old_benchmark_cli_delegates_without_running_work(name, monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tools.benchmarks as package

    main = Mock(return_value=0)
    monkeypatch.setattr(package, name, SimpleNamespace(main=main), raising=False)
    if name == "benchmark_catalog_ingest":
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(ROOT / "tools" / f"{name}.py"), run_name="__main__")
        assert exit_info.value.code == 0
    else:
        runpy.run_path(str(ROOT / "tools" / f"{name}.py"), run_name="__main__")
    main.assert_called_once_with()


@pytest.mark.parametrize("name", ["benchmark_bff", "benchmark_catalog_ingest"])
def test_old_benchmark_import_is_the_canonical_module(name) -> None:
    import importlib

    old = importlib.import_module(f"tools.{name}")
    canonical = importlib.import_module(f"tools.benchmarks.{name}")
    assert old is canonical


def test_catalog_repository_root_survives_relocation() -> None:
    from tools.benchmarks.benchmark_catalog_ingest import REPO_ROOT

    assert REPO_ROOT == ROOT
