"""Compatibility entrypoint; implementation: scripts.catalog._stop_timetable_fallback."""

from pathlib import Path
import sys

# Support direct execution and importlib loaders from outside the repository.
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.catalog import _stop_timetable_fallback as _implementation


def __getattr__(name):
    """Expose attributes to callers retaining an importlib loader's module."""
    return getattr(_implementation, name)


sys.modules[__name__] = _implementation
