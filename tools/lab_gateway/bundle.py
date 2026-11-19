"""Validation of submitted bundles and job parameters. Everything a member sends is data, never a command."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath

MAX_BUNDLE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
MAX_FILES = 5000
ENTRY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,150}\.py")
ARG = re.compile(r"[A-Za-z0-9_./=:,\-]{1,120}")
NAME = re.compile(r"[A-Za-z0-9_\- ]{1,60}")
KEY = re.compile(r"[A-Za-z0-9_\-]{1,64}")


class BundleError(ValueError):
    pass


def validate_bundle(path: Path, entry: str) -> int:
    """Reject path escapes, zip bombs and a missing entry point. Returns the unpacked size."""
    if not ENTRY.fullmatch(entry) or ".." in PurePosixPath(entry).parts:
        raise BundleError("entry must be a relative .py path inside the bundle")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BundleError("the upload is not a valid zip file") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_FILES:
            raise BundleError(f"the bundle must contain 1..{MAX_FILES} files")
        total = 0
        names = set()
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            if name.startswith(("/", "\\")) or "\\" in name or ".." in parts or (parts and ":" in parts[0]):
                raise BundleError(f"unsafe path in bundle: {name[:80]!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise BundleError("symbolic links are not allowed")
            total += info.file_size
            names.add(name)
        if total > MAX_UNPACKED_BYTES:
            raise BundleError("the unpacked bundle exceeds the 1 GiB limit")
        if entry not in names:
            raise BundleError("entry file is not in the bundle")
    return total


def validate_args(values: list) -> list[str]:
    if not isinstance(values, list) or len(values) > 40:
        raise BundleError("args must be a list of at most 40 strings")
    cleaned = []
    for value in values:
        if not isinstance(value, str) or not ARG.fullmatch(value):
            raise BundleError("each arg may use letters, digits and _ . / = : , - only")
        cleaned.append(value)
    return cleaned
