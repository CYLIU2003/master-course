"""Local browser controls for the existing frozen-controller supervisor.

Runs independently of the solver BFF so its stop does not remove recovery
controls. Only the registered controller's browser origin may change state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.store import ControllerLock
from tools.research import controller_supervisor as supervisor
from tools.research.weekly_operator import load_operation
from tools.research import lab_console


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)


class Controls:
    def __init__(self, operation_path: Path):
        self.operation_path = operation_path.resolve()
        self.operation, self.settings, _ = load_operation(self.operation_path)
        self.root = Path(self.settings["queue"]) / "controller-supervision"
        if not (Path(self.settings["queue"]) / "cluster.sqlite3").is_file():
            raise ValueError("Existing queue is required")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.json"
        self.token = secrets.token_urlsafe(32)
        self.last_tick: str | None = None
        self.last_error: str | None = None
        self.stop = threading.Event()

    def read(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_bytes())
        return {"binding": supervisor.binding(self.operation, self.settings),
                "enabled": False, "status": "DISABLED", "starts": 0}

    def view(self) -> dict:
        state = self.read()
        matches = state["binding"] == supervisor.binding(self.operation, self.settings)
        return {"schema_version": "supervisor_ui_v1", "controller_port": self.settings["port"],
                "solver_git_sha": self.settings["git_sha"], "enabled": bool(state["enabled"]),
                "status": state["status"] if matches else "BLOCKED_BINDING_CHANGED",
                "binding_matches": matches, "starts": state["starts"], "max_starts": supervisor.MAX_STARTS,
                "next_start_at": state.get("next_start_at"), "process": state.get("process"),
                "observed_at_utc": state.get("observed_at_utc"), "service_observed_at_utc": utc_now(),
                "last_tick_utc": self.last_tick, "last_error": self.last_error}

    def action(self, action: str) -> dict:
        if action not in {"enable", "disable"}:
            raise ValueError("Unsupported action")
        # Reuse CLI policy and its OS lock. Never expose paths/commands from HTTP.
        result = subprocess.run([self.settings["python"], "-X", "utf8", str(Path(supervisor.__file__)),
                                 action, "--operation", str(self.operation_path)],
                                capture_output=True, timeout=20, check=False)
        if result.returncode:
            raise ValueError("操作を適用できません。状態不明・設定不一致・別操作中の可能性があります。詳細状態を確認してください。")
        return self.view()

    def supervise(self) -> None:
        while not self.stop.is_set():
            lock = None
            try:
                lock = ControllerLock(self.root)
                supervisor.tick(self.read(), self.operation, self.settings, self.path)
                self.last_error = None
            except Exception as exc:
                # Service boundary: show the failure to the operator and retain
                # all records. Never convert an unexpected failure into a start.
                self.last_error = type(exc).__name__
            finally:
                if lock:
                    lock.close()
                self.last_tick = utc_now()
            self.stop.wait(30)


def handler_for(controls: Controls):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never log request headers or the session nonce.

        def allowed(self, *, write: bool = False, preflight: bool = False) -> bool:
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            expected_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            try:
                origin_ok = local_origin(origin)
                if write:
                    origin_ok = origin_ok and urlsplit(origin).port == controls.settings["port"]
            except ValueError:
                origin_ok = False
            token_ok = preflight or secrets.compare_digest(self.headers.get("X-Supervisor-Token", ""), controls.token)
            return self.client_address[0] == "127.0.0.1" and host in expected_hosts and origin_ok and token_ok

        def send_json(self, code: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            origin = self.headers.get("Origin", "")
            try:
                if local_origin(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
            except ValueError:
                pass
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            if not self.allowed(write=self.headers.get("Access-Control-Request-Method") == "POST", preflight=True):
                self.send_json(403, {"error": "許可されていない操作元です"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Supervisor-Token")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            if not self.allowed():
                self.send_json(403, {"error": "許可されていない操作元です"})
                return
            if self.path == "/lab":
                try:
                    self.send_json(200, lab_console.view(controls.root, controls.settings))
                except (OSError, ValueError, KeyError, sqlite3.Error):
                    self.send_json(503, {"error": "受付・結果の記録を確認できません"})
                return
            if self.path.startswith("/lab/report/"):
                try:
                    _, _, _, revision, name = self.path.split("/")
                    config = json.loads((controls.root / "lab-config.json").read_bytes())
                    data = lab_console.report_file(Path(config["report_root"]), revision, name, controls.settings["git_sha"])
                    self.send_response(200)
                    self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                    self.send_header("Vary", "Origin")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Type", "image/png" if name.endswith(".png") else "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (OSError, ValueError, KeyError):
                    self.send_json(409, {"error": "結果ファイルの整合性を確認できません"})
                return
            if self.path != "/status":
                self.send_json(404, {"error": "Not found"})
                return
            try:
                self.send_json(200, controls.view())
            except (OSError, ValueError, KeyError) as exc:
                self.send_json(503, {"error": "状態記録を確認できません", "error_type": type(exc).__name__})

        def do_POST(self):
            if not self.allowed(write=True):
                self.send_json(403, {"error": "この管理サーバーの画面から操作してください"})
                return
            if self.path == "/lab/requests":
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if self.headers.get("Transfer-Encoding") or not 0 < size <= 65536:
                        raise ValueError("Invalid request size")
                    self.connection.settimeout(5)
                    payload = json.loads(self.rfile.read(size))
                    result = lab_console.receive(controls.root / "lab-intake", payload)
                    self.send_json(200, result)
                except (ValueError, OSError, sqlite3.Error):
                    self.send_json(400, {"error": "依頼を保存できません。同一IDの内容・必須項目・データ容量を確認してください。"})
                return
            if self.path not in {"/enable", "/disable"}:
                self.send_json(404, {"error": "Not found"})
                return
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
                self.send_json(400, {"error": "この操作はリクエストデータを受け付けません"})
                return
            try:
                self.send_json(200, controls.action(self.path[1:]))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                self.send_json(409, {"error": str(exc) if isinstance(exc, ValueError) else "操作が完了しませんでした。状態を再取得してください。"})
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, required=True)
    args = parser.parse_args()
    controls = Controls(args.operation)
    # Separate from the tick/CLI lock, held for the service's entire lifetime.
    service_lock = ControllerLock(controls.root / "ui-service")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(controls))
    thread = threading.Thread(target=controls.supervise, daemon=True)
    try:
        discovery = {"schema_version": "supervisor_discovery_v1", "controller_port": controls.settings["port"],
                     "solver_git_sha": controls.settings["git_sha"], "control_origin": f"http://127.0.0.1:{server.server_port}",
                     "token": controls.token}
        supervisor.save(Path(controls.settings["frontend"]) / f"supervisor-control-{controls.settings['port']}.json", discovery)
        thread.start()
        server.serve_forever(poll_interval=.5)
    finally:
        controls.stop.set()
        server.server_close()
        service_lock.close()


if __name__ == "__main__":
    main()
