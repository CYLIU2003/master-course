import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import pytest

from bff.services import scenario_periods as store


@pytest.fixture
def plans(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "scenarios_root", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(store.scenario_store, "get_desktop_context", lambda sid: ({"id": sid}, {}))
    return tmp_path


def edit(revision=0, start="2025-01-06"):
    return store.PeriodEdit(revision=revision, periods=[store.Period(id="jan", label="1月代表週", start=start)])


def test_two_scenarios_have_separate_periods_and_no_scenario_clones(plans):
    store.save_periods("a", edit())
    assert store.get_periods("b")["periods"] == []
    assert store.get_periods("a")["periods"][0]["end"] == "2025-01-12"
    assert not (plans / "scenarios").exists()


def test_concurrent_edits_cannot_silently_overwrite(plans):
    store.get_periods("a")
    def write():
        try:
            store.save_periods("a", edit())
            return "saved"
        except ValueError:
            return "stale"
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: write(), range(2))) == ["saved", "stale"]


def bind(plans, parent="a"):
    campaign = plans / "campaign"
    campaign.mkdir()
    (campaign / "binding.json").write_text(json.dumps({"parent": parent, "weeks": ["2025-01-06"]}))
    store.save_periods("a", edit())
    return campaign


def test_binding_is_idempotent_and_executed_dates_immutable(plans):
    campaign = bind(plans)
    store.bind_campaign("a", "jan", campaign)
    result = store.bind_campaign("a", "jan", campaign)
    assert len(result["periods"][0]["attempts"]) == 1
    with pytest.raises(ValueError, match="IMMUTABLE"):
        store.save_periods("a", edit(1, "2025-01-13"))
    assert store.get_periods("a")["revision"] == 1


def test_wrong_parent_cannot_bind(plans):
    campaign = bind(plans, "other")
    with pytest.raises(ValueError, match="parent"):
        store.bind_campaign("a", "jan", campaign)


def test_stale_or_offline_progress_is_unknown_not_success(plans):
    campaign = bind(plans)
    (campaign / "operations").mkdir()
    snapshot = {"observed_at_utc": (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(),
                "connection": "CONNECTED", "cases": [{"week": "2025-01-06", "state": "RUNNING", "verified": False}]}
    (campaign / "operations/status.json").write_text(json.dumps(snapshot))
    result = store.bind_campaign("a", "jan", campaign)
    assert result["periods"][0]["attempts"][0]["state"] == "UNKNOWN"
    assert result["progress"]["verified"] == 0


def test_reject_duplicate_periods_and_invalid_dates(plans):
    with pytest.raises(ValueError):
        store.PeriodEdit(revision=0, periods=[edit().periods[0], edit().periods[0]])
    with pytest.raises(ValueError):
        edit(start="2025-02-30")


def test_recorded_terminal_outcome_survives_observer_exit(plans):
    campaign = bind(plans)
    (campaign / "operations").mkdir()
    snapshot = {"observed_at_utc": "2025-01-01T00:00:00+00:00", "connection": "CONNECTED",
                "cases": [{"week": "2025-01-06", "state": "FAILED", "verified": False}]}
    (campaign / "operations/status.json").write_text(json.dumps(snapshot))
    result = store.bind_campaign("a", "jan", campaign)
    assert result["periods"][0]["attempts"][0]["state"] == "FAILED"
    assert result["periods"][0]["attempts"][0]["stale"] is True


def test_run_instances_are_hidden_from_reusable_scenario_list(plans, monkeypatch):
    from bff.store import desktop_store
    paths = []
    for identity, name, extra in [("parent", "仮・正式用", {}), ("instance", "weekly run", {"run_instance": True, "base_scenario_id": "parent"})]:
        path = plans / f"{identity}.json"
        path.write_text(json.dumps({"meta": {"id": identity, "name": name, **extra}}))
        paths.append(path)
    monkeypatch.setattr(store.scenario_store, "scenario_metadata_paths", lambda: paths)
    assert [p["id"] for p in desktop_store.scenario_page("", 0, 50, period_kind="reusable")["items"]] == ["parent"]
    assert len(desktop_store.scenario_page("", 0, 50, period_kind="all")["items"]) == 2


def test_http_validates_periods_and_revision_before_writing(plans):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bff.routers.desktop import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        path = "/desktop/scenarios/a/periods"
        assert client.get(path).json()["revision"] == 0
        assert client.put(path, json=edit().model_dump(mode="json")).status_code == 200
        assert client.put(path, json=edit().model_dump(mode="json")).status_code == 409
        assert client.put(path, json={"revision": 1, "periods": [], "campaign": "C:/private"}).status_code == 422
