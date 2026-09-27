"""Durable, non-executing intake for laboratory calculation requests.

This ledger is deliberately separate from the solver queue. Receiving a request
does not authorize a license, execute uploaded code, or create a solver attempt.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    size: int = Field(ge=0, le=2**40)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if any(c in value for c in '/\\\r\n:') or value in {".", ".."}:
            raise ValueError("Attachment name must be a basename")
        return value


class LabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["lab_request_v1"] = "lab_request_v1"
    request_id: UUID
    requester: str = Field(min_length=1, max_length=100)
    project: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    workload: Literal["thesis_scenario", "python", "other"]
    solver: Literal["gurobi", "no_gurobi", "other"]
    memory_gib: float = Field(gt=0, le=256, allow_inf_nan=False)
    threads: int = Field(ge=1, le=128)
    time_limit_minutes: int = Field(ge=1, le=10080)
    license_basis: str = Field(min_length=1, max_length=1000)
    instructions: str = Field(min_length=1, max_length=3000)
    scenario_id: str = Field(default="", max_length=100)
    attachments: list[Attachment] = Field(default_factory=list, max_length=40)


def receive(root: Path, payload: dict) -> dict:
    request = LabRequest.model_validate(payload).model_dump(mode="json")
    body = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(body.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "requests.sqlite3", timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, checksum TEXT NOT NULL, received TEXT NOT NULL, body TEXT NOT NULL)")
        # Lock before reading identity; otherwise concurrent, different bodies
        # could both report success although INSERT OR IGNORE stored only one.
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT checksum FROM requests WHERE id=?", (request["request_id"],)).fetchone()
        if existing and existing[0] != checksum:
            raise ValueError("同じ依頼IDで内容が異なります。原本を確認してください。")
        db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?)", (request["request_id"], checksum,
                   datetime.now(timezone.utc).isoformat(), body))
    return {"request_id": request["request_id"], "state": "REVIEW_REQUIRED", "sha256": checksum,
            "reused": existing is not None, "solver_submitted": False}


def requests(root: Path) -> list[dict]:
    path = root / "requests.sqlite3"
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        return [{"request": json.loads(body), "sha256": checksum, "received_at": received,
                 "state": "REVIEW_REQUIRED", "solver_submitted": False}
                for checksum, received, body in db.execute("SELECT checksum, received, body FROM requests ORDER BY received DESC")]


REPORT_FILES = {"report.md", "weekly_summary.csv", "daily_summary.csv", "experiment_index.csv", "monthly_cost.png", "comparison.json", "manifest.json"}


def report_file(report_root: Path, revision: str, name: str, expected_sha: str | None = None) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", revision) or name not in REPORT_FILES:
        raise ValueError("Unknown report artifact")
    directory = report_root / "revisions" / revision
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if expected_sha is not None:
        comparison = (directory / "comparison.json").read_bytes()
        if hashlib.sha256(comparison).hexdigest() != manifest.get("comparison.json"):
            raise ValueError("Report artifact hash mismatch")
        if json.loads(comparison)["source_sha"] != expected_sha:
            raise ValueError("Report solver version differs from controller")
    data = (directory / name).read_bytes()
    if name != "manifest.json" and hashlib.sha256(data).hexdigest() != manifest.get(name):
        raise ValueError("Report artifact hash mismatch")
    return data


def view(root: Path, settings: dict) -> dict:
    config_path = root / "lab-config.json"
    config = json.loads(config_path.read_bytes()) if config_path.exists() else {}
    port = config.get("inventory_port")
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError("Invalid inventory port")
    result = {"schema_version": "lab_console_v1", "controller_port": settings["port"],
              "solver_git_sha": settings["git_sha"], "inventory_port": port,
              "requests": requests(root / "lab-intake"), "report": None}
    if config.get("report_root"):
        report_root = Path(config["report_root"])
        latest = json.loads((report_root / "latest.json").read_bytes())
        report = json.loads(report_file(report_root, latest["revision"], "comparison.json", settings["git_sha"]))
        if report["source_sha"] != settings["git_sha"]:
            raise ValueError("Report solver version differs from controller")
        result["report"] = {"revision": latest["revision"], "parent": report["parent"],
                            "observed_at_utc": latest["observed_at_utc"],
                            "cases": [{k: c[k] for k in ("week", "state", "included", "original_state", "total_cost_jpy") if k in c} for c in report["cases"]],
                            "included": len(report["rows"]), "declared": len(report["cases"]),
                            "complete": report["complete"]}
    return result
