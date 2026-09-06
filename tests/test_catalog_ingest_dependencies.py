"""Optional ETL dependencies must fail before output or scenario mutation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import catalog_update_app as catalog
from scripts.catalog import fast_catalog_ingest as ingest


def test_fetch_dependency_failure_does_not_create_output(tmp_path, monkeypatch):
    missing = Mock(side_effect=ingest.CatalogDependencyError('missing data-prep'))
    monkeypatch.setattr(ingest, '_catalog_builder_module', missing)
    credentials = Mock()
    monkeypatch.setattr(ingest, '_validate_fetch_odpt_preconditions', credentials)
    output = tmp_path / 'not-created'
    args = ingest.build_parser().parse_args(['fetch-odpt', '--out-dir', str(output)])
    with pytest.raises(ingest.CatalogDependencyError):
        asyncio.run(ingest.run_fetch_odpt(args))
    assert not output.exists()
    credentials.assert_not_called()


def test_sync_dependency_failure_does_not_create_scenario(monkeypatch):
    monkeypatch.setattr(catalog, '_require_sync_dependencies', Mock(
        side_effect=ingest.CatalogDependencyError('missing data-prep')))
    create = Mock()
    monkeypatch.setattr(catalog, '_resolve_scenario_id', create)
    args = ingest.build_parser().parse_args(['sync-gtfs', '--scenario', 'new'])
    with pytest.raises(ingest.CatalogDependencyError):
        ingest.run_sync_gtfs(args)
    create.assert_not_called()


def test_sync_load_failure_does_not_create_scenario(monkeypatch):
    monkeypatch.setattr(catalog, '_require_sync_dependencies', lambda: None)
    monkeypatch.setattr(catalog, '_get_or_load_bundle', Mock(side_effect=ValueError('invalid feed')))
    create = Mock()
    monkeypatch.setattr(catalog, '_resolve_scenario_id', create)
    args = ingest.build_parser().parse_args(['sync-gtfs', '--scenario', 'new'])
    with pytest.raises(ValueError, match='invalid feed'):
        ingest.run_sync_gtfs(args)
    create.assert_not_called()


def test_dependency_error_is_actionable_cli_error(monkeypatch, capsys):
    monkeypatch.setattr(ingest, '_catalog_builder_module', Mock(
        side_effect=ingest.CatalogDependencyError('requires data-prep/lib/catalog_builder')))
    with pytest.raises(SystemExit) as error:
        ingest.main(['fetch-odpt', '--out-dir', 'unused'])
    assert error.value.code == 2
    assert 'data-prep/lib/catalog_builder' in capsys.readouterr().err


def test_delegates_to_separated_catalog_implementation(monkeypatch):
    builder = SimpleNamespace(build_odpt_url=Mock(return_value='https://example.invalid'))
    load = Mock(return_value=builder)
    monkeypatch.setattr(ingest, '_catalog_builder_module', load)
    assert ingest.build_odpt_url('resource', 'test-key', 'operator') == 'https://example.invalid'
    builder.build_odpt_url.assert_called_once_with('resource', 'test-key', 'operator', extra_params=None)
    load.assert_called_once_with('odpt_fetch')


def test_catalog_loader_returns_canonical_module():
    from scripts.catalog import build_tokyu_gtfs_db
    assert catalog._build_tokyu_gtfs_db_module() is build_tokyu_gtfs_db
