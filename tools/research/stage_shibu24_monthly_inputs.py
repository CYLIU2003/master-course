"""Copy frozen monthly Prepared/PV inputs into a matching controller release.

This is a data transfer after Prepare, not a re-Prepare or solve. Existing
different files are never overwritten. It is safe to rerun after interruption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import git_state
from bff.services.cluster.weekly_inputs import execution_references


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_exact(source: Path, target: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("An input has no valid SHA-256")
    if not source.is_file() or source.is_symlink() or _sha(source.read_bytes()) != expected:
        raise ValueError(f"Input missing or changed: {source}")
    if target.is_symlink() or (target.exists() and _sha(target.read_bytes()) != expected):
        raise ValueError(f"Refusing to replace different controller input: {target}")
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial-" + uuid.uuid4().hex)
    try:
        temporary.write_bytes(source.read_bytes())
        if _sha(temporary.read_bytes()) != expected:
            raise ValueError("Input changed during controller staging")
        try:
            os.link(temporary, target)
        except FileExistsError:
            if _sha(target.read_bytes()) != expected:
                raise ValueError(f"Controller input changed during staging: {target}")
    finally:
        if temporary.exists():
            temporary.unlink()


def stage(campaign: Path, source_worktree: Path, settings_path: Path) -> dict:
    settings = _read(settings_path)
    binding = _read(campaign / "binding.json")
    summary = _read(campaign / "summary.json")
    expected_git = {"sha": binding["git_sha"], "dirty": False}
    if (git_state(source_worktree) != expected_git or
            git_state(Path(settings["release"])) != expected_git or
            settings.get("git_sha") != binding["git_sha"]):
        raise ValueError("Prepared worktree and controller release SHA differ")
    if not summary.get("all_prepared") or summary.get("binding") != binding:
        raise ValueError("All twelve strict Prepared weeks are required")
    weeks = binding["weeks"]
    if len(weeks) != 12 or len(set(weeks)) != 12:
        raise ValueError("Monthly campaign must contain twelve distinct weeks")
    if (source_worktree / "output" / "scenarios").resolve() != Path(settings["scenarios"]).resolve():
        raise ValueError("Controller and Prepared scenario stores differ")

    source_prepared = source_worktree / "output" / "prepared_inputs"
    target_prepared = Path(settings["outputs"]) / "prepared_inputs"
    release = Path(settings["release"])
    rows = []
    for week in weeks:
        record = _read(campaign / week / "state.json")
        if (record.get("status") != "PREPARED" or
                record.get("week") != week or
                record.get("strict_scope_audit_passed") is not True):
            raise ValueError(f"Week {week} has not passed strict Prepare")
        scenario_id, prepared_id = record["scenario_id"], record["prepared_input_id"]
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in (scenario_id, prepared_id)):
            raise ValueError("Unsafe scenario or Prepared ID")
        relative = Path(scenario_id) / f"{prepared_id}.json"
        source = source_prepared / relative
        expected = record["prepared_input_sha256"]
        content = source.read_bytes()
        if _sha(content) != expected:
            raise ValueError(f"Prepared source changed for {week}")
        prepared = json.loads(content)
        if (prepared.get("scenario_id") != scenario_id or
                prepared.get("prepared_input_id") != prepared_id):
            raise ValueError(f"Prepared identity mismatch for {week}")
        references = execution_references(prepared.get("simulation_config") or {})
        if not references:
            raise ValueError(f"Historical PV execution input missing for {week}")
        for name, digest in references.items():
            _copy_exact(source_worktree / name, release / name, digest)
        _copy_exact(source, target_prepared / relative, expected)
        rows.append({"week": week, "scenario_id": scenario_id,
                     "prepared_input_id": prepared_id, "prepared_sha256": expected,
                     "execution_inputs": references})
    report = {"schema_version": "shibu24_monthly_staged_inputs_v1",
              "git_sha": binding["git_sha"], "status": "STAGED_HASH_VERIFIED",
              "cases": rows, "formal_solve_executed": False}
    target = campaign / "staged_inputs.json"
    if target.exists() and _read(target) != report:
        raise ValueError("Staged input manifest changed; preserve the old campaign")
    if not target.exists():
        temporary = target.with_name(target.name + ".partial-" + uuid.uuid4().hex)
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            os.link(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--source-worktree", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.campaign.resolve(), args.source_worktree.resolve(), args.settings.resolve())
    print(json.dumps({"status": result["status"], "weeks": len(result["cases"]),
                      "git_sha": result["git_sha"]}))


if __name__ == "__main__":
    main()
