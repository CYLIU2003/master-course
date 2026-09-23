"""The cluster UI can use the existing scenario store without moving originals."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

def test_controller_binds_existing_scenarios_separately_from_run_outputs(tmp_path, monkeypatch):
    from bff.services.cluster import contracts
    from tools.cluster import serve_controller

    release = tmp_path / "release"
    release.mkdir()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok", encoding="utf-8")
    scenarios = tmp_path / "legacy-scenarios"
    scenarios.mkdir()
    config = tmp_path / "workers.json"
    config.write_text(json.dumps({"workers": [{"id": "local", "name": "Parent", "repo": str(release)}]}), encoding="utf-8")
    settings = {"release": str(release), "python": sys.executable,
                "frontend": str(frontend), "config": str(config),
                "queue": str(tmp_path / "queue"), "outputs": str(tmp_path / "new-outputs"),
                "scenarios": str(scenarios), "git_sha": "a" * 40,
                "source_digest": "source", "runtime_versions": {"python": "test"}}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(serve_controller.subprocess, "check_output", lambda *args, **kwargs: "" if "status" in args[0] else "a" * 40)
    monkeypatch.setattr(contracts, "source_digest", lambda: "source")
    monkeypatch.setattr(contracts, "runtime_versions", lambda: {"python": "test"})
    initial = Path.cwd()
    prior_path = list(sys.path)
    watched = ("SCENARIO_STORE_PATH", "MC_OUTPUTS_DIR", "MC_CLUSTER_CONFIG",
               "MC_CLUSTER_DIR", "BUILT_ROOT", "DEFAULT_DATASET_ID")
    prior_environment = {key: os.environ.get(key) for key in watched}
    try:
        resolved = serve_controller.configure(path)
        assert resolved["scenarios"] == str(scenarios)
        assert os.environ["SCENARIO_STORE_PATH"] == str(scenarios)
        assert os.environ["MC_OUTPUTS_DIR"] == str(tmp_path / "new-outputs")
    finally:
        os.chdir(initial)
        sys.path[:] = prior_path
        for key, value in prior_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
