"""Read-only fleet monitor: every lab PC, the thesis queue and the lab gateway on one local page.

    python -m tools.fleet_monitor.server --port 8897            # then open http://127.0.0.1:8897/

It only reads: the cluster ledger, the thesis queue SQLite (read-only URI, short queries), the lab gateway's
SQLite/config/claims, `tailscale status --json`, and a fixed PowerShell probe over SSH (BatchMode, strict host
keys). It never changes a PC, a job or a controller. Binds to 127.0.0.1 by default because the page shows hosts.
"""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SSH = "C:/Windows/System32/OpenSSH/ssh.exe"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED", "LOST", "REJECTED", "TIMEOUT"}
PROBE = r"""$ErrorActionPreference='SilentlyContinue';$ProgressPreference='SilentlyContinue'
$c=@(Get-CimInstance Win32_Processor); $o=Get-CimInstance Win32_OperatingSystem; $d=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$b=@(Get-CimInstance Win32_Battery)
$py=@(Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like 'C:\mc-*' })
[Console]::Write((@{cpu=($c[0].Name).Trim();cores=($c|Measure-Object NumberOfCores -Sum).Sum;threads=($c|Measure-Object NumberOfLogicalProcessors -Sum).Sum;
cpu_load=($c|Measure-Object LoadPercentage -Average).Average;ram_total=[math]::Round($o.TotalVisibleMemorySize/1MB,1);
ram_free=[math]::Round($o.FreePhysicalMemory/1MB,1);disk_free=[math]::Round($d.FreeSpace/1GB,1);disk_total=[math]::Round($d.Size/1GB,1);
os=$o.Caption;boot=$o.LastBootUpTime.ToUniversalTime().ToString('o');has_battery=($b.Count -gt 0);
battery_pct=$(if($b.Count){$b[0].EstimatedChargeRemaining}else{$null});on_ac=$(if($b.Count){$b[0].BatteryStatus -eq 2}else{$true});
work_python=$py.Count;hostname=$env:COMPUTERNAME} | ConvertTo-Json -Compress))"""
PROBE_ENCODED = base64.b64encode(PROBE.encode("utf-16le")).decode("ascii")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def ro_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    return db


