from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

gp = None
GRB = None
_GUROBI_AVAILABLE = False
_GUROBI_DLL_HANDLES: list[Any] = []

try:
    import gurobipy as _gp
    from gurobipy import GRB as _GRB

    gp = _gp
    GRB = _GRB
    _GUROBI_AVAILABLE = True
except Exception:
    gp = None
    GRB = None
    _GUROBI_AVAILABLE = False


def candidate_gurobi_homes() -> list[Path]:
    candidates: list[Path] = []
    raw_env_home = str(os.environ.get("GUROBI_HOME") or "").strip()
    if raw_env_home:
        candidates.append(Path(raw_env_home))
    root = Path("C:/")
    if root.exists():
        for path in sorted(root.glob("gurobi*/win64"), reverse=True):
            candidates.append(path)
        for path in sorted(root.glob("gurobi*"), reverse=True):
            candidates.append(path)
    return candidates


def configure_gurobipy_sys_path() -> None:
    try:
        import site
    except Exception:
        site = None  # type: ignore[assignment]

    candidate_site_roots: list[Path] = []
    if site is not None:
        try:
            for raw in site.getsitepackages() if hasattr(site, "getsitepackages") else []:
                candidate_site_roots.append(Path(raw))
        except Exception:
            pass
        try:
            user_site = site.getusersitepackages() if hasattr(site, "getusersitepackages") else ""
            if user_site:
                candidate_site_roots.append(Path(user_site))
        except Exception:
            pass

    base_prefixes = {
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable).resolve().parent,
    }
    for prefix in base_prefixes:
        candidate_site_roots.append(prefix / "Lib" / "site-packages")
        candidate_site_roots.append(prefix / "lib" / "site-packages")

    seen: set[str] = set()
    for root in candidate_site_roots:
        normalized = str(root).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if not root.exists():
            continue
        if not ((root / "gurobipy").exists() or any(root.glob("gurobipy*.pth"))):
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))


def configure_gurobi_runtime() -> None:
    configure_gurobipy_sys_path()

    raw_license = str(os.environ.get("GRB_LICENSE_FILE") or "").strip()
    if not raw_license:
        for candidate in (
            Path.home() / "gurobi.lic",
            Path("C:/gurobi/gurobi.lic"),
            Path("C:/gurobi1301/gurobi.lic"),
        ):
            if candidate.exists():
                os.environ["GRB_LICENSE_FILE"] = str(candidate)
                break

    seen_bin_dirs: set[str] = set()
    path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    normalized_entries = {str(Path(entry)).lower() for entry in path_entries}
    for candidate in candidate_gurobi_homes():
        if candidate.name.lower() == "bin":
            home_dir = candidate.parent
            bin_dir = candidate
        elif candidate.name.lower() == "win64":
            home_dir = candidate
            bin_dir = candidate / "bin"
        else:
            win64_dir = candidate / "win64"
            home_dir = win64_dir if win64_dir.exists() else candidate
            bin_dir = home_dir / "bin"
        if not bin_dir.exists():
            continue
        normalized_bin_dir = str(bin_dir).lower()
        if normalized_bin_dir in seen_bin_dirs:
            continue
        seen_bin_dirs.add(normalized_bin_dir)
        os.environ.setdefault("GUROBI_HOME", str(home_dir))
        if normalized_bin_dir not in normalized_entries:
            path_entries.insert(0, str(bin_dir))
            normalized_entries.add(normalized_bin_dir)
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                handle = os.add_dll_directory(str(bin_dir))
            except (FileNotFoundError, OSError):
                continue
            _GUROBI_DLL_HANDLES.append(handle)
    if path_entries:
        os.environ["PATH"] = os.pathsep.join(path_entries)


def ensure_gurobi():
    global _GUROBI_AVAILABLE, gp, GRB  # noqa: PLW0603
    if _GUROBI_AVAILABLE and gp is not None and GRB is not None:
        return gp, GRB
    configure_gurobi_runtime()
    try:
        import gurobipy as _gp
        from gurobipy import GRB as _GRB

        gp = _gp
        GRB = _GRB
        _GUROBI_AVAILABLE = True
        return gp, GRB
    except Exception as exc:
        raise RuntimeError(
            f"gurobipy をインポートできません: {exc}  "
            "Gurobi がインストールされているか、DLL パスとライセンスファイルが正しい場所にあるか確認してください。"
        ) from exc


def is_gurobi_available() -> bool:
    try:
        ensure_gurobi()
        return True
    except Exception:
        return False
