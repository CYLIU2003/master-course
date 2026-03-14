from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_VERSION_PATHS = [
    _REPO_ROOT / "app" / "VERSION",
    _REPO_ROOT / "bff" / "VERSION",
]


def _load_runtime_version() -> str:
    for path in _RUNTIME_VERSION_PATHS:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return "0.1.0"


RUNTIME_VERSION = _load_runtime_version()
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = {"v1"}


class ContractErrorCode(StrEnum):
    MANIFEST_MISSING = "ARTIFACT_MANIFEST_MISSING"
    MANIFEST_INVALID = "ARTIFACT_MANIFEST_INVALID"
    SCHEMA_VERSION_UNSUPPORTED = "MANIFEST_SCHEMA_VERSION_UNSUPPORTED"
    DATASET_VERSION_MISMATCH = "DATASET_VERSION_MISMATCH"
    RUNTIME_VERSION_TOO_OLD = "RUNTIME_VERSION_TOO_OLD"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"


@dataclass
class ArtifactContractError(Exception):
    code: ContractErrorCode
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": str(self.code),
            "message": self.message,
            **(self.details or {}),
        }


def _parse_semver(v: str) -> tuple[int, int, int]:
    try:
        parts = v.strip().lstrip("v").split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return 0, 0, 0


def _version_gte(a: str, b: str) -> bool:
    return _parse_semver(a) >= _parse_semver(b)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_artifact_contract(
    built_dir: Path,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    manifest_path = built_dir / "manifest.json"
    if not manifest_path.exists():
        raise ArtifactContractError(
            code=ContractErrorCode.MANIFEST_MISSING,
            message=f"manifest.json not found in {built_dir}",
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactContractError(
            code=ContractErrorCode.MANIFEST_INVALID,
            message=f"manifest.json is not valid JSON: {exc}",
        ) from exc

    schema_version = manifest.get("schema_version")
    if schema_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise ArtifactContractError(
            code=ContractErrorCode.SCHEMA_VERSION_UNSUPPORTED,
            message=(
                f"Manifest schema version '{schema_version}' is not supported. "
                f"Supported: {sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)}"
            ),
        )

    min_runtime = str(manifest.get("min_runtime_version") or "").strip()
    if min_runtime and not _version_gte(RUNTIME_VERSION, min_runtime):
        raise ArtifactContractError(
            code=ContractErrorCode.RUNTIME_VERSION_TOO_OLD,
            message=(
                f"Runtime version {RUNTIME_VERSION} is below the minimum required "
                f"by this built dataset: {min_runtime}. Upgrade the runtime or rebuild "
                "with a compatible producer."
            ),
            details={
                "runtime_version": RUNTIME_VERSION,
                "min_runtime_version": min_runtime,
            },
        )

    required_artifacts = ["routes.parquet", "trips.parquet", "timetables.parquet"]
    missing = [name for name in required_artifacts if not (built_dir / name).exists()]
    if missing:
        raise ArtifactContractError(
            code=ContractErrorCode.ARTIFACT_MISSING,
            message=f"Required artifacts are missing: {missing}",
            details={"missing_artifacts": missing},
        )

    if verify_hashes:
        artifact_hashes = dict(manifest.get("artifact_hashes") or {})
        for name, expected_hash in artifact_hashes.items():
            artifact_path = built_dir / name
            if not artifact_path.exists():
                continue
            actual_hash = _sha256_file(artifact_path)
            if actual_hash != expected_hash:
                raise ArtifactContractError(
                    code=ContractErrorCode.ARTIFACT_HASH_MISMATCH,
                    message=(
                        f"Artifact '{name}' hash mismatch. The file may have been modified "
                        "or partially written."
                    ),
                    details={
                        "artifact": name,
                        "expected": expected_hash,
                        "actual": actual_hash,
                    },
                )

    return manifest
