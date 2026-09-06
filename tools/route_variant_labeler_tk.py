"""Compatibility entrypoint; implementation: tools.gui.route_variant_labeler_tk."""

from pathlib import Path
import sys

# Support direct execution and importlib loaders from outside the repository.
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.gui import route_variant_labeler_tk as _implementation


def __getattr__(name):
    """Expose attributes to callers retaining an importlib loader's module."""
    return getattr(_implementation, name)


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
