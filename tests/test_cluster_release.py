"""Release deployment tests use temporary Git repositories and WinPS, no SSH."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest

from tools.cluster.release import package, release_root
from bff.services.cluster.runner import handle

SCRIPT = Path(__file__).resolve().parents[1] / "tools/cluster/stage_release.ps1"


def test_release_root_stays_stable_across_sequential_stages():
    first = release_root("C:/mc-worker/repo")
    second = release_root(str(first / ("a" * 40)))
    assert first == second
    assert str(second / ("b" * 40)).replace("\\", "/") == "C:/mc-worker/releases/" + "b" * 40


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), "-c", "core.autocrlf=false", *args], stderr=subprocess.STDOUT)


def test_clean_release_packages_git_and_dataset_without_ignored_private_material(tmp_path):
    root = tmp_path / "clean"
    root.mkdir()
    git(root, "init")
    (root / "src").mkdir()
    (root / "src/example.py").write_text("pass\n")
    lock = root / "tools/cluster/environment/uv.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("locked")
    (root / ".gitignore").write_text("*.lic\ndata/\n")
    (root / "gurobi.lic").write_text("PRIVATE-SENTINEL")
    dataset = root / "data/built/test"
    dataset.mkdir(parents=True)
    (dataset / "trips.json").write_text("[]")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    manifest = package(root, tmp_path / "package", "data/built/test")
    archive = tmp_path / "package" / manifest["archive"]
    with zipfile.ZipFile(archive) as contents:
        assert "gurobi.lic" not in contents.namelist()
        assert ".git/HEAD" in contents.namelist()
        assert contents.read("data/built/test/trips.json") == b"[]"
        assert all(b"PRIVATE-SENTINEL" not in contents.read(name) for name in contents.namelist())
        unpacked = tmp_path / "unpacked"
        contents.extractall(unpacked)
    assert not git(unpacked, "status", "--porcelain").strip()
    assert manifest["git"]["sha"] == git(unpacked, "rev-parse", "HEAD").decode().strip()
    (root / "src/example.py").write_text("changed\n")
    with pytest.raises(ValueError, match="clean frozen"):
        package(root, tmp_path / "bad", "data/built/test")


@pytest.mark.skipif(os.name != "nt", reason="Windows staging")
@pytest.mark.parametrize("entry,allowed", [("src/ok.py", True), ("../escaped", False), ("C:/escaped", False), ("src/name. ", False)])
def test_powershell_staging_paths_are_bounded_and_existing_releases_preserved(tmp_path, entry, allowed):
    root = tmp_path / "配布 領域"
    root.mkdir()
    archive = root / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr(entry, "test")
    destination = root / "fixed"
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
            "-Root", str(root), "-Archive", str(archive), "-Destination", str(destination),
            "-Sha256", hashlib.sha256(archive.read_bytes()).hexdigest()]
    result = subprocess.run(args, capture_output=True, timeout=20)
    assert (result.returncode == 0) is allowed, result.stderr.decode(errors="replace")
    if allowed:
        assert (destination / entry).read_text() == "test"
        assert subprocess.run(args, capture_output=True, timeout=20).returncode != 0
        assert (destination / entry).read_text() == "test"
    else:
        assert not destination.exists()
    assert not (tmp_path / "escaped").exists()


def test_dataset_probe_rejects_reading_outside_built_root(tmp_path):
    with pytest.raises(ValueError, match="restricted"):
        handle({"operation": "dataset-hashes", "path": str(tmp_path)}, tmp_path)


def test_cancelled_attempt_can_be_collected_after_owned_exit(tmp_path):
    from bff.services.cluster.runner import write_json
    from bff.services.cluster.contracts import canonical, digest
    directory = tmp_path / "attempt"
    directory.mkdir()
    manifest = {"id": "attempt"}
    state = {"id": "attempt", "state": "CANCELLED", "manifest_sha256": digest(canonical(manifest))}
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "state.json", state)
    result = handle({"operation": "collect", "id": "attempt", "stream_artifacts": True}, tmp_path)
    assert result["state"] == "CANCELLED" and result["archive_sha256"]
