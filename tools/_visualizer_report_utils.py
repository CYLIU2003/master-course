"""Compatibility entrypoint; implementation: tools.gui._visualizer_report_utils."""

from pathlib import Path
import sys

# Support direct execution and importlib loaders from outside the repository.
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.gui import _visualizer_report_utils as _implementation


def __getattr__(name):
    """Expose attributes to callers retaining an importlib loader's module."""
    return getattr(_implementation, name)


sys.modules[__name__] = _implementation
