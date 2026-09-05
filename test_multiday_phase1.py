"""Compatibility entrypoint; manual BFF experiment, never a pytest test.

Canonical script: tools/manual_experiments/test_multiday_phase1.py.
Running this file creates scenarios and starts solver jobs; importing it does not.
"""

from pathlib import Path
import runpy

__test__ = False

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "tools/manual_experiments/test_multiday_phase1.py"),
        run_name="__main__",
    )
