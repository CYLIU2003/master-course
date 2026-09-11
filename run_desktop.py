"""Start the TypeScript/React/Electron app from any working directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke", action="store_true", help="Run the hidden read-only desktop check"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    frontend = root / "frontend"
    binary = (
        frontend
        / "node_modules"
        / "electron"
        / "dist"
        / ("electron.exe" if os.name == "nt" else "electron")
    )
    if not binary.exists() or not (frontend / "dist-electron" / "main.js").exists():
        print(
            "Desktop build missing. In frontend/, run: npm.cmd ci; npm.cmd run build; npm.cmd start"
        )
        return 1
    command = [str(binary), str(frontend)]
    if args.smoke:
        command.append("--smoke")
    environment = {**os.environ, "EV_BUS_WORKSPACE": str(root)}
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    return subprocess.run(
        command, cwd=frontend, env=environment, check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
