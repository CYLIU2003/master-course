"""The ODPT refresh is an explicit, immutable action, separate from Prepare."""

import hashlib
import json

import pytest

from scripts.audits import acquire_shibu24_odpt as capture
from scripts.audits.audit_shibu24_source import load_capture, load_stops


def test_manual_capture_creates_auditable_manifest_without_persisting_key(tmp_path, monkeypatch):
    pattern_id = "odpt.BusroutePattern:TokyuBus.Shibu24.A"
    calls = []
    monkeypatch.setattr(capture, "resolve_odpt_api_key", lambda _: "secret-for-test")

    def fake_capture(output, resource, params, key):
        assert output == tmp_path
        assert key == "secret-for-test"
        calls.append((resource, params))
        if resource == "odpt:BusroutePattern":
            rows = [{"owl:sameAs": pattern_id, "dc:title": "渋２４",
                     "odpt:operator": capture.OPERATOR_ID}]
        elif resource == "odpt:BusTimetable":
            rows = [{"owl:sameAs": "trip-1", "odpt:operator": capture.OPERATOR_ID,
                     "odpt:busroutePattern": pattern_id}]
        else:
            rows = [{"owl:sameAs": "stop-1", "odpt:operator": capture.OPERATOR_ID}]
        path = tmp_path / f"{resource.split(':')[-1]}.json"
        raw = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        source = {"path": str(path),
                  "request": {"endpoint": resource, "query": params},
                  "sha256": hashlib.sha256(raw).hexdigest()}
        path.with_suffix(".manifest.json").write_text(json.dumps(source), encoding="utf-8")
        return rows, source

    monkeypatch.setattr(capture, "capture_resource", fake_capture)
    result = capture.acquire(tmp_path)
    saved = (tmp_path / "shibu24_capture_manifest.json").read_text(encoding="utf-8")
    assert result["pattern_count"] == 1
    assert result["timetable_count"] == 1
    assert len(result["sources"]) == 3
    assert len(calls) == 3
    assert "secret-for-test" not in saved
    assert json.loads(saved)["stop_source_path"].endswith("BusstopPole.json")
    _, patterns, timetables, _ = load_capture(tmp_path)
    stops, _ = load_stops(tmp_path / "BusstopPole.json")
    assert len(patterns) == len(timetables) == len(stops) == 1
    with pytest.raises(FileExistsError, match="immutable"):
        capture.acquire(tmp_path)
    assert len(calls) == 3


def test_manual_capture_rejects_incomplete_timetable(tmp_path, monkeypatch):
    pattern_id = "odpt.BusroutePattern:TokyuBus.Shibu24.A"
    monkeypatch.setattr(capture, "resolve_odpt_api_key", lambda _: "secret-for-test")

    def fake_capture(_output, resource, _params, _key):
        source = {"path": "unused.json"}
        if resource == "odpt:BusroutePattern":
            return ([{"owl:sameAs": pattern_id, "dc:title": "渋24",
                      "odpt:operator": capture.OPERATOR_ID}], source)
        return [], source

    monkeypatch.setattr(capture, "capture_resource", fake_capture)
    with pytest.raises(ValueError, match="Invalid Shibu24 ODPT timetable"):
        capture.acquire(tmp_path)
    assert not (tmp_path / "shibu24_capture_manifest.json").exists()
