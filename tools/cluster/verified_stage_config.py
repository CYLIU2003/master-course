"""Derive a fail-closed controller inventory from a partial release-stage report.

Only workers verified for the exact frozen release may accept jobs. Unavailable
workers remain visible for monitoring and may be enabled after a new stage run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import ClusterConfig, git_state
from tools.cluster.release import release_root


def derive(source: Path, report_paths: list[Path], release: Path,
           manifest_path: Path) -> tuple[ClusterConfig, dict]:
    config = ClusterConfig.model_validate_json(source.read_text(encoding="utf-8-sig"))
    expected = git_state(release)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if expected["dirty"] or not report_paths:
        raise ValueError("A clean release and at least one stage report are required")
    if manifest.get("git") != expected:
        raise ValueError("Release manifest does not match the frozen release")
    identities = {worker.id for worker in config.workers}
    verified_ids: set[str] = set()
    for index, report_path in enumerate(report_paths):
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        if report.get("git") != expected or report.get("gurobi_env_started") != 0:
            raise ValueError("Stage report does not match the clean frozen release")
        rows = report.get("workers")
        if not isinstance(rows, list):
            raise ValueError("Stage report worker list is missing")
        by_id = {row.get("id"): row.get("status") for row in rows}
        if len(by_id) != len(rows) or not set(by_id) <= identities or (index == 0 and set(by_id) != identities):
            raise ValueError("Stage report worker identities are incomplete or duplicated")
        if any(status not in {"VERIFIED", "FAILED"} for status in by_id.values()):
            raise ValueError("Unrecognized stage status")
        for identity, status in by_id.items():
            if status != "VERIFIED":
                continue
            evidence = report_path.parent / identity
            probe = json.loads((evidence / "transport.stdout").read_text(encoding="utf-8-sig"))
            dataset = json.loads((evidence / "dataset/transport.stdout").read_text(encoding="utf-8-sig"))
            if (probe.get("git") != expected or
                    probe.get("source_digest") != manifest.get("source_digest") or
                    probe.get("runtime_versions", {}).get("uv_lock_sha256") != manifest.get("uv_lock_sha256") or
                    dataset != manifest.get("dataset_hashes")):
                raise ValueError(f"Stage evidence differs from release manifest: {identity}")
            verified_ids.add(identity)
    verified = []
    unavailable = []
    for worker in config.workers:
        if worker.transport == "local":
            worker.repo = str(release.resolve())
        else:
            worker.repo = (release_root(worker.repo) / expected["sha"]).as_posix()
        if worker.id in verified_ids:
            verified.append(worker.id)
        else:
            worker.enabled = False
            worker.monitoring_enabled = True
            unavailable.append(worker.id)
    if "local" not in verified:
        raise ValueError("The controller's own worker was not verified")
    return config, {"git_sha": expected["sha"], "verified": verified,
                    "disabled_until_restage": unavailable,
                    "research_approval": "NOT_GRANTED_BY_STAGING"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, action="append",
                        help="Pass the full stage report first, then any single-worker retry reports")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config, summary = derive(args.config, args.report, args.release, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(config.model_dump_json() + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
