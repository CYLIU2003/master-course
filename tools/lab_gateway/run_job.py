"""Runs on a lab PC (copied next to job.json). Standard library only.

    python run_job.py JOB_DIR --detach    # returns at once; the run survives the end of the SSH session
    python run_job.py JOB_DIR             # runs in the foreground (used by --detach and by the tests)

status.json is the only thing the gateway reads: RUNNING with the program's pid, then DONE with the outcome.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

NT = os.name == "nt"
# Windows OpenSSH owns a kill-on-close Job Object, so the detached copy must break away from it (same as the cluster runner).
DETACH_FLAGS = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB) if NT else 0


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_status(directory: Path, **values) -> None:
    temporary = directory / "status.json.tmp"
    temporary.write_text(json.dumps(values), encoding="ascii")
    os.replace(temporary, directory / "status.json")


def package(directory: Path, output: Path) -> Path:
    result = directory / "result.zip"
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
        for name in ("stdout.log", "stderr.log"):
            if (directory / name).is_file():
                archive.write(directory / name, name)
    return result


def run(directory: Path) -> None:
    job = json.loads((directory / "job.json").read_text(encoding="ascii"))
    work, output = directory / "work", directory / "out"
    output.mkdir(exist_ok=True)
    environment = {**os.environ, "MC_LAB_OUTPUT_DIR": str(output), "MC_LAB_JOB_ID": job["job_id"],
                   "MC_LAB_THREADS": str(job["threads"]), "OMP_NUM_THREADS": str(job["threads"])}
    started = utc()
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if NT else 0
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen([job["python"], job["entry"], *job["args"]], cwd=work, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, creationflags=flags)
        write_status(directory, state="RUNNING", pid=process.pid, started_at=started)
        try:
            code = process.wait(timeout=job["timeout_min"] * 60)
            outcome = "EXITED" if code == 0 else "EXITED_NONZERO"
        except subprocess.TimeoutExpired:
            if NT:
                subprocess.run(["taskkill.exe", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
            else:
                process.kill()
            process.wait()
            code, outcome = -1, "TIMEOUT"
    result = package(directory, output)
    write_status(directory, state="DONE", outcome=outcome, exit_code=code, started_at=started, finished_at=utc(),
                 result_bytes=result.stat().st_size)


def main(argv: list[str]) -> int:
    directory = Path(argv[1])
    if "--detach" in argv[2:]:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(directory)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, creationflags=DETACH_FLAGS)
        return 0
    run(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
