"""Scenario-owned period plans, separate from frozen optimization inputs.

SQLite serializes edits and revision checks. Only the local operator may bind a
campaign directory; HTTP clients cannot request arbitrary filesystem reads.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import re
from uuid import uuid4
import zipfile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bff.store import scenario_store
from bff.store.output_paths import scenarios_root


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=120)
    start: date
    days: int = Field(default=7, ge=1, le=366)


class PeriodEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    periods: list[Period] = Field(max_length=366)

    @model_validator(mode="after")
    def unique_periods(self):
        if len({p.id for p in self.periods}) != len(self.periods):
            raise ValueError("Period IDs must be unique")
        if len({(p.start, p.days) for p in self.periods}) != len(self.periods):
            raise ValueError("Duplicate periods are not separate experiments")
        return self


def _connection():
    path = scenarios_root().parent / "scenario_periods.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS plans(scenario TEXT PRIMARY KEY, revision INTEGER NOT NULL, periods TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS attempts(scenario TEXT NOT NULL, period TEXT NOT NULL, id TEXT PRIMARY KEY, campaign TEXT NOT NULL, week TEXT NOT NULL, UNIQUE(scenario,period,campaign,week))")
    db.commit()
    return db


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def _attempt(row: sqlite3.Row) -> dict:
    result = {"id": row["id"], "state": "UNKNOWN", "prepared": False, "verified": False}
    campaign = Path(row["campaign"])
    try:
        snapshot = _read(campaign / "operations/status.json")
        observed = snapshot["observed_at_utc"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(observed)).total_seconds()
        case = next((c for c in snapshot["cases"] if c["week"] == row["week"]), None)
        result.update(observed_at=observed, stale=age > 120, source_git_sha=snapshot.get("solver_git_sha"))
        if case:
            result.update({k: case.get(k) for k in ("state", "prepared", "verified", "job_id", "worker", "error", "placement")})
            result["last_recorded_state"] = case["state"]
            terminal = case["state"] in {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED", "VERIFIED"}
            if not terminal and (age > 120 or age < -30 or snapshot.get("connection") != "CONNECTED"):
                result["state"] = "UNKNOWN"
                result["verified"] = False
            job = result.get("job_id")
            if result["state"] == "FAILED" and job and not result.get("error"):
                # Read only a collected attempt's small state entry; never
                # extract a ZIP or accept a browser-supplied path.
                if isinstance(job, str) and re.fullmatch(r"[A-Za-z0-9-]{1,80}", job):
                    archive = campaign / row["week"] / "state" / f"{job}.zip"
                    if archive.is_file():
                        with zipfile.ZipFile(archive) as bundle:
                            entry = bundle.getinfo("state.json")
                            if entry.file_size <= 1_000_000:
                                state = json.loads(bundle.read(entry))
                                if state.get("id") == job:
                                    nested = state.get("result") or {}
                                    result["error"] = nested.get("error") or nested.get("message")
        else:
            result["state"] = "NOT_STARTED"
        # Native failure details can be nested, whereas the parent error is null.
        failure = campaign / row["week"] / "operations" / "failure_detail.json"
        if failure.is_file():
            result["failure_detail"] = _read(failure)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        result["error"] = f"Progress unavailable: {type(exc).__name__}"
    return result


def get_periods(scenario_id: str) -> dict:
    scenario_store.get_desktop_context(scenario_id)
    with closing(_connection()) as db:
        row = db.execute("SELECT * FROM plans WHERE scenario=?", (scenario_id,)).fetchone()
        attempts = db.execute("SELECT * FROM attempts WHERE scenario=? ORDER BY rowid", (scenario_id,)).fetchall()
    periods = json.loads(row["periods"]) if row else []
    for period in periods:
        period["end"] = (date.fromisoformat(period["start"]) + timedelta(days=period["days"]-1)).isoformat()
        period["attempts"] = [_attempt(a) for a in attempts if a["period"] == period["id"]]
    count = len(periods)
    latest = [p["attempts"][-1] if p["attempts"] else {} for p in periods]
    for attempt in latest:
        attempt["completed"] = attempt.get("state") in {"COMPLETED", "VERIFIED"}
    return {"scenario_id": scenario_id, "revision": row["revision"] if row else 0, "periods": periods,
            "progress": {key: round(100 * sum(bool(a.get(key)) for a in latest)/count, 1) if count else 0
                         for key in ("prepared", "completed", "verified")},
            "semantics": "independent_periods;continuous_state_within_each_period;not_a_continuous_year"}


def save_periods(scenario_id: str, edit: PeriodEdit) -> dict:
    scenario_store.get_desktop_context(scenario_id)
    with closing(_connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM plans WHERE scenario=?", (scenario_id,)).fetchone()
        revision = old["revision"] if old else 0
        if revision != edit.revision:
            raise ValueError("PERIOD_PLAN_STALE: reload before saving")
        bound = {r[0] for r in db.execute("SELECT period FROM attempts WHERE scenario=?", (scenario_id,))}
        new = {p.id: p.model_dump(mode="json") for p in edit.periods}
        for period in json.loads(old["periods"]) if old else []:
            if period["id"] in bound and (period["id"] not in new or any(
                    new[period["id"]][key] != period[key] for key in ("start", "days"))):
                raise ValueError("BOUND_PERIOD_IMMUTABLE: retain the executed period and add a new one")
        db.execute("INSERT INTO plans VALUES(?,?,?) ON CONFLICT(scenario) DO UPDATE SET revision=excluded.revision,periods=excluded.periods",
                   (scenario_id, revision+1, json.dumps(list(new.values()), ensure_ascii=False)))
    return get_periods(scenario_id)


def bind_campaign(scenario_id: str, period_id: str, campaign: Path) -> dict:
    """Local CLI only: attach evidence, never submit or alter an existing run."""
    scenario_store.get_desktop_context(scenario_id)
    binding = _read(campaign / "binding.json")
    with closing(_connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        plan = db.execute("SELECT periods FROM plans WHERE scenario=?", (scenario_id,)).fetchone()
        period = next((p for p in json.loads(plan[0]) if p["id"] == period_id), None) if plan else None
        if period is None:
            raise ValueError("Unknown period")
        if binding["parent"] != scenario_id or period["days"] != 7 or period["start"] not in binding["weeks"]:
            raise ValueError("Campaign parent or dates do not match the period")
        db.execute("INSERT OR IGNORE INTO attempts VALUES(?,?,?,?,?)",
                   (scenario_id, period_id, str(uuid4()), str(campaign.resolve()), period["start"]))
    return get_periods(scenario_id)
