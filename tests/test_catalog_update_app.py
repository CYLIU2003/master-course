from __future__ import annotations

import types

import catalog_update_app


def test_catalog_update_app_defaults_to_tokyu_gtfs_feed():
    assert catalog_update_app.DEFAULT_GTFS_FEED_PATH == "GTFS/TokyuBus-GTFS"


def test_rebuild_tokyu_built_datasets_calls_build_all_for_each_dataset(monkeypatch):
    calls = []

    def fake_build_dataset(dataset_id, **kwargs):
        calls.append((dataset_id, kwargs))
        return 0

    monkeypatch.setattr(
        catalog_update_app,
        "_data_prep_build_all",
        lambda: types.SimpleNamespace(build_dataset=fake_build_dataset),
    )

    result = catalog_update_app._rebuild_tokyu_built_datasets(
        dataset_ids=["tokyu_core", "tokyu_full"],
        feed_path="GTFS/TokyuBus-GTFS",
        strict_gtfs_reconciliation=True,
    )

    assert list(result) == ["tokyu_core", "tokyu_full"]
    assert [call[0] for call in calls] == ["tokyu_core", "tokyu_full"]
    assert all(call[1]["no_fetch"] is True for call in calls)
    assert all(call[1]["force"] is True for call in calls)
    assert all(call[1]["feed_path"] == "GTFS/TokyuBus-GTFS" for call in calls)
    assert all(call[1]["strict_gtfs_reconciliation"] is True for call in calls)


def test_build_gtfs_sqlite_catalog_invokes_gtfs_db_builder(monkeypatch, tmp_path):
    calls = []

    def fake_build_tokyu_gtfs_db(path, *, dataset_id, feed_path):
        calls.append((path, dataset_id, feed_path))
        return path

    monkeypatch.setattr(
        catalog_update_app,
        "_build_tokyu_gtfs_db_module",
        lambda: types.SimpleNamespace(build_tokyu_gtfs_db=fake_build_tokyu_gtfs_db),
    )

    result = catalog_update_app._build_gtfs_sqlite_catalog(
        dataset_id="tokyu_full",
        feed_path="GTFS/TokyuBus-GTFS",
        db_path=str(tmp_path / "tokyu_gtfs.sqlite"),
    )

    assert result["datasetId"] == "tokyu_full"
    assert result["dbPath"].endswith("tokyu_gtfs.sqlite")
    assert calls[0][1] == "tokyu_full"
    assert calls[0][2] == "GTFS/TokyuBus-GTFS"
