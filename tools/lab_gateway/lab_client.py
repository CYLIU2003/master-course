"""Single-file client for the lab gateway. Standard library only; copy this file to your own PC.

    set LAB_GATEWAY_URL=http://<host>:8899       (given by the operator)
    set LAB_GATEWAY_TOKEN=lab_...                (your personal token; never put it in a file you share or commit)

    python lab_client.py submit ./my_project --entry main.py --ram 4 --time 60 [--threads 2] [--args --n 3]
    python lab_client.py status JOB_ID | list | pool | cancel JOB_ID
    python lab_client.py wait JOB_ID [--interval 20]
    python lab_client.py fetch JOB_ID --out ./results

The program is run as `python <entry> <args>` on a lab PC with the PC's own Python (gurobipy, numpy, pandas, scipy,
pydantic) and Gurobi licence. Write results to the folder named by the environment variable MC_LAB_OUTPUT_DIR; that
folder, stdout.log and stderr.log come back in result.zip. Jobs may be stopped when the lab PC is needed elsewhere.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache"}
MAX_BUNDLE = 100 * 1024 * 1024
TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED", "LOST", "REJECTED"}


def settings() -> tuple[str, str]:
    url, token = os.environ.get("LAB_GATEWAY_URL", "").rstrip("/"), os.environ.get("LAB_GATEWAY_TOKEN", "")
    if not url or not token:
        raise SystemExit("set LAB_GATEWAY_URL and LAB_GATEWAY_TOKEN first (ask the operator)")
    return url, token


def call(method: str, path: str, *, body: bytes | None = None, headers: dict | None = None, raw: bool = False):
    url, token = settings()
    request = urllib.request.Request(url + path, data=body, method=method, headers={"Authorization": f"Bearer {token}", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach the gateway: {exc.reason}") from None
    return data if raw else json.loads(data)


def make_bundle(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if path.is_file() and not (set(relative.parts) & SKIP_DIRS) and path.suffix != ".pyc" and not path.is_symlink():
                archive.write(path, relative.as_posix())
    data = buffer.getvalue()
    if len(data) > MAX_BUNDLE:
        raise SystemExit(f"bundle is {len(data) // 2**20} MiB; the limit is {MAX_BUNDLE // 2**20} MiB (keep large inputs out of it)")
    return data


def safe_extract(data: bytes, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            target = (destination / Path(*parts)).resolve() if parts else root
            if ".." in parts or not str(target).startswith(str(root)):
                raise SystemExit(f"unsafe path in result: {info.filename!r}")
        archive.extractall(destination)
        return len(archive.infolist())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("directory", type=Path)
    submit.add_argument("--entry", required=True, help="relative path of the .py file inside the directory")
    submit.add_argument("--ram", type=float, required=True, help="GiB the program needs (be honest; it is checked)")
    submit.add_argument("--time", type=int, required=True, help="time limit in minutes (the run is stopped then)")
    submit.add_argument("--threads", type=int, default=1)
    submit.add_argument("--name", default="job")
    submit.add_argument("--key", help="idempotency key: resubmitting with the same key returns the same job")
    submit.add_argument("--args", nargs=argparse.REMAINDER, default=[], help="arguments for the program (last option)")
    for name in ("status", "cancel", "wait", "fetch"):
        command = sub.add_parser(name)
        command.add_argument("job_id")
        if name == "wait":
            command.add_argument("--interval", type=float, default=20)
        if name == "fetch":
            command.add_argument("--out", type=Path, required=True)
    sub.add_parser("list")
    sub.add_parser("pool")
    args = parser.parse_args(argv)
    if args.command == "submit":
        headers = {"Content-Type": "application/zip", "X-Entry": args.entry, "X-Name": args.name, "X-Ram-Gb": str(args.ram),
                   "X-Time-Limit-Min": str(args.time), "X-Threads": str(args.threads), "X-Args": json.dumps(args.args)}
        if args.key:
            headers["X-Idempotency-Key"] = args.key
        print(json.dumps(call("POST", "/v1/jobs", body=make_bundle(args.directory), headers=headers), indent=1, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(call("GET", f"/v1/jobs/{args.job_id}"), indent=1, ensure_ascii=False))
    elif args.command == "list":
        for job in call("GET", "/v1/jobs")["jobs"]:
            print(job["id"], job["state"], job["name"], job["machine"] or "-", job["message"] or "")
    elif args.command == "pool":
        print(json.dumps(call("GET", "/v1/pool"), indent=1))
    elif args.command == "cancel":
        print(json.dumps(call("POST", f"/v1/jobs/{args.job_id}/cancel"), indent=1, ensure_ascii=False))
    elif args.command == "wait":
        while True:
            job = call("GET", f"/v1/jobs/{args.job_id}")
            print(time.strftime("%H:%M:%S"), job["state"], job["machine"] or "-", job["message"] or "", flush=True)
            if job["state"] in TERMINAL:
                return 0 if job["state"] == "COMPLETED" else 1
            time.sleep(args.interval)
    elif args.command == "fetch":
        count = safe_extract(call("GET", f"/v1/jobs/{args.job_id}/result", raw=True), args.out)
        print(f"extracted {count} entries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
