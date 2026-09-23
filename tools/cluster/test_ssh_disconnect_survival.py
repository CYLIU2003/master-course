"""One-shot, solver-free Windows worker survival test after an SSH client dies.

This tests only OS/OpenSSH process lifetime, not scheduler reconciliation or
research-job acceptance. A unique marker remains under the worker workspace.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import read_config
from bff.services.cluster.transport import ssh_command


def _remote_powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}"


def _python_launcher(marker: str, receipt: str, nonce: str) -> str:
    # The child uses the same explicit breakaway flags as the actual runner.
    child = (
        "from pathlib import Path; import time; "
        "time.sleep(6); "
        f"Path({json.dumps(marker)}).write_text({json.dumps(nonce)}, encoding='utf-8')"
    )
    return "\n".join((
        "import json, subprocess, sys, time",
        "from pathlib import Path",
        f"folder = Path({json.dumps(str(Path(marker).parent))})",
        "folder.mkdir(parents=True, exist_ok=True)",
        "flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB)",
        f"child = {json.dumps(child)}",
        "process = subprocess.Popen([sys.executable, '-c', child], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)",
        f"Path({json.dumps(receipt)}).write_text(json.dumps({{'pid': process.pid, 'started': True}}), encoding='utf-8')",
        "print('MC_FAULT_LAUNCHED', flush=True)",
        "time.sleep(25)",
    ))


def run(worker_id: str, output: Path) -> dict:
    worker = next((row for row in read_config().workers if row.id == worker_id), None)
    if worker is None or worker.transport != "ssh" or worker.shell != "powershell":
        raise ValueError("Select a registered Windows SSH worker")
    nonce = uuid4().hex
    remote_dir = str(Path(worker.workspace) / ".fault-tests" / nonce).replace("\\", "/")
    marker = remote_dir + "/survived.txt"
    receipt = remote_dir + "/launch.json"
    python_code = _python_launcher(marker, receipt, nonce)
    code_b64 = base64.b64encode(python_code.encode("utf-8")).decode("ascii")
    launcher = remote_dir + "/launcher.py"
    launch_script = (
        f"$code=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{code_b64}')); "
        f"New-Item -ItemType Directory -Path '{remote_dir}' -Force | Out-Null; "
        f"Set-Content -LiteralPath '{launcher}' -Value $code -Encoding UTF8; "
        f"& '{worker.python}' '{launcher}'; exit $LASTEXITCODE"
    )
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    with (output / "launch_stdout.log").open("wb") as stdout, (output / "launch_stderr.log").open("wb") as stderr:
        connection = subprocess.Popen(
            ssh_command(worker, _remote_powershell(launch_script)),
            stdout=stdout, stderr=stderr,
        )
        deadline = time.monotonic() + 15
        launched = False
        while time.monotonic() < deadline and connection.poll() is None:
            stdout.flush()
            if b"MC_FAULT_LAUNCHED" in (output / "launch_stdout.log").read_bytes():
                launched = True
                break
            time.sleep(0.2)
        connection.kill()
        connection.wait(timeout=10)
    if launched:
        time.sleep(8)
    check_script = (
        f"if (Test-Path -LiteralPath '{marker}') {{ "
        f"Get-Content -LiteralPath '{marker}'; exit 0 }} "
        f"elseif (Test-Path -LiteralPath '{receipt}') {{ Write-Output 'CHILD_NOT_COMPLETED'; exit 2 }} "
        "else { Write-Output 'NO_LAUNCH_RECEIPT'; exit 3 }"
    )
    checked = subprocess.run(
        ssh_command(worker, _remote_powershell(check_script)),
        capture_output=True, timeout=15,
    )
    observed = checked.stdout.decode("utf-8", errors="replace").strip()
    result = {
        "schema_version": "ssh_disconnect_survival_v1",
        "worker_id": worker_id,
        "started_at_utc": started,
        "ssh_client_killed": True,
        "launch_confirmed_before_disconnect": launched,
        "marker_matched": launched and checked.returncode == 0 and observed == nonce,
        "remote_check_exit_code": checked.returncode,
        "observed_status": "SURVIVED" if observed == nonce else observed[-200:],
        "remote_test_directory": remote_dir,
        "scope": "SSH disconnect and detached non-solver child survival only",
        "not_tested": "controller restart, scheduler reconciliation, worker reboot, Gurobi, research solve",
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.worker, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["marker_matched"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
