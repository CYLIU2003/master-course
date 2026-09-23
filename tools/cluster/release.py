"""Package a clean release and stage it to registered workers without AI.

Deployment uses immutable per-SHA directories, never replaces a running checkout,
and writes a new private config only after every selected worker passes its probe.
Runtime installation/credentials remain the separately authorized setup step.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.artifacts import file_digest
from bff.services.cluster.contracts import ClusterConfig, canonical, git_state, source_digest, runtime_versions
from bff.services.cluster.transport import invoke, ssh_command
from bff.services.cluster.runner import file_hashes


def package(release: Path, output: Path, dataset: str) -> dict:
    release = release.resolve()
    git = git_state(release)
    if git["dirty"]:
        raise ValueError("Package requires a clean frozen release")
    dataset_path = release / dataset
    if not dataset_path.resolve().is_relative_to(release) or dataset_path.is_junction() or dataset_path.is_symlink():
        raise ValueError("Dataset must remain inside the release")
    # Only tracked files, Git objects, and this explicitly selected immutable
    # dataset are included. Ignored keys, logs and runtime outputs stay outside.
    tracked = subprocess.check_output(["git", "-C", str(release), "ls-files", "-z"]).decode("utf8").split("\0")
    paths = {release / name for name in tracked if name}
    git_dir = release / ".git"
    if not git_dir.is_dir():
        raise ValueError("Package needs a standalone Git release, not a worktree link")
    # The archive sanitizes .git/config. Preserve this one non-secret checkout
    # setting so Windows CRLF files remain clean against the transported index.
    try:
        autocrlf = subprocess.check_output(
            ["git", "-C", str(release), "config", "--get", "core.autocrlf"],
            text=True, timeout=30,
        ).strip().lower()
    except subprocess.CalledProcessError:
        autocrlf = "false"
    if autocrlf not in {"true", "false", "input"}:
        raise ValueError("Unsupported core.autocrlf setting")
    paths.update(path for path in git_dir.rglob("*") if path.is_file())
    paths.update(dataset_path / name for name in file_hashes(dataset_path))
    for path in paths:
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(release):
            raise ValueError("Linked release member")
        name = path.relative_to(release).as_posix()
        if path.suffix.lower() in {".lic", ".pem", ".key"} or "private" in path.name.lower() or path.name.startswith("workers.local.json"):
            raise ValueError("Private material is forbidden in a release archive")
        if any(parent.is_symlink() or parent.is_junction() for parent in path.parents if parent != release and parent.is_relative_to(release)):
            raise ValueError("Linked release directory")
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / (git["sha"] + ".zip")
    if archive_path.exists():
        raise ValueError("Use a new package directory; existing releases are immutable")
    temporary = archive_path.with_suffix(".partial")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(paths):
            name = path.relative_to(release).as_posix()
            if name == ".git/config":
                archive.writestr(name, "[core]\nrepositoryformatversion = 0\nbare = false\nfilemode = false\nautocrlf = " + autocrlf + "\n")
            elif not name.startswith((".git/hooks/", ".git/logs/")):
                archive.write(path, name)
    temporary.replace(archive_path)
    if git_state(release) != git:
        raise ValueError("Release changed while packaging")
    manifest = {"schema_version": 1, "git": git, "source_digest": source_digest(release),
                "git_core_autocrlf": autocrlf,
                "archive": archive_path.name, "archive_sha256": file_digest(archive_path),
                "dataset": dataset, "dataset_hashes": file_hashes(dataset_path),
                "uv_lock_sha256": file_digest(release / "tools/cluster/environment/uv.lock")}
    (output / "release.json").write_bytes(canonical(manifest))
    return manifest


def remote(worker, script: str, timeout: int = 90) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(ssh_command(worker, "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded),
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # Do not put remote stderr, account paths, or license diagnostics in reports.
        raise RuntimeError(f"RELEASE_REMOTE_FAILED: exit={result.returncode}")
    return result.stdout.decode("utf8").strip()


def quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def release_root(repo: str) -> PureWindowsPath:
    """Keep upgrades under the same release directory after the first stage."""
    path = PureWindowsPath(repo)
    if path.parent.name.lower() == "releases" and re.fullmatch(r"[0-9a-f]{40}", path.name):
        return path.parent
    return path.parent / "releases"


def stage(worker, release: Path, manifest: dict, archive: Path, evidence: Path):
    updated = worker.model_copy(deep=True)
    if worker.transport == "local":
        updated.repo = str(release.resolve())
    else:
        if worker.shell != "powershell":
            raise ValueError("This deployment command supports registered Windows workers")
        root = release_root(worker.repo)
        destination = root / manifest["git"]["sha"]
        updated.repo = destination.as_posix()
        # Unique staging names survive interrupted uploads without replacing any
        # verified release. No recursive deletion or cross-shell moving occurs.
        upload = root / (manifest["git"]["sha"] + "-" + uuid.uuid4().hex + ".zip")
        root_q, dest_q, upload_q = map(quote_ps, (str(root), str(destination), str(upload)))
        exists = remote(worker, f"$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Path {root_q} -Force | Out-Null; [int](Test-Path -LiteralPath {dest_q})")
        if exists != "1":
            args = ["scp", "-B", "-P", str(worker.ssh_port), "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=4"]
            host = (worker.ssh_user + "@" if worker.ssh_user else "") + worker.host
            transferred = subprocess.run([*args, str(archive), host + ":" + upload.as_posix()], capture_output=True, timeout=300)
            if transferred.returncode:
                raise RuntimeError("RELEASE_UPLOAD_FAILED")
            extract = (ROOT / "tools/cluster/stage_release.ps1").read_text(encoding="utf-8-sig")
            # The script is shipped source; parameters are literals from the
            # local administrator config, never from submitted job payloads.
            script = "& {\n" + extract + "\n} -Root " + root_q + " -Archive " + upload_q + " -Destination " + dest_q + " -Sha256 " + quote_ps(manifest["archive_sha256"])
            remote(worker, script, 180)
    probe = invoke(updated, {"operation": "probe"}, evidence / worker.id, timeout=45)
    if probe["git"] != manifest["git"] or probe["source_digest"] != manifest["source_digest"]:
        raise ValueError("RELEASE_CODE_MISMATCH")
    if probe["runtime_versions"].get("uv_lock_sha256") != manifest["uv_lock_sha256"]:
        raise ValueError("RELEASE_LOCK_MISMATCH")
    if probe["runtime_versions"] != runtime_versions():
        raise ValueError("RELEASE_RUNTIME_MISMATCH")
    checked = invoke(updated, {"operation": "dataset-hashes", "path": manifest["dataset"]}, evidence / worker.id / "dataset", timeout=60)
    if checked != manifest["dataset_hashes"]:
        raise ValueError("RELEASE_DATASET_MISMATCH")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    packing = sub.add_parser("package")
    packing.add_argument("--release", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("--dataset", default="data/built/tokyu_full")
    deploying = sub.add_parser("stage")
    deploying.add_argument("--release", type=Path, required=True)
    deploying.add_argument("--manifest", type=Path, required=True)
    deploying.add_argument("--config", type=Path, required=True)
    deploying.add_argument("--output-config", type=Path, required=True)
    deploying.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "package":
        print(json.dumps(package(args.release, args.output, args.dataset)))
        return 0
    manifest = json.loads(args.manifest.read_bytes())
    archive = args.manifest.parent / manifest["archive"]
    if not archive.resolve().is_relative_to(args.manifest.parent.resolve()) or file_digest(archive) != manifest["archive_sha256"]:
        raise ValueError("RELEASE_ARCHIVE_MISMATCH")
    if git_state(args.release) != manifest["git"] or source_digest(args.release) != manifest["source_digest"]:
        raise ValueError("RELEASE_CHANGED")
    config = ClusterConfig.model_validate_json(args.config.read_text(encoding="utf-8-sig"))
    if args.output_config.exists():
        raise ValueError("Refusing to overwrite an existing deployment config")
    args.evidence.mkdir(parents=True, exist_ok=True)
    rows = []
    def one(worker):
        try:
            updated = stage(worker, args.release, manifest, archive, args.evidence)
            rows.append({"id": worker.id, "status": "VERIFIED"})
            return updated
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            rows.append({"id": worker.id, "status": "FAILED", "error_type": type(exc).__name__, "reason": str(exc) if isinstance(exc, ValueError) else "STAGING_OR_CONNECTION_FAILED"})
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        updated = list(pool.map(one, config.workers))
    (args.evidence / "report.json").write_bytes(canonical({"git": manifest["git"], "workers": rows, "gurobi_env_started": 0}))
    if any(worker is None for worker in updated):
        print(json.dumps({"status": "BLOCKED", "verified": sum(worker is not None for worker in updated), "report": str(args.evidence / "report.json")}))
        return 2
    config.workers = updated
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    # This is a new config, not live activation. Restart the frozen controller
    # with it only after resolving old active attempts in its existing queue.
    with args.output_config.open("xb") as output:
        output.write(canonical(config.model_dump()))
    print(json.dumps({"status": "VERIFIED", "workers": len(updated), "config": str(args.output_config)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
