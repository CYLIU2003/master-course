"""Serve an explicitly frozen cluster release with an already built frontend."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def configure(settings_path: Path) -> dict:
    settings = json.loads(settings_path.read_text(encoding="utf8"))
    for key in ("release", "python", "frontend", "config", "queue", "outputs"):
        settings[key] = str(Path(settings[key]).resolve())
    if Path(sys.executable).resolve() != Path(settings["python"]):
        raise ValueError("Start this controller with the configured uv-managed Python")
    release = settings["release"]
    actual_sha = subprocess.check_output(["git", "-C", release, "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", release, "status", "--porcelain"], text=True).strip()
    if actual_sha != settings["git_sha"] or dirty:
        raise ValueError("Frozen release SHA changed or worktree is dirty; redeploy before execution")
    if not (Path(settings["frontend"]) / "index.html").is_file():
        raise ValueError("Build the frontend before starting the controller")
    if not Path(settings["config"]).is_file():
        raise ValueError("Worker configuration is missing")
    scenarios = Path(settings.get("scenarios", Path(settings["outputs"]) / "scenarios")).resolve()
    if "scenarios" in settings and not scenarios.is_dir():
        raise ValueError("Configured existing scenario store is missing")
    settings["scenarios"] = str(scenarios)
    os.environ.update(MC_CLUSTER_CONFIG=settings["config"], MC_CLUSTER_DIR=settings["queue"],
                      MC_OUTPUTS_DIR=settings["outputs"], SCENARIO_STORE_PATH=str(scenarios),
                      BUILT_ROOT=str(Path(release) / "data" / "built"), DEFAULT_DATASET_ID="tokyu_full")
    os.chdir(release)
    sys.path.insert(0, release)
    from bff.services.cluster.contracts import read_config, source_digest, runtime_versions
    if source_digest() != settings["source_digest"] or runtime_versions() != settings["runtime_versions"]:
        raise ValueError("Runtime or source digest differs from the deployed workers")
    config = read_config()
    local = [worker for worker in config.workers if worker.transport == "local"]
    if any(Path(worker.repo).resolve() != Path(release) for worker in local):
        raise ValueError("Local worker repository must match this frozen controller")
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Validate without starting a scheduler or solver")
    args = parser.parse_args()
    settings = configure(args.settings.resolve())
    if args.check:
        print(json.dumps({"status": "PASS", "git_sha": settings["git_sha"], "python": sys.executable}))
        return
    from bff.main import app
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    app.mount("/", StaticFiles(directory=settings["frontend"], html=True), name="frontend")
    # The existing scheduler owns the shared queue lock; a second controller fails closed.
    uvicorn.run(app, host="127.0.0.1", port=settings.get("port", 8868))


if __name__ == "__main__":
    main()
