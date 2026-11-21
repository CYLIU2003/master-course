"""HTTP API for lab members. Bearer token per person; members see only their own jobs."""
from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .bundle import KEY, MAX_BUNDLE_BYTES, NAME, BundleError, validate_args, validate_bundle
from .store import ACTIVE, TERMINAL, JobStore, Tokens, now

JOB_PATH = re.compile(r"/v1/jobs/([0-9a-f]{12})(/cancel|/result)?")
MAX_QUEUED_PER_OWNER = 20
HIDDEN = {"bundle_path", "result_path", "idempotency_key"}


def public(job: dict) -> dict:
    view = {k: v for k, v in job.items() if k not in HIDDEN}
    view["result_available"] = bool(job["result_path"]) and Path(job["result_path"]).is_file()
    return view


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, store: JobStore, tokens: Tokens, dispatcher, data_dir: Path):
        super().__init__(address, Handler)
        self.store, self.tokens, self.dispatcher, self.data_dir = store, tokens, dispatcher, data_dir
        self.audit_lock = threading.Lock()
        (data_dir / "bundles").mkdir(parents=True, exist_ok=True)
        (data_dir / "results").mkdir(parents=True, exist_ok=True)

    def handle_error(self, request, client_address):  # a peer that connects and drops (port probe, browser, closed client) is not an error
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server: Gateway
    protocol_version = "HTTP/1.1"
    owner = "-"

    def log_message(self, *_args):  # request lines carry no secrets, but keep stderr quiet; audit() records what matters
        pass

    def audit(self, status: int) -> None:
        with self.server.audit_lock, (self.server.data_dir / "audit.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{now()} {self.owner} {self.command} {self.path.split('?')[0]} {status}\n")

    def reply(self, status: int, body, *, content_type: str = "application/json") -> None:
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.audit(status)  # before the reply, so a client that saw the answer can rely on the record
        self.send_response(status)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type == "application/json" else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def fail(self, status: int, message: str, *, close: bool = False) -> None:
        if close:
            self.close_connection = True
        self.reply(status, {"error": message})

    def authenticate(self) -> dict | None:
        header = self.headers.get("Authorization", "")
        who = self.server.tokens.authenticate(header[7:].strip() if header.startswith("Bearer ") else None)
        if who:
            self.owner = who["name"]
        return who

    def job_for(self, who: dict, job_id: str) -> dict | None:
        try:
            job = self.server.store.get(job_id)
        except KeyError:
            return None
        return job if who["admin"] or job["owner"] == who["name"] else None  # 404, not 403: do not reveal other members' ids

    # ---- routes
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/v1/health":
            return self.reply(200, {"ok": True})
        who = self.authenticate()
        if not who:
            return self.fail(401, "missing or invalid token")
        if path == "/v1/pool":
            probes, active = self.server.dispatcher.last_probe, self.server.store.rows(states=ACTIVE)
            borrowed = self.server.dispatcher.borrowed.copy()
            machines = [{"id": mid, "busy": any(j["machine"] == mid for j in active),
                         "free_ram_gb": probes.get(mid, {}).get("free_gb"), "total_ram_gb": probes.get(mid, {}).get("total_gb"),
                         "probed_at": probes.get(mid, {}).get("probed_at"), "borrowed": mid in borrowed}
                        for mid in [*self.server.dispatcher.machines, *borrowed]]
            return self.reply(200, {"machines": machines, "queued": len(self.server.store.rows(states={"QUEUED"}))})
        if path == "/v1/jobs":
            rows = self.server.store.rows(owner=None if who["admin"] else who["name"])
            return self.reply(200, {"jobs": [public(j) for j in rows]})
        match = JOB_PATH.fullmatch(path)
        job = self.job_for(who, match.group(1)) if match else None
        if not match or job is None:
            return self.fail(404, "not found")
        if match.group(2) == "/result":
            if not public(job)["result_available"]:
                return self.fail(409, f"no result is stored (state {job['state']})")
            data = Path(job["result_path"]).read_bytes()
            return self.reply(200, data, content_type="application/zip")
        return self.reply(200, public(job))

    def do_POST(self):
        path = self.path.split("?")[0]
        who = self.authenticate()
        if not who:
            return self.fail(401, "missing or invalid token", close=True)
        if path == "/v1/jobs":
            return self.submit(who)
        match = JOB_PATH.fullmatch(path)
        job = self.job_for(who, match.group(1)) if match and match.group(2) == "/cancel" else None
        if job is None:
            return self.fail(404, "not found", close=True)
        if job["state"] in TERMINAL:
            return self.fail(409, f"the job is already {job['state']}")
        return self.reply(200, public(self.server.dispatcher.cancel(job["id"])))

    def submit(self, who: dict) -> None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.fail(411, "Content-Length is required", close=True)
        if length <= 0 or length > MAX_BUNDLE_BYTES:
            return self.fail(413, f"bundle must be 1 byte to {MAX_BUNDLE_BYTES // 2**20} MiB", close=True)
        tmp = self.server.data_dir / "bundles" / f"_upload-{uuid.uuid4().hex}.zip"
        try:
            with tmp.open("wb") as handle:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        return self.fail(400, "upload ended early", close=True)
                    handle.write(chunk)
                    remaining -= len(chunk)
            spec = self.parse_spec()
            key = spec["idempotency_key"]
            if key and (existing := self.server.store.find_idempotent(who["name"], key)):
                return self.reply(200, {**public(existing), "reused": True})
            active = [j for j in self.server.store.rows(owner=who["name"]) if j["state"] not in TERMINAL]
            if len(active) >= MAX_QUEUED_PER_OWNER:
                return self.fail(429, f"at most {MAX_QUEUED_PER_OWNER} unfinished jobs per member")
            validate_bundle(tmp, spec["entry"])
            job_id = uuid.uuid4().hex[:12]
            bundle = self.server.data_dir / "bundles" / f"{job_id}.zip"
            shutil.move(str(tmp), bundle)
            job = self.server.store.create(id=job_id, owner=who["name"], name=spec["name"], entry=spec["entry"], args=spec["args"],
                                           ram_gb=spec["ram_gb"], threads=spec["threads"], time_limit_min=spec["time_limit_min"],
                                           idempotency_key=key, bundle_path=str(bundle), bundle_bytes=length)
            return self.reply(201, public(job))
        except (BundleError, ValueError) as exc:
            return self.fail(400, str(exc))
        finally:
            tmp.unlink(missing_ok=True)

    def parse_spec(self) -> dict:
        header = self.headers.get
        try:
            args = json.loads(header("X-Args", "[]"))
            spec = {"entry": header("X-Entry", ""), "name": header("X-Name", "job"), "args": validate_args(args),
                    "ram_gb": float(header("X-Ram-Gb", "")), "time_limit_min": int(header("X-Time-Limit-Min", "")),
                    "threads": int(header("X-Threads", "1")), "idempotency_key": header("X-Idempotency-Key") or None}
        except (TypeError, ValueError) as exc:
            raise ValueError("X-Entry, X-Ram-Gb and X-Time-Limit-Min are required; X-Args must be a JSON list") from exc
        if not NAME.fullmatch(spec["name"]):
            raise ValueError("X-Name: up to 60 letters, digits, space, _ or -")
        if spec["idempotency_key"] and not KEY.fullmatch(spec["idempotency_key"]):
            raise ValueError("X-Idempotency-Key: up to 64 letters, digits, _ or -")
        if not 0.5 <= spec["ram_gb"] <= 64:
            raise ValueError("X-Ram-Gb must be between 0.5 and 64")
        if not 1 <= spec["time_limit_min"] <= 720:
            raise ValueError("X-Time-Limit-Min must be between 1 and 720")
        if not 1 <= spec["threads"] <= 32:
            raise ValueError("X-Threads must be between 1 and 32")
        return spec
