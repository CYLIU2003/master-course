"""Disk-backed, Zip64 artifact transfer for long multi-day runs."""
import hashlib
import shutil
import zipfile
from pathlib import Path


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_to_disk(directory: Path, response: dict) -> dict:
    destination = directory.with_suffix(".zip")
    temporary = directory.with_suffix(".zip.tmp")
    hashes = {}
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Refusing linked artifact")
            if path.is_file() and path.name != "state.tmp":
                name = path.relative_to(directory).as_posix()
                hashes[name] = file_digest(path)
                archive.write(path, name)
    temporary.replace(destination)
    return {**response, "artifact_hashes": hashes, "archive_sha256": file_digest(destination)}


def copy_verified_member(archive, info, destination: Path, expected: str):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    if file_digest(destination) != expected:
        raise ValueError("Artifact hash mismatch")
