from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_builder_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "build_tokyu_full_db.py"
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("build_tokyu_full_db_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_builder_accepts_env_backed_key_when_flag_is_omitted(tmp_path, monkeypatch):
    module = _load_builder_module()
    seen_keys: list[str] = []

    def fake_phase_stops(conn, api_key, use_cache):
        del conn, use_cache
        seen_keys.append(api_key)

    def fake_phase_patterns(conn, api_key, use_cache):
        del conn, use_cache
        seen_keys.append(api_key)
        return {"pattern:black": "黒01"}

    monkeypatch.setattr(module, "resolve_odpt_api_key", lambda explicit_key: "env-key")
    monkeypatch.setattr(module, "phase_stops", fake_phase_stops)
    monkeypatch.setattr(module, "phase_patterns", fake_phase_patterns)
    monkeypatch.setattr(module, "phase_timetables", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "phase_stop_timetables", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "print_summary", lambda conn: None)
    monkeypatch.setattr(module, "write_env_hint", lambda db_path: None)

    out_path = tmp_path / "tokyu_full.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_tokyu_full_db.py",
            "--skip-stop-timetables",
            "--phases",
            "1,2",
            "--out",
            str(out_path),
        ],
    )

    module.main()

    assert seen_keys == ["env-key", "env-key"]
    conn = sqlite3.connect(out_path)
    meta = dict(conn.execute("SELECT key, value FROM pipeline_meta").fetchall())
    assert meta["schema_version"] == "1.1"
    conn.close()