class Collector:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.probes: dict[str, dict] = {}
        self.state: dict = {"collected_at": None}
        self.stop = threading.Event()

    # ---- sources
    def ledger(self) -> list[dict]:
        from bff.services.cluster.contracts import read_config
        return [{"id": w.id, "host": w.host, "ssh_user": w.ssh_user, "transport": w.transport, "enabled": w.enabled,
                 "gurobi": w.gurobi, "ram_gb": w.ram_gb} for w in read_config().workers]

    def tailscale(self) -> dict[str, dict]:
        try:
            out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, timeout=15).stdout
            peers = json.loads(out.decode("utf-8", "replace")).get("Peer", {}).values()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {}
        result = {}
        for peer in peers:
            for ip in peer.get("TailscaleIPs") or []:
                result[ip] = {"online": bool(peer.get("Online")), "last_seen": peer.get("LastSeen"),
                              "hostname": peer.get("HostName")}
        return result

    def thesis(self) -> dict:
        """Workers, running/queued jobs and recent ends from each configured thesis queue (read-only)."""
        workers, jobs, counts, recent, errors = {}, [], {}, [], []
        for path in self.args.thesis_db:
            path = Path(path)
            if not path.exists():
                errors.append(f"{path} がありません")
                continue
            try:
                with ro_db(path) as db:
                    for row in db.execute("SELECT id, mode, observation, updated_at FROM workers"):
                        observation = json.loads(row["observation"] or "{}")
                        workers[row["id"]] = {"mode": row["mode"], "observation": observation, "queue": path.parent.parent.name}
                    for row in db.execute("SELECT state, count(*) n FROM jobs GROUP BY state"):
                        counts[row["state"]] = counts.get(row["state"], 0) + row["n"]
                    select = ("SELECT j.id, j.state, j.worker_id, j.created_at, j.updated_at, j.error,"
                              " json_extract(j.manifest,'$.batch_id') batch, json_extract(j.manifest,'$.task_id') task,"
                              " json_extract(j.manifest,'$.minimum_ram_gb') ram, p.percent, p.stage, p.message progress"
                              " FROM jobs j LEFT JOIN job_progress p ON p.job_id=j.id")
                    for row in db.execute(select + " WHERE j.state NOT IN (%s) ORDER BY j.created_at" % ",".join("?" * len(TERMINAL)), tuple(TERMINAL)):
                        jobs.append(dict(row))
                    for row in db.execute(select + " WHERE j.state IN ('COMPLETED','FAILED','LOST','BLOCKED') ORDER BY j.updated_at DESC LIMIT 12"):
                        recent.append(dict(row))
            except sqlite3.Error as exc:
                errors.append(f"{path.parent.parent.name}: {exc}")
        return {"workers": workers, "jobs": jobs, "counts": counts, "recent": recent, "errors": errors}

    def gateway(self) -> dict:
        directory = Path(self.args.gateway_dir)
        config = read_json(directory / "config.json", {})
        claims = read_json(directory / "overflow_claims.json", {})
        jobs, counts, recent, error = [], {}, [], None
        try:
            with ro_db(directory / "jobs.sqlite3") as db:
                for row in db.execute("SELECT state, count(*) n FROM jobs GROUP BY state"):
                    counts[row["state"]] = row["n"]
                cols = "id, owner, name, state, machine, ram_gb, time_limit_min, created_at, started_at, finished_at, message"
                jobs = [dict(r) for r in db.execute(f"SELECT {cols} FROM jobs WHERE state IN ('QUEUED','STAGING','RUNNING','COLLECTING') ORDER BY created_at")]
                recent = [dict(r) for r in db.execute(f"SELECT {cols} FROM jobs WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 10")]
        except sqlite3.Error as exc:
            error = str(exc)
        try:
            urllib.request.urlopen(self.args.gateway_url.rstrip("/") + "/v1/pool", timeout=4)
            alive = True
        except urllib.error.HTTPError as exc:
            alive = exc.code == 401  # answers, token required: running
        except (urllib.error.URLError, OSError):
            alive = False
        return {"alive": alive, "pool": config.get("machines", []), "overflow": config.get("thesis_overflow"),
                "claims": claims, "jobs": jobs, "counts": counts, "recent": recent, "error": error}

    def probe(self, machine: dict) -> tuple[str, dict]:
        command = [SSH, "-n", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
                   f"{machine['ssh_user']}@{machine['host']}", "powershell -NoProfile -NonInteractive -EncodedCommand " + PROBE_ENCODED]
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
            text = result.stdout.decode("utf-8", "replace")
            data = json.loads(text[text.rindex('{"'):].strip())  # skip any PowerShell progress (CLIXML) noise
            data.update(ok=True, latency_ms=round((time.monotonic() - started) * 1000), probed_at=utcnow())
            return machine["id"], data
        except subprocess.TimeoutExpired:
            return machine["id"], {"ok": False, "error": "SSHの応答なし（60秒）", "probed_at": utcnow()}
        except (OSError, ValueError, IndexError):
            return machine["id"], {"ok": False, "error": "SSH接続または応答の読み取りに失敗", "probed_at": utcnow()}

    # ---- loops
    def probe_loop(self) -> None:
        while not self.stop.is_set():
            try:
                targets = [m for m in self.ledger() if m["transport"] == "ssh" and m["host"] and m["ssh_user"]]
                with ThreadPoolExecutor(6) as pool:
                    for machine_id, data in pool.map(self.probe, targets):
                        with self.lock:
                            self.probes[machine_id] = data
            except Exception as exc:  # keep probing after a transient failure
                print("probe loop:", exc, file=sys.stderr)
            self.stop.wait(self.args.probe_seconds)

    def state_loop(self) -> None:
        while not self.stop.is_set():
            try:
                state = self.build()
                with self.lock:
                    self.state = state
            except Exception as exc:
                print("state loop:", exc, file=sys.stderr)
            self.stop.wait(self.args.refresh_seconds)

    # ---- one snapshot for the page
    def build(self) -> dict:
        ledger, tailnet, thesis, gateway = self.ledger(), self.tailscale(), self.thesis(), self.gateway()
        with self.lock:
            probes = dict(self.probes)
        ids = [m["id"] for m in ledger] + [w for w in thesis["workers"] if w not in {m["id"] for m in ledger}]
        by_id = {m["id"]: m for m in ledger}
        machines, alerts = [], []
        for machine_id in ids:
            m = by_id.get(machine_id, {"id": machine_id, "host": None, "ssh_user": None, "transport": "ssh", "enabled": None})
            tw = thesis["workers"].get(machine_id)
            probe = probes.get(machine_id)
            capability = (tw or {}).get("observation", {}).get("capability") or {}
            running_thesis = any(j["worker_id"] == machine_id and j["state"] != "QUEUED" for j in thesis["jobs"])
            if machine_id in gateway["claims"]:
                role = "borrowed"
            elif running_thesis:
                role = "thesis"
            elif machine_id in gateway["pool"]:
                role = "lab"
            elif tw and tw["mode"] in (None, "", "active", "draining"):
                role = "thesis"  # mode NULL means the controller's config default (enabled)
            else:
                role = "none"
            ts = tailnet.get(m["host"] or "") if m.get("host") else None
            thesis_jobs = [j for j in thesis["jobs"] if j["worker_id"] == machine_id and j["state"] != "QUEUED"]
            lab_jobs = [j for j in gateway["jobs"] if j["machine"] == machine_id]
            spec = probe if probe and probe.get("ok") else {
                "cpu": capability.get("cpu_model"), "cores": capability.get("cpu_physical_cores"), "threads": capability.get("cpu_count"),
                "cpu_load": capability.get("cpu_percent"), "ram_total": capability.get("installed_ram_gb") or capability.get("ram_gb"),
                "ram_free": capability.get("ram_free_gb"), "disk_free": capability.get("disk_free_gb"), "source": "thesis_controller"}
            row = {"id": machine_id, "host": m.get("host"), "user": m.get("ssh_user"), "transport": m.get("transport"), "role": role,
                   "thesis_mode": (tw or {}).get("mode"), "queue": (tw or {}).get("queue"),
                   "tailscale": ts, "probe_ok": bool(probe and probe.get("ok")), "probe_error": (probe or {}).get("error"),
                   "probed_at": (probe or {}).get("probed_at"), "spec": spec, "thesis_jobs": thesis_jobs, "lab_jobs": lab_jobs}
            machines.append(row)
            name = machine_id
            if m.get("transport") == "local":
                continue
            if ts is not None and not ts["online"] and role != "none":
                alerts.append({"level": "critical", "machine": name, "text": "Tailscaleがオフライン"})
            elif probe and not probe.get("ok") and role != "none":
                alerts.append({"level": "serious", "machine": name, "text": probe.get("error")})
            s = probe if probe and probe.get("ok") else {}
            if s.get("has_battery") and s.get("on_ac") is False:
                alerts.append({"level": "critical", "machine": name, "text": f"バッテリー駆動中（残り{s.get('battery_pct')}%）。電源が抜けています"})
            elif s.get("has_battery") and (s.get("battery_pct") or 0) <= 5:
                alerts.append({"level": "warning", "machine": name, "text": f"バッテリー残量{s.get('battery_pct')}%（電源が抜けると即停止）"})
            if s.get("disk_free") is not None and s["disk_free"] < 20:
                alerts.append({"level": "warning", "machine": name, "text": f"C:の空きが{s['disk_free']} GB"})
            if s.get("ram_free") is not None and s["ram_free"] < 1.5 and (thesis_jobs or lab_jobs):
                alerts.append({"level": "warning", "machine": name, "text": f"空きRAMが{s['ram_free']} GB（計算中）"})
        if thesis["counts"].get("LOST"):
            alerts.append({"level": "serious", "machine": "修論キュー", "text": f"LOSTのジョブが{thesis['counts']['LOST']}件（照合待ち）"})
        for error in thesis["errors"]:
            alerts.append({"level": "serious", "machine": "修論キュー", "text": error})
        if not gateway["alive"]:
            alerts.append({"level": "serious", "machine": "後輩用ゲートウェイ", "text": "応答なし（停止中）"})
        order = {"critical": 0, "serious": 1, "warning": 2}
        alerts.sort(key=lambda a: order[a["level"]])
        return {"collected_at": utcnow(), "machines": machines, "alerts": alerts,
                "thesis": {k: thesis[k] for k in ("jobs", "counts", "recent", "errors")}, "gateway": gateway,
                "probe_seconds": self.args.probe_seconds, "refresh_seconds": self.args.refresh_seconds}


class Handler(BaseHTTPRequestHandler):
    collector: Collector

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body, kind = (Path(__file__).with_name("index.html")).read_bytes(), "text/html; charset=utf-8"
        elif self.path == "/api/state":
            with self.collector.lock:
                body = json.dumps(self.collector.state, ensure_ascii=False).encode("utf-8")
            kind = "application/json; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_error(self, *_args):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8897)
    parser.add_argument("--thesis-db", action="append",
                        default=None, help="thesis queue cluster.sqlite3 (repeatable)")
    parser.add_argument("--gateway-dir", default=str(ROOT / "output" / "lab-gateway"))
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8899")
    parser.add_argument("--probe-seconds", type=float, default=60)
    parser.add_argument("--refresh-seconds", type=float, default=15)
    args = parser.parse_args(argv)
    args.thesis_db = args.thesis_db or [str(ROOT / "output" / "monthly_latest_20260925" / "controller" / "queue" / "cluster.sqlite3")]
    collector = Collector(args)
    Handler.collector = collector
    threading.Thread(target=collector.probe_loop, daemon=True).start()
    threading.Thread(target=collector.state_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fleet monitor on http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
